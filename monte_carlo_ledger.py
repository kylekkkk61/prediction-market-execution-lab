#!/usr/bin/env python3
"""
Monte Carlo analysis over existing Polymarket bot ledgers.

This script treats each settled traded market as the primary unit of risk.
It supports:

- market bootstrap: resample individual markets with replacement
- day bootstrap: resample UTC trading days with replacement, preserving
  within-day market ordering

The goal is not to perfectly replay execution. It is to estimate the
distribution of outcomes implied by the observed ledger sample.
"""

from __future__ import annotations

import argparse
import csv
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def norm_side(side: str) -> str:
    return "UP" if side == "YES" else side


def to_float(value: str | None, default: float = 0.0) -> float:
    if value in (None, ""):
        return default
    return float(value)


def percentile(values: Sequence[float], q: float) -> float:
    if not values:
        return float("nan")
    if q <= 0:
        return min(values)
    if q >= 1:
        return max(values)
    ordered = sorted(values)
    pos = (len(ordered) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return ordered[lo]
    weight = pos - lo
    return ordered[lo] * (1 - weight) + ordered[hi] * weight


@dataclass(frozen=True)
class MarketSample:
    market_slug: str
    market_start_utc: str
    market_date: str
    total_cost: float
    net_pnl: float
    win: bool
    max_side_cost: float
    held_side: str
    resolved_side: str
    success_orders: int
    failed_orders: int
    success_yes_orders: int
    success_down_orders: int
    success_hit_rate: float | None
    low_price_success_orders: int
    post6_success_orders: int
    first_success_elapsed: float | None
    last_success_elapsed: float | None
    extension_rejections: int
    total_rejections: int
    replay_added_orders: int = 0
    replay_removed_orders: int = 0


@dataclass(frozen=True)
class IncludedFill:
    recorded_at: str
    market_start_utc: str
    outcome_bought: str
    amount_usd: float
    execution_price: float
    net_shares: float
    pnl_contribution: float
    synthetic: bool = False


@dataclass(frozen=True)
class ReplayEvent:
    kind: str
    recorded_at_raw: str
    recorded_at: datetime
    market_start_utc: str
    outcome_bought: str
    amount_usd: float
    ask: float
    execution_price: float
    signal_edge: float
    edge_after_fill: float
    raw: dict[str, str]


@dataclass(frozen=True)
class ReplayConfig:
    min_entry_ask_price: float
    market_max_total_cost: float
    market_max_side_cost: float
    side_extension_start_cost: float
    side_extension_max_side_cost: float
    side_extension_min_seconds: float
    side_extension_cooldown_seconds: float
    side_extension_min_edge: float
    side_extension_min_edge_after_fill: float
    side_extension_min_ask_price: float
    side_extension_max_ask_price: float
    side_extension_max_opposite_cost: float


@dataclass(frozen=True)
class LedgerContext:
    settlements: list[dict[str, str]]
    orders: list[dict[str, str]]
    rejections: list[dict[str, str]]
    settlements_by_slug: dict[str, dict[str, str]]
    orders_by_market: dict[str, list[dict[str, str]]]
    rejections_by_market: dict[str, list[dict[str, str]]]


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


DEFAULT_REPLAY_CONFIG = ReplayConfig(
    min_entry_ask_price=0.0,
    market_max_total_cost=12.0,
    market_max_side_cost=6.0,
    side_extension_start_cost=6.0,
    side_extension_max_side_cost=9.0,
    side_extension_min_seconds=20.0,
    side_extension_cooldown_seconds=15.0,
    side_extension_min_edge=0.22,
    side_extension_min_edge_after_fill=0.20,
    side_extension_min_ask_price=0.40,
    side_extension_max_ask_price=0.80,
    side_extension_max_opposite_cost=1.0,
)


def load_ledger_context(ledger_dir: Path) -> LedgerContext:
    settlements = load_csv(ledger_dir / "market_settlements.csv")
    orders = load_csv(ledger_dir / "orders.csv")
    rejections = load_csv(ledger_dir / "signal_rejections.csv")

    settlements_by_slug = {row["market_slug"]: row for row in settlements}
    orders_by_market: dict[str, list[dict[str, str]]] = defaultdict(list)
    rejections_by_market: dict[str, list[dict[str, str]]] = defaultdict(list)

    for row in orders:
        if row["market_slug"] in settlements_by_slug:
            orders_by_market[row["market_slug"]].append(row)

    for row in rejections:
        if row["market_slug"] in settlements_by_slug:
            rejections_by_market[row["market_slug"]].append(row)

    return LedgerContext(
        settlements=settlements,
        orders=orders,
        rejections=rejections,
        settlements_by_slug=settlements_by_slug,
        orders_by_market=dict(orders_by_market),
        rejections_by_market=dict(rejections_by_market),
    )


def estimate_fee_usdc(amount_usd: float, price: float, fee_rate_bps: float) -> float:
    return amount_usd * (fee_rate_bps / 10000.0) * min(price, 1.0 - price)


def estimate_net_shares(amount_usd: float, price: float, fee_rate_bps: float) -> float:
    if price <= 0:
        return 0.0
    gross_shares = amount_usd / price
    fee_shares = estimate_fee_usdc(amount_usd, price, fee_rate_bps) / price
    return max(0.0, gross_shares - fee_shares)


def fee_rate_bps_for_side(settlement: dict[str, str], side: str) -> float:
    fees_enabled = settlement.get("fees_enabled", "").strip().lower() == "true"
    if not fees_enabled:
        return 0.0
    if side == "YES":
        return to_float(settlement.get("yes_fee_rate_bps"))
    return to_float(settlement.get("down_fee_rate_bps"))


def build_market_sample_from_fills(
    settlement: dict[str, str],
    fills: Sequence[IncludedFill],
    failed_orders: int,
    extension_rejections: int,
    total_rejections: int,
    replay_added_orders: int = 0,
    replay_removed_orders: int = 0,
) -> MarketSample | None:
    total_cost = sum(fill.amount_usd for fill in fills)
    if total_cost <= 0:
        return None

    resolved_side = settlement["resolved_side"]
    success_yes = sum(1 for fill in fills if fill.outcome_bought == "YES")
    success_down = sum(1 for fill in fills if fill.outcome_bought == "DOWN")
    low_price_success = sum(1 for fill in fills if fill.execution_price <= 0.2)

    hits = [
        norm_side(fill.outcome_bought) == resolved_side
        for fill in fills
    ]
    hit_rate = (sum(hits) / len(hits)) if hits else None

    start_dt = parse_dt(fills[0].market_start_utc)
    elapsed_values = [
        (parse_dt(fill.recorded_at) - start_dt).total_seconds()
        for fill in fills
    ]
    first_success_elapsed = min(elapsed_values) if elapsed_values else None
    last_success_elapsed = max(elapsed_values) if elapsed_values else None

    post6_success_orders = 0
    yes_cost_running = 0.0
    down_cost_running = 0.0
    for fill in sorted(fills, key=lambda item: parse_dt(item.recorded_at)):
        side = fill.outcome_bought
        if (yes_cost_running if side == "YES" else down_cost_running) >= 6.0:
            post6_success_orders += 1
        if side == "YES":
            yes_cost_running += fill.amount_usd
        else:
            down_cost_running += fill.amount_usd

    yes_net_shares = sum(fill.net_shares for fill in fills if fill.outcome_bought == "YES")
    down_net_shares = sum(fill.net_shares for fill in fills if fill.outcome_bought == "DOWN")
    held_side = "BAL"
    if yes_net_shares > down_net_shares:
        held_side = "UP"
    elif down_net_shares > yes_net_shares:
        held_side = "DOWN"

    return MarketSample(
        market_slug=settlement["market_slug"],
        market_start_utc=settlement["market_start_utc"],
        market_date=parse_dt(settlement["market_start_utc"]).date().isoformat(),
        total_cost=total_cost,
        net_pnl=sum(fill.pnl_contribution for fill in fills),
        win=sum(fill.pnl_contribution for fill in fills) > 0,
        max_side_cost=max(yes_cost_running, down_cost_running),
        held_side=held_side,
        resolved_side=resolved_side,
        success_orders=len(fills),
        failed_orders=failed_orders,
        success_yes_orders=success_yes,
        success_down_orders=success_down,
        success_hit_rate=hit_rate,
        low_price_success_orders=low_price_success,
        post6_success_orders=post6_success_orders,
        first_success_elapsed=first_success_elapsed,
        last_success_elapsed=last_success_elapsed,
        extension_rejections=extension_rejections,
        total_rejections=total_rejections,
        replay_added_orders=replay_added_orders,
        replay_removed_orders=replay_removed_orders,
    )


def fill_from_success_order(
    row: dict[str, str],
    settlement: dict[str, str],
) -> IncludedFill | None:
    amount_usd = to_float(row.get("amount_usd"))
    execution_price = to_float(row.get("execution_price_estimate"))
    if amount_usd <= 0 or execution_price <= 0:
        return None
    net_shares = to_float(row.get("estimated_shares_net"))
    if net_shares <= 0:
        net_shares = estimate_net_shares(
            amount_usd=amount_usd,
            price=execution_price,
            fee_rate_bps=fee_rate_bps_for_side(settlement, row["outcome_bought"]),
        )
    won = norm_side(row["outcome_bought"]) == settlement["resolved_side"]
    pnl = (net_shares - amount_usd) if won else (-amount_usd)
    return IncludedFill(
        recorded_at=row["recorded_at"],
        market_start_utc=row["market_start_utc"],
        outcome_bought=row["outcome_bought"],
        amount_usd=amount_usd,
        execution_price=execution_price,
        net_shares=net_shares,
        pnl_contribution=pnl,
        synthetic=False,
    )


def fill_from_rejection(
    row: dict[str, str],
    settlement: dict[str, str],
) -> IncludedFill | None:
    amount_usd = to_float(row.get("amount_usd"))
    ask = to_float(row.get("signal_ask"))
    if amount_usd <= 0 or ask <= 0:
        return None
    fee_rate_bps = fee_rate_bps_for_side(settlement, row["outcome_bought"])
    net_shares = estimate_net_shares(amount_usd=amount_usd, price=ask, fee_rate_bps=fee_rate_bps)
    won = norm_side(row["outcome_bought"]) == settlement["resolved_side"]
    pnl = (net_shares - amount_usd) if won else (-amount_usd)
    return IncludedFill(
        recorded_at=row["recorded_at"],
        market_start_utc=row["market_start_utc"],
        outcome_bought=row["outcome_bought"],
        amount_usd=amount_usd,
        execution_price=ask,
        net_shares=net_shares,
        pnl_contribution=pnl,
        synthetic=True,
    )


def success_event_from_row(row: dict[str, str]) -> ReplayEvent | None:
    ask = to_float(row.get("signal_ask"), to_float(row.get("execution_price_estimate")))
    execution_price = to_float(row.get("execution_price_estimate"), ask)
    amount_usd = to_float(row.get("amount_usd"))
    if amount_usd <= 0 or ask <= 0 or execution_price <= 0:
        return None
    return ReplayEvent(
        kind="success",
        recorded_at_raw=row["recorded_at"],
        recorded_at=parse_dt(row["recorded_at"]),
        market_start_utc=row["market_start_utc"],
        outcome_bought=row["outcome_bought"],
        amount_usd=amount_usd,
        ask=ask,
        execution_price=execution_price,
        signal_edge=to_float(row.get("signal_edge")),
        edge_after_fill=to_float(row.get("signal_edge_after_fill_estimate")),
        raw=row,
    )


def rejection_event_from_row(row: dict[str, str]) -> ReplayEvent | None:
    ask = to_float(row.get("signal_ask"), to_float(row.get("signal_reference_price")))
    amount_usd = to_float(row.get("amount_usd"))
    if amount_usd <= 0 or ask <= 0:
        return None
    return ReplayEvent(
        kind="rejection",
        recorded_at_raw=row["recorded_at"],
        recorded_at=parse_dt(row["recorded_at"]),
        market_start_utc=row["market_start_utc"],
        outcome_bought=row["outcome_bought"],
        amount_usd=amount_usd,
        ask=ask,
        execution_price=ask,
        signal_edge=to_float(row.get("signal_edge")),
        edge_after_fill=to_float(row.get("signal_edge_after_fill_estimate")),
        raw=row,
    )


def infer_observed_replay_config(rejections: Sequence[dict[str, str]]) -> ReplayConfig:
    values = {
        "min_entry_ask_price": DEFAULT_REPLAY_CONFIG.min_entry_ask_price,
        "market_max_total_cost": DEFAULT_REPLAY_CONFIG.market_max_total_cost,
        "market_max_side_cost": DEFAULT_REPLAY_CONFIG.market_max_side_cost,
        "side_extension_start_cost": DEFAULT_REPLAY_CONFIG.side_extension_start_cost,
        "side_extension_max_side_cost": DEFAULT_REPLAY_CONFIG.side_extension_max_side_cost,
        "side_extension_min_seconds": DEFAULT_REPLAY_CONFIG.side_extension_min_seconds,
        "side_extension_cooldown_seconds": DEFAULT_REPLAY_CONFIG.side_extension_cooldown_seconds,
        "side_extension_min_edge": DEFAULT_REPLAY_CONFIG.side_extension_min_edge,
        "side_extension_min_edge_after_fill": DEFAULT_REPLAY_CONFIG.side_extension_min_edge_after_fill,
        "side_extension_min_ask_price": DEFAULT_REPLAY_CONFIG.side_extension_min_ask_price,
        "side_extension_max_ask_price": DEFAULT_REPLAY_CONFIG.side_extension_max_ask_price,
        "side_extension_max_opposite_cost": DEFAULT_REPLAY_CONFIG.side_extension_max_opposite_cost,
    }

    patterns = {
        "market_max_total_cost": re.compile(r"market_cap=(?P<v>[0-9.]+)"),
        "side_extension_max_side_cost": re.compile(r"extension_cap=(?P<v>[0-9.]+)"),
        "side_extension_min_seconds": re.compile(r"min_seconds=(?P<v>[0-9.]+)"),
        "side_extension_cooldown_seconds": re.compile(r"cooldown=(?P<v>[0-9.]+)"),
        "side_extension_min_edge": re.compile(r"min_edge=(?P<v>[0-9.]+)"),
        "side_extension_min_edge_after_fill": re.compile(r"min_edge_after_fill=(?P<v>[0-9.]+)"),
        "side_extension_max_opposite_cost": re.compile(r"max_opposite_cost=(?P<v>[0-9.]+)"),
    }

    for row in rejections:
        reason = row["rejection_reason"]
        if reason.startswith("extension_ask_out_of_range"):
            match = re.search(r"range=(?P<lo>[0-9.]+)-(?P<hi>[0-9.]+)", reason)
            if match:
                values["side_extension_min_ask_price"] = float(match.group("lo"))
                values["side_extension_max_ask_price"] = float(match.group("hi"))
        for key, pattern in patterns.items():
            match = pattern.search(reason)
            if match:
                values[key] = float(match.group("v"))

    return ReplayConfig(**values)


def build_replay_market_samples(context: LedgerContext) -> tuple[list[MarketSample], dict[str, int]]:
    meta = {
        "settled_markets": len(context.settlements),
        "skipped_markets": 0,
        "traded_markets": 0,
        "live_success_orders": 0,
        "live_failed_orders": 0,
        "signal_rejections": len(context.rejections),
        "replay_added_orders": 0,
        "replay_removed_orders": 0,
    }

    samples: list[MarketSample] = []

    for settlement in context.settlements:
        total_cost = to_float(settlement["total_cost"])
        if total_cost <= 0:
            meta["skipped_markets"] += 1
            continue

        slug = settlement["market_slug"]
        market_orders = sorted(
            context.orders_by_market.get(slug, []),
            key=lambda row: parse_dt(row["recorded_at"]),
        )
        market_rejections = context.rejections_by_market.get(slug, [])
        success_orders = [row for row in market_orders if row["status"] == "live_success"]
        failed_orders = [row for row in market_orders if row["status"] == "live_failed"]

        meta["live_success_orders"] += len(success_orders)
        meta["live_failed_orders"] += len(failed_orders)

        fills = [
            fill
            for row in success_orders
            if (fill := fill_from_success_order(row, settlement)) is not None
        ]
        extension_rejections = sum(
            1
            for row in market_rejections
            if row["rejection_reason"].startswith("extension_")
            or row["rejection_reason"].startswith("market_side_extension_cap_reached")
        )
        sample = build_market_sample_from_fills(
            settlement=settlement,
            fills=fills,
            failed_orders=len(failed_orders),
            extension_rejections=extension_rejections,
            total_rejections=len(market_rejections),
        )
        if sample is None:
            meta["skipped_markets"] += 1
            continue

        samples.append(sample)
        meta["traded_markets"] += 1

    samples.sort(key=lambda sample: sample.market_start_utc)
    return samples, meta


def build_market_samples(context: LedgerContext) -> tuple[list[MarketSample], dict[str, int]]:
    meta = {
        "settled_markets": len(context.settlements),
        "skipped_markets": 0,
        "traded_markets": 0,
        "live_success_orders": 0,
        "live_failed_orders": 0,
        "signal_rejections": len(context.rejections),
        "replay_added_orders": 0,
        "replay_removed_orders": 0,
    }
    samples: list[MarketSample] = []

    for settlement in context.settlements:
        total_cost = to_float(settlement["total_cost"])
        if total_cost <= 0:
            meta["skipped_markets"] += 1
            continue

        slug = settlement["market_slug"]
        market_orders = sorted(
            context.orders_by_market.get(slug, []),
            key=lambda row: parse_dt(row["recorded_at"]),
        )
        market_rejections = context.rejections_by_market.get(slug, [])
        success_orders = [row for row in market_orders if row["status"] == "live_success"]
        failed_orders = [row for row in market_orders if row["status"] == "live_failed"]
        meta["live_success_orders"] += len(success_orders)
        meta["live_failed_orders"] += len(failed_orders)

        success_yes = sum(1 for row in success_orders if row["outcome_bought"] == "YES")
        success_down = sum(1 for row in success_orders if row["outcome_bought"] == "DOWN")
        low_price_success = sum(
            1 for row in success_orders if to_float(row["execution_price_estimate"]) <= 0.2
        )
        hits = [norm_side(row["outcome_bought"]) == settlement["resolved_side"] for row in success_orders]
        hit_rate = (sum(hits) / len(hits)) if hits else None

        first_success_elapsed = None
        last_success_elapsed = None
        if success_orders:
            start_dt = parse_dt(success_orders[0]["market_start_utc"])
            elapsed_values = [
                (parse_dt(row["recorded_at"]) - start_dt).total_seconds()
                for row in success_orders
            ]
            first_success_elapsed = min(elapsed_values)
            last_success_elapsed = max(elapsed_values)

        post6_success_orders = 0
        yes_cost_running = 0.0
        down_cost_running = 0.0
        for row in success_orders:
            side = row["outcome_bought"]
            if (yes_cost_running if side == "YES" else down_cost_running) >= 6.0:
                post6_success_orders += 1
            amount = to_float(row["amount_usd"])
            if side == "YES":
                yes_cost_running += amount
            else:
                down_cost_running += amount

        held_side = "BAL"
        yes_shares = to_float(settlement["yes_shares"])
        down_shares = to_float(settlement["down_shares"])
        if yes_shares > down_shares:
            held_side = "UP"
        elif down_shares > yes_shares:
            held_side = "DOWN"

        extension_rejections = sum(
            1
            for row in market_rejections
            if row["rejection_reason"].startswith("extension_")
            or row["rejection_reason"].startswith("market_side_extension_cap_reached")
        )

        samples.append(
            MarketSample(
                market_slug=slug,
                market_start_utc=settlement["market_start_utc"],
                market_date=parse_dt(settlement["market_start_utc"]).date().isoformat(),
                total_cost=total_cost,
                net_pnl=to_float(settlement["net_pnl_estimate"]),
                win=to_float(settlement["net_pnl_estimate"]) > 0,
                max_side_cost=max(to_float(settlement["yes_cost"]), to_float(settlement["down_cost"])),
                held_side=held_side,
                resolved_side=settlement["resolved_side"],
                success_orders=len(success_orders),
                failed_orders=len(failed_orders),
                success_yes_orders=success_yes,
                success_down_orders=success_down,
                success_hit_rate=hit_rate,
                low_price_success_orders=low_price_success,
                post6_success_orders=post6_success_orders,
                first_success_elapsed=first_success_elapsed,
                last_success_elapsed=last_success_elapsed,
                extension_rejections=extension_rejections,
                total_rejections=len(market_rejections),
            )
        )
        meta["traded_markets"] += 1

    samples.sort(key=lambda sample: sample.market_start_utc)
    return samples, meta


def resolve_replay_config(args: argparse.Namespace, context: LedgerContext) -> ReplayConfig | None:
    cf_fields = (
        "cf_min_entry_ask_price",
        "cf_market_max_total_cost",
        "cf_market_max_side_cost",
        "cf_side_extension_start_cost",
        "cf_side_extension_max_side_cost",
        "cf_side_extension_min_seconds",
        "cf_side_extension_cooldown_seconds",
        "cf_side_extension_min_edge",
        "cf_side_extension_min_edge_after_fill",
        "cf_side_extension_min_ask_price",
        "cf_side_extension_max_ask_price",
        "cf_side_extension_max_opposite_cost",
    )
    if not any(getattr(args, field) is not None for field in cf_fields):
        return None

    inferred = infer_observed_replay_config(context.rejections)
    return ReplayConfig(
        min_entry_ask_price=args.cf_min_entry_ask_price if args.cf_min_entry_ask_price is not None else inferred.min_entry_ask_price,
        market_max_total_cost=args.cf_market_max_total_cost if args.cf_market_max_total_cost is not None else inferred.market_max_total_cost,
        market_max_side_cost=args.cf_market_max_side_cost if args.cf_market_max_side_cost is not None else inferred.market_max_side_cost,
        side_extension_start_cost=args.cf_side_extension_start_cost if args.cf_side_extension_start_cost is not None else inferred.side_extension_start_cost,
        side_extension_max_side_cost=args.cf_side_extension_max_side_cost if args.cf_side_extension_max_side_cost is not None else inferred.side_extension_max_side_cost,
        side_extension_min_seconds=args.cf_side_extension_min_seconds if args.cf_side_extension_min_seconds is not None else inferred.side_extension_min_seconds,
        side_extension_cooldown_seconds=args.cf_side_extension_cooldown_seconds if args.cf_side_extension_cooldown_seconds is not None else inferred.side_extension_cooldown_seconds,
        side_extension_min_edge=args.cf_side_extension_min_edge if args.cf_side_extension_min_edge is not None else inferred.side_extension_min_edge,
        side_extension_min_edge_after_fill=args.cf_side_extension_min_edge_after_fill if args.cf_side_extension_min_edge_after_fill is not None else inferred.side_extension_min_edge_after_fill,
        side_extension_min_ask_price=args.cf_side_extension_min_ask_price if args.cf_side_extension_min_ask_price is not None else inferred.side_extension_min_ask_price,
        side_extension_max_ask_price=args.cf_side_extension_max_ask_price if args.cf_side_extension_max_ask_price is not None else inferred.side_extension_max_ask_price,
        side_extension_max_opposite_cost=args.cf_side_extension_max_opposite_cost if args.cf_side_extension_max_opposite_cost is not None else inferred.side_extension_max_opposite_cost,
    )


def evaluate_replay_event(
    event: ReplayEvent,
    yes_cost: float,
    down_cost: float,
    extension_start_at: dict[str, datetime | None],
    last_extension_order_at: dict[str, datetime | None],
    config: ReplayConfig,
) -> tuple[bool, bool, str | None]:
    side = event.outcome_bought
    side_cost = yes_cost if side == "YES" else down_cost
    opposite_cost = down_cost if side == "YES" else yes_cost
    total_cost = yes_cost + down_cost

    if total_cost >= config.market_max_total_cost:
        return False, False, "market_total_cap_reached"
    if event.ask < config.min_entry_ask_price:
        return False, False, "min_entry_ask_price"
    if side_cost < config.market_max_side_cost:
        return True, False, None

    if side_cost >= config.side_extension_max_side_cost:
        return False, True, "market_side_extension_cap_reached"
    if event.ask < config.side_extension_min_ask_price or event.ask > config.side_extension_max_ask_price:
        return False, True, "extension_ask_out_of_range"
    if event.signal_edge < config.side_extension_min_edge:
        return False, True, "extension_edge_too_low"
    if event.edge_after_fill < config.side_extension_min_edge_after_fill:
        return False, True, "extension_edge_after_fill_too_low"
    if opposite_cost > config.side_extension_max_opposite_cost:
        return False, True, "extension_opposite_cost_too_high"

    start_at = extension_start_at[side]
    if start_at is None:
        return False, True, "extension_min_seconds_not_met"
    if (event.recorded_at - start_at).total_seconds() < config.side_extension_min_seconds:
        return False, True, "extension_min_seconds_not_met"
    last_extension = last_extension_order_at[side]
    if last_extension is not None and (event.recorded_at - last_extension).total_seconds() < config.side_extension_cooldown_seconds:
        return False, True, "extension_cooldown_not_met"
    return True, True, None


def update_replay_state(
    event: ReplayEvent,
    yes_cost: float,
    down_cost: float,
    extension_start_at: dict[str, datetime | None],
    last_extension_order_at: dict[str, datetime | None],
    config: ReplayConfig,
    is_extension_order: bool,
) -> tuple[float, float]:
    side = event.outcome_bought
    pre_side_cost = yes_cost if side == "YES" else down_cost
    if side == "YES":
        yes_cost += event.amount_usd
    else:
        down_cost += event.amount_usd

    post_side_cost = yes_cost if side == "YES" else down_cost
    if extension_start_at[side] is None and pre_side_cost < config.side_extension_start_cost <= post_side_cost:
        extension_start_at[side] = event.recorded_at
    if is_extension_order:
        last_extension_order_at[side] = event.recorded_at
    return yes_cost, down_cost


def build_counterfactual_market_samples(
    context: LedgerContext,
    config: ReplayConfig,
) -> tuple[list[MarketSample], dict[str, int]]:
    meta = {
        "settled_markets": len(context.settlements),
        "skipped_markets": 0,
        "traded_markets": 0,
        "live_success_orders": 0,
        "live_failed_orders": 0,
        "signal_rejections": len(context.rejections),
        "replay_added_orders": 0,
        "replay_removed_orders": 0,
    }
    samples: list[MarketSample] = []

    for settlement in context.settlements:
        slug = settlement["market_slug"]
        market_orders = sorted(
            context.orders_by_market.get(slug, []),
            key=lambda row: parse_dt(row["recorded_at"]),
        )
        market_rejections = sorted(
            context.rejections_by_market.get(slug, []),
            key=lambda row: parse_dt(row["recorded_at"]),
        )
        failed_orders = [row for row in market_orders if row["status"] == "live_failed"]
        meta["live_failed_orders"] += len(failed_orders)

        events: list[ReplayEvent] = []
        for row in market_orders:
            if row["status"] != "live_success":
                continue
            event = success_event_from_row(row)
            if event is not None:
                events.append(event)
        for row in market_rejections:
            event = rejection_event_from_row(row)
            if event is not None:
                events.append(event)
        events.sort(key=lambda item: (item.recorded_at, 0 if item.kind == "success" else 1))

        yes_cost = 0.0
        down_cost = 0.0
        extension_start_at: dict[str, datetime | None] = {"YES": None, "DOWN": None}
        last_extension_order_at: dict[str, datetime | None] = {"YES": None, "DOWN": None}
        fills: list[IncludedFill] = []
        replay_added = 0
        replay_removed = 0

        for event in events:
            allowed, is_extension_order, _ = evaluate_replay_event(
                event=event,
                yes_cost=yes_cost,
                down_cost=down_cost,
                extension_start_at=extension_start_at,
                last_extension_order_at=last_extension_order_at,
                config=config,
            )
            if not allowed:
                if event.kind == "success":
                    replay_removed += 1
                continue

            fill = (
                fill_from_success_order(event.raw, settlement)
                if event.kind == "success"
                else fill_from_rejection(event.raw, settlement)
            )
            if fill is None:
                continue
            fills.append(fill)
            yes_cost, down_cost = update_replay_state(
                event=event,
                yes_cost=yes_cost,
                down_cost=down_cost,
                extension_start_at=extension_start_at,
                last_extension_order_at=last_extension_order_at,
                config=config,
                is_extension_order=is_extension_order,
            )
            if event.kind == "rejection":
                replay_added += 1

        extension_rejections = sum(
            1
            for row in market_rejections
            if row["rejection_reason"].startswith("extension_")
            or row["rejection_reason"].startswith("market_side_extension_cap_reached")
        )
        sample = build_market_sample_from_fills(
            settlement=settlement,
            fills=fills,
            failed_orders=len(failed_orders),
            extension_rejections=extension_rejections,
            total_rejections=len(market_rejections),
            replay_added_orders=replay_added,
            replay_removed_orders=replay_removed,
        )
        meta["replay_added_orders"] += replay_added
        meta["replay_removed_orders"] += replay_removed
        meta["live_success_orders"] += len(fills)
        if sample is None:
            meta["skipped_markets"] += 1
            continue
        samples.append(sample)
        meta["traded_markets"] += 1

    samples.sort(key=lambda sample: sample.market_start_utc)
    return samples, meta


def max_drawdown_from_pnls(pnls: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    max_drawdown = 0.0
    for pnl in pnls:
        equity += pnl
        peak = max(peak, equity)
        max_drawdown = max(max_drawdown, peak - equity)
    return max_drawdown


def max_losing_streak(pnls: Sequence[float]) -> int:
    best = 0
    cur = 0
    for pnl in pnls:
        if pnl <= 0:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def summarize_sequence(samples: Sequence[MarketSample]) -> dict[str, float]:
    pnls = [sample.net_pnl for sample in samples]
    costs = [sample.total_cost for sample in samples]
    total_pnl = sum(pnls)
    total_cost = sum(costs)
    wins = sum(1 for sample in samples if sample.win)
    low_price_orders = sum(sample.low_price_success_orders for sample in samples)
    success_orders = sum(sample.success_orders for sample in samples)
    post6_orders = sum(sample.post6_success_orders for sample in samples)
    replay_added_orders = sum(sample.replay_added_orders for sample in samples)
    replay_removed_orders = sum(sample.replay_removed_orders for sample in samples)

    return {
        "traded_markets": float(len(samples)),
        "wins": float(wins),
        "losses": float(len(samples) - wins),
        "win_rate": (wins / len(samples)) if samples else float("nan"),
        "total_cost": total_cost,
        "total_pnl": total_pnl,
        "roi": (total_pnl / total_cost) if total_cost > 0 else float("nan"),
        "avg_market_pnl": (total_pnl / len(samples)) if samples else float("nan"),
        "max_drawdown": max_drawdown_from_pnls(pnls),
        "max_losing_streak": float(max_losing_streak(pnls)),
        "worst_market_pnl": min(pnls) if pnls else float("nan"),
        "best_market_pnl": max(pnls) if pnls else float("nan"),
        "avg_max_side_cost": (
            sum(sample.max_side_cost for sample in samples) / len(samples)
            if samples
            else float("nan")
        ),
        "low_price_success_share": (
            low_price_orders / success_orders if success_orders > 0 else float("nan")
        ),
        "post6_success_share": (
            post6_orders / success_orders if success_orders > 0 else float("nan")
        ),
        "avg_success_orders_per_market": (
            success_orders / len(samples) if samples else float("nan")
        ),
        "replay_added_share": (
            replay_added_orders / success_orders if success_orders > 0 else float("nan")
        ),
        "replay_removed_share": (
            replay_removed_orders / (success_orders + replay_removed_orders)
            if (success_orders + replay_removed_orders) > 0
            else float("nan")
        ),
    }


def bootstrap_market(
    samples: Sequence[MarketSample],
    rng: random.Random,
) -> list[MarketSample]:
    return [rng.choice(samples) for _ in range(len(samples))]


def bootstrap_day(
    samples: Sequence[MarketSample],
    rng: random.Random,
) -> list[MarketSample]:
    by_day: dict[str, list[MarketSample]] = defaultdict(list)
    for sample in samples:
        by_day[sample.market_date].append(sample)
    days = sorted(by_day)
    picked: list[MarketSample] = []
    for _ in range(len(days)):
        day = rng.choice(days)
        picked.extend(by_day[day])
    return picked


def simulate(
    samples: Sequence[MarketSample],
    simulations: int,
    method: str,
    seed: int | None,
) -> dict[str, list[float]]:
    rng = random.Random(seed)
    metrics = defaultdict(list)

    sampler = bootstrap_market if method == "market" else bootstrap_day

    for _ in range(simulations):
        draw = sampler(samples, rng)
        summary = summarize_sequence(draw)
        for key, value in summary.items():
            metrics[key].append(value)

    return dict(metrics)


def print_observed(label: str, meta: dict[str, int], observed: dict[str, float]) -> None:
    print(label)
    print(f"  settled_markets: {meta['settled_markets']}")
    print(f"  traded_markets: {meta['traded_markets']}")
    print(f"  skipped_markets: {meta['skipped_markets']}")
    print(f"  live_success_orders: {meta['live_success_orders']}")
    print(f"  live_failed_orders: {meta['live_failed_orders']}")
    print(f"  signal_rejections: {meta['signal_rejections']}")
    if "replay_added_orders" in meta:
        print(f"  replay_added_orders: {meta['replay_added_orders']}")
    if "replay_removed_orders" in meta:
        print(f"  replay_removed_orders: {meta['replay_removed_orders']}")
    print(f"  win_rate: {observed['win_rate']:.4f}")
    print(f"  total_cost: {observed['total_cost']:.2f}")
    print(f"  total_pnl: {observed['total_pnl']:.4f}")
    print(f"  roi: {observed['roi']:.4f}")
    print(f"  max_drawdown: {observed['max_drawdown']:.4f}")
    print(f"  max_losing_streak: {observed['max_losing_streak']:.0f}")
    print(f"  worst_market_pnl: {observed['worst_market_pnl']:.4f}")
    print(f"  best_market_pnl: {observed['best_market_pnl']:.4f}")
    print(f"  avg_max_side_cost: {observed['avg_max_side_cost']:.4f}")
    print(f"  low_price_success_share: {observed['low_price_success_share']:.4f}")
    print(f"  post6_success_share: {observed['post6_success_share']:.4f}")
    if "replay_added_share" in observed:
        print(f"  replay_added_share: {observed['replay_added_share']:.4f}")
    if "replay_removed_share" in observed:
        print(f"  replay_removed_share: {observed['replay_removed_share']:.4f}")
    print()


def print_distribution(
    observed: dict[str, float],
    metrics: dict[str, list[float]],
    metric_names: Sequence[str],
) -> None:
    header = (
        f"{'metric':<24}"
        f"{'observed':>12}"
        f"{'mean':>12}"
        f"{'p05':>12}"
        f"{'p25':>12}"
        f"{'p50':>12}"
        f"{'p75':>12}"
        f"{'p95':>12}"
    )
    print(header)
    print("-" * len(header))
    for name in metric_names:
        values = metrics[name]
        mean = sum(values) / len(values)
        row = (
            f"{name:<24}"
            f"{observed[name]:>12.4f}"
            f"{mean:>12.4f}"
            f"{percentile(values, 0.05):>12.4f}"
            f"{percentile(values, 0.25):>12.4f}"
            f"{percentile(values, 0.50):>12.4f}"
            f"{percentile(values, 0.75):>12.4f}"
            f"{percentile(values, 0.95):>12.4f}"
        )
        print(row)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run market-level Monte Carlo simulations from ledger CSVs."
    )
    parser.add_argument(
        "--ledger-dir",
        default="ledger",
        help="Path to ledger directory. Defaults to ./ledger",
    )
    parser.add_argument(
        "--method",
        choices=("market", "day"),
        default="market",
        help="Bootstrap unit. 'market' resamples traded markets; 'day' resamples UTC days.",
    )
    parser.add_argument(
        "--simulations",
        type=int,
        default=5000,
        help="Number of bootstrap simulations. Defaults to 5000.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed. Defaults to 42.",
    )
    parser.add_argument("--cf-min-entry-ask-price", type=float)
    parser.add_argument("--cf-market-max-total-cost", type=float)
    parser.add_argument("--cf-market-max-side-cost", type=float)
    parser.add_argument("--cf-side-extension-start-cost", type=float)
    parser.add_argument("--cf-side-extension-max-side-cost", type=float)
    parser.add_argument("--cf-side-extension-min-seconds", type=float)
    parser.add_argument("--cf-side-extension-cooldown-seconds", type=float)
    parser.add_argument("--cf-side-extension-min-edge", type=float)
    parser.add_argument("--cf-side-extension-min-edge-after-fill", type=float)
    parser.add_argument("--cf-side-extension-min-ask-price", type=float)
    parser.add_argument("--cf-side-extension-max-ask-price", type=float)
    parser.add_argument("--cf-side-extension-max-opposite-cost", type=float)
    return parser


def print_replay_config(config: ReplayConfig) -> None:
    print("Counterfactual Config")
    print(f"  min_entry_ask_price: {config.min_entry_ask_price:.4f}")
    print(f"  market_max_total_cost: {config.market_max_total_cost:.4f}")
    print(f"  market_max_side_cost: {config.market_max_side_cost:.4f}")
    print(f"  side_extension_start_cost: {config.side_extension_start_cost:.4f}")
    print(f"  side_extension_max_side_cost: {config.side_extension_max_side_cost:.4f}")
    print(f"  side_extension_min_seconds: {config.side_extension_min_seconds:.4f}")
    print(f"  side_extension_cooldown_seconds: {config.side_extension_cooldown_seconds:.4f}")
    print(f"  side_extension_min_edge: {config.side_extension_min_edge:.4f}")
    print(
        "  side_extension_min_edge_after_fill: "
        f"{config.side_extension_min_edge_after_fill:.4f}"
    )
    print(f"  side_extension_min_ask_price: {config.side_extension_min_ask_price:.4f}")
    print(f"  side_extension_max_ask_price: {config.side_extension_max_ask_price:.4f}")
    print(
        "  side_extension_max_opposite_cost: "
        f"{config.side_extension_max_opposite_cost:.4f}"
    )
    print()


def print_delta(observed: dict[str, float], counterfactual: dict[str, float]) -> None:
    print("Counterfactual Delta")
    for metric in (
        "traded_markets",
        "win_rate",
        "total_cost",
        "total_pnl",
        "roi",
        "avg_market_pnl",
        "max_drawdown",
        "max_losing_streak",
        "low_price_success_share",
        "post6_success_share",
        "replay_added_share",
        "replay_removed_share",
    ):
        print(f"  {metric}: {counterfactual[metric] - observed[metric]:+.4f}")
    print()


def main() -> None:
    args = build_parser().parse_args()
    ledger_dir = Path(args.ledger_dir).resolve()
    context = load_ledger_context(ledger_dir)
    samples, meta = build_market_samples(context)

    if not samples:
        raise SystemExit("No traded settled markets found in ledger.")

    observed = summarize_sequence(samples)
    metrics = simulate(
        samples=samples,
        simulations=args.simulations,
        method=args.method,
        seed=args.seed,
    )

    print(f"Ledger dir: {ledger_dir}")
    print(f"Bootstrap method: {args.method}")
    print(f"Simulations: {args.simulations}")
    print(f"Seed: {args.seed}")
    print()
    print_observed("Observed", meta, observed)
    print("Bootstrap Distribution")
    print_distribution(
        observed,
        metrics,
        metric_names=(
            "traded_markets",
            "win_rate",
            "total_cost",
            "total_pnl",
            "roi",
            "avg_market_pnl",
            "max_drawdown",
            "max_losing_streak",
            "worst_market_pnl",
            "best_market_pnl",
            "avg_max_side_cost",
            "low_price_success_share",
            "post6_success_share",
            "avg_success_orders_per_market",
            "replay_added_share",
            "replay_removed_share",
        ),
    )

    counterfactual_config = resolve_replay_config(args, context)
    if counterfactual_config is None:
        return

    counterfactual_samples, counterfactual_meta = build_counterfactual_market_samples(
        context=context,
        config=counterfactual_config,
    )
    if not counterfactual_samples:
        raise SystemExit("Counterfactual replay removed every traded market.")

    counterfactual_observed = summarize_sequence(counterfactual_samples)
    counterfactual_metrics = simulate(
        samples=counterfactual_samples,
        simulations=args.simulations,
        method=args.method,
        seed=args.seed,
    )

    print()
    print_replay_config(counterfactual_config)
    print_observed("Counterfactual (Approx Replay)", counterfactual_meta, counterfactual_observed)
    print_delta(observed, counterfactual_observed)
    print("Counterfactual Bootstrap Distribution")
    print_distribution(
        counterfactual_observed,
        counterfactual_metrics,
        metric_names=(
            "traded_markets",
            "win_rate",
            "total_cost",
            "total_pnl",
            "roi",
            "avg_market_pnl",
            "max_drawdown",
            "max_losing_streak",
            "worst_market_pnl",
            "best_market_pnl",
            "avg_max_side_cost",
            "low_price_success_share",
            "post6_success_share",
            "avg_success_orders_per_market",
            "replay_added_share",
            "replay_removed_share",
        ),
    )


if __name__ == "__main__":
    main()
