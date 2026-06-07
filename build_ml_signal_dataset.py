#!/usr/bin/env python3
"""Build an order-level ML dataset from tick snapshots and settlements."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict, deque
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import backtest_ticks as bt
from ml_filter import FEATURE_NAMES, optional_float


IDENTIFIER_FIELDS = [
    "recorded_at",
    "market_slug",
    "market_start_utc",
    "market_end_utc",
    "market_day",
    "source_event",
    "side",
    "is_baseline_order",
    "order_index_in_market",
]

LABEL_FIELDS = [
    "resolved_side",
    "would_win",
    "single_order_pnl",
    "single_order_pnl_per_usd",
    "single_order_fee_usdc",
    "single_order_net_shares",
    "amount_usd",
]


def baseline_config(args: argparse.Namespace) -> bt.ReplayConfig:
    return bt.ReplayConfig(
        edge_prob_threshold=args.edge_prob_threshold,
        edge_reference_price=args.edge_reference_price,
        max_spread=args.max_spread,
        min_entry_ask_price=args.min_entry_ask_price,
        min_edge_after_fill=args.min_edge_after_fill,
        exec_slippage_ticks=args.exec_slippage_ticks,
        exec_price_mode=args.exec_price_mode,
        exec_price_cap=args.exec_price_cap,
        tick_size=args.tick_size,
        trade_amount_usd=args.trade_amount_usd,
        order_cooldown_seconds=args.order_cooldown_seconds,
        signal_cooldown_seconds=args.signal_cooldown_seconds,
        market_max_total_cost=args.market_max_total_cost,
        market_max_side_cost=args.market_max_side_cost,
        side_extension_enabled=args.side_extension_enabled,
        side_extension_start_cost=args.side_extension_start_cost,
        side_extension_max_side_cost=args.side_extension_max_side_cost,
        side_extension_min_seconds=args.side_extension_min_seconds,
        side_extension_cooldown_seconds=args.side_extension_cooldown_seconds,
        side_extension_min_edge=args.side_extension_min_edge,
        side_extension_min_edge_after_fill=args.side_extension_min_edge_after_fill,
        side_extension_min_ask_price=args.side_extension_min_ask_price,
        side_extension_max_ask_price=args.side_extension_max_ask_price,
        side_extension_max_opposite_cost=args.side_extension_max_opposite_cost,
        fair_mode=args.fair_mode,
        sigma_short_weight=args.sigma_short_weight,
        sigma_long_weight=args.sigma_long_weight,
        sigma_min=args.sigma_min,
        tau_floor_seconds=args.tau_floor_seconds,
        z_cap=args.z_cap,
        entry_time_windows=(),
        block_time_windows=(),
        tail_reversal_lookback_seconds=0.0,
        tail_reversal_trigger_count=0,
        tail_reversal_cooldown_seconds=0.0,
        tail_reversal_min_anchor_prob=0.55,
        tail_reversal_min_prob_drop=0.10,
        tail_reversal_min_mid_gain=0.03,
        ml_filter_enabled=False,
        ml_model_path=Path("models/signal_filter_lgbm_v1.txt"),
        ml_features_path=Path("models/signal_filter_lgbm_v1_features.json"),
        ml_min_ev=0.0,
        ml_fail_open=False,
    )


def ratio_return(price: Optional[float], anchor: Optional[float]) -> Optional[float]:
    if price is None or anchor is None or anchor <= 0:
        return None
    return (price / anchor) - 1.0


def mean(values: list[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def rolling_features(recent_results: deque[tuple[float, bool]]) -> dict[str, Optional[float]]:
    last_6 = list(recent_results)[-6:]
    last_10 = list(recent_results)[-10:]
    return {
        "rolling_6_market_roi": mean([roi for roi, _ in last_6]),
        "rolling_10_market_roi": mean([roi for roi, _ in last_10]),
        "rolling_10_market_win_rate": mean([1.0 if win else 0.0 for _, win in last_10]),
    }


def market_pnl_and_roi(
    state: bt.MarketState, settlement: bt.Settlement
) -> tuple[float, float, bool]:
    payout = state.yes_shares if settlement.resolved_side == "UP" else state.down_shares
    pnl = payout - state.total_cost - state.fee_total
    roi = pnl / state.total_cost if state.total_cost > 0 else 0.0
    return pnl, roi, pnl > 0


class DatasetReplay:
    def __init__(
        self,
        settlements: dict[str, bt.Settlement],
        cfg: bt.ReplayConfig,
    ) -> None:
        self.settlements = settlements
        self.cfg = cfg
        self.states: dict[str, bt.MarketState] = defaultdict(bt.MarketState)
        self.rows: list[dict[str, Any]] = []
        self.recent_results: deque[tuple[float, bool]] = deque(maxlen=50)
        self.ordered_settlements = sorted(
            settlements.values(),
            key=lambda item: bt.parse_dt(item.market_end_utc)
            or datetime.max.replace(tzinfo=timezone.utc),
        )
        self.next_settlement_idx = 0
        self.finalized: set[str] = set()

    def finalize_settled_markets(self, now: datetime) -> None:
        while self.next_settlement_idx < len(self.ordered_settlements):
            settlement = self.ordered_settlements[self.next_settlement_idx]
            market_end_dt = bt.parse_dt(settlement.market_end_utc)
            if market_end_dt is None or market_end_dt > now:
                break
            self.next_settlement_idx += 1
            if settlement.market_slug in self.finalized:
                continue
            self.finalized.add(settlement.market_slug)
            state = self.states.get(settlement.market_slug)
            if state is None or state.total_cost <= 0:
                continue
            _, roi, is_win = market_pnl_and_roi(state, settlement)
            self.recent_results.append((roi, is_win))

    def process_snapshot(self, snapshot: dict[str, Any]) -> None:
        slug = str(snapshot.get("market_slug") or "")
        settlement = self.settlements.get(slug)
        if settlement is None:
            return
        now = snapshot["_dt"]
        self.finalize_settled_markets(now)
        state = self.states[slug]
        market_start_dt = bt.parse_dt(
            snapshot.get("market_start_utc") or settlement.market_start_utc
        )
        elapsed_seconds = (
            (now - market_start_dt).total_seconds() if market_start_dt else None
        )
        signals = bt.build_signals(snapshot, self.cfg)
        if signals and not bt.passes_time_gate(elapsed_seconds, self.cfg):
            return

        for signal in signals:
            last_signal = state.last_signal_ts.get(signal.side)
            if (
                last_signal is not None
                and (now - last_signal).total_seconds()
                < self.cfg.signal_cooldown_seconds
            ):
                continue
            state.last_signal_ts[signal.side] = now

            if (
                state.last_order_ts is not None
                and (now - state.last_order_ts).total_seconds()
                < self.cfg.order_cooldown_seconds
            ):
                continue

            allowed, is_extension = bt.can_pass_exposure(state, signal, self.cfg, now)
            if not allowed:
                continue

            order_index = state.yes_orders + state.down_orders + 1
            self.rows.append(
                row_from_order(
                    snapshot=snapshot,
                    settlement=settlement,
                    state=state,
                    signal=signal,
                    cfg=self.cfg,
                    is_extension=is_extension,
                    recent_results=self.recent_results,
                    order_index_in_market=order_index,
                )
            )
            state.add_fill(
                side=signal.side,
                amount_usd=self.cfg.trade_amount_usd,
                execution_price=signal.max_execution_price,
                fee_rate_bps=bt.fee_rate_for_side(settlement, signal.side),
                snapshot_dt=now,
                market_start_dt=market_start_dt,
                is_extension=is_extension,
            )


def row_from_order(
    *,
    snapshot: dict[str, Any],
    settlement: bt.Settlement,
    state: bt.MarketState,
    signal: bt.Signal,
    cfg: bt.ReplayConfig,
    is_extension: bool,
    recent_results: deque[tuple[float, bool]],
    order_index_in_market: int,
) -> dict[str, Any]:
    now: datetime = snapshot["_dt"]
    market_start_dt = bt.parse_dt(snapshot.get("market_start_utc") or settlement.market_start_utc)
    elapsed_seconds = (now - market_start_dt).total_seconds() if market_start_dt else None
    remaining_seconds = optional_float(snapshot.get("remaining_seconds"))
    yes_bid = optional_float(snapshot.get("yes_bid"))
    yes_ask = optional_float(snapshot.get("yes_ask"))
    down_bid = optional_float(snapshot.get("down_bid"))
    down_ask = optional_float(snapshot.get("down_ask"))
    bn_price = optional_float(snapshot.get("bn_price"))
    bn_open_price = optional_float(snapshot.get("bn_open_price"))
    side_cost = state.side_cost(signal.side)
    opposite_cost = state.opposite_cost(signal.side)
    fee_rate = bt.fee_rate_for_side(settlement, signal.side)
    _, fee_usdc, net_shares = bt.estimate_taker_buy_execution(
        cfg.trade_amount_usd,
        signal.max_execution_price,
        fee_rate,
    )
    would_win = signal.side == settlement.resolved_side
    single_order_pnl = (
        net_shares if would_win else 0.0
    ) - cfg.trade_amount_usd - fee_usdc
    single_order_pnl_per_usd = (
        single_order_pnl / cfg.trade_amount_usd
        if cfg.trade_amount_usd > 0
        else 0.0
    )
    rolling = rolling_features(recent_results)

    row = {
        "recorded_at": now.isoformat(),
        "market_slug": settlement.market_slug,
        "market_start_utc": settlement.market_start_utc,
        "market_end_utc": settlement.market_end_utc,
        "market_day": settlement.market_start_utc[:10],
        "source_event": snapshot.get("source_event", ""),
        "side": signal.side,
        "is_baseline_order": True,
        "order_index_in_market": order_index_in_market,
        "side_is_up": 1.0 if signal.side == "UP" else 0.0,
        "elapsed_seconds": elapsed_seconds,
        "remaining_seconds": remaining_seconds,
        "fair": signal.fair,
        "edge": signal.edge,
        "edge_after_fill": signal.edge_after_fill,
        "bid": signal.bid,
        "ask": signal.ask,
        "spread": signal.spread,
        "limit_price": signal.max_execution_price,
        "bn_price": bn_price,
        "bn_open_price": bn_open_price,
        "bn_return_from_open": ratio_return(bn_price, bn_open_price),
        "sigma_short": optional_float(snapshot.get("sigma_short")),
        "sigma_long": optional_float(snapshot.get("sigma_long")),
        "sigma_eff": optional_float(snapshot.get("sigma_eff")),
        "tau_seconds": optional_float(snapshot.get("tau_seconds")),
        "z": optional_float(snapshot.get("z")),
        "yes_bid": yes_bid,
        "yes_ask": yes_ask,
        "down_bid": down_bid,
        "down_ask": down_ask,
        "yes_mid": optional_float(snapshot.get("yes_mid")),
        "down_mid": optional_float(snapshot.get("down_mid")),
        "side_cost": side_cost,
        "opposite_cost": opposite_cost,
        "total_cost": state.total_cost,
        "is_extension_order": 1.0 if is_extension else 0.0,
        "utc_hour": float(now.astimezone(timezone.utc).hour),
        "utc_day_of_week": float(now.astimezone(timezone.utc).weekday()),
        "rolling_6_market_roi": rolling["rolling_6_market_roi"],
        "rolling_10_market_roi": rolling["rolling_10_market_roi"],
        "rolling_10_market_win_rate": rolling["rolling_10_market_win_rate"],
        "resolved_side": settlement.resolved_side,
        "would_win": would_win,
        "single_order_pnl": single_order_pnl,
        "single_order_pnl_per_usd": single_order_pnl_per_usd,
        "single_order_fee_usdc": fee_usdc,
        "single_order_net_shares": net_shares,
        "amount_usd": cfg.trade_amount_usd,
    }
    return row


def build_dataset(
    snapshots: list[dict[str, Any]],
    settlements: dict[str, bt.Settlement],
    cfg: bt.ReplayConfig,
) -> list[dict[str, Any]]:
    replay = DatasetReplay(settlements, cfg)
    for snapshot in snapshots:
        replay.process_snapshot(snapshot)
    return replay.rows


def load_filtered_snapshots_for_path(
    *,
    path: Path,
    settlements: dict[str, bt.Settlement],
    source_filter: set[str],
    source_mode: str,
    strict_jsonl: bool,
    stats: bt.SnapshotLoadStats,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    stats.files_read += 1
    with bt.open_snapshot_text(path) as handle:
        for line_no, line in enumerate(handle, start=1):
            stats.total_lines += 1
            text = line.strip()
            if not text:
                stats.empty_lines += 1
                continue
            try:
                item = json.loads(text)
            except json.JSONDecodeError as exc:
                stats.bad_json_lines += 1
                if len(stats.bad_json_samples) < 5:
                    preview = text[:160]
                    stats.bad_json_samples.append(
                        f"{path}:{line_no}: {exc}; preview={preview!r}"
                    )
                if strict_jsonl:
                    raise ValueError(
                        f"Invalid JSONL at {path}:{line_no}: {exc}"
                    ) from exc
                continue
            stats.valid_json_lines += 1
            slug = str(item.get("market_slug") or "")
            source_event = str(item.get("source_event") or "")
            stats.source_counts[source_event or "<missing>"] += 1
            stats.market_counts[slug or "<missing>"] += 1
            if slug not in settlements:
                stats.skipped_missing_settlement += 1
                continue
            if source_mode != "all" and source_event not in source_filter:
                stats.skipped_source += 1
                continue
            ts = bt.parse_dt(item.get("ts"))
            if ts is None:
                stats.bad_ts_lines += 1
                continue
            item["_dt"] = ts
            rows.append(item)
            stats.mark_loaded(item, ts)
    rows.sort(key=lambda row: (row["_dt"], str(row.get("market_slug") or "")))
    return rows


def write_dataset(rows: list[dict[str, Any]], output_csv: Path) -> None:
    output_csv.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = IDENTIFIER_FIELDS + FEATURE_NAMES + LABEL_FIELDS
    with output_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a LightGBM signal-filter dataset.")
    parser.add_argument("--snapshot-dir", type=Path, default=Path("tick_snapshots"))
    parser.add_argument("--snapshot-glob", default="*.jsonl.gz")
    parser.add_argument("--ledger-dir", type=Path, default=Path("ledger"))
    parser.add_argument("--output-csv", type=Path, default=Path("analysis/ml_signal_dataset.csv"))
    parser.add_argument("--evaluate-sources", default=",".join(bt.DEFAULT_EVALUATE_SOURCES))
    parser.add_argument("--strict-jsonl", action="store_true")

    parser.add_argument("--edge-prob-threshold", type=float, default=0.18)
    parser.add_argument("--edge-reference-price", choices=["bid", "ask"], default="ask")
    parser.add_argument("--max-spread", type=float, default=0.02)
    parser.add_argument("--min-entry-ask-price", type=float, default=0.0)
    parser.add_argument("--min-edge-after-fill", type=float, default=0.24)
    parser.add_argument("--exec-price-mode", choices=["book", "edge", "hybrid"], default="hybrid")
    parser.add_argument("--exec-slippage-ticks", type=int, default=2)
    parser.add_argument("--exec-price-cap", type=float, default=0.99)
    parser.add_argument("--tick-size", type=float, default=0.01)
    parser.add_argument("--trade-amount-usd", type=float, default=1.0)
    parser.add_argument("--order-cooldown-seconds", type=float, default=3.0)
    parser.add_argument("--signal-cooldown-seconds", type=float, default=3.0)
    parser.add_argument("--market-max-total-cost", type=float, default=12.0)
    parser.add_argument("--market-max-side-cost", type=float, default=6.0)
    parser.add_argument("--side-extension-enabled", action="store_true", default=True)
    parser.add_argument("--no-side-extension", dest="side_extension_enabled", action="store_false")
    parser.add_argument("--side-extension-start-cost", type=float, default=6.0)
    parser.add_argument("--side-extension-max-side-cost", type=float, default=9.0)
    parser.add_argument("--side-extension-min-seconds", type=float, default=20.0)
    parser.add_argument("--side-extension-cooldown-seconds", type=float, default=15.0)
    parser.add_argument("--side-extension-min-edge", type=float, default=0.20)
    parser.add_argument("--side-extension-min-edge-after-fill", type=float, default=0.18)
    parser.add_argument("--side-extension-min-ask-price", type=float, default=0.40)
    parser.add_argument("--side-extension-max-ask-price", type=float, default=0.80)
    parser.add_argument("--side-extension-max-opposite-cost", type=float, default=1.0)
    parser.add_argument("--fair-mode", choices=["snapshot", "recompute"], default="snapshot")
    parser.add_argument("--sigma-short-weight", type=float, default=0.75)
    parser.add_argument("--sigma-long-weight", type=float, default=0.25)
    parser.add_argument("--sigma-min", type=float, default=0.000015)
    parser.add_argument("--tau-floor-seconds", type=float, default=5.0)
    parser.add_argument("--z-cap", type=float, default=6.0)
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    settlements = bt.load_settlements(args.ledger_dir)
    source_mode = args.evaluate_sources.strip().lower()
    source_filter = set() if source_mode == "all" else set(bt.parse_str_list(args.evaluate_sources))
    stats = bt.SnapshotLoadStats()
    paths = bt.iter_snapshot_paths(args.snapshot_dir, args.snapshot_glob)
    cfg = baseline_config(args)
    replay = DatasetReplay(settlements, cfg)
    for path in paths:
        snapshots = load_filtered_snapshots_for_path(
            path=path,
            settlements=settlements,
            source_filter=source_filter,
            source_mode=source_mode,
            strict_jsonl=args.strict_jsonl,
            stats=stats,
        )
        for snapshot in snapshots:
            replay.process_snapshot(snapshot)
    bt.print_snapshot_quality(stats)
    if stats.loaded_rows <= 0:
        raise SystemExit("No usable snapshots found.")
    write_dataset(replay.rows, args.output_csv)
    print(f"Wrote dataset rows={len(replay.rows)} to {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
