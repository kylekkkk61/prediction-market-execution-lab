#!/usr/bin/env python3
"""
Compress completed tick snapshot JSONL files.

By default this skips the current UTC date because bot.py writes snapshot files
by UTC date. Compression is verified before the source .jsonl is removed.
"""

from __future__ import annotations

import argparse
import gzip
import shutil
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path


SKIP_SUFFIXES = (".tmp", ".part", ".swp")


@dataclass
class CompressionStats:
    scanned: int = 0
    compressed: int = 0
    skipped: int = 0
    source_bytes: int = 0
    compressed_bytes: int = 0


def format_bytes(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f}{unit}" if unit != "B" else f"{value}B"
        size /= 1024
    return f"{size:.1f}GB"


def snapshot_date_from_path(path: Path) -> date | None:
    if path.suffix != ".jsonl":
        return None
    try:
        return date.fromisoformat(path.stem)
    except ValueError:
        return None


def iter_raw_snapshots(snapshot_dir: Path, snapshot_glob: str) -> list[Path]:
    if not snapshot_dir.exists():
        return []
    paths: list[Path] = []
    for path in sorted(snapshot_dir.glob(snapshot_glob)):
        if not path.is_file() or path.name.endswith(SKIP_SUFFIXES):
            continue
        if path.suffix != ".jsonl":
            continue
        paths.append(path)
    return paths


def verify_gzip(path: Path) -> None:
    with gzip.open(path, "rb") as handle:
        while handle.read(1024 * 1024):
            pass


def should_skip(path: Path, args: argparse.Namespace, today_utc: date) -> str | None:
    snapshot_date = snapshot_date_from_path(path)
    if snapshot_date == today_utc and not args.include_today:
        return "current UTC date"
    age_seconds = time.time() - path.stat().st_mtime
    if args.min_age_seconds > 0 and age_seconds < args.min_age_seconds:
        return f"younger than {args.min_age_seconds:.0f}s"
    output_path = path.with_suffix(path.suffix + ".gz")
    if output_path.exists() and not args.force:
        return "compressed file already exists"
    return None


def compress_one(path: Path, args: argparse.Namespace) -> tuple[int, int]:
    output_path = path.with_suffix(path.suffix + ".gz")
    tmp_path = output_path.with_name(output_path.name + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()

    with path.open("rb") as source, tmp_path.open("wb") as raw_target:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_target,
            compresslevel=args.level,
            mtime=0,
        ) as target:
            shutil.copyfileobj(source, target, length=1024 * 1024)

    if not args.no_verify:
        verify_gzip(tmp_path)

    tmp_path.replace(output_path)
    source_size = path.stat().st_size
    compressed_size = output_path.stat().st_size
    if not args.keep_source:
        path.unlink()
    return source_size, compressed_size


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Compress completed tick snapshot JSONL files.")
    parser.add_argument("--snapshot-dir", type=Path, default=Path("tick_snapshots"))
    parser.add_argument("--snapshot-glob", default="*.jsonl")
    parser.add_argument("--level", type=int, default=6, choices=range(1, 10), metavar="1-9")
    parser.add_argument("--min-age-seconds", type=float, default=300.0)
    parser.add_argument("--include-today", action="store_true", help="Also process the current UTC date.")
    parser.add_argument("--keep-source", action="store_true", help="Keep the source .jsonl after compression.")
    parser.add_argument("--force", action="store_true", help="Overwrite an existing .jsonl.gz.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without writing files.")
    parser.add_argument("--no-verify", action="store_true", help="Skip gzip read-back verification.")
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    stats = CompressionStats()
    today_utc = datetime.now(timezone.utc).date()

    paths = iter_raw_snapshots(args.snapshot_dir, args.snapshot_glob)
    if not paths:
        print(f"No raw .jsonl snapshots found in {args.snapshot_dir} matching {args.snapshot_glob}.")
        return 0

    for path in paths:
        stats.scanned += 1
        reason = should_skip(path, args, today_utc)
        if reason:
            stats.skipped += 1
            print(f"SKIP {path}: {reason}")
            continue
        if args.dry_run:
            stats.skipped += 1
            print(f"DRY-RUN compress {path} -> {path.with_suffix(path.suffix + '.gz')}")
            continue
        source_size, compressed_size = compress_one(path, args)
        stats.compressed += 1
        stats.source_bytes += source_size
        stats.compressed_bytes += compressed_size
        ratio = compressed_size / source_size if source_size else 0.0
        print(
            f"COMPRESSED {path}: {format_bytes(source_size)} -> "
            f"{format_bytes(compressed_size)} ({ratio:.3f})"
        )

    print(
        "Summary: "
        f"scanned={stats.scanned}, compressed={stats.compressed}, skipped={stats.skipped}, "
        f"source={format_bytes(stats.source_bytes)}, gzip={format_bytes(stats.compressed_bytes)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
