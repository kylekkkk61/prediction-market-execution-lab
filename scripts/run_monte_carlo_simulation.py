#!/usr/bin/env python3
"""Generate the sample-only risk simulation report."""

from __future__ import annotations

import argparse
from pathlib import Path

from risk.monte_carlo import load_normalized_pnl, render_risk_report, summarize_monte_carlo


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settlements",
        default="data/sample/settlements_sample.csv",
        help="Public settlements sample CSV with normalized PnL.",
    )
    parser.add_argument(
        "--output",
        default="reports/risk_simulation_report.md",
        help="Markdown report output path.",
    )
    parser.add_argument("--simulations", type=int, default=1000)
    parser.add_argument("--horizon", type=int, default=None)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pnl_values = load_normalized_pnl(args.settlements)
    summary = summarize_monte_carlo(
        pnl_values,
        simulation_count=args.simulations,
        horizon=args.horizon,
        seed=args.seed,
    )
    report = render_risk_report(summary)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
