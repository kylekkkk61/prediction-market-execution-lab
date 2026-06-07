#!/usr/bin/env python3
"""Generate the public execution-quality report from sample data."""

from __future__ import annotations

import argparse
from pathlib import Path

from execution_quality.fill_analysis import render_markdown, summarize_execution_quality


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample-dir",
        type=Path,
        default=Path("data/sample"),
        help="Directory containing public sample CSV files.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("reports/execution_quality_report.md"),
        help="Markdown report output path.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summary = summarize_execution_quality(args.sample_dir)
    report = render_markdown(summary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
