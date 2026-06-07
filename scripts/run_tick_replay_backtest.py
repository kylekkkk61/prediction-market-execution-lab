"""Run the public tick replay demo on sample data.

This script is intentionally read-only and research-oriented. It loads synthetic
sample snapshots, emits candidate signals, and prints a compact summary.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from backtesting.tick_replay import ReplayConfig, load_tick_snapshots_csv, replay_tick_snapshots
from execution_quality.edge import ExecutionEdgeConfig


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run a sample tick replay demo.")
    parser.add_argument(
        "--input",
        default="data/sample/tick_snapshots_sample.csv",
        help="Path to a tick snapshot CSV file.",
    )
    parser.add_argument("--edge-threshold", type=float, default=0.03)
    parser.add_argument("--min-edge-after-fill", type=float, default=0.03)
    parser.add_argument("--max-spread", type=float, default=0.08)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = PROJECT_ROOT / args.input
    snapshots = load_tick_snapshots_csv(input_path)
    config = ReplayConfig(
        edge_threshold=args.edge_threshold,
        max_spread=args.max_spread,
        execution_edge_config=ExecutionEdgeConfig(
            min_edge_after_fill=args.min_edge_after_fill,
        ),
    )
    signals = replay_tick_snapshots(snapshots, config)

    print(f"Loaded snapshots: {len(snapshots)}")
    print(f"Candidate signals: {len(signals)}")
    for signal in signals:
        print(
            " | ".join(
                [
                    signal.timestamp,
                    signal.market_id,
                    signal.side,
                    f"fair={signal.fair_probability:.4f}",
                    f"bid={signal.bid:.2f}",
                    f"ask={signal.ask:.2f}",
                    f"edge={signal.theoretical_edge:.4f}",
                    f"max_px={signal.max_execution_price:.2f}",
                    f"edge_after_fill={signal.edge_after_fill:.4f}",
                ]
            )
        )


if __name__ == "__main__":
    main()
