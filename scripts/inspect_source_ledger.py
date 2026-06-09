#!/usr/bin/env python3
"""Inspect private ledger CSV files with aggregate output only."""

from __future__ import annotations

import argparse
from pathlib import Path

from data_sources.source_inspection import SourceDataInventory, inspect_source_data, inventory_to_markdown


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ledger-dir",
        type=Path,
        default=Path("private/raw_data/ledger"),
        help="Local private ledger directory. This path must stay gitignored.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    inventory = inspect_source_data(ledger_dir=args.ledger_dir, tick_dir=Path("__skip_ticks__"))
    ledger_only = SourceDataInventory(
        ledger_dir=inventory.ledger_dir,
        tick_dir="not inspected",
        ledger_csv_files=inventory.ledger_csv_files,
        tick_files=(),
        skipped_files=inventory.skipped_files,
    )
    print(inventory_to_markdown(ledger_only))


if __name__ == "__main__":
    main()
