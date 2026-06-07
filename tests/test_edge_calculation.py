from __future__ import annotations

import pytest

from execution_quality.edge import (
    EdgeSnapshot,
    ExecutionEdgeConfig,
    compute_execution_plan,
    is_candidate_edge,
    quantize_price_down,
    theoretical_edge,
)


def test_quantize_price_down_respects_tick_size() -> None:
    assert quantize_price_down(0.678, 0.01) == pytest.approx(0.67)
    assert quantize_price_down(0.678, 0.001) == pytest.approx(0.678)


def test_theoretical_edge_is_fair_minus_reference_price() -> None:
    assert theoretical_edge(0.62, 0.58) == pytest.approx(0.04)


def test_compute_execution_plan_preserves_min_edge_after_fill() -> None:
    plan = compute_execution_plan(
        fair_probability=0.67,
        ask_price=0.61,
        config=ExecutionEdgeConfig(
            min_edge_after_fill=0.03,
            exec_slippage_ticks=5,
            exec_price_mode="min",
            tick_size=0.01,
        ),
    )

    assert plan is not None
    assert plan.max_execution_price == pytest.approx(0.64)
    assert plan.edge_after_fill == pytest.approx(0.03)


def test_compute_execution_plan_returns_none_when_ask_violates_edge_constraint() -> None:
    plan = compute_execution_plan(
        fair_probability=0.62,
        ask_price=0.61,
        config=ExecutionEdgeConfig(min_edge_after_fill=0.03, tick_size=0.01),
    )

    assert plan is None


def test_compute_execution_plan_rejects_unknown_price_mode() -> None:
    with pytest.raises(ValueError):
        compute_execution_plan(
            fair_probability=0.67,
            ask_price=0.61,
            config=ExecutionEdgeConfig(exec_price_mode="unknown"),
        )


def test_is_candidate_edge_uses_bid_reference_price_by_default() -> None:
    snapshot = EdgeSnapshot(side="UP", fair_probability=0.62, bid=0.58, ask=0.60)

    assert is_candidate_edge(
        snapshot,
        edge_threshold=0.03,
        max_spread=0.03,
        min_entry_ask_price=0.10,
    )


def test_is_candidate_edge_blocks_wide_spread() -> None:
    snapshot = EdgeSnapshot(side="UP", fair_probability=0.62, bid=0.50, ask=0.60)

    assert not is_candidate_edge(
        snapshot,
        edge_threshold=0.03,
        max_spread=0.03,
        min_entry_ask_price=0.10,
    )
