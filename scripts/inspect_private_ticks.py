#!/usr/bin/env python3
"""Inspect private tick snapshot JSONL files with aggregate output only."""

from __future__ import annotations

import argparse
from pathlib import Path

from data_sources.private_inspection import PrivateDataInventory, inspect_private_data, inventory_to_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tick-dir",
        type=Path,
        default=Path("private/raw_data/tick_snapshots"),
        help="Local private tick snapshot directory. This path must stay gitignored.",
    )
    parser.add_argument(
        "--max-rows-per-file",
        type=int,
        default=5_000,
        help="Rows to scan per tick file for quick local inspection. Use 0 for full scan.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    max_rows = None if args.max_rows_per_file == 0 else args.max_rows_per_file
    inventory = inspect_private_data(
        ledger_dir=Path("__skip_ledger__"),
        tick_dir=args.tick_dir,
        tick_max_rows=max_rows,
    )
    tick_only = PrivateDataInventory(
        ledger_dir="not inspected",
        tick_dir=inventory.tick_dir,
        ledger_csv_files=(),
        tick_files=inventory.tick_files,
        skipped_files=inventory.skipped_files,
    )
    print(inventory_to_markdown(tick_only))


if __name__ == "__main__":
    main()
