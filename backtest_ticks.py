#!/usr/bin/env python3
"""
Replay tick snapshot JSONL files produced by bot.py.

This is a research backtester, not a fill simulator. It replays the same
high-level signal gates against recorded bot-visible state:

- PM bid/ask snapshots
- recorded or recomputed fair probabilities
- execution price caps
- order/signal cooldowns
- market and side exposure caps

The output is meant to screen parameter sets before live dry-run validation.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import itertools
import json
import math
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from ml_filter import MLSignalFilter, build_live_feature_values

DEFAULT_EVALUATE_SOURCES = (
    "pm_best_bid_ask",
    "pm_price_change",
    "pm_last_trade_price",
)

SKIP_SNAPSHOT_FILE_SUFFIXES = (".tmp", ".part", ".swp")
TimeWindows = tuple[tuple[float, float], ...]


def safe_float(value: Any, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    try:
        result = float(value)
    except Exception:
        return default
    return result if math.isfinite(result) else default


def optional_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except Exception:
        return None
    return result if math.isfinite(result) else None


def parse_dt(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return (
            value.astimezone(timezone.utc)
            if value.tzinfo
            else value.replace(tzinfo=timezone.utc)
        )
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(
            timezone.utc
        )
    except Exception:
        return None


def normal_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    ordered = sorted(values)
    if q <= 0:
        return ordered[0]
    if q >= 1:
        return ordered[-1]
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


def parse_float_list(raw: str) -> list[float]:
    return [float(item.strip()) for item in raw.split(",") if item.strip()]


def parse_int_list(raw: str) -> list[int]:
    return [int(item.strip()) for item in raw.split(",") if item.strip()]


def parse_str_list(raw: str) -> list[str]:
    return [item.strip() for item in raw.split(",") if item.strip()]


def parse_day_set(raw: str) -> set[str]:
    return {item.strip() for item in raw.split(",") if item.strip()}


def parse_time_window_spec(raw: str, *, no_filter_tokens: set[str]) -> TimeWindows:
    text = raw.strip()
    if text.lower() in no_filter_tokens:
        return ()

    windows: list[tuple[float, float]] = []
    for item in text.split(","):
        token = item.strip()
        if not token:
            continue
        if "-" not in token:
            raise ValueError(
                f"Invalid time window '{token}'. Use start-end seconds, e.g. 90-150."
            )
        start_text, end_text = token.split("-", 1)
        start = float(start_text.strip())
        end = float(end_text.strip())
        if start < 0 or end <= start:
            raise ValueError(
                f"Invalid time window '{token}'. Require 0 <= start < end."
            )
        windows.append((start, end))
    return tuple(windows)


def parse_time_window_values(
    raw: str, *, no_filter_tokens: set[str]
) -> list[TimeWindows]:
    values = [
        parse_time_window_spec(item, no_filter_tokens=no_filter_tokens)
        for item in raw.split(";")
        if item.strip()
    ]
    return values or [()]


def format_time_windows(windows: TimeWindows, *, empty_label: str) -> str:
    if not windows:
        return empty_label
    return ",".join(f"{start:g}-{end:g}" for start, end in windows)


def quantize_price_down(price: float, tick: float) -> float:
    if tick <= 0:
        return price
    tick_text = f"{tick:.12f}".rstrip("0")
    decimals = len(tick_text.split(".", 1)[1]) if "." in tick_text else 0
    steps = math.floor((price / tick) + 1e-9)
    return round(steps * tick, decimals)


def round_fee_usdc(value: float) -> float:
    return round(value + 1e-12, 5)


def estimate_taker_buy_execution(
    amount_usd: float, price: float, fee_rate_bps: float
) -> tuple[float, float, float]:
    if price <= 0 or amount_usd <= 0:
        return 0.0, 0.0, 0.0
    fee_rate = fee_rate_bps / 10000.0
    gross_shares = amount_usd / price
    fee_usdc = round_fee_usdc(gross_shares * fee_rate * price * (1.0 - price))
    fee_shares = fee_usdc / price if fee_usdc > 0 else 0.0
    net_shares = max(gross_shares - fee_shares, 0.0)
    return gross_shares, fee_usdc, net_shares


@dataclass(frozen=True)
class Settlement:
    market_slug: str
    market_start_utc: str
    market_end_utc: str
    resolved_side: str
    yes_fee_rate_bps: float
    down_fee_rate_bps: float
    fees_enabled: bool


@dataclass(frozen=True)
class TailReversalPoint:
    remaining_seconds: float
    up_mid: Optional[float]
    down_mid: Optional[float]
    up_prob: Optional[float]
    down_prob: Optional[float]


@dataclass(frozen=True)
class TailReversalProfile:
    anchor: Optional[TailReversalPoint]
    confirm: Optional[TailReversalPoint]
    final: Optional[TailReversalPoint]


@dataclass(frozen=True)
class ReplayConfig:
    edge_prob_threshold: float
    edge_reference_price: str
    max_spread: float
    min_entry_ask_price: float
    min_edge_after_fill: float
    exec_slippage_ticks: int
    exec_price_mode: str
    exec_price_cap: float
    tick_size: float
    trade_amount_usd: float
    order_cooldown_seconds: float
    signal_cooldown_seconds: float
    market_max_total_cost: float
    market_max_side_cost: float
    side_extension_enabled: bool
    side_extension_start_cost: float
    side_extension_max_side_cost: float
    side_extension_min_seconds: float
    side_extension_cooldown_seconds: float
    side_extension_min_edge: float
    side_extension_min_edge_after_fill: float
    side_extension_min_ask_price: float
    side_extension_max_ask_price: float
    side_extension_max_opposite_cost: float
    fair_mode: str
    sigma_short_weight: float
    sigma_long_weight: float
    sigma_min: float
    tau_floor_seconds: float
    z_cap: float
    entry_time_windows: TimeWindows
    block_time_windows: TimeWindows
    tail_reversal_lookback_seconds: float
    tail_reversal_trigger_count: int
    tail_reversal_cooldown_seconds: float
    tail_reversal_min_anchor_prob: float
    tail_reversal_min_prob_drop: float
    tail_reversal_min_mid_gain: float
    ml_filter_enabled: bool
    ml_model_path: Path
    ml_features_path: Path
    ml_min_ev: float
    ml_fail_open: bool

    def label(self) -> str:
        label = (
            f"edge={self.edge_prob_threshold:g} "
            f"minAsk={self.min_entry_ask_price:g} "
            f"spread={self.max_spread:g} "
            f"eaf={self.min_edge_after_fill:g} "
            f"slip={self.exec_slippage_ticks} "
            f"mode={self.exec_price_mode}"
        )
        if self.entry_time_windows:
            label += f" allow={format_time_windows(self.entry_time_windows, empty_label='all')}"
        if self.block_time_windows:
            label += f" block={format_time_windows(self.block_time_windows, empty_label='none')}"
        if (
            self.tail_reversal_lookback_seconds > 0
            and self.tail_reversal_trigger_count > 0
            and self.tail_reversal_cooldown_seconds > 0
        ):
            label += (
                " trv="
                f"{self.tail_reversal_trigger_count}/"
                f"{self.tail_reversal_lookback_seconds:g}s->"
                f"{self.tail_reversal_cooldown_seconds:g}s"
            )
        if self.ml_filter_enabled:
            label += f" ml_ev>={self.ml_min_ev:g}"
        return label


@dataclass
class MarketState:
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

    def __post_init__(self) -> None:
        if self.last_signal_ts is None:
            self.last_signal_ts = {}
        if self.extension_start_ts is None:
            self.extension_start_ts = {"UP": None, "DOWN": None}
        if self.last_extension_order_ts is None:
            self.last_extension_order_ts = {"UP": None, "DOWN": None}
        if self.price_bands is None:
            self.price_bands = defaultdict(int)

    @property
    def total_cost(self) -> float:
        return self.yes_cost + self.down_cost

    def side_cost(self, side: str) -> float:
        return self.yes_cost if side == "UP" else self.down_cost

    def opposite_cost(self, side: str) -> float:
        return self.down_cost if side == "UP" else self.yes_cost

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
    ) -> None:
        _, fee_usdc, net_shares = estimate_taker_buy_execution(
            amount_usd, execution_price, fee_rate_bps
        )
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
            self.first_order_elapsed = (
                elapsed
                if self.first_order_elapsed is None
                else min(self.first_order_elapsed, elapsed)
            )
            self.last_order_elapsed = (
                elapsed
                if self.last_order_elapsed is None
                else max(self.last_order_elapsed, elapsed)
            )
        self.price_bands[price_band(execution_price)] += 1


@dataclass(frozen=True)
class Signal:
    side: str
    fair: float
    bid: float
    ask: float
    spread: float
    reference_price: float
    edge: float
    max_execution_price: float
    edge_after_fill: float


@dataclass(frozen=True)
class ReplayResult:
    config: ReplayConfig
    settled_markets: int
    traded_markets: int
    orders: int
    total_cost: float
    total_pnl: float
    roi: float
    wins: int
    losses: int
    win_rate: float
    max_drawdown: float
    avg_orders_per_traded_market: float
    p50_market_pnl: float
    p05_market_pnl: float
    p95_market_pnl: float
    skipped_due_order_cooldown: int
    skipped_due_signal_cooldown: int
    skipped_due_exposure: int
    skipped_due_time_gate: int
    skipped_due_tail_reversal_cooldown: int
    skipped_due_ml_filter: int
    ml_evaluated_signals: int
    ml_passed_signals: int
    ml_blocked_signals: int
    ml_error_signals: int
    ml_pass_rate: float
    tail_reversal_hits: int
    tail_reversal_cooldown_activations: int


@dataclass
class SnapshotLoadStats:
    files_read: int = 0
    total_lines: int = 0
    empty_lines: int = 0
    valid_json_lines: int = 0
    bad_json_lines: int = 0
    bad_ts_lines: int = 0
    skipped_missing_settlement: int = 0
    skipped_source: int = 0
    loaded_rows: int = 0
    first_loaded_dt: Optional[datetime] = None
    last_loaded_dt: Optional[datetime] = None
    source_counts: Counter[str] = field(default_factory=Counter)
    loaded_source_counts: Counter[str] = field(default_factory=Counter)
    market_counts: Counter[str] = field(default_factory=Counter)
    loaded_market_counts: Counter[str] = field(default_factory=Counter)
    bad_json_samples: list[str] = field(default_factory=list)

    def mark_loaded(self, item: dict[str, Any], ts: datetime) -> None:
        source_event = str(item.get("source_event") or "<missing>")
        market_slug = str(item.get("market_slug") or "<missing>")
        self.loaded_rows += 1
        self.loaded_source_counts[source_event] += 1
        self.loaded_market_counts[market_slug] += 1
        if self.first_loaded_dt is None or ts < self.first_loaded_dt:
            self.first_loaded_dt = ts
        if self.last_loaded_dt is None or ts > self.last_loaded_dt:
            self.last_loaded_dt = ts


def price_band(price: float) -> str:
    if price <= 0.2:
        return "<=0.2"
    if price <= 0.4:
        return "0.2-0.4"
    if price <= 0.6:
        return "0.4-0.6"
    if price <= 0.8:
        return "0.6-0.8"
    return ">0.8"


def elapsed_in_windows(elapsed_seconds: float, windows: TimeWindows) -> bool:
    return any(start <= elapsed_seconds < end for start, end in windows)


def passes_time_gate(elapsed_seconds: Optional[float], cfg: ReplayConfig) -> bool:
    has_gate = bool(cfg.entry_time_windows or cfg.block_time_windows)
    if not has_gate:
        return True
    if elapsed_seconds is None:
        return False
    if cfg.entry_time_windows and not elapsed_in_windows(
        elapsed_seconds, cfg.entry_time_windows
    ):
        return False
    if cfg.block_time_windows and elapsed_in_windows(
        elapsed_seconds, cfg.block_time_windows
    ):
        return False
    return True


def tail_point_from_snapshot(snapshot: dict[str, Any]) -> TailReversalPoint:
    return TailReversalPoint(
        remaining_seconds=safe_float(snapshot.get("remaining_seconds")),
        up_mid=optional_float(snapshot.get("yes_mid")),
        down_mid=optional_float(snapshot.get("down_mid")),
        up_prob=optional_float(snapshot.get("pm_implied_up")),
        down_prob=optional_float(snapshot.get("pm_implied_down")),
    )


def tail_point_side_mid(
    point: Optional[TailReversalPoint], side: str
) -> Optional[float]:
    if point is None:
        return None
    return point.up_mid if side == "UP" else point.down_mid


def tail_point_side_prob(
    point: Optional[TailReversalPoint], side: str
) -> Optional[float]:
    if point is None:
        return None
    return point.up_prob if side == "UP" else point.down_prob


def build_tail_reversal_profiles(
    snapshots: Sequence[dict[str, Any]],
    *,
    anchor_seconds: float,
    confirm_seconds: float,
) -> dict[str, TailReversalProfile]:
    raw: dict[str, dict[str, Any]] = {}
    for snapshot in snapshots:
        if snapshot.get("quote_complete") is not True:
            continue
        slug = str(snapshot.get("market_slug") or "")
        if not slug:
            continue
        remaining = optional_float(snapshot.get("remaining_seconds"))
        if remaining is None:
            continue
        bucket = raw.setdefault(
            slug,
            {
                "anchor_abs": None,
                "anchor": None,
                "confirm_abs": None,
                "confirm": None,
                "final_remaining": None,
                "final": None,
            },
        )
        anchor_abs = abs(remaining - anchor_seconds)
        if bucket["anchor_abs"] is None or anchor_abs < bucket["anchor_abs"]:
            bucket["anchor_abs"] = anchor_abs
            bucket["anchor"] = tail_point_from_snapshot(snapshot)
        confirm_abs = abs(remaining - confirm_seconds)
        if bucket["confirm_abs"] is None or confirm_abs < bucket["confirm_abs"]:
            bucket["confirm_abs"] = confirm_abs
            bucket["confirm"] = tail_point_from_snapshot(snapshot)
        if bucket["final_remaining"] is None or remaining < bucket["final_remaining"]:
            bucket["final_remaining"] = remaining
            bucket["final"] = tail_point_from_snapshot(snapshot)

    profiles: dict[str, TailReversalProfile] = {}
    for slug, bucket in raw.items():
        profiles[slug] = TailReversalProfile(
            anchor=bucket["anchor"],
            confirm=bucket["confirm"],
            final=bucket["final"],
        )
    return profiles


def tail_reversal_hit_for_market(
    state: MarketState,
    settlement: Settlement,
    profile: Optional[TailReversalProfile],
    cfg: ReplayConfig,
) -> bool:
    if (
        profile is None
        or state.total_cost <= 0
        or settlement.resolved_side not in {"UP", "DOWN"}
    ):
        return False

    if state.yes_shares > state.down_shares:
        side = "UP"
        side_cost = state.yes_cost
        side_shares = state.yes_shares
    elif state.down_shares > state.yes_shares:
        side = "DOWN"
        side_cost = state.down_cost
        side_shares = state.down_shares
    elif state.yes_cost >= state.down_cost and state.yes_cost > 0:
        side = "UP"
        side_cost = state.yes_cost
        side_shares = state.yes_shares
    elif state.down_cost > 0:
        side = "DOWN"
        side_cost = state.down_cost
        side_shares = state.down_shares
    else:
        return False

    if side == settlement.resolved_side or side_cost <= 0 or side_shares <= 0:
        return False

    avg_entry_price = side_cost / side_shares
    anchor_point = profile.anchor
    end_point = profile.final or profile.confirm
    anchor_mid = tail_point_side_mid(anchor_point, side)
    anchor_prob = tail_point_side_prob(anchor_point, side)
    end_prob = tail_point_side_prob(end_point, side)
    if anchor_prob is None or end_prob is None:
        return False

    favorable_at_anchor = (
        anchor_mid is not None
        and anchor_mid - avg_entry_price >= cfg.tail_reversal_min_mid_gain
    ) or anchor_prob >= cfg.tail_reversal_min_anchor_prob
    if not favorable_at_anchor:
        return False
    if anchor_prob - end_prob < cfg.tail_reversal_min_prob_drop:
        return False
    if end_prob > 0.5:
        return False

    payout = state.yes_shares if settlement.resolved_side == "UP" else state.down_shares
    pnl = payout - state.total_cost - state.fee_total
    return pnl < 0


def load_settlements(ledger_dir: Path) -> dict[str, Settlement]:
    path = ledger_dir / "market_settlements.csv"
    if not path.exists():
        raise FileNotFoundError(
            f"Missing settlements CSV: {path}. "
            "backtest_ticks.py needs resolved UP/DOWN rows from market_settlements.csv; "
            "pass --ledger-dir if the ledger is stored elsewhere."
        )

    settlements: dict[str, Settlement] = {}
    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            slug = row.get("market_slug", "")
            resolved_side = row.get("resolved_side", "")
            if not slug or resolved_side not in {"UP", "DOWN"}:
                continue
            fees_enabled = str(row.get("fees_enabled", "")).strip().lower() == "true"
            settlements[slug] = Settlement(
                market_slug=slug,
                market_start_utc=row.get("market_start_utc", ""),
                market_end_utc=row.get("market_end_utc", ""),
                resolved_side=resolved_side,
                yes_fee_rate_bps=(
                    safe_float(row.get("yes_fee_rate_bps")) if fees_enabled else 0.0
                ),
                down_fee_rate_bps=(
                    safe_float(row.get("down_fee_rate_bps")) if fees_enabled else 0.0
                ),
                fees_enabled=fees_enabled,
            )
    return settlements


def iter_snapshot_paths(snapshot_dir: Path, snapshot_glob: str) -> list[Path]:
    if not snapshot_dir.exists():
        return []
    selected: dict[str, Path] = {}
    for path in sorted(snapshot_dir.glob(snapshot_glob)):
        if not path.is_file() or path.name.endswith(SKIP_SNAPSHOT_FILE_SUFFIXES):
            continue
        identity = path.name[:-3] if path.name.endswith(".gz") else path.name
        current = selected.get(identity)
        if current is None or (
            current.name.endswith(".gz") and not path.name.endswith(".gz")
        ):
            selected[identity] = path
    return sorted(selected.values())


def open_snapshot_text(path: Path):
    if path.name.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open(encoding="utf-8")


def format_counter(counter: Counter[str], limit: int = 8) -> str:
    if not counter:
        return "none"
    parts = [f"{key}={value}" for key, value in counter.most_common(limit)]
    remaining = sum(counter.values()) - sum(
        value for _, value in counter.most_common(limit)
    )
    if remaining > 0:
        parts.append(f"other={remaining}")
    return ", ".join(parts)


def print_snapshot_quality(stats: SnapshotLoadStats) -> None:
    print(
        "Snapshot quality: "
        f"files={stats.files_read}, lines={stats.total_lines}, "
        f"valid_json={stats.valid_json_lines}, bad_json={stats.bad_json_lines}, "
        f"loaded={stats.loaded_rows}"
    )
    if stats.first_loaded_dt and stats.last_loaded_dt:
        duration = (stats.last_loaded_dt - stats.first_loaded_dt).total_seconds()
        print(
            "Snapshot range: "
            f"{stats.first_loaded_dt.isoformat()} -> {stats.last_loaded_dt.isoformat()} "
            f"({duration:.1f}s)"
        )
    print(f"Snapshot sources: {format_counter(stats.source_counts)}")
    print(f"Loaded sources: {format_counter(stats.loaded_source_counts)}")
    print(
        "Skipped rows: "
        f"empty={stats.empty_lines}, missing_settlement={stats.skipped_missing_settlement}, "
        f"source_filter={stats.skipped_source}, bad_ts={stats.bad_ts_lines}"
    )
    if stats.bad_json_samples:
        print("Bad JSON samples:")
        for sample in stats.bad_json_samples:
            print(f"  {sample}")


def load_snapshots(
    snapshot_dir: Path,
    snapshot_glob: str,
    settlements: dict[str, Settlement],
    evaluate_sources: set[str],
    source_mode: str,
    strict_jsonl: bool,
) -> tuple[list[dict[str, Any]], SnapshotLoadStats]:
    snapshots: list[dict[str, Any]] = []
    stats = SnapshotLoadStats()
    paths = iter_snapshot_paths(snapshot_dir, snapshot_glob)
    for path in paths:
        stats.files_read += 1
        with open_snapshot_text(path) as handle:
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
                if source_mode != "all" and source_event not in evaluate_sources:
                    stats.skipped_source += 1
                    continue
                ts = parse_dt(item.get("ts"))
                if ts is None:
                    stats.bad_ts_lines += 1
                    continue
                item["_dt"] = ts
                snapshots.append(item)
                stats.mark_loaded(item, ts)
    snapshots.sort(key=lambda row: (row["_dt"], str(row.get("market_slug") or "")))
    return snapshots, stats


def load_snapshots_for_path(
    *,
    path: Path,
    settlements: dict[str, Settlement],
    evaluate_sources: set[str],
    source_mode: str,
    strict_jsonl: bool,
    stats: SnapshotLoadStats,
) -> list[dict[str, Any]]:
    snapshots: list[dict[str, Any]] = []
    stats.files_read += 1
    with open_snapshot_text(path) as handle:
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
            if source_mode != "all" and source_event not in evaluate_sources:
                stats.skipped_source += 1
                continue
            ts = parse_dt(item.get("ts"))
            if ts is None:
                stats.bad_ts_lines += 1
                continue
            item["_dt"] = ts
            snapshots.append(item)
            stats.mark_loaded(item, ts)
    snapshots.sort(key=lambda row: (row["_dt"], str(row.get("market_slug") or "")))
    return snapshots


def market_day_from_row(row: dict[str, Any]) -> str:
    market_start = str(row.get("market_start_utc") or "")
    return market_start[:10] if len(market_start) >= 10 else ""


def filter_snapshots_by_day(
    snapshots: Sequence[dict[str, Any]],
    *,
    start_day: str,
    end_day: str,
    include_days: set[str],
    exclude_days: set[str],
) -> list[dict[str, Any]]:
    if not any([start_day, end_day, include_days, exclude_days]):
        return list(snapshots)

    filtered: list[dict[str, Any]] = []
    for snapshot in snapshots:
        day = market_day_from_row(snapshot)
        if not day:
            continue
        if start_day and day < start_day:
            continue
        if end_day and day > end_day:
            continue
        if include_days and day not in include_days:
            continue
        if exclude_days and day in exclude_days:
            continue
        filtered.append(snapshot)
    return filtered


def compute_execution_plan(
    fair: float, ask: float, cfg: ReplayConfig
) -> Optional[tuple[float, float]]:
    if ask <= 0 or fair <= 0:
        return None
    max_book_price = ask + (cfg.exec_slippage_ticks * cfg.tick_size)
    max_edge_price = fair - cfg.min_edge_after_fill
    if cfg.exec_price_mode == "book":
        max_execution_price = max_book_price
    elif cfg.exec_price_mode == "edge":
        max_execution_price = max_edge_price
    else:
        max_execution_price = min(max_book_price, max_edge_price)
    if cfg.exec_price_cap > 0:
        max_execution_price = min(max_execution_price, cfg.exec_price_cap)
    max_execution_price = min(max_execution_price, 1.0 - cfg.tick_size)
    max_execution_price = quantize_price_down(max_execution_price, cfg.tick_size)
    if max_execution_price < ask:
        return None
    return max_execution_price, fair - max_execution_price


def fair_from_snapshot(
    snapshot: dict[str, Any], cfg: ReplayConfig
) -> tuple[Optional[float], Optional[float]]:
    if cfg.fair_mode == "snapshot":
        fair_yes = optional_float(snapshot.get("fair_yes"))
        fair_no = optional_float(snapshot.get("fair_no"))
        return fair_yes, fair_no

    bn_price = optional_float(snapshot.get("bn_price"))
    open_anchor = optional_float(snapshot.get("open_anchor_price"))
    sigma_short = optional_float(snapshot.get("sigma_short"))
    sigma_long = optional_float(snapshot.get("sigma_long"))
    remaining = optional_float(snapshot.get("remaining_seconds"))
    if None in {bn_price, open_anchor, sigma_short, sigma_long, remaining}:
        return optional_float(snapshot.get("fair_yes")), optional_float(
            snapshot.get("fair_no")
        )

    weight_sum = cfg.sigma_short_weight + cfg.sigma_long_weight
    if weight_sum <= 0:
        short_weight = 1.0
        long_weight = 0.0
    else:
        short_weight = cfg.sigma_short_weight / weight_sum
        long_weight = cfg.sigma_long_weight / weight_sum

    sigma_eff = math.sqrt(
        short_weight * (sigma_short or 0.0) ** 2
        + long_weight * (sigma_long or 0.0) ** 2
        + cfg.sigma_min**2
    )
    tau = max(remaining or 0.0, cfg.tau_floor_seconds)
    if sigma_eff <= 0 or tau <= 0 or not bn_price or not open_anchor:
        return optional_float(snapshot.get("fair_yes")), optional_float(
            snapshot.get("fair_no")
        )
    z = math.log(bn_price / open_anchor) / (sigma_eff * math.sqrt(tau))
    z = max(min(z, cfg.z_cap), -cfg.z_cap)
    fair_yes = normal_cdf(z)
    return fair_yes, 1.0 - fair_yes


def build_signals(snapshot: dict[str, Any], cfg: ReplayConfig) -> list[Signal]:
    fair_yes, fair_no = fair_from_snapshot(snapshot, cfg)
    yes_bid = optional_float(snapshot.get("yes_bid"))
    yes_ask = optional_float(snapshot.get("yes_ask"))
    down_bid = optional_float(snapshot.get("down_bid"))
    down_ask = optional_float(snapshot.get("down_ask"))
    if None in {fair_yes, fair_no, yes_bid, yes_ask, down_bid, down_ask}:
        return []

    candidates: list[tuple[str, float, float, float]] = [
        ("UP", fair_yes or 0.0, yes_bid or 0.0, yes_ask or 0.0),
        ("DOWN", fair_no or 0.0, down_bid or 0.0, down_ask or 0.0),
    ]
    signals: list[Signal] = []
    for side, fair, bid, ask in candidates:
        if bid <= 0 or ask <= 0:
            continue
        spread = ask - bid
        if spread > cfg.max_spread or ask < cfg.min_entry_ask_price:
            continue
        reference_price = ask if cfg.edge_reference_price == "ask" else bid
        edge = fair - reference_price
        if edge <= cfg.edge_prob_threshold:
            continue
        plan = compute_execution_plan(fair, ask, cfg)
        if plan is None:
            continue
        max_execution_price, edge_after_fill = plan
        signals.append(
            Signal(
                side=side,
                fair=fair,
                bid=bid,
                ask=ask,
                spread=spread,
                reference_price=reference_price,
                edge=edge,
                max_execution_price=max_execution_price,
                edge_after_fill=edge_after_fill,
            )
        )
    return signals


def can_pass_exposure(
    state: MarketState, signal: Signal, cfg: ReplayConfig, now: datetime
) -> tuple[bool, bool]:
    total_cost = state.total_cost
    if cfg.market_max_total_cost > 0 and total_cost >= cfg.market_max_total_cost:
        return False, False

    side_cost = state.side_cost(signal.side)
    opposite_cost = state.opposite_cost(signal.side)
    if cfg.market_max_side_cost <= 0 or side_cost < cfg.market_max_side_cost:
        return True, False

    if not cfg.side_extension_enabled:
        return False, False

    effective_start_cost = max(cfg.market_max_side_cost, cfg.side_extension_start_cost)
    effective_max_side_cost = max(
        effective_start_cost, cfg.side_extension_max_side_cost
    )

    if effective_max_side_cost > 0 and side_cost >= effective_max_side_cost:
        return False, False
    if (
        signal.ask < cfg.side_extension_min_ask_price
        or signal.ask > cfg.side_extension_max_ask_price
    ):
        return False, False
    if signal.edge < cfg.side_extension_min_edge:
        return False, False
    if signal.edge_after_fill < cfg.side_extension_min_edge_after_fill:
        return False, False
    if (
        cfg.side_extension_max_opposite_cost > 0
        and opposite_cost > cfg.side_extension_max_opposite_cost
    ):
        return False, False

    start_ts = state.extension_start_ts.get(signal.side)
    if start_ts is None:
        state.extension_start_ts[signal.side] = now
        return False, False
    if (now - start_ts).total_seconds() < cfg.side_extension_min_seconds:
        return False, False

    last_extension_ts = state.last_extension_order_ts.get(signal.side)
    if last_extension_ts is not None:
        if (
            now - last_extension_ts
        ).total_seconds() < cfg.side_extension_cooldown_seconds:
            return False, False

    return True, True


def fee_rate_for_side(settlement: Settlement, side: str) -> float:
    if not settlement.fees_enabled:
        return 0.0
    return settlement.yes_fee_rate_bps if side == "UP" else settlement.down_fee_rate_bps


def mean_optional(values: Sequence[float]) -> Optional[float]:
    return sum(values) / len(values) if values else None


def rolling_market_features(
    recent_results: deque[tuple[float, bool]],
) -> tuple[Optional[float], Optional[float], Optional[float]]:
    last_6 = list(recent_results)[-6:]
    last_10 = list(recent_results)[-10:]
    rolling_6_roi = mean_optional([roi for roi, _ in last_6])
    rolling_10_roi = mean_optional([roi for roi, _ in last_10])
    rolling_10_win_rate = mean_optional([1.0 if win else 0.0 for _, win in last_10])
    return rolling_6_roi, rolling_10_roi, rolling_10_win_rate


def ratio_return(price: Optional[float], anchor: Optional[float]) -> Optional[float]:
    if price is None or anchor is None or anchor <= 0:
        return None
    return (price / anchor) - 1.0


def signal_to_source_signal(
    *,
    snapshot: dict[str, Any],
    signal: Signal,
    elapsed_seconds: Optional[float],
    market_start_dt: Optional[datetime],
    is_extension: bool,
) -> dict[str, Any]:
    remaining_seconds = optional_float(snapshot.get("remaining_seconds"))
    if remaining_seconds is None:
        market_end_dt = parse_dt(snapshot.get("market_end_utc"))
        now = snapshot.get("_dt")
        if isinstance(now, datetime) and market_end_dt is not None:
            remaining_seconds = (market_end_dt - now).total_seconds()

    return {
        "side": signal.side,
        "fair": signal.fair,
        "diff": signal.edge,
        "edge_after_fill_estimate": signal.edge_after_fill,
        "bid": signal.bid,
        "ask": signal.ask,
        "spread": signal.spread,
        "reference_price": signal.reference_price,
        "max_execution_price": signal.max_execution_price,
        "bn_price": optional_float(snapshot.get("bn_price")),
        "bn_open_price": optional_float(snapshot.get("bn_open_price")),
        "open_price": optional_float(snapshot.get("open_anchor_price")),
        "sigma_short": optional_float(snapshot.get("sigma_short")),
        "sigma_long": optional_float(snapshot.get("sigma_long")),
        "sigma_eff": optional_float(snapshot.get("sigma_eff")),
        "tau_seconds": optional_float(snapshot.get("tau_seconds")),
        "z": optional_float(snapshot.get("z")),
        "elapsed_seconds": elapsed_seconds,
        "remaining_seconds": remaining_seconds,
        "market_start_utc": market_start_dt.isoformat()
        if market_start_dt is not None
        else "",
        "is_extension_order": is_extension,
    }


def state_to_ledger(state: MarketState) -> dict[str, float]:
    return {
        "yes_cost": state.yes_cost,
        "down_cost": state.down_cost,
        "total_cost": state.total_cost,
    }


def replay_config(
    snapshots: Sequence[dict[str, Any]],
    settlements: dict[str, Settlement],
    tail_profiles: dict[str, TailReversalProfile],
    cfg: ReplayConfig,
) -> ReplayResult:
    states: dict[str, MarketState] = defaultdict(MarketState)
    skipped_order_cooldown = 0
    skipped_signal_cooldown = 0
    skipped_exposure = 0
    skipped_time_gate = 0
    skipped_tail_reversal_cooldown = 0
    skipped_ml_filter = 0
    ml_evaluated_signals = 0
    ml_passed_signals = 0
    ml_blocked_signals = 0
    ml_error_signals = 0
    tail_reversal_hits = 0
    tail_reversal_cooldown_activations = 0
    cooldown_until: Optional[datetime] = None
    recent_tail_hit_times: deque[datetime] = deque()
    recent_market_results: deque[tuple[float, bool]] = deque(maxlen=50)
    tail_reversal_enabled = (
        cfg.tail_reversal_lookback_seconds > 0
        and cfg.tail_reversal_trigger_count > 0
        and cfg.tail_reversal_cooldown_seconds > 0
    )
    ml_filter = MLSignalFilter(
        enabled=cfg.ml_filter_enabled,
        model_path=cfg.ml_model_path,
        features_path=cfg.ml_features_path,
        min_ev=cfg.ml_min_ev,
        fail_open=cfg.ml_fail_open,
    )

    ordered_settlements = sorted(
        settlements.values(),
        key=lambda item: parse_dt(item.market_end_utc)
        or datetime.max.replace(tzinfo=timezone.utc),
    )
    next_settlement_idx = 0

    def finalize_settled_markets(now: datetime) -> None:
        nonlocal next_settlement_idx
        nonlocal cooldown_until
        nonlocal tail_reversal_hits
        nonlocal tail_reversal_cooldown_activations

        while next_settlement_idx < len(ordered_settlements):
            settlement = ordered_settlements[next_settlement_idx]
            market_end_dt = parse_dt(settlement.market_end_utc)
            if market_end_dt is None or market_end_dt > now:
                break
            next_settlement_idx += 1

            state = states.get(settlement.market_slug)
            if state is None or state.total_cost <= 0:
                if tail_reversal_enabled:
                    while (
                        recent_tail_hit_times
                        and (market_end_dt - recent_tail_hit_times[0]).total_seconds()
                        > cfg.tail_reversal_lookback_seconds
                    ):
                        recent_tail_hit_times.popleft()
                continue

            payout = (
                state.yes_shares
                if settlement.resolved_side == "UP"
                else state.down_shares
            )
            pnl = payout - state.total_cost - state.fee_total
            recent_market_results.append((pnl / state.total_cost, pnl > 0))

            if tail_reversal_enabled:
                is_hit = tail_reversal_hit_for_market(
                    state,
                    settlement,
                    tail_profiles.get(settlement.market_slug),
                    cfg,
                )
                if is_hit:
                    tail_reversal_hits += 1
                    recent_tail_hit_times.append(market_end_dt)
                while (
                    recent_tail_hit_times
                    and (market_end_dt - recent_tail_hit_times[0]).total_seconds()
                    > cfg.tail_reversal_lookback_seconds
                ):
                    recent_tail_hit_times.popleft()
                if (
                    is_hit
                    and len(recent_tail_hit_times) >= cfg.tail_reversal_trigger_count
                ):
                    new_until = market_end_dt + timedelta(
                        seconds=cfg.tail_reversal_cooldown_seconds
                    )
                    if cooldown_until is None or new_until > cooldown_until:
                        cooldown_until = new_until
                        tail_reversal_cooldown_activations += 1

    for snapshot in snapshots:
        slug = str(snapshot.get("market_slug") or "")
        settlement = settlements.get(slug)
        if settlement is None:
            continue
        now = snapshot["_dt"]
        finalize_settled_markets(now)
        state = states[slug]
        market_start_dt = parse_dt(
            snapshot.get("market_start_utc") or settlement.market_start_utc
        )
        elapsed_seconds = (
            (now - market_start_dt).total_seconds() if market_start_dt else None
        )

        signals = build_signals(snapshot, cfg)
        if cooldown_until is not None and now < cooldown_until and signals:
            skipped_tail_reversal_cooldown += len(signals)
            continue
        if signals and not passes_time_gate(elapsed_seconds, cfg):
            skipped_time_gate += len(signals)
            continue

        for signal in signals:
            last_signal = state.last_signal_ts.get(signal.side)
            if (
                last_signal is not None
                and (now - last_signal).total_seconds() < cfg.signal_cooldown_seconds
            ):
                skipped_signal_cooldown += 1
                continue
            state.last_signal_ts[signal.side] = now

            if (
                state.last_order_ts is not None
                and (now - state.last_order_ts).total_seconds()
                < cfg.order_cooldown_seconds
            ):
                skipped_order_cooldown += 1
                continue

            allowed, is_extension = can_pass_exposure(state, signal, cfg, now)
            if not allowed:
                skipped_exposure += 1
                continue

            if cfg.ml_filter_enabled:
                rolling_6_roi, rolling_10_roi, rolling_10_win_rate = (
                    rolling_market_features(recent_market_results)
                )
                source_signal = signal_to_source_signal(
                    snapshot=snapshot,
                    signal=signal,
                    elapsed_seconds=elapsed_seconds,
                    market_start_dt=market_start_dt,
                    is_extension=is_extension,
                )
                features = build_live_feature_values(
                    source_signal=source_signal,
                    ledger=state_to_ledger(state),
                    signal_side=signal.side,
                    yes_bid=optional_float(snapshot.get("yes_bid")),
                    yes_ask=optional_float(snapshot.get("yes_ask")),
                    down_bid=optional_float(snapshot.get("down_bid")),
                    down_ask=optional_float(snapshot.get("down_ask")),
                    rolling_6_market_roi=rolling_6_roi,
                    rolling_10_market_roi=rolling_10_roi,
                    rolling_10_market_win_rate=rolling_10_win_rate,
                    now_dt=now,
                )
                decision = ml_filter.evaluate(features)
                ml_evaluated_signals += 1
                if decision.passed:
                    ml_passed_signals += 1
                else:
                    skipped_ml_filter += 1
                    ml_blocked_signals += 1
                    if decision.reason.startswith(
                        ("model_unavailable", "prediction_failed")
                    ):
                        ml_error_signals += 1
                    continue

            state.add_fill(
                side=signal.side,
                amount_usd=cfg.trade_amount_usd,
                execution_price=signal.max_execution_price,
                fee_rate_bps=fee_rate_for_side(settlement, signal.side),
                snapshot_dt=now,
                market_start_dt=market_start_dt,
                is_extension=is_extension,
            )

    market_pnls: list[float] = []
    traded_markets = 0
    orders = 0
    total_cost = 0.0
    wins = 0
    losses = 0

    for slug, settlement in settlements.items():
        state = states.get(slug)
        if state is None or state.total_cost <= 0:
            continue
        traded_markets += 1
        orders += state.yes_orders + state.down_orders
        total_cost += state.total_cost
        payout = (
            state.yes_shares if settlement.resolved_side == "UP" else state.down_shares
        )
        pnl = payout - state.total_cost - state.fee_total
        market_pnls.append(pnl)
        if pnl > 0:
            wins += 1
        else:
            losses += 1

    total_pnl = sum(market_pnls)
    roi = total_pnl / total_cost if total_cost > 0 else 0.0
    win_rate = wins / (wins + losses) if wins + losses > 0 else 0.0
    max_drawdown = compute_max_drawdown(market_pnls)

    return ReplayResult(
        config=cfg,
        settled_markets=len(settlements),
        traded_markets=traded_markets,
        orders=orders,
        total_cost=total_cost,
        total_pnl=total_pnl,
        roi=roi,
        wins=wins,
        losses=losses,
        win_rate=win_rate,
        max_drawdown=max_drawdown,
        avg_orders_per_traded_market=orders / traded_markets if traded_markets else 0.0,
        p50_market_pnl=percentile(market_pnls, 0.50),
        p05_market_pnl=percentile(market_pnls, 0.05),
        p95_market_pnl=percentile(market_pnls, 0.95),
        skipped_due_order_cooldown=skipped_order_cooldown,
        skipped_due_signal_cooldown=skipped_signal_cooldown,
        skipped_due_exposure=skipped_exposure,
        skipped_due_time_gate=skipped_time_gate,
        skipped_due_tail_reversal_cooldown=skipped_tail_reversal_cooldown,
        skipped_due_ml_filter=skipped_ml_filter,
        ml_evaluated_signals=ml_evaluated_signals,
        ml_passed_signals=ml_passed_signals,
        ml_blocked_signals=ml_blocked_signals,
        ml_error_signals=ml_error_signals,
        ml_pass_rate=(
            ml_passed_signals / ml_evaluated_signals
            if ml_evaluated_signals
            else 0.0
        ),
        tail_reversal_hits=tail_reversal_hits,
        tail_reversal_cooldown_activations=tail_reversal_cooldown_activations,
    )


class ReplayRunner:
    def __init__(
        self,
        *,
        settlements: dict[str, Settlement],
        tail_profiles: dict[str, TailReversalProfile],
        cfg: ReplayConfig,
    ) -> None:
        self.settlements = settlements
        self.tail_profiles = tail_profiles
        self.cfg = cfg
        self.states: dict[str, MarketState] = defaultdict(MarketState)
        self.skipped_order_cooldown = 0
        self.skipped_signal_cooldown = 0
        self.skipped_exposure = 0
        self.skipped_time_gate = 0
        self.skipped_tail_reversal_cooldown = 0
        self.skipped_ml_filter = 0
        self.ml_evaluated_signals = 0
        self.ml_passed_signals = 0
        self.ml_blocked_signals = 0
        self.ml_error_signals = 0
        self.tail_reversal_hits = 0
        self.tail_reversal_cooldown_activations = 0
        self.cooldown_until: Optional[datetime] = None
        self.recent_tail_hit_times: deque[datetime] = deque()
        self.recent_market_results: deque[tuple[float, bool]] = deque(maxlen=50)
        self.tail_reversal_enabled = (
            cfg.tail_reversal_lookback_seconds > 0
            and cfg.tail_reversal_trigger_count > 0
            and cfg.tail_reversal_cooldown_seconds > 0
        )
        self.ml_filter = MLSignalFilter(
            enabled=cfg.ml_filter_enabled,
            model_path=cfg.ml_model_path,
            features_path=cfg.ml_features_path,
            min_ev=cfg.ml_min_ev,
            fail_open=cfg.ml_fail_open,
        )
        self.ordered_settlements = sorted(
            settlements.values(),
            key=lambda item: parse_dt(item.market_end_utc)
            or datetime.max.replace(tzinfo=timezone.utc),
        )
        self.next_settlement_idx = 0

    def finalize_settled_markets(self, now: datetime) -> None:
        while self.next_settlement_idx < len(self.ordered_settlements):
            settlement = self.ordered_settlements[self.next_settlement_idx]
            market_end_dt = parse_dt(settlement.market_end_utc)
            if market_end_dt is None or market_end_dt > now:
                break
            self.next_settlement_idx += 1

            state = self.states.get(settlement.market_slug)
            if state is None or state.total_cost <= 0:
                if self.tail_reversal_enabled:
                    while (
                        self.recent_tail_hit_times
                        and (market_end_dt - self.recent_tail_hit_times[0]).total_seconds()
                        > self.cfg.tail_reversal_lookback_seconds
                    ):
                        self.recent_tail_hit_times.popleft()
                continue

            payout = (
                state.yes_shares
                if settlement.resolved_side == "UP"
                else state.down_shares
            )
            pnl = payout - state.total_cost - state.fee_total
            self.recent_market_results.append((pnl / state.total_cost, pnl > 0))

            if self.tail_reversal_enabled:
                is_hit = tail_reversal_hit_for_market(
                    state,
                    settlement,
                    self.tail_profiles.get(settlement.market_slug),
                    self.cfg,
                )
                if is_hit:
                    self.tail_reversal_hits += 1
                    self.recent_tail_hit_times.append(market_end_dt)
                while (
                    self.recent_tail_hit_times
                    and (market_end_dt - self.recent_tail_hit_times[0]).total_seconds()
                    > self.cfg.tail_reversal_lookback_seconds
                ):
                    self.recent_tail_hit_times.popleft()
                if (
                    is_hit
                    and len(self.recent_tail_hit_times)
                    >= self.cfg.tail_reversal_trigger_count
                ):
                    new_until = market_end_dt + timedelta(
                        seconds=self.cfg.tail_reversal_cooldown_seconds
                    )
                    if self.cooldown_until is None or new_until > self.cooldown_until:
                        self.cooldown_until = new_until
                        self.tail_reversal_cooldown_activations += 1

    def process_snapshot(self, snapshot: dict[str, Any]) -> None:
        slug = str(snapshot.get("market_slug") or "")
        settlement = self.settlements.get(slug)
        if settlement is None:
            return
        now = snapshot["_dt"]
        self.finalize_settled_markets(now)
        state = self.states[slug]
        market_start_dt = parse_dt(
            snapshot.get("market_start_utc") or settlement.market_start_utc
        )
        elapsed_seconds = (
            (now - market_start_dt).total_seconds() if market_start_dt else None
        )

        signals = build_signals(snapshot, self.cfg)
        if self.cooldown_until is not None and now < self.cooldown_until and signals:
            self.skipped_tail_reversal_cooldown += len(signals)
            return
        if signals and not passes_time_gate(elapsed_seconds, self.cfg):
            self.skipped_time_gate += len(signals)
            return

        for signal in signals:
            last_signal = state.last_signal_ts.get(signal.side)
            if (
                last_signal is not None
                and (now - last_signal).total_seconds()
                < self.cfg.signal_cooldown_seconds
            ):
                self.skipped_signal_cooldown += 1
                continue
            state.last_signal_ts[signal.side] = now

            if (
                state.last_order_ts is not None
                and (now - state.last_order_ts).total_seconds()
                < self.cfg.order_cooldown_seconds
            ):
                self.skipped_order_cooldown += 1
                continue

            allowed, is_extension = can_pass_exposure(state, signal, self.cfg, now)
            if not allowed:
                self.skipped_exposure += 1
                continue

            if self.cfg.ml_filter_enabled:
                rolling_6_roi, rolling_10_roi, rolling_10_win_rate = (
                    rolling_market_features(self.recent_market_results)
                )
                source_signal = signal_to_source_signal(
                    snapshot=snapshot,
                    signal=signal,
                    elapsed_seconds=elapsed_seconds,
                    market_start_dt=market_start_dt,
                    is_extension=is_extension,
                )
                features = build_live_feature_values(
                    source_signal=source_signal,
                    ledger=state_to_ledger(state),
                    signal_side=signal.side,
                    yes_bid=optional_float(snapshot.get("yes_bid")),
                    yes_ask=optional_float(snapshot.get("yes_ask")),
                    down_bid=optional_float(snapshot.get("down_bid")),
                    down_ask=optional_float(snapshot.get("down_ask")),
                    rolling_6_market_roi=rolling_6_roi,
                    rolling_10_market_roi=rolling_10_roi,
                    rolling_10_market_win_rate=rolling_10_win_rate,
                    now_dt=now,
                )
                decision = self.ml_filter.evaluate(features)
                self.ml_evaluated_signals += 1
                if decision.passed:
                    self.ml_passed_signals += 1
                else:
                    self.skipped_ml_filter += 1
                    self.ml_blocked_signals += 1
                    if decision.reason.startswith(
                        ("model_unavailable", "prediction_failed")
                    ):
                        self.ml_error_signals += 1
                    continue

            state.add_fill(
                side=signal.side,
                amount_usd=self.cfg.trade_amount_usd,
                execution_price=signal.max_execution_price,
                fee_rate_bps=fee_rate_for_side(settlement, signal.side),
                snapshot_dt=now,
                market_start_dt=market_start_dt,
                is_extension=is_extension,
            )

    def result(self, settled_markets_count: Optional[int] = None) -> ReplayResult:
        market_pnls: list[float] = []
        traded_markets = 0
        orders = 0
        total_cost = 0.0
        wins = 0
        losses = 0

        for slug, settlement in self.settlements.items():
            state = self.states.get(slug)
            if state is None or state.total_cost <= 0:
                continue
            traded_markets += 1
            orders += state.yes_orders + state.down_orders
            total_cost += state.total_cost
            payout = (
                state.yes_shares
                if settlement.resolved_side == "UP"
                else state.down_shares
            )
            pnl = payout - state.total_cost - state.fee_total
            market_pnls.append(pnl)
            if pnl > 0:
                wins += 1
            else:
                losses += 1

        total_pnl = sum(market_pnls)
        roi = total_pnl / total_cost if total_cost > 0 else 0.0
        win_rate = wins / (wins + losses) if wins + losses > 0 else 0.0
        max_drawdown = compute_max_drawdown(market_pnls)

        return ReplayResult(
            config=self.cfg,
            settled_markets=(
                settled_markets_count
                if settled_markets_count is not None
                else len(self.settlements)
            ),
            traded_markets=traded_markets,
            orders=orders,
            total_cost=total_cost,
            total_pnl=total_pnl,
            roi=roi,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            max_drawdown=max_drawdown,
            avg_orders_per_traded_market=orders / traded_markets
            if traded_markets
            else 0.0,
            p50_market_pnl=percentile(market_pnls, 0.50),
            p05_market_pnl=percentile(market_pnls, 0.05),
            p95_market_pnl=percentile(market_pnls, 0.95),
            skipped_due_order_cooldown=self.skipped_order_cooldown,
            skipped_due_signal_cooldown=self.skipped_signal_cooldown,
            skipped_due_exposure=self.skipped_exposure,
            skipped_due_time_gate=self.skipped_time_gate,
            skipped_due_tail_reversal_cooldown=self.skipped_tail_reversal_cooldown,
            skipped_due_ml_filter=self.skipped_ml_filter,
            ml_evaluated_signals=self.ml_evaluated_signals,
            ml_passed_signals=self.ml_passed_signals,
            ml_blocked_signals=self.ml_blocked_signals,
            ml_error_signals=self.ml_error_signals,
            ml_pass_rate=(
                self.ml_passed_signals / self.ml_evaluated_signals
                if self.ml_evaluated_signals
                else 0.0
            ),
            tail_reversal_hits=self.tail_reversal_hits,
            tail_reversal_cooldown_activations=self.tail_reversal_cooldown_activations,
        )


def compute_max_drawdown(pnls: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_dd = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_dd = max(max_dd, peak - equity)
    return max_dd


def build_configs(args: argparse.Namespace) -> list[ReplayConfig]:
    base = ReplayConfig(
        edge_prob_threshold=0.03,
        edge_reference_price=args.edge_reference_price,
        max_spread=0.02,
        min_entry_ask_price=0.0,
        min_edge_after_fill=0.03,
        exec_slippage_ticks=1,
        exec_price_mode="hybrid",
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
        sigma_min=0.00001,
        tau_floor_seconds=5.0,
        z_cap=6.0,
        entry_time_windows=(),
        block_time_windows=(),
        tail_reversal_lookback_seconds=0.0,
        tail_reversal_trigger_count=0,
        tail_reversal_cooldown_seconds=0.0,
        tail_reversal_min_anchor_prob=args.tail_reversal_min_anchor_prob,
        tail_reversal_min_prob_drop=args.tail_reversal_min_prob_drop,
        tail_reversal_min_mid_gain=args.tail_reversal_min_mid_gain,
        ml_filter_enabled=args.ml_filter_enabled,
        ml_model_path=args.ml_model_path,
        ml_features_path=args.ml_features_path,
        ml_min_ev=0.0,
        ml_fail_open=args.ml_fail_open,
    )

    combos = itertools.product(
        parse_float_list(args.edge_thresholds),
        parse_float_list(args.min_entry_ask_prices),
        parse_float_list(args.max_spreads),
        parse_float_list(args.min_edge_after_fill_values),
        parse_int_list(args.exec_slippage_ticks_values),
        parse_str_list(args.exec_price_modes),
        parse_float_list(args.sigma_min_values),
        parse_float_list(args.tau_floor_seconds_values),
        parse_float_list(args.z_cap_values),
        parse_time_window_values(
            args.entry_time_windows_values, no_filter_tokens={"", "all", "*"}
        ),
        parse_time_window_values(
            args.block_time_windows_values, no_filter_tokens={"", "none"}
        ),
        parse_float_list(args.tail_reversal_lookback_seconds_values),
        parse_int_list(args.tail_reversal_trigger_count_values),
        parse_float_list(args.tail_reversal_cooldown_seconds_values),
        parse_float_list(args.ml_min_ev_values),
    )
    configs: list[ReplayConfig] = []
    for (
        edge,
        min_ask,
        spread,
        min_eaf,
        slip,
        exec_mode,
        sigma_min,
        tau_floor,
        z_cap,
        entry_windows,
        block_windows,
        tail_lookback,
        tail_trigger,
        tail_cooldown,
        ml_min_ev,
    ) in combos:
        configs.append(
            replace(
                base,
                edge_prob_threshold=edge,
                min_entry_ask_price=min_ask,
                max_spread=spread,
                min_edge_after_fill=min_eaf,
                exec_slippage_ticks=slip,
                exec_price_mode=exec_mode,
                sigma_min=sigma_min,
                tau_floor_seconds=tau_floor,
                z_cap=z_cap,
                entry_time_windows=entry_windows,
                block_time_windows=block_windows,
                tail_reversal_lookback_seconds=tail_lookback,
                tail_reversal_trigger_count=tail_trigger,
                tail_reversal_cooldown_seconds=tail_cooldown,
                ml_min_ev=ml_min_ev,
            )
        )
    return configs


def print_results(results: Sequence[ReplayResult], limit: int) -> None:
    if not results:
        print("No replay results.")
        return

    ordered = sorted(results, key=lambda item: (item.roi, item.total_pnl), reverse=True)
    print(
        "rank,roi,total_pnl,total_cost,traded,wins,losses,win_rate,orders,"
        "avg_orders,max_dd,p50,p05,p95,skip_time,skip_tail,skip_ml,"
        "ml_eval,ml_pass_rate,tail_hits,tail_cd_acts,config"
    )
    for rank, result in enumerate(ordered[:limit], start=1):
        print(
            f"{rank},"
            f"{result.roi:.4f},"
            f"{result.total_pnl:.2f},"
            f"{result.total_cost:.2f},"
            f"{result.traded_markets},"
            f"{result.wins},"
            f"{result.losses},"
            f"{result.win_rate:.4f},"
            f"{result.orders},"
            f"{result.avg_orders_per_traded_market:.2f},"
            f"{result.max_drawdown:.2f},"
            f"{result.p50_market_pnl:.2f},"
            f"{result.p05_market_pnl:.2f},"
            f"{result.p95_market_pnl:.2f},"
            f"{result.skipped_due_time_gate},"
            f"{result.skipped_due_tail_reversal_cooldown},"
            f"{result.skipped_due_ml_filter},"
            f"{result.ml_evaluated_signals},"
            f"{result.ml_pass_rate:.4f},"
            f"{result.tail_reversal_hits},"
            f"{result.tail_reversal_cooldown_activations},"
            f'"{result.config.label()}"'
        )


def write_results_csv(results: Sequence[ReplayResult], output_path: Path) -> None:
    fieldnames = [
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
        "tail_reversal_min_anchor_prob",
        "tail_reversal_min_prob_drop",
        "tail_reversal_min_mid_gain",
        "ml_filter_enabled",
        "ml_model_path",
        "ml_features_path",
        "ml_min_ev",
        "ml_fail_open",
        "settled_markets",
        "traded_markets",
        "orders",
        "total_cost",
        "total_pnl",
        "roi",
        "wins",
        "losses",
        "win_rate",
        "max_drawdown",
        "avg_orders_per_traded_market",
        "p50_market_pnl",
        "p05_market_pnl",
        "p95_market_pnl",
        "skipped_due_order_cooldown",
        "skipped_due_signal_cooldown",
        "skipped_due_exposure",
        "skipped_due_time_gate",
        "skipped_due_tail_reversal_cooldown",
        "skipped_due_ml_filter",
        "ml_evaluated_signals",
        "ml_passed_signals",
        "ml_blocked_signals",
        "ml_error_signals",
        "ml_pass_rate",
        "tail_reversal_hits",
        "tail_reversal_cooldown_activations",
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for result in sorted(
            results, key=lambda item: (item.roi, item.total_pnl), reverse=True
        ):
            cfg = result.config
            writer.writerow(
                {
                    "edge_prob_threshold": cfg.edge_prob_threshold,
                    "min_entry_ask_price": cfg.min_entry_ask_price,
                    "max_spread": cfg.max_spread,
                    "min_edge_after_fill": cfg.min_edge_after_fill,
                    "exec_slippage_ticks": cfg.exec_slippage_ticks,
                    "exec_price_mode": cfg.exec_price_mode,
                    "sigma_min": cfg.sigma_min,
                    "tau_floor_seconds": cfg.tau_floor_seconds,
                    "z_cap": cfg.z_cap,
                    "entry_time_windows": format_time_windows(
                        cfg.entry_time_windows, empty_label="all"
                    ),
                    "block_time_windows": format_time_windows(
                        cfg.block_time_windows, empty_label="none"
                    ),
                    "tail_reversal_lookback_seconds": cfg.tail_reversal_lookback_seconds,
                    "tail_reversal_trigger_count": cfg.tail_reversal_trigger_count,
                    "tail_reversal_cooldown_seconds": cfg.tail_reversal_cooldown_seconds,
                    "tail_reversal_min_anchor_prob": cfg.tail_reversal_min_anchor_prob,
                    "tail_reversal_min_prob_drop": cfg.tail_reversal_min_prob_drop,
                    "tail_reversal_min_mid_gain": cfg.tail_reversal_min_mid_gain,
                    "ml_filter_enabled": cfg.ml_filter_enabled,
                    "ml_model_path": str(cfg.ml_model_path),
                    "ml_features_path": str(cfg.ml_features_path),
                    "ml_min_ev": cfg.ml_min_ev,
                    "ml_fail_open": cfg.ml_fail_open,
                    "settled_markets": result.settled_markets,
                    "traded_markets": result.traded_markets,
                    "orders": result.orders,
                    "total_cost": round(result.total_cost, 8),
                    "total_pnl": round(result.total_pnl, 8),
                    "roi": round(result.roi, 8),
                    "wins": result.wins,
                    "losses": result.losses,
                    "win_rate": round(result.win_rate, 8),
                    "max_drawdown": round(result.max_drawdown, 8),
                    "avg_orders_per_traded_market": round(
                        result.avg_orders_per_traded_market, 8
                    ),
                    "p50_market_pnl": round(result.p50_market_pnl, 8),
                    "p05_market_pnl": round(result.p05_market_pnl, 8),
                    "p95_market_pnl": round(result.p95_market_pnl, 8),
                    "skipped_due_order_cooldown": result.skipped_due_order_cooldown,
                    "skipped_due_signal_cooldown": result.skipped_due_signal_cooldown,
                    "skipped_due_exposure": result.skipped_due_exposure,
                    "skipped_due_time_gate": result.skipped_due_time_gate,
                    "skipped_due_tail_reversal_cooldown": result.skipped_due_tail_reversal_cooldown,
                    "skipped_due_ml_filter": result.skipped_due_ml_filter,
                    "ml_evaluated_signals": result.ml_evaluated_signals,
                    "ml_passed_signals": result.ml_passed_signals,
                    "ml_blocked_signals": result.ml_blocked_signals,
                    "ml_error_signals": result.ml_error_signals,
                    "ml_pass_rate": round(result.ml_pass_rate, 8),
                    "tail_reversal_hits": result.tail_reversal_hits,
                    "tail_reversal_cooldown_activations": result.tail_reversal_cooldown_activations,
                }
            )


def config_needs_tail_profiles(cfg: ReplayConfig) -> bool:
    return (
        cfg.tail_reversal_lookback_seconds > 0
        and cfg.tail_reversal_trigger_count > 0
        and cfg.tail_reversal_cooldown_seconds > 0
    )


def day_filter_matches_snapshot(
    snapshot: dict[str, Any],
    *,
    start_day: str,
    end_day: str,
    include_days: set[str],
    exclude_days: set[str],
) -> bool:
    day = market_day_from_row(snapshot)
    if not day:
        return False
    if start_day and day < start_day:
        return False
    if end_day and day > end_day:
        return False
    if include_days and day not in include_days:
        return False
    if exclude_days and day in exclude_days:
        return False
    return True


def replay_configs_streaming(
    *,
    args: argparse.Namespace,
    settlements: dict[str, Settlement],
    evaluate_sources: set[str],
    source_mode: str,
    configs: Sequence[ReplayConfig],
) -> tuple[list[ReplayResult], SnapshotLoadStats, int, int]:
    stats = SnapshotLoadStats()
    runners = [
        ReplayRunner(settlements=settlements, tail_profiles={}, cfg=cfg)
        for cfg in configs
    ]
    active_slugs: set[str] = set()
    filtered_loaded_rows = 0
    start_day = args.start_day.strip()
    end_day = args.end_day.strip()
    include_days = parse_day_set(args.include_days)
    exclude_days = parse_day_set(args.exclude_days)

    for path in iter_snapshot_paths(args.snapshot_dir, args.snapshot_glob):
        snapshots = load_snapshots_for_path(
            path=path,
            settlements=settlements,
            evaluate_sources=evaluate_sources,
            source_mode=source_mode,
            strict_jsonl=args.strict_jsonl,
            stats=stats,
        )
        for snapshot in snapshots:
            if not day_filter_matches_snapshot(
                snapshot,
                start_day=start_day,
                end_day=end_day,
                include_days=include_days,
                exclude_days=exclude_days,
            ):
                continue
            filtered_loaded_rows += 1
            slug = str(snapshot.get("market_slug") or "")
            if slug:
                active_slugs.add(slug)
            for runner in runners:
                runner.process_snapshot(snapshot)

    results = [
        runner.result(settled_markets_count=len(active_slugs)) for runner in runners
    ]
    return results, stats, filtered_loaded_rows, len(active_slugs)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Replay bot tick snapshots and sweep gate parameters."
    )
    parser.add_argument("--snapshot-dir", type=Path, default=Path("tick_snapshots"))
    parser.add_argument(
        "--snapshot-glob",
        default="*.jsonl*",
        help="Snapshot glob; supports .jsonl and .jsonl.gz.",
    )
    parser.add_argument("--ledger-dir", type=Path, default=Path("ledger"))
    parser.add_argument(
        "--evaluate-sources",
        default=",".join(DEFAULT_EVALUATE_SOURCES),
        help="Comma-separated source_event values to evaluate, or 'all'.",
    )
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--output-csv", type=Path)
    parser.add_argument("--start-day", default="")
    parser.add_argument("--end-day", default="")
    parser.add_argument("--include-days", default="")
    parser.add_argument("--exclude-days", default="")
    parser.add_argument(
        "--strict-jsonl",
        action="store_true",
        help="Fail on the first invalid JSONL line instead of skipping bad lines.",
    )

    parser.add_argument("--edge-thresholds", default="0.03")
    parser.add_argument("--edge-reference-price", choices=["bid", "ask"], default="bid")
    parser.add_argument("--min-entry-ask-prices", default="0.0")
    parser.add_argument("--max-spreads", default="0.02")
    parser.add_argument("--min-edge-after-fill-values", default="0.03")
    parser.add_argument("--exec-slippage-ticks-values", default="1")
    parser.add_argument(
        "--exec-price-modes", default="hybrid", help="Comma-separated: book,edge,hybrid"
    )
    parser.add_argument("--exec-price-cap", type=float, default=0.99)
    parser.add_argument("--tick-size", type=float, default=0.01)
    parser.add_argument("--trade-amount-usd", type=float, default=1.0)
    parser.add_argument("--order-cooldown-seconds", type=float, default=15.0)
    parser.add_argument("--signal-cooldown-seconds", type=float, default=15.0)
    parser.add_argument("--market-max-total-cost", type=float, default=12.0)
    parser.add_argument("--market-max-side-cost", type=float, default=6.0)

    parser.add_argument("--side-extension-enabled", action="store_true")
    parser.add_argument("--side-extension-start-cost", type=float, default=6.0)
    parser.add_argument("--side-extension-max-side-cost", type=float, default=8.0)
    parser.add_argument("--side-extension-min-seconds", type=float, default=20.0)
    parser.add_argument("--side-extension-cooldown-seconds", type=float, default=15.0)
    parser.add_argument("--side-extension-min-edge", type=float, default=0.22)
    parser.add_argument(
        "--side-extension-min-edge-after-fill", type=float, default=0.20
    )
    parser.add_argument("--side-extension-min-ask-price", type=float, default=0.40)
    parser.add_argument("--side-extension-max-ask-price", type=float, default=0.80)
    parser.add_argument("--side-extension-max-opposite-cost", type=float, default=1.0)

    parser.add_argument(
        "--fair-mode", choices=["snapshot", "recompute"], default="snapshot"
    )
    parser.add_argument("--sigma-short-weight", type=float, default=0.6)
    parser.add_argument("--sigma-long-weight", type=float, default=0.4)
    parser.add_argument("--sigma-min-values", default="0.00001")
    parser.add_argument("--tau-floor-seconds-values", default="5")
    parser.add_argument("--z-cap-values", default="6")
    parser.add_argument("--tail-reversal-lookback-seconds-values", default="0")
    parser.add_argument("--tail-reversal-trigger-count-values", default="0")
    parser.add_argument("--tail-reversal-cooldown-seconds-values", default="0")
    parser.add_argument("--tail-reversal-anchor-seconds", type=float, default=30.0)
    parser.add_argument("--tail-reversal-confirm-seconds", type=float, default=5.0)
    parser.add_argument("--tail-reversal-min-anchor-prob", type=float, default=0.55)
    parser.add_argument("--tail-reversal-min-prob-drop", type=float, default=0.10)
    parser.add_argument("--tail-reversal-min-mid-gain", type=float, default=0.03)
    parser.add_argument("--ml-filter-enabled", action="store_true")
    parser.add_argument(
        "--ml-model-path",
        type=Path,
        default=Path("models/signal_filter_lgbm_v1.txt"),
    )
    parser.add_argument(
        "--ml-features-path",
        type=Path,
        default=Path("models/signal_filter_lgbm_v1_features.json"),
    )
    parser.add_argument("--ml-min-ev-values", default="0.15")
    parser.add_argument("--ml-fail-open", action="store_true")
    parser.add_argument(
        "--entry-time-windows-values",
        default="all",
        help=(
            "Semicolon-separated allow-list variants in elapsed seconds. "
            "Each variant is 'all' or comma-separated start-end windows, "
            "e.g. 'all;90-150;90-150,210-240'."
        ),
    )
    parser.add_argument(
        "--block-time-windows-values",
        default="none",
        help=(
            "Semicolon-separated block-list variants in elapsed seconds. "
            "Each variant is 'none' or comma-separated start-end windows, "
            "e.g. 'none;150-180;240-300'."
        ),
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
    source_mode = (
        "all" if args.evaluate_sources.strip().lower() == "all" else "selected"
    )
    evaluate_sources = set(
        DEFAULT_EVALUATE_SOURCES
        if source_mode == "all"
        else parse_str_list(args.evaluate_sources)
    )
    try:
        configs = build_configs(args)
    except ValueError as exc:
        print(f"ERROR: {exc}")
        return 1

    if not any(config_needs_tail_profiles(cfg) for cfg in configs):
        try:
            results, snapshot_stats, filtered_loaded_rows, active_market_count = (
                replay_configs_streaming(
                    args=args,
                    settlements=settlements,
                    evaluate_sources=evaluate_sources,
                    source_mode=source_mode,
                    configs=configs,
                )
            )
        except ValueError as exc:
            print(f"ERROR: {exc}")
            return 1
        print_snapshot_quality(snapshot_stats)
        if any([args.start_day, args.end_day, args.include_days, args.exclude_days]):
            print(f"Day-filtered snapshots: {filtered_loaded_rows}")
        if filtered_loaded_rows <= 0:
            print(
                f"No usable snapshots found in {args.snapshot_dir} matching {args.snapshot_glob}. "
                "Check --ledger-dir, --evaluate-sources, and day filters."
            )
            return 1
        print(
            f"Loaded {filtered_loaded_rows} snapshots across {active_market_count} "
            f"settled markets; replaying {len(configs)} config(s)."
        )
        print_results(results, args.top)
        if args.output_csv:
            write_results_csv(results, args.output_csv)
            print(f"Wrote CSV: {args.output_csv}")
        return 0

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
    snapshots = filter_snapshots_by_day(
        snapshots,
        start_day=args.start_day.strip(),
        end_day=args.end_day.strip(),
        include_days=parse_day_set(args.include_days),
        exclude_days=parse_day_set(args.exclude_days),
    )
    if any([args.start_day, args.end_day, args.include_days, args.exclude_days]):
        print(f"Day-filtered snapshots: {len(snapshots)}")
    if not snapshots:
        print(
            f"No usable snapshots found in {args.snapshot_dir} matching {args.snapshot_glob}. "
            "Check --ledger-dir, --evaluate-sources, and whether the snapshots cover settled markets."
        )
        return 1

    snapshot_slugs = {str(row.get("market_slug") or "") for row in snapshots}
    active_settlements = {
        slug: settlement
        for slug, settlement in settlements.items()
        if slug in snapshot_slugs
    }
    tail_profiles = build_tail_reversal_profiles(
        snapshots,
        anchor_seconds=args.tail_reversal_anchor_seconds,
        confirm_seconds=args.tail_reversal_confirm_seconds,
    )
    print(
        f"Loaded {len(snapshots)} snapshots across {len(active_settlements)} "
        f"settled markets; replaying {len(configs)} config(s)."
    )
    results = [
        replay_config(snapshots, active_settlements, tail_profiles, cfg)
        for cfg in configs
    ]
    print_results(results, args.top)
    if args.output_csv:
        write_results_csv(results, args.output_csv)
        print(f"Wrote CSV: {args.output_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
