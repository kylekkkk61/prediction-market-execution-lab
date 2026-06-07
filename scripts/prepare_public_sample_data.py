#!/usr/bin/env python3
"""Generate public-safe sample CSVs from local private raw data.

This script never writes raw private rows directly. It writes small anonymized
CSV samples under data/sample by default.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from data_sources.public_sample import generate_public_samples


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger-dir", type=Path, default=Path("private/raw_data/ledger"))
    parser.add_argument("--tick-dir", type=Path, default=Path("private/raw_data/tick_snapshots"))
    parser.add_argument("--output-dir", type=Path, default=Path("data/sample"))
    parser.add_argument("--max-tick-files", type=int, default=7)
    parser.add_argument("--max-tick-rows-per-file", type=int, default=1500)
    parser.add_argument("--max-ledger-rows-per-file", type=int, default=1000)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    summaries = generate_public_samples(
        ledger_dir=args.ledger_dir,
        tick_dir=args.tick_dir,
        output_dir=args.output_dir,
        max_tick_files=args.max_tick_files,
        max_tick_rows_per_file=args.max_tick_rows_per_file,
        max_ledger_rows_per_file=args.max_ledger_rows_per_file,
    )
    print("Generated public-safe sample files:")
    for summary in summaries:
        print(f"- {summary.output_path}: {summary.rows_written} rows, {len(summary.columns)} columns")


if __name__ == "__main__":
    main()
