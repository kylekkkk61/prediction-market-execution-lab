#!/usr/bin/env python3
"""Run the public-sample ML filter methodology demo."""

from __future__ import annotations

import argparse
from pathlib import Path

from models.ml_filter import (
    load_public_model_decision_diagnostics,
    load_signal_examples,
    render_ml_filter_report,
    run_walk_forward_demo,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        default="data/sample/executions_sample.csv",
        help="Public sample executions CSV.",
    )
    parser.add_argument(
        "--output",
        default="reports/ml_filter_report.md",
        help="Markdown report output path.",
    )
    parser.add_argument(
        "--train-fraction",
        type=float,
        default=0.7,
        help="Chronological train fraction for the demo split.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    examples = load_signal_examples(args.input, label_column="filled")
    train, test = run_walk_forward_demo(examples, train_fraction=args.train_fraction)
    model_diagnostics = load_public_model_decision_diagnostics(args.input)
    report = render_ml_filter_report(
        train,
        test,
        source_path=args.input,
        model_diagnostics=model_diagnostics,
    )

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report, encoding="utf-8")
    print(f"Loaded examples: {len(examples)}")
    print(f"Wrote {output_path}")


if __name__ == "__main__":
    main()
