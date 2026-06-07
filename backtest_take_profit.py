#!/usr/bin/env python3
"""
Replay bot tick snapshots with a fixed take-profit exit policy.

This research backtester reuses the same entry-side logic as backtest_ticks.py,
but adds an intra-market full-exit state machine:

- build positions using the existing entry rules
- monitor quote-complete snapshots for take-profit opportunities
- liquidate the full market inventory at bid when the configured target hits
- prohibit any re-entry after an early close
- otherwise hold the inventory to market settlement
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional, Sequence

from backtest_ticks import (
    DEFAULT_EVALUATE_SOURCES,
    ReplayConfig,
    Settlement,
    TailReversalProfile,
    build_arg_parser as build_tick_arg_parser,
    build_configs as build_tick_configs,
    build_signals,
    build_tail_reversal_profiles,
    can_pass_exposure,
    compute_max_drawdown,
    estimate_taker_buy_execution,
    fee_rate_for_side,
    format_time_windows,
    load_settlements,
    load_snapshots,
    optional_float,
    parse_dt,
    parse_float_list,
    parse_int_list,
    parse_str_list,
    percentile,
    print_snapshot_quality,
    safe_float,
    tail_reversal_hit_for_market,
)


TW_TZ = timezone(timedelta(hours=8))


def parse_bool_list(raw: str) -> list[bool]:
    truthy = {"1", "true", "yes", "on"}
    falsy = {"0", "false", "no", "off"}
    values: list[bool] = []
    for item in raw.split(","):
        token = item.strip().lower()
        if not token:
            continue
        if token in truthy:
            values.append(True)
            continue
        if token in falsy:
            values.append(False)
            continue
        raise ValueError(f"Invalid boolean value '{item.strip()}'. Use true/false style tokens.")
    return values


@dataclass(frozen=True)
class WeakRegimeConfig:
    enabled: bool
    settled_lookback_markets: int
    min_settled_markets: int
    roi_trigger: float
    win_rate_trigger: float
    tail_hit_lookback_seconds: float
    tail_hit_trigger: int
    weekend_prior_enabled: bool
    on_score: int
    off_score: int
    off_confirm_settled_markets: int

    def label(self) -> str:
        if not self.enabled:
            return "weakTP=off"
        weekend = "+wknd" if self.weekend_prior_enabled else ""
        return (
            "weakTP="
            f"n{self.settled_lookback_markets}/min{self.min_settled_markets} "
            f"roi<={self.roi_trigger:g} "
            f"wr<={self.win_rate_trigger:g} "
            f"tail={self.tail_hit_trigger}/{self.tail_hit_lookback_seconds:g}s"
            f"{weekend} "
            f"score{self.on_score}->{self.off_score}:{self.off_confirm_settled_markets}"
        )


@dataclass(frozen=True)
class TakeProfitConfig:
    base: ReplayConfig
    weak_regime: WeakRegimeConfig
    tp_delta: float
    tp_min_hold_seconds: float
    tp_confirm_snapshots: int
    tp_disable_last_seconds: float

    def label(self) -> str:
        return (
            f"{self.base.label()} "
            f"{self.weak_regime.label()} "
            f"tp={self.tp_delta:g} "
            f"minHold={self.tp_min_hold_seconds:g}s "
            f"confirm={self.tp_confirm_snapshots} "
            f"disableLast={self.tp_disable_last_seconds:g}s"
        )


@dataclass
class TakeProfitMarketState:
    yes_cost: float = 0.0
    down_cost: float = 0.0
    yes_shares: float = 0.0
    down_shares: float = 0.0
    fee_total: float = 0.0
    yes_orders: int = 0
    down_orders: int = 0
    last_order_ts: Optional[datetime] = None
    last_signal_ts: dict[str, datetime] = None  # type: ignore[assignment]
    extension_start_ts: dict[str, Optional[datetime]] = None  # type: ignore[assignment]
    last_extension_order_ts: dict[str, Optional[datetime]] = None  # type: ignore[assignment]
    first_order_elapsed: Optional[float] = None
    last_order_elapsed: Optional[float] = None
    price_bands: dict[str, int] = None  # type: ignore[assignment]
    tp_qualifying_streaks: dict[str, int] = None  # type: ignore[assignment]
    closed_early: bool = False
    close_reason: Optional[str] = None
    close_ts: Optional[datetime] = None
    close_elapsed_seconds: Optional[float] = None
    trigger_side: Optional[str] = None
    exit_fee_total: float = 0.0
    realized_exit_proceeds: float = 0.0
    hold_to_settlement_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    delta_vs_hold: Optional[float] = None
    exit_yes_bid: Optional[float] = None
    exit_down_bid: Optional[float] = None
    weak_regime_on_first_fill: Optional[bool] = None
    weak_regime_seen: bool = False
    weak_regime_fill_count: int = 0
    weak_regime_active_on_exit: bool = False

    def __post_init__(self) -> None:
        if self.last_signal_ts is None:
            self.last_signal_ts = {}
        if self.extension_start_ts is None:
            self.extension_start_ts = {"UP": None, "DOWN": None}
        if self.last_extension_order_ts is None:
            self.last_extension_order_ts = {"UP": None, "DOWN": None}
        if self.price_bands is None:
            self.price_bands = defaultdict(int)
        if self.tp_qualifying_streaks is None:
            self.tp_qualifying_streaks = {"UP": 0, "DOWN": 0}

    @property
    def total_cost(self) -> float:
        return self.yes_cost + self.down_cost

    def side_cost(self, side: str) -> float:
        return self.yes_cost if side == "UP" else self.down_cost

    def opposite_cost(self, side: str) -> float:
        return self.down_cost if side == "UP" else self.yes_cost

    def side_shares(self, side: str) -> float:
        return self.yes_shares if side == "UP" else self.down_shares

    def avg_entry_price(self, side: str) -> Optional[float]:
        shares = self.side_shares(side)
        if shares <= 0:
            return None
        return self.side_cost(side) / shares

    def entry_side_summary(self) -> str:
        has_up = self.yes_orders > 0
        has_down = self.down_orders > 0
        if has_up and has_down:
            return "UP+DOWN"
        if has_up:
            return "UP"
        if has_down:
            return "DOWN"
        return "NONE"

    def reset_tp_streaks(self) -> None:
        self.tp_qualifying_streaks["UP"] = 0
        self.tp_qualifying_streaks["DOWN"] = 0

    def add_fill(
        self,
        *,
        side: str,
        amount_usd: float,
        execution_price: float,
        fee_rate_bps: float,
        snapshot_dt: datetime,
        market_start_dt: Optional[datetime],
        is_extension: bool,
        weak_regime_active: bool,
    ) -> None:
        if self.first_order_elapsed is None:
            self.weak_regime_on_first_fill = weak_regime_active
        if weak_regime_active:
            self.weak_regime_seen = True
            self.weak_regime_fill_count += 1
        _, fee_usdc, net_shares = estimate_taker_buy_execution(amount_usd, execution_price, fee_rate_bps)
        if side == "UP":
            self.yes_cost += amount_usd
            self.yes_shares += net_shares
            self.yes_orders += 1
        else:
            self.down_cost += amount_usd
            self.down_shares += net_shares
            self.down_orders += 1
        self.fee_total += fee_usdc
        self.last_order_ts = snapshot_dt
        if is_extension:
            self.last_extension_order_ts[side] = snapshot_dt
        if market_start_dt:
            elapsed = (snapshot_dt - market_start_dt).total_seconds()
            self.first_order_elapsed = elapsed if self.first_order_elapsed is None else min(self.first_order_elapsed, elapsed)
            self.last_order_elapsed = elapsed if self.last_order_elapsed is None else max(self.last_order_elapsed, elapsed)


@dataclass(frozen=True)
class TakeProfitMarketOutcome:
    config_label: str
    market_slug: str
    market_start_utc: str
    market_end_utc: str
    segment: str
    resolved_side: str
    traded_market: bool
    entry_side_summary: str
    yes_orders: int
    down_orders: int
    yes_avg_entry: Optional[float]
    down_avg_entry: Optional[float]
    closed_early: bool
    close_reason: str
    trigger_side: str
    close_ts: str
    close_elapsed_seconds: Optional[float]
    tp_delta: float
    tp_min_hold_seconds: float
    tp_confirm_snapshots: int
    tp_disable_last_seconds: float
    exit_yes_bid: Optional[float]
    exit_down_bid: Optional[float]
    entry_fee_total: float
    exit_fee_total: float
    realized_exit_proceeds: float
    market_pnl: float
    hold_to_settlement_pnl: float
    delta_vs_hold: float
    total_cost: float
    orders: int
    weak_regime_on_first_fill: Optional[bool]
    weak_regime_seen: bool
    weak_regime_fill_count: int
    weak_regime_active_on_exit: bool


@dataclass(frozen=True)
class TakeProfitReplayResult:
    config: TakeProfitConfig
    segment: str
    settled_markets: int
    traded_markets: int
    closed_early_markets: int
    early_close_rate: float
    orders: int
    total_cost: float
    total_pnl: float
    roi: float
    wins: int
    losses: int
    win_rate: float
    max_drawdown: float
    avg_exit_elapsed_seconds: float
    avg_delta_vs_hold: float
    rescued_loss_markets: int
    clipped_winner_markets: int
    hold_baseline_total_pnl: float
    hold_baseline_roi: float
    delta_total_pnl_vs_hold: float
    delta_roi_vs_hold: float
    median_day_roi: Optional[float]
    worst_day_roi: Optional[float]
    best_day_roi: Optional[float]
    day_count: int
    weak_regime_traded_markets: int
    weak_regime_entry_markets: int
    weak_regime_closed_early_markets: int


def estimate_taker_sell_execution(shares: float, price: float, fee_rate_bps: float) -> tuple[float, float, float]:
    if shares <= 0 or price <= 0:
        return 0.0, 0.0, 0.0
    fee_rate = fee_rate_bps / 10000.0
    gross_usdc = shares * price
    fee_usdc = round((shares * fee_rate * price * (1.0 - price)) + 1e-12, 5)
    net_usdc = max(gross_usdc - fee_usdc, 0.0)
    return gross_usdc, fee_usdc, net_usdc


def market_segment(settlement: Settlement) -> str:
    return settlement.market_start_utc[:10]


def summary_segments(outcomes: Sequence[TakeProfitMarketOutcome]) -> list[str]:
    return ["combined", *sorted({outcome.segment for outcome in outcomes})]


def snapshot_bid(snapshot: dict[str, object], side: str) -> Optional[float]:
    field = "yes_bid" if side == "UP" else "down_bid"
    return optional_float(snapshot.get(field))


def weekend_prior_active(now: datetime) -> bool:
    local = now.astimezone(TW_TZ)
    weekday = local.weekday()
    hour = local.hour + (local.minute / 60.0) + (local.second / 3600.0)
    if weekday == 4:
        return hour >= 20.0
    if weekday == 5:
        return True
    if weekday == 6:
        return True
    if weekday == 0:
        return hour < 8.0
    return False


def trim_tail_hit_times(hit_times: deque[datetime], now: datetime, lookback_seconds: float) -> None:
    if lookback_seconds <= 0:
        hit_times.clear()
        return
    while hit_times and (now - hit_times[0]).total_seconds() > lookback_seconds:
        hit_times.popleft()


def weak_regime_score(
    weak_cfg: WeakRegimeConfig,
    now: datetime,
    recent_traded_settlements: deque[tuple[datetime, float, float, bool]],
    recent_tail_hit_times: deque[datetime],
) -> int:
    score = 0

    if weak_cfg.weekend_prior_enabled and weekend_prior_active(now):
        score += 1

    trim_tail_hit_times(recent_tail_hit_times, now, weak_cfg.tail_hit_lookback_seconds)
    tail_hits = len(recent_tail_hit_times)
    if weak_cfg.tail_hit_trigger > 0 and tail_hits >= weak_cfg.tail_hit_trigger:
        score += 2
    elif weak_cfg.tail_hit_trigger > 1 and tail_hits == (weak_cfg.tail_hit_trigger - 1):
        score += 1

    if weak_cfg.settled_lookback_markets <= 0:
        return score

    recent_rows = list(recent_traded_settlements)[-weak_cfg.settled_lookback_markets :]
    if len(recent_rows) < weak_cfg.min_settled_markets:
        return score

    total_cost = sum(row[2] for row in recent_rows)
    total_pnl = sum(row[1] for row in recent_rows)
    recent_roi = (total_pnl / total_cost) if total_cost > 0 else 0.0
    recent_win_rate = sum(1 for row in recent_rows if row[3]) / len(recent_rows)
    if recent_roi <= weak_cfg.roi_trigger:
        score += 2
    if recent_win_rate <= weak_cfg.win_rate_trigger:
        score += 1
    return score


def market_has_complete_exit_quote(state: TakeProfitMarketState, snapshot: dict[str, object]) -> bool:
    if snapshot.get("quote_complete") is not True:
        return False
    if state.yes_shares > 0 and (snapshot_bid(snapshot, "UP") or 0.0) <= 0:
        return False
    if state.down_shares > 0 and (snapshot_bid(snapshot, "DOWN") or 0.0) <= 0:
        return False
    return state.yes_shares > 0 or state.down_shares > 0


def maybe_take_profit_exit(
    state: TakeProfitMarketState,
    settlement: Settlement,
    snapshot: dict[str, object],
    now: datetime,
    market_start_dt: Optional[datetime],
    cfg: TakeProfitConfig,
    *,
    weak_regime_active: bool,
) -> bool:
    if state.closed_early or state.total_cost <= 0:
        return False
    if not market_has_complete_exit_quote(state, snapshot):
        state.reset_tp_streaks()
        return False

    remaining_seconds = optional_float(snapshot.get("remaining_seconds"))
    if remaining_seconds is None:
        state.reset_tp_streaks()
        return False
    if cfg.tp_disable_last_seconds > 0 and remaining_seconds <= cfg.tp_disable_last_seconds:
        state.reset_tp_streaks()
        return False

    if market_start_dt is None or state.first_order_elapsed is None:
        state.reset_tp_streaks()
        return False

    elapsed_seconds = (now - market_start_dt).total_seconds()
    held_seconds = elapsed_seconds - state.first_order_elapsed
    if held_seconds < cfg.tp_min_hold_seconds:
        state.reset_tp_streaks()
        return False

    qualifying_sides: list[tuple[str, float]] = []
    for side in ("UP", "DOWN"):
        shares = state.side_shares(side)
        if shares <= 0:
            state.tp_qualifying_streaks[side] = 0
            continue
        bid = snapshot_bid(snapshot, side)
        avg_entry = state.avg_entry_price(side)
        if bid is None or bid <= 0 or avg_entry is None:
            state.tp_qualifying_streaks[side] = 0
            continue
        delta = bid - avg_entry
        if delta >= cfg.tp_delta:
            state.tp_qualifying_streaks[side] += 1
            if state.tp_qualifying_streaks[side] >= cfg.tp_confirm_snapshots:
                qualifying_sides.append((side, delta))
        else:
            state.tp_qualifying_streaks[side] = 0

    if not qualifying_sides:
        return False

    qualifying_sides.sort(key=lambda item: (item[1], item[0] == "UP"), reverse=True)
    trigger_side = qualifying_sides[0][0]

    hold_to_settlement_pnl = (
        state.yes_shares if settlement.resolved_side == "UP" else state.down_shares
    ) - state.total_cost - state.fee_total

    exit_fee_total = 0.0
    realized_exit_proceeds = 0.0
    exit_yes_bid = snapshot_bid(snapshot, "UP")
    exit_down_bid = snapshot_bid(snapshot, "DOWN")

    if state.yes_shares > 0 and exit_yes_bid is not None and exit_yes_bid > 0:
        _, fee_usdc, net_usdc = estimate_taker_sell_execution(
            state.yes_shares,
            exit_yes_bid,
            fee_rate_for_side(settlement, "UP"),
        )
        exit_fee_total += fee_usdc
        realized_exit_proceeds += net_usdc
    if state.down_shares > 0 and exit_down_bid is not None and exit_down_bid > 0:
        _, fee_usdc, net_usdc = estimate_taker_sell_execution(
            state.down_shares,
            exit_down_bid,
            fee_rate_for_side(settlement, "DOWN"),
        )
        exit_fee_total += fee_usdc
        realized_exit_proceeds += net_usdc

    realized_pnl = realized_exit_proceeds - state.total_cost - state.fee_total

    state.closed_early = True
    state.close_reason = "take_profit"
    state.close_ts = now
    state.close_elapsed_seconds = elapsed_seconds
    state.trigger_side = trigger_side
    state.exit_fee_total = exit_fee_total
    state.realized_exit_proceeds = realized_exit_proceeds
    state.hold_to_settlement_pnl = hold_to_settlement_pnl
    state.realized_pnl = realized_pnl
    state.delta_vs_hold = realized_pnl - hold_to_settlement_pnl
    state.exit_yes_bid = exit_yes_bid
    state.exit_down_bid = exit_down_bid
    state.weak_regime_active_on_exit = weak_regime_active
    state.reset_tp_streaks()
    return True


def finalize_settlement_close(
    state: TakeProfitMarketState,
    settlement: Settlement,
) -> None:
    if state.closed_early:
        return
    market_end_dt = parse_dt(settlement.market_end_utc)
    elapsed_seconds = None
    market_start_dt = parse_dt(settlement.market_start_utc)
    if market_end_dt and market_start_dt:
        elapsed_seconds = (market_end_dt - market_start_dt).total_seconds()
    hold_pnl = (
        state.yes_shares if settlement.resolved_side == "UP" else state.down_shares
    ) - state.total_cost - state.fee_total
    state.close_reason = "settlement"
    state.close_ts = market_end_dt
    state.close_elapsed_seconds = elapsed_seconds
    state.trigger_side = None
    state.exit_fee_total = 0.0
    state.realized_exit_proceeds = 0.0
    state.hold_to_settlement_pnl = hold_pnl
    state.realized_pnl = hold_pnl
    state.delta_vs_hold = 0.0


def build_market_outcomes(
    settlements: dict[str, Settlement],
    states: dict[str, TakeProfitMarketState],
    cfg: TakeProfitConfig,
) -> list[TakeProfitMarketOutcome]:
    outcomes: list[TakeProfitMarketOutcome] = []
    for slug, settlement in sorted(settlements.items(), key=lambda item: item[1].market_start_utc):
        state = states.get(slug)
        if state is None:
            outcomes.append(
                TakeProfitMarketOutcome(
                    config_label=cfg.label(),
                    market_slug=slug,
                    market_start_utc=settlement.market_start_utc,
                    market_end_utc=settlement.market_end_utc,
                    segment=market_segment(settlement),
                    resolved_side=settlement.resolved_side,
                    traded_market=False,
                    entry_side_summary="NONE",
                    yes_orders=0,
                    down_orders=0,
                    yes_avg_entry=None,
                    down_avg_entry=None,
                    closed_early=False,
                    close_reason="",
                    trigger_side="",
                    close_ts="",
                    close_elapsed_seconds=None,
                    tp_delta=cfg.tp_delta,
                    tp_min_hold_seconds=cfg.tp_min_hold_seconds,
                    tp_confirm_snapshots=cfg.tp_confirm_snapshots,
                    tp_disable_last_seconds=cfg.tp_disable_last_seconds,
                    exit_yes_bid=None,
                    exit_down_bid=None,
                    entry_fee_total=0.0,
                    exit_fee_total=0.0,
                    realized_exit_proceeds=0.0,
                    market_pnl=0.0,
                    hold_to_settlement_pnl=0.0,
                    delta_vs_hold=0.0,
                    total_cost=0.0,
                    orders=0,
                    weak_regime_on_first_fill=None,
                    weak_regime_seen=False,
                    weak_regime_fill_count=0,
                    weak_regime_active_on_exit=False,
                )
            )
            continue

        if state.total_cost > 0 and state.realized_pnl is None:
            finalize_settlement_close(state, settlement)

        outcomes.append(
            TakeProfitMarketOutcome(
                config_label=cfg.label(),
                market_slug=slug,
                market_start_utc=settlement.market_start_utc,
                market_end_utc=settlement.market_end_utc,
                segment=market_segment(settlement),
                resolved_side=settlement.resolved_side,
                traded_market=state.total_cost > 0,
                entry_side_summary=state.entry_side_summary(),
                yes_orders=state.yes_orders,
                down_orders=state.down_orders,
                yes_avg_entry=state.avg_entry_price("UP"),
                down_avg_entry=state.avg_entry_price("DOWN"),
                closed_early=state.closed_early,
                close_reason=state.close_reason or "",
                trigger_side=state.trigger_side or "",
                close_ts=state.close_ts.isoformat() if state.close_ts else "",
                close_elapsed_seconds=state.close_elapsed_seconds,
                tp_delta=cfg.tp_delta,
                tp_min_hold_seconds=cfg.tp_min_hold_seconds,
                tp_confirm_snapshots=cfg.tp_confirm_snapshots,
                tp_disable_last_seconds=cfg.tp_disable_last_seconds,
                exit_yes_bid=state.exit_yes_bid,
                exit_down_bid=state.exit_down_bid,
                entry_fee_total=state.fee_total,
                exit_fee_total=state.exit_fee_total,
                realized_exit_proceeds=state.realized_exit_proceeds,
                market_pnl=state.realized_pnl or 0.0,
                hold_to_settlement_pnl=state.hold_to_settlement_pnl or 0.0,
                delta_vs_hold=state.delta_vs_hold or 0.0,
                total_cost=state.total_cost,
                orders=state.yes_orders + state.down_orders,
                weak_regime_on_first_fill=state.weak_regime_on_first_fill,
                weak_regime_seen=state.weak_regime_seen,
                weak_regime_fill_count=state.weak_regime_fill_count,
                weak_regime_active_on_exit=state.weak_regime_active_on_exit,
            )
        )
    return outcomes


def aggregate_segment_results(
    cfg: TakeProfitConfig,
    outcomes: Sequence[TakeProfitMarketOutcome],
) -> list[TakeProfitReplayResult]:
    by_segment: dict[str, list[TakeProfitMarketOutcome]] = defaultdict(list)
    for outcome in outcomes:
        by_segment[outcome.segment].append(outcome)
        by_segment["combined"].append(outcome)

    day_rois = {}
    for segment, rows in by_segment.items():
        if segment == "combined":
            continue
        traded_rows = [row for row in rows if row.traded_market]
        total_cost = sum(row.total_cost for row in traded_rows)
        total_pnl = sum(row.market_pnl for row in traded_rows)
        day_rois[segment] = total_pnl / total_cost if total_cost > 0 else 0.0

    results: list[TakeProfitReplayResult] = []
    for segment in summary_segments(outcomes):
        rows = by_segment[segment]
        traded_rows = [row for row in rows if row.traded_market]
        market_pnls = [row.market_pnl for row in traded_rows]
        total_cost = sum(row.total_cost for row in traded_rows)
        total_pnl = sum(market_pnls)
        hold_total_pnl = sum(row.hold_to_settlement_pnl for row in traded_rows)
        hold_roi = hold_total_pnl / total_cost if total_cost > 0 else 0.0
        roi = total_pnl / total_cost if total_cost > 0 else 0.0
        wins = sum(1 for pnl in market_pnls if pnl > 0)
        losses = sum(1 for pnl in market_pnls if pnl <= 0)
        closed_rows = [row for row in traded_rows if row.closed_early]
        exit_elapsed_values = [row.close_elapsed_seconds for row in closed_rows if row.close_elapsed_seconds is not None]
        delta_values = [row.delta_vs_hold for row in closed_rows]

        median_day_roi = None
        worst_day_roi = None
        best_day_roi = None
        day_count = 0
        if segment == "combined" and day_rois:
            ordered_day_rois = sorted(day_rois.values())
            day_count = len(ordered_day_rois)
            median_day_roi = percentile(ordered_day_rois, 0.50)
            worst_day_roi = min(ordered_day_rois)
            best_day_roi = max(ordered_day_rois)

        results.append(
            TakeProfitReplayResult(
                config=cfg,
                segment=segment,
                settled_markets=len(rows),
                traded_markets=len(traded_rows),
                closed_early_markets=len(closed_rows),
                early_close_rate=(len(closed_rows) / len(traded_rows)) if traded_rows else 0.0,
                orders=sum(row.orders for row in traded_rows),
                total_cost=total_cost,
                total_pnl=total_pnl,
                roi=roi,
                wins=wins,
                losses=losses,
                win_rate=(wins / len(traded_rows)) if traded_rows else 0.0,
                max_drawdown=compute_max_drawdown(market_pnls),
                avg_exit_elapsed_seconds=(sum(exit_elapsed_values) / len(exit_elapsed_values)) if exit_elapsed_values else 0.0,
                avg_delta_vs_hold=(sum(delta_values) / len(delta_values)) if delta_values else 0.0,
                rescued_loss_markets=sum(
                    1
                    for row in closed_rows
                    if row.hold_to_settlement_pnl < 0 and row.market_pnl > row.hold_to_settlement_pnl
                ),
                clipped_winner_markets=sum(
                    1
                    for row in closed_rows
                    if row.hold_to_settlement_pnl > 0 and row.market_pnl < row.hold_to_settlement_pnl
                ),
                hold_baseline_total_pnl=hold_total_pnl,
                hold_baseline_roi=hold_roi,
                delta_total_pnl_vs_hold=total_pnl - hold_total_pnl,
                delta_roi_vs_hold=roi - hold_roi,
                median_day_roi=median_day_roi,
                worst_day_roi=worst_day_roi,
                best_day_roi=best_day_roi,
                day_count=day_count,
                weak_regime_traded_markets=sum(1 for row in traded_rows if row.weak_regime_seen),
                weak_regime_entry_markets=sum(1 for row in traded_rows if row.weak_regime_on_first_fill is True),
                weak_regime_closed_early_markets=sum(1 for row in closed_rows if row.weak_regime_active_on_exit),
            )
        )
    return results


def replay_take_profit_config(
    snapshots: Sequence[dict[str, object]],
    settlements: dict[str, Settlement],
    tail_profiles: dict[str, TailReversalProfile],
    cfg: TakeProfitConfig,
) -> tuple[list[TakeProfitReplayResult], list[TakeProfitMarketOutcome]]:
    states: dict[str, TakeProfitMarketState] = defaultdict(TakeProfitMarketState)
    cooldown_until: Optional[datetime] = None
    recent_tail_hit_times: deque[datetime] = deque()
    weak_recent_tail_hit_times: deque[datetime] = deque()
    weak_recent_traded_settlements: deque[tuple[datetime, float, float, bool]] = deque()
    weak_regime_active = False
    weak_regime_off_streak = 0
    weak_cfg = cfg.weak_regime
    ordered_settlements = sorted(
        settlements.values(),
        key=lambda item: parse_dt(item.market_end_utc) or datetime.max.replace(tzinfo=timezone.utc),
    )
    next_settlement_idx = 0

    def finalize_settled_markets(now: datetime) -> None:
        nonlocal cooldown_until
        nonlocal next_settlement_idx
        nonlocal weak_regime_active
        nonlocal weak_regime_off_streak
        while next_settlement_idx < len(ordered_settlements):
            settlement = ordered_settlements[next_settlement_idx]
            market_end_dt = parse_dt(settlement.market_end_utc)
            if market_end_dt is None or market_end_dt > now:
                break
            next_settlement_idx += 1
            state = states.get(settlement.market_slug)
            if state is not None and state.total_cost > 0 and state.realized_pnl is None:
                finalize_settlement_close(state, settlement)

            weak_trade_processed = False
            if weak_cfg.enabled:
                if state is not None and state.total_cost > 0:
                    weak_recent_traded_settlements.append(
                        (
                            market_end_dt,
                            state.realized_pnl or 0.0,
                            state.total_cost,
                            (state.realized_pnl or 0.0) > 0,
                        )
                    )
                    while len(weak_recent_traded_settlements) > max(weak_cfg.settled_lookback_markets, 0):
                        weak_recent_traded_settlements.popleft()
                    weak_trade_processed = True

                if (
                    state is not None
                    and state.total_cost > 0
                    and not state.closed_early
                    and weak_cfg.tail_hit_lookback_seconds > 0
                    and weak_cfg.tail_hit_trigger > 0
                ):
                    if tail_reversal_hit_for_market(
                        state,
                        settlement,
                        tail_profiles.get(settlement.market_slug),
                        cfg.base,
                    ):
                        weak_recent_tail_hit_times.append(market_end_dt)
                trim_tail_hit_times(weak_recent_tail_hit_times, market_end_dt, weak_cfg.tail_hit_lookback_seconds)

            if (
                cfg.base.tail_reversal_lookback_seconds <= 0
                or cfg.base.tail_reversal_trigger_count <= 0
                or cfg.base.tail_reversal_cooldown_seconds <= 0
            ):
                trim_tail_hit_times(recent_tail_hit_times, market_end_dt, cfg.base.tail_reversal_lookback_seconds)
            else:
                if state is None or state.total_cost <= 0 or state.closed_early:
                    trim_tail_hit_times(recent_tail_hit_times, market_end_dt, cfg.base.tail_reversal_lookback_seconds)
                else:
                    is_hit = tail_reversal_hit_for_market(
                        state,
                        settlement,
                        tail_profiles.get(settlement.market_slug),
                        cfg.base,
                    )
                    if is_hit:
                        recent_tail_hit_times.append(market_end_dt)
                    trim_tail_hit_times(recent_tail_hit_times, market_end_dt, cfg.base.tail_reversal_lookback_seconds)
                    if is_hit and len(recent_tail_hit_times) >= cfg.base.tail_reversal_trigger_count:
                        new_until = market_end_dt + timedelta(seconds=cfg.base.tail_reversal_cooldown_seconds)
                        if cooldown_until is None or new_until > cooldown_until:
                            cooldown_until = new_until

            if weak_cfg.enabled:
                score = weak_regime_score(
                    weak_cfg,
                    market_end_dt,
                    weak_recent_traded_settlements,
                    weak_recent_tail_hit_times,
                )
                if not weak_regime_active:
                    if score >= weak_cfg.on_score:
                        weak_regime_active = True
                        weak_regime_off_streak = 0
                else:
                    if weak_trade_processed:
                        if score <= weak_cfg.off_score:
                            weak_regime_off_streak += 1
                        else:
                            weak_regime_off_streak = 0
                        if weak_regime_off_streak >= weak_cfg.off_confirm_settled_markets:
                            weak_regime_active = False
                            weak_regime_off_streak = 0
                    elif score > weak_cfg.off_score:
                        weak_regime_off_streak = 0

    for snapshot in snapshots:
        slug = str(snapshot.get("market_slug") or "")
        settlement = settlements.get(slug)
        if settlement is None:
            continue
        now = snapshot["_dt"]  # type: ignore[index]
        finalize_settled_markets(now)
        state = states[slug]
        market_start_dt = parse_dt(snapshot.get("market_start_utc") or settlement.market_start_utc)
        elapsed_seconds = (now - market_start_dt).total_seconds() if market_start_dt else None

        if state.total_cost > 0 and not state.closed_early:
            if weak_cfg.enabled and weak_regime_active:
                state.weak_regime_seen = True
            if weak_cfg.enabled and not weak_regime_active:
                state.reset_tp_streaks()
            else:
                closed_now = maybe_take_profit_exit(
                    state,
                    settlement,
                    snapshot,
                    now,
                    market_start_dt,
                    cfg,
                    weak_regime_active=weak_regime_active,
                )
                if closed_now:
                    continue

        if state.closed_early:
            continue

        signals = build_signals(snapshot, cfg.base)
        if not signals:
            continue

        if cooldown_until is not None and now < cooldown_until:
            continue

        if elapsed_seconds is None:
            continue
        if cfg.base.entry_time_windows and not any(start <= elapsed_seconds < end for start, end in cfg.base.entry_time_windows):
            continue
        if cfg.base.block_time_windows and any(start <= elapsed_seconds < end for start, end in cfg.base.block_time_windows):
            continue

        for signal in signals:
            last_signal = state.last_signal_ts.get(signal.side)
            if last_signal is not None and (now - last_signal).total_seconds() < cfg.base.signal_cooldown_seconds:
                continue
            state.last_signal_ts[signal.side] = now

            if state.last_order_ts is not None and (now - state.last_order_ts).total_seconds() < cfg.base.order_cooldown_seconds:
                continue

            allowed, is_extension = can_pass_exposure(state, signal, cfg.base, now)
            if not allowed:
                continue

            state.add_fill(
                side=signal.side,
                amount_usd=cfg.base.trade_amount_usd,
                execution_price=signal.max_execution_price,
                fee_rate_bps=fee_rate_for_side(settlement, signal.side),
                snapshot_dt=now,
                market_start_dt=market_start_dt,
                is_extension=is_extension,
                weak_regime_active=weak_regime_active,
            )

    outcomes = build_market_outcomes(settlements, states, cfg)
    results = aggregate_segment_results(cfg, outcomes)
    return results, outcomes


def build_take_profit_configs(args) -> list[TakeProfitConfig]:
    base_configs = build_tick_configs(args)
    tp_deltas = parse_float_list(args.tp_delta_values)
    tp_min_hold_seconds = parse_float_list(args.tp_min_hold_seconds_values)
    tp_confirm_snapshots = parse_int_list(args.tp_confirm_snapshots_values)
    tp_disable_last_seconds = parse_float_list(args.tp_disable_last_seconds_values)
    weak_configs: list[WeakRegimeConfig]
    if args.weak_regime_tp_enabled:
        weak_configs = []
        for settled_lookback in parse_int_list(args.weak_regime_settled_lookback_markets_values):
            for min_settled in parse_int_list(args.weak_regime_min_settled_markets_values):
                for roi_trigger in parse_float_list(args.weak_regime_roi_trigger_values):
                    for win_rate_trigger in parse_float_list(args.weak_regime_win_rate_trigger_values):
                        for tail_lookback in parse_float_list(args.weak_regime_tail_hit_lookback_seconds_values):
                            for tail_trigger in parse_int_list(args.weak_regime_tail_hit_trigger_values):
                                for weekend_prior in parse_bool_list(args.weak_regime_weekend_prior_enabled_values):
                                    for on_score in parse_int_list(args.weak_regime_on_score_values):
                                        for off_score in parse_int_list(args.weak_regime_off_score_values):
                                            for off_confirm in parse_int_list(args.weak_regime_off_confirm_settled_markets_values):
                                                weak_configs.append(
                                                    WeakRegimeConfig(
                                                        enabled=True,
                                                        settled_lookback_markets=max(settled_lookback, 0),
                                                        min_settled_markets=max(min_settled, 0),
                                                        roi_trigger=roi_trigger,
                                                        win_rate_trigger=win_rate_trigger,
                                                        tail_hit_lookback_seconds=max(tail_lookback, 0.0),
                                                        tail_hit_trigger=max(tail_trigger, 0),
                                                        weekend_prior_enabled=weekend_prior,
                                                        on_score=max(on_score, 0),
                                                        off_score=max(off_score, 0),
                                                        off_confirm_settled_markets=max(off_confirm, 1),
                                                    )
                                                )
    else:
        weak_configs = [
            WeakRegimeConfig(
                enabled=False,
                settled_lookback_markets=0,
                min_settled_markets=0,
                roi_trigger=0.0,
                win_rate_trigger=0.0,
                tail_hit_lookback_seconds=0.0,
                tail_hit_trigger=0,
                weekend_prior_enabled=False,
                on_score=0,
                off_score=0,
                off_confirm_settled_markets=1,
            )
        ]

    configs: list[TakeProfitConfig] = []
    for base in base_configs:
        for weak in weak_configs:
            for tp_delta in tp_deltas:
                for min_hold in tp_min_hold_seconds:
                    for confirm in tp_confirm_snapshots:
                        for disable_last in tp_disable_last_seconds:
                            configs.append(
                                TakeProfitConfig(
                                    base=base,
                                    weak_regime=weak,
                                    tp_delta=tp_delta,
                                    tp_min_hold_seconds=min_hold,
                                    tp_confirm_snapshots=max(confirm, 1),
                                    tp_disable_last_seconds=max(disable_last, 0.0),
                                )
                            )
    return configs


def print_combined_results(results: Sequence[TakeProfitReplayResult], limit: int) -> None:
    combined = [result for result in results if result.segment == "combined"]
    if not combined:
        print("No take-profit replay results.")
        return
    ordered = sorted(combined, key=lambda item: (item.roi, item.delta_total_pnl_vs_hold), reverse=True)
    print(
        "rank,roi,total_pnl,total_cost,traded,closed_early,win_rate,max_dd,"
        "hold_roi,delta_vs_hold,median_day,worst_day,config"
    )
    for rank, result in enumerate(ordered[:limit], start=1):
        median_day = "" if result.median_day_roi is None else f"{result.median_day_roi:.4f}"
        worst_day = "" if result.worst_day_roi is None else f"{result.worst_day_roi:.4f}"
        print(
            f"{rank},"
            f"{result.roi:.4f},"
            f"{result.total_pnl:.2f},"
            f"{result.total_cost:.2f},"
            f"{result.traded_markets},"
            f"{result.closed_early_markets},"
            f"{result.win_rate:.4f},"
            f"{result.max_drawdown:.2f},"
            f"{result.hold_baseline_roi:.4f},"
            f"{result.delta_total_pnl_vs_hold:.2f},"
            f"{median_day},"
            f"{worst_day},"
            f"\"{result.config.label()}\""
        )


def write_summary_csv(results: Sequence[TakeProfitReplayResult], output_path: Path) -> None:
    fieldnames = [
        "segment",
        "edge_prob_threshold",
        "min_entry_ask_price",
        "max_spread",
        "min_edge_after_fill",
        "exec_slippage_ticks",
        "exec_price_mode",
        "sigma_min",
        "tau_floor_seconds",
        "z_cap",
        "entry_time_windows",
        "block_time_windows",
        "tail_reversal_lookback_seconds",
        "tail_reversal_trigger_count",
        "tail_reversal_cooldown_seconds",
        "weak_regime_enabled",
        "weak_regime_settled_lookback_markets",
        "weak_regime_min_settled_markets",
        "weak_regime_roi_trigger",
        "weak_regime_win_rate_trigger",
        "weak_regime_tail_hit_lookback_seconds",
        "weak_regime_tail_hit_trigger",
        "weak_regime_weekend_prior_enabled",
        "weak_regime_on_score",
        "weak_regime_off_score",
        "weak_regime_off_confirm_settled_markets",
        "tp_delta",
        "tp_min_hold_seconds",
        "tp_confirm_snapshots",
        "tp_disable_last_seconds",
        "settled_markets",
        "traded_markets",
        "closed_early_markets",
        "early_close_rate",
        "orders",
        "total_cost",
        "total_pnl",
        "roi",
        "wins",
        "losses",
        "win_rate",
        "max_drawdown",
        "avg_exit_elapsed_seconds",
        "avg_delta_vs_hold",
        "rescued_loss_markets",
        "clipped_winner_markets",
        "hold_baseline_total_pnl",
        "hold_baseline_roi",
        "delta_total_pnl_vs_hold",
        "delta_roi_vs_hold",
        "median_day_roi",
        "worst_day_roi",
        "best_day_roi",
        "day_count",
        "weak_regime_traded_markets",
        "weak_regime_entry_markets",
        "weak_regime_closed_early_markets",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in sorted(results, key=lambda item: (item.segment != "combined", item.segment, -item.roi, -item.delta_total_pnl_vs_hold)):
            base = result.config.base
            weak = result.config.weak_regime
            writer.writerow(
                {
                    "segment": result.segment,
                    "edge_prob_threshold": base.edge_prob_threshold,
                    "min_entry_ask_price": base.min_entry_ask_price,
                    "max_spread": base.max_spread,
                    "min_edge_after_fill": base.min_edge_after_fill,
                    "exec_slippage_ticks": base.exec_slippage_ticks,
                    "exec_price_mode": base.exec_price_mode,
                    "sigma_min": base.sigma_min,
                    "tau_floor_seconds": base.tau_floor_seconds,
                    "z_cap": base.z_cap,
                    "entry_time_windows": format_time_windows(base.entry_time_windows, empty_label="all"),
                    "block_time_windows": format_time_windows(base.block_time_windows, empty_label="none"),
                    "tail_reversal_lookback_seconds": base.tail_reversal_lookback_seconds,
                    "tail_reversal_trigger_count": base.tail_reversal_trigger_count,
                    "tail_reversal_cooldown_seconds": base.tail_reversal_cooldown_seconds,
                    "weak_regime_enabled": weak.enabled,
                    "weak_regime_settled_lookback_markets": weak.settled_lookback_markets,
                    "weak_regime_min_settled_markets": weak.min_settled_markets,
                    "weak_regime_roi_trigger": weak.roi_trigger,
                    "weak_regime_win_rate_trigger": weak.win_rate_trigger,
                    "weak_regime_tail_hit_lookback_seconds": weak.tail_hit_lookback_seconds,
                    "weak_regime_tail_hit_trigger": weak.tail_hit_trigger,
                    "weak_regime_weekend_prior_enabled": weak.weekend_prior_enabled,
                    "weak_regime_on_score": weak.on_score,
                    "weak_regime_off_score": weak.off_score,
                    "weak_regime_off_confirm_settled_markets": weak.off_confirm_settled_markets,
                    "tp_delta": result.config.tp_delta,
                    "tp_min_hold_seconds": result.config.tp_min_hold_seconds,
                    "tp_confirm_snapshots": result.config.tp_confirm_snapshots,
                    "tp_disable_last_seconds": result.config.tp_disable_last_seconds,
                    "settled_markets": result.settled_markets,
                    "traded_markets": result.traded_markets,
                    "closed_early_markets": result.closed_early_markets,
                    "early_close_rate": round(result.early_close_rate, 8),
                    "orders": result.orders,
                    "total_cost": round(result.total_cost, 8),
                    "total_pnl": round(result.total_pnl, 8),
                    "roi": round(result.roi, 8),
                    "wins": result.wins,
                    "losses": result.losses,
                    "win_rate": round(result.win_rate, 8),
                    "max_drawdown": round(result.max_drawdown, 8),
                    "avg_exit_elapsed_seconds": round(result.avg_exit_elapsed_seconds, 8),
                    "avg_delta_vs_hold": round(result.avg_delta_vs_hold, 8),
                    "rescued_loss_markets": result.rescued_loss_markets,
                    "clipped_winner_markets": result.clipped_winner_markets,
                    "hold_baseline_total_pnl": round(result.hold_baseline_total_pnl, 8),
                    "hold_baseline_roi": round(result.hold_baseline_roi, 8),
                    "delta_total_pnl_vs_hold": round(result.delta_total_pnl_vs_hold, 8),
                    "delta_roi_vs_hold": round(result.delta_roi_vs_hold, 8),
                    "median_day_roi": "" if result.median_day_roi is None else round(result.median_day_roi, 8),
                    "worst_day_roi": "" if result.worst_day_roi is None else round(result.worst_day_roi, 8),
                    "best_day_roi": "" if result.best_day_roi is None else round(result.best_day_roi, 8),
                    "day_count": result.day_count,
                    "weak_regime_traded_markets": result.weak_regime_traded_markets,
                    "weak_regime_entry_markets": result.weak_regime_entry_markets,
                    "weak_regime_closed_early_markets": result.weak_regime_closed_early_markets,
                }
            )


def write_market_details_csv(outcomes: Sequence[TakeProfitMarketOutcome], output_path: Path) -> None:
    fieldnames = [
        "config_label",
        "market_slug",
        "market_start_utc",
        "market_end_utc",
        "segment",
        "resolved_side",
        "traded_market",
        "entry_side_summary",
        "yes_orders",
        "down_orders",
        "yes_avg_entry",
        "down_avg_entry",
        "closed_early",
        "close_reason",
        "trigger_side",
        "close_ts",
        "close_elapsed_seconds",
        "tp_delta",
        "tp_min_hold_seconds",
        "tp_confirm_snapshots",
        "tp_disable_last_seconds",
        "exit_yes_bid",
        "exit_down_bid",
        "entry_fee_total",
        "exit_fee_total",
        "realized_exit_proceeds",
        "market_pnl",
        "hold_to_settlement_pnl",
        "delta_vs_hold",
        "total_cost",
        "orders",
        "weak_regime_on_first_fill",
        "weak_regime_seen",
        "weak_regime_fill_count",
        "weak_regime_active_on_exit",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for outcome in outcomes:
            writer.writerow(
                {
                    "config_label": outcome.config_label,
                    "market_slug": outcome.market_slug,
                    "market_start_utc": outcome.market_start_utc,
                    "market_end_utc": outcome.market_end_utc,
                    "segment": outcome.segment,
                    "resolved_side": outcome.resolved_side,
                    "traded_market": outcome.traded_market,
                    "entry_side_summary": outcome.entry_side_summary,
                    "yes_orders": outcome.yes_orders,
                    "down_orders": outcome.down_orders,
                    "yes_avg_entry": "" if outcome.yes_avg_entry is None else round(outcome.yes_avg_entry, 8),
                    "down_avg_entry": "" if outcome.down_avg_entry is None else round(outcome.down_avg_entry, 8),
                    "closed_early": outcome.closed_early,
                    "close_reason": outcome.close_reason,
                    "trigger_side": outcome.trigger_side,
                    "close_ts": outcome.close_ts,
                    "close_elapsed_seconds": "" if outcome.close_elapsed_seconds is None else round(outcome.close_elapsed_seconds, 8),
                    "tp_delta": outcome.tp_delta,
                    "tp_min_hold_seconds": outcome.tp_min_hold_seconds,
                    "tp_confirm_snapshots": outcome.tp_confirm_snapshots,
                    "tp_disable_last_seconds": outcome.tp_disable_last_seconds,
                    "exit_yes_bid": "" if outcome.exit_yes_bid is None else round(outcome.exit_yes_bid, 8),
                    "exit_down_bid": "" if outcome.exit_down_bid is None else round(outcome.exit_down_bid, 8),
                    "entry_fee_total": round(outcome.entry_fee_total, 8),
                    "exit_fee_total": round(outcome.exit_fee_total, 8),
                    "realized_exit_proceeds": round(outcome.realized_exit_proceeds, 8),
                    "market_pnl": round(outcome.market_pnl, 8),
                    "hold_to_settlement_pnl": round(outcome.hold_to_settlement_pnl, 8),
                    "delta_vs_hold": round(outcome.delta_vs_hold, 8),
                    "total_cost": round(outcome.total_cost, 8),
                    "orders": outcome.orders,
                    "weak_regime_on_first_fill": "" if outcome.weak_regime_on_first_fill is None else outcome.weak_regime_on_first_fill,
                    "weak_regime_seen": outcome.weak_regime_seen,
                    "weak_regime_fill_count": outcome.weak_regime_fill_count,
                    "weak_regime_active_on_exit": outcome.weak_regime_active_on_exit,
                }
            )


def derive_market_details_path(summary_path: Path) -> Path:
    if summary_path.suffix:
        return summary_path.with_name(f"{summary_path.stem}_market_details{summary_path.suffix}")
    return summary_path.with_name(f"{summary_path.name}_market_details.csv")


def build_arg_parser():
    parser = build_tick_arg_parser()
    parser.description = "Replay bot snapshots with a fixed take-profit exit policy."
    parser.add_argument("--tp-delta-values", default="0.05,0.10,0.15,0.20,0.25,0.30")
    parser.add_argument("--tp-min-hold-seconds-values", default="0,15,30")
    parser.add_argument("--tp-confirm-snapshots-values", default="1,2")
    parser.add_argument("--tp-disable-last-seconds-values", default="0,15,30")
    parser.add_argument("--weak-regime-tp-enabled", action="store_true")
    parser.add_argument("--weak-regime-settled-lookback-markets-values", default="8")
    parser.add_argument("--weak-regime-min-settled-markets-values", default="5")
    parser.add_argument("--weak-regime-roi-trigger-values", default="-0.08")
    parser.add_argument("--weak-regime-win-rate-trigger-values", default="0.35")
    parser.add_argument("--weak-regime-tail-hit-lookback-seconds-values", default="5400")
    parser.add_argument("--weak-regime-tail-hit-trigger-values", default="2")
    parser.add_argument("--weak-regime-weekend-prior-enabled-values", default="true")
    parser.add_argument("--weak-regime-on-score-values", default="3")
    parser.add_argument("--weak-regime-off-score-values", default="1")
    parser.add_argument("--weak-regime-off-confirm-settled-markets-values", default="4")
    parser.add_argument(
        "--market-details-csv",
        type=Path,
        help="Per-market detail output path. Defaults to <output-csv>_market_details.csv when --output-csv is set.",
    )
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    exec_modes = set(parse_str_list(args.exec_price_modes))
    invalid_modes = exec_modes - {"book", "edge", "hybrid"}
    if invalid_modes:
        parser.error(f"Invalid --exec-price-modes values: {sorted(invalid_modes)}")

    try:
        settlements = load_settlements(args.ledger_dir)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}")
        return 1

    source_mode = "all" if args.evaluate_sources.strip().lower() == "all" else "selected"
    evaluate_sources = set(DEFAULT_EVALUATE_SOURCES if source_mode == "all" else parse_str_list(args.evaluate_sources))
    try:
        snapshots, snapshot_stats = load_snapshots(
            args.snapshot_dir,
            args.snapshot_glob,
            settlements,
            evaluate_sources=evaluate_sources,
            source_mode=source_mode,
            strict_jsonl=args.strict_jsonl,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1
    print_snapshot_quality(snapshot_stats)
    if not snapshots:
        print(
            f"No usable snapshots found in {args.snapshot_dir} matching {args.snapshot_glob}. "
            "Check --ledger-dir, --evaluate-sources, and whether the snapshots cover settled markets."
        )
        return 1

    snapshot_slugs = {str(row.get("market_slug") or "") for row in snapshots}
    active_settlements = {slug: settlement for slug, settlement in settlements.items() if slug in snapshot_slugs}
    tail_profiles = build_tail_reversal_profiles(
        snapshots,
        anchor_seconds=args.tail_reversal_anchor_seconds,
        confirm_seconds=args.tail_reversal_confirm_seconds,
    )
    try:
        configs = build_take_profit_configs(args)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(
        f"Loaded {len(snapshots)} snapshots across {len(active_settlements)} "
        f"settled markets; replaying {len(configs)} take-profit config(s)."
    )

    all_results: list[TakeProfitReplayResult] = []
    all_outcomes: list[TakeProfitMarketOutcome] = []
    for cfg in configs:
        results, outcomes = replay_take_profit_config(snapshots, active_settlements, tail_profiles, cfg)
        all_results.extend(results)
        all_outcomes.extend(outcomes)

    print_combined_results(all_results, args.top)

    details_path = args.market_details_csv
    if args.output_csv and details_path is None:
        details_path = derive_market_details_path(args.output_csv)

    if args.output_csv:
        write_summary_csv(all_results, args.output_csv)
        print(f"Wrote summary CSV: {args.output_csv}")
    if details_path:
        write_market_details_csv(all_outcomes, details_path)
        print(f"Wrote market details CSV: {details_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
