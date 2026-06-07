"""Tick-level replay utilities for short-horizon prediction-market research.

The replay layer converts historical or synthetic market snapshots into candidate
signals. It intentionally stops at research outputs and contains no live order
placement, wallet, or production execution logic.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping

from execution_quality.edge import (
    EdgeSnapshot,
    ExecutionEdgeConfig,
    ExecutionPlan,
    compute_execution_plan,
    is_candidate_edge,
    theoretical_edge,
)
from models.fair_probability import FairProbabilityConfig, estimate_binary_probabilities


@dataclass(frozen=True)
class TickSnapshot:
    """A single replayable market snapshot.

    Prices are probabilities in the ``[0, 1]`` range. Volatility inputs should use
    the same time unit as ``remaining_seconds``.
    """

    timestamp: str
    market_id: str
    current_price: float
    open_anchor_price: float
    sigma_short: float
    sigma_long: float
    remaining_seconds: float
    up_bid: float
    up_ask: float
    down_bid: float
    down_ask: float


@dataclass(frozen=True)
class ReplayConfig:
    """Configuration for a dry-run tick replay."""

    edge_threshold: float = 0.03
    max_spread: float = 0.08
    min_entry_ask_price: float = 0.02
    reference_price: str = "bid"
    fair_probability_config: FairProbabilityConfig | None = None
    execution_edge_config: ExecutionEdgeConfig | None = None


@dataclass(frozen=True)
class ReplaySignal:
    """A candidate signal emitted by the replay engine."""

    timestamp: str
    market_id: str
    side: str
    fair_probability: float
    bid: float
    ask: float
    spread: float
    theoretical_edge: float
    max_execution_price: float
    edge_after_fill: float


_REQUIRED_COLUMNS = {
    "timestamp",
    "market_id",
    "current_price",
    "open_anchor_price",
    "sigma_short",
    "sigma_long",
    "remaining_seconds",
    "up_bid",
    "up_ask",
    "down_bid",
    "down_ask",
}


def _to_float(row: Mapping[str, str], key: str) -> float:
    value = row[key]
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"Invalid float for column {key!r}: {value!r}") from exc


def tick_snapshot_from_mapping(row: Mapping[str, str]) -> TickSnapshot:
    """Build a :class:`TickSnapshot` from a CSV-style mapping."""

    missing_columns = _REQUIRED_COLUMNS.difference(row.keys())
    if missing_columns:
        missing = ", ".join(sorted(missing_columns))
        raise ValueError(f"Missing required tick snapshot columns: {missing}")

    return TickSnapshot(
        timestamp=row["timestamp"],
        market_id=row["market_id"],
        current_price=_to_float(row, "current_price"),
        open_anchor_price=_to_float(row, "open_anchor_price"),
        sigma_short=_to_float(row, "sigma_short"),
        sigma_long=_to_float(row, "sigma_long"),
        remaining_seconds=_to_float(row, "remaining_seconds"),
        up_bid=_to_float(row, "up_bid"),
        up_ask=_to_float(row, "up_ask"),
        down_bid=_to_float(row, "down_bid"),
        down_ask=_to_float(row, "down_ask"),
    )


def load_tick_snapshots_csv(path: str | Path) -> list[TickSnapshot]:
    """Load replay snapshots from a CSV file."""

    with Path(path).open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [tick_snapshot_from_mapping(row) for row in reader]


def replay_tick_snapshots(
    snapshots: Iterable[TickSnapshot],
    config: ReplayConfig | None = None,
) -> list[ReplaySignal]:
    """Replay snapshots and return execution-aware candidate signals.

    The replay estimates UP/DOWN fair probabilities, checks basic quote filters,
    and computes a maximum acceptable fill price for each accepted candidate.
    """

    cfg = config or ReplayConfig()
    signals: list[ReplaySignal] = []

    for snapshot in snapshots:
        up_probability, down_probability = estimate_binary_probabilities(
            current_price=snapshot.current_price,
            open_anchor_price=snapshot.open_anchor_price,
            sigma_short=snapshot.sigma_short,
            sigma_long=snapshot.sigma_long,
            remaining_seconds=snapshot.remaining_seconds,
            config=cfg.fair_probability_config,
        )

        side_quotes = [
            EdgeSnapshot(
                side="UP",
                fair_probability=up_probability,
                bid=snapshot.up_bid,
                ask=snapshot.up_ask,
            ),
            EdgeSnapshot(
                side="DOWN",
                fair_probability=down_probability,
                bid=snapshot.down_bid,
                ask=snapshot.down_ask,
            ),
        ]

        for quote in side_quotes:
            if not is_candidate_edge(
                quote,
                edge_threshold=cfg.edge_threshold,
                max_spread=cfg.max_spread,
                min_entry_ask_price=cfg.min_entry_ask_price,
                reference_price=cfg.reference_price,
            ):
                continue

            execution_plan = compute_execution_plan(
                fair_probability=quote.fair_probability,
                ask_price=quote.ask,
                config=cfg.execution_edge_config,
            )
            if execution_plan is None:
                continue

            signals.append(_build_signal(snapshot, quote, execution_plan, cfg.reference_price))

    return signals


def _build_signal(
    snapshot: TickSnapshot,
    quote: EdgeSnapshot,
    execution_plan: ExecutionPlan,
    reference_price: str,
) -> ReplaySignal:
    selected_price = quote.bid if reference_price == "bid" else quote.ask
    return ReplaySignal(
        timestamp=snapshot.timestamp,
        market_id=snapshot.market_id,
        side=quote.side,
        fair_probability=quote.fair_probability,
        bid=quote.bid,
        ask=quote.ask,
        spread=quote.spread,
        theoretical_edge=theoretical_edge(quote.fair_probability, selected_price),
        max_execution_price=execution_plan.max_execution_price,
        edge_after_fill=execution_plan.edge_after_fill,
    )
