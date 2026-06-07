from pathlib import Path

from backtesting.tick_replay import (
    ReplayConfig,
    TickSnapshot,
    load_tick_snapshots_csv,
    replay_tick_snapshots,
)
from execution_quality.edge import ExecutionEdgeConfig


def test_replay_emits_candidate_signal_for_sample_snapshot() -> None:
    snapshots = [
        TickSnapshot(
            timestamp="2026-06-01T00:00:10Z",
            market_id="demo-market",
            current_price=100.4,
            open_anchor_price=100.0,
            sigma_short=0.0012,
            sigma_long=0.0010,
            remaining_seconds=250.0,
            up_bid=0.50,
            up_ask=0.52,
            down_bid=0.46,
            down_ask=0.48,
        )
    ]

    signals = replay_tick_snapshots(
        snapshots,
        ReplayConfig(
            edge_threshold=0.03,
            execution_edge_config=ExecutionEdgeConfig(min_edge_after_fill=0.03),
        ),
    )

    assert len(signals) == 1
    signal = signals[0]
    assert signal.side == "UP"
    assert signal.fair_probability > signal.ask
    assert signal.edge_after_fill >= 0.03


def test_replay_loads_sample_csv() -> None:
    sample_path = Path("data/sample/tick_snapshots_sample.csv")

    snapshots = load_tick_snapshots_csv(sample_path)

    assert len(snapshots) > 0
    assert snapshots[0].market_id.startswith("market_")
    assert snapshots[0].current_price > 0
    assert snapshots[0].up_ask >= snapshots[0].up_bid


def test_replay_filters_wide_spread() -> None:
    snapshots = [
        TickSnapshot(
            timestamp="2026-06-01T00:00:10Z",
            market_id="wide-spread-demo",
            current_price=100.6,
            open_anchor_price=100.0,
            sigma_short=0.0012,
            sigma_long=0.0010,
            remaining_seconds=250.0,
            up_bid=0.40,
            up_ask=0.60,
            down_bid=0.39,
            down_ask=0.59,
        )
    ]

    signals = replay_tick_snapshots(snapshots, ReplayConfig(max_spread=0.05))

    assert signals == []
