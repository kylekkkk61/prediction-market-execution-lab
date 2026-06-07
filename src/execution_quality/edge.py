"""Executable-edge calculations for short-horizon prediction-market analysis.

This module separates theoretical pricing edge from execution-aware edge. It is
safe for public research use and does not contain live order-placement logic.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ExecutionEdgeConfig:
    """Configuration for execution-aware edge calculations."""

    min_edge_after_fill: float = 0.03
    exec_slippage_ticks: int = 0
    exec_price_mode: str = "min"  # one of: book, edge, min
    exec_price_cap: float = 0.0
    tick_size: float = 0.01


@dataclass(frozen=True)
class ExecutionPlan:
    """Maximum acceptable fill price and estimated edge after fill."""

    max_execution_price: float
    edge_after_fill: float


@dataclass(frozen=True)
class EdgeSnapshot:
    """A single side's market quote and model-implied fair probability."""

    side: str
    fair_probability: float
    bid: float
    ask: float

    @property
    def spread(self) -> float:
        """Return ask minus bid."""

        return self.ask - self.bid


def quantize_price_down(price: float, tick_size: float) -> float:
    """Round a price down to the nearest allowed tick."""

    if tick_size <= 0:
        return price
    tick_text = f"{tick_size:.12f}".rstrip("0")
    decimals = len(tick_text.split(".", 1)[1]) if "." in tick_text else 0
    steps = math.floor((price / tick_size) + 1e-9)
    return round(steps * tick_size, decimals)


def theoretical_edge(fair_probability: float, reference_price: float) -> float:
    """Return fair probability minus the selected market reference price."""

    return fair_probability - reference_price


def compute_execution_plan(
    *,
    fair_probability: float,
    ask_price: float,
    config: ExecutionEdgeConfig | None = None,
) -> ExecutionPlan | None:
    """Compute a maximum acceptable execution price for a candidate signal.

    ``edge_after_fill`` is the remaining probability edge after assuming the
    maximum fill price. A return value of ``None`` means the ask cannot satisfy
    the configured execution-aware edge constraint.
    """

    cfg = config or ExecutionEdgeConfig()
    if ask_price <= 0 or fair_probability <= 0:
        return None

    max_book_price = ask_price + (cfg.exec_slippage_ticks * cfg.tick_size)
    max_edge_price = fair_probability - cfg.min_edge_after_fill

    if cfg.exec_price_mode == "book":
        max_execution_price = max_book_price
    elif cfg.exec_price_mode == "edge":
        max_execution_price = max_edge_price
    elif cfg.exec_price_mode == "min":
        max_execution_price = min(max_book_price, max_edge_price)
    else:
        raise ValueError("exec_price_mode must be one of: book, edge, min")

    if cfg.exec_price_cap > 0:
        max_execution_price = min(max_execution_price, cfg.exec_price_cap)

    max_execution_price = min(max_execution_price, 1.0 - cfg.tick_size)
    max_execution_price = quantize_price_down(max_execution_price, cfg.tick_size)
    if max_execution_price < ask_price:
        return None

    return ExecutionPlan(
        max_execution_price=max_execution_price,
        edge_after_fill=fair_probability - max_execution_price,
    )


def is_candidate_edge(
    snapshot: EdgeSnapshot,
    *,
    edge_threshold: float,
    max_spread: float,
    min_entry_ask_price: float,
    reference_price: str = "bid",
) -> bool:
    """Return whether a quote passes basic research-level edge filters."""

    if snapshot.bid <= 0 or snapshot.ask <= 0:
        return False
    if snapshot.spread > max_spread:
        return False
    if snapshot.ask < min_entry_ask_price:
        return False
    if reference_price == "bid":
        selected_price = snapshot.bid
    elif reference_price == "ask":
        selected_price = snapshot.ask
    else:
        raise ValueError("reference_price must be either 'bid' or 'ask'")
    return theoretical_edge(snapshot.fair_probability, selected_price) > edge_threshold
