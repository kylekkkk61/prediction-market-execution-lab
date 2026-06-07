"""Private raw data inspection utilities.

These helpers intentionally produce aggregate schema summaries only. They do not
emit raw ledger rows, raw tick payloads, order IDs, token IDs, wallet addresses,
or API responses.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

SENSITIVE_NAME_PARTS = (
    "address",
    "allowance",
    "api",
    "claim",
    "config",
    "feature_values",
    "key",
    "model_path",
    "order_id",
    "private",
    "raw_response",
    "relayer",
    "response_order_id",
    "secret",
    "signature",
    "signer",
    "token_id",
    "wallet",
)

DEFAULT_LEDGER_DIR = Path("private/raw_data/ledger")
DEFAULT_TICK_DIR = Path("private/raw_data/tick_snapshots")


@dataclass(frozen=True)
class CsvFileSummary:
    """Aggregate summary for one private ledger CSV file."""

    path: str
    rows: int
    columns: tuple[str, ...]
    sensitive_columns: tuple[str, ...]


@dataclass(frozen=True)
class TickFileSummary:
    """Aggregate summary for one private tick JSONL file."""

    path: str
    rows: int
    columns: tuple[str, ...]
    sensitive_columns: tuple[str, ...]
    event_counts: dict[str, int] = field(default_factory=dict)
    runtime_mode_counts: dict[str, int] = field(default_factory=dict)
    market_count: int = 0
    min_ts: str | None = None
    max_ts: str | None = None


@dataclass(frozen=True)
class PrivateDataInventory:
    """Aggregate inventory of local private raw inputs."""

    ledger_dir: str
    tick_dir: str
    ledger_csv_files: tuple[CsvFileSummary, ...]
    tick_files: tuple[TickFileSummary, ...]
    skipped_files: tuple[str, ...] = ()


def detect_sensitive_columns(columns: Iterable[str]) -> tuple[str, ...]:
    """Return column names that look unsafe for public sample outputs."""

    flagged = []
    for column in columns:
        normalized = column.lower()
        if any(part in normalized for part in SENSITIVE_NAME_PARTS):
            flagged.append(column)
    return tuple(sorted(set(flagged)))


def summarize_csv_file(path: Path) -> CsvFileSummary:
    """Inspect one CSV file without printing or storing raw rows."""

    rows = 0
    columns: tuple[str, ...] = ()
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        reader = csv.DictReader(file_obj)
        columns = tuple(reader.fieldnames or ())
        for _ in reader:
            rows += 1

    return CsvFileSummary(
        path=str(path),
        rows=rows,
        columns=columns,
        sensitive_columns=detect_sensitive_columns(columns),
    )


def _open_tick_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _string_or_none(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def summarize_tick_file(path: Path, *, max_rows: int | None = None) -> TickFileSummary:
    """Inspect one JSONL tick file using aggregate counts only.

    Args:
        path: JSONL or JSONL.GZ file to inspect.
        max_rows: Optional cap for quick schema checks. ``None`` scans the full file.
    """

    rows = 0
    columns: set[str] = set()
    event_counts: Counter[str] = Counter()
    runtime_mode_counts: Counter[str] = Counter()
    markets: set[str] = set()
    min_ts: str | None = None
    max_ts: str | None = None

    with _open_tick_text(path) as file_obj:
        for line in file_obj:
            if max_rows is not None and rows >= max_rows:
                break
            line = line.strip()
            if not line:
                continue
            payload = json.loads(line)
            rows += 1
            columns.update(str(key) for key in payload.keys())

            event = _string_or_none(payload.get("event") or payload.get("type"))
            if event:
                event_counts[event] += 1

            runtime_mode = _string_or_none(payload.get("runtime_mode"))
            if runtime_mode:
                runtime_mode_counts[runtime_mode] += 1

            market = _string_or_none(
                payload.get("market_slug") or payload.get("market_id") or payload.get("condition_id")
            )
            if market:
                markets.add(market)

            ts = _string_or_none(payload.get("ts") or payload.get("timestamp"))
            if ts:
                min_ts = ts if min_ts is None else min(min_ts, ts)
                max_ts = ts if max_ts is None else max(max_ts, ts)

    sorted_columns = tuple(sorted(columns))
    return TickFileSummary(
        path=str(path),
        rows=rows,
        columns=sorted_columns,
        sensitive_columns=detect_sensitive_columns(sorted_columns),
        event_counts=dict(sorted(event_counts.items())),
        runtime_mode_counts=dict(sorted(runtime_mode_counts.items())),
        market_count=len(markets),
        min_ts=min_ts,
        max_ts=max_ts,
    )


def inspect_private_data(
    ledger_dir: Path = DEFAULT_LEDGER_DIR,
    tick_dir: Path = DEFAULT_TICK_DIR,
    *,
    tick_max_rows: int | None = None,
) -> PrivateDataInventory:
    """Inspect local private raw inputs and return aggregate summaries."""

    ledger_csv_files = []
    tick_files = []
    skipped_files = []

    if ledger_dir.exists():
        for path in sorted(ledger_dir.iterdir()):
            if path.suffix.lower() == ".csv":
                ledger_csv_files.append(summarize_csv_file(path))
            elif path.is_file():
                skipped_files.append(str(path))

    if tick_dir.exists():
        for path in sorted(tick_dir.iterdir()):
            name = path.name.lower()
            if name.endswith(".jsonl") or name.endswith(".jsonl.gz"):
                tick_files.append(summarize_tick_file(path, max_rows=tick_max_rows))
            elif path.is_file():
                skipped_files.append(str(path))

    return PrivateDataInventory(
        ledger_dir=str(ledger_dir),
        tick_dir=str(tick_dir),
        ledger_csv_files=tuple(ledger_csv_files),
        tick_files=tuple(tick_files),
        skipped_files=tuple(skipped_files),
    )


def inventory_to_markdown(inventory: PrivateDataInventory) -> str:
    """Render an aggregate inventory summary without raw rows."""

    lines = [
        "# Private Data Inventory Summary",
        "",
        "This summary is generated from local private files and contains aggregate schema",
        "information only. It should not include raw rows, order IDs, token IDs, wallet",
        "addresses, or raw API responses.",
        "",
        f"Ledger directory: `{inventory.ledger_dir}`",
        f"Tick directory: `{inventory.tick_dir}`",
        "",
        "## Ledger CSV files",
        "",
    ]

    if not inventory.ledger_csv_files:
        lines.append("No ledger CSV files found.")
    else:
        lines.extend(["| File | Rows | Columns | Sensitive-column warnings |", "|---|---:|---:|---|"])
        for summary in inventory.ledger_csv_files:
            sensitive = ", ".join(summary.sensitive_columns) or "None"
            lines.append(
                f"| `{Path(summary.path).name}` | {summary.rows} | {len(summary.columns)} | {sensitive} |"
            )

    lines.extend(["", "## Tick snapshot files", ""])
    if not inventory.tick_files:
        lines.append("No tick snapshot files found.")
    else:
        lines.extend(
            [
                "| File | Rows scanned | Markets | Time range | Events | Runtime modes | Sensitive-column warnings |",
                "|---|---:|---:|---|---|---|---|",
            ]
        )
        for summary in inventory.tick_files:
            events = ", ".join(f"{k}:{v}" for k, v in summary.event_counts.items()) or "None"
            modes = ", ".join(f"{k}:{v}" for k, v in summary.runtime_mode_counts.items()) or "None"
            sensitive = ", ".join(summary.sensitive_columns) or "None"
            time_range = "n/a"
            if summary.min_ts or summary.max_ts:
                time_range = f"{summary.min_ts or 'n/a'} to {summary.max_ts or 'n/a'}"
            lines.append(
                f"| `{Path(summary.path).name}` | {summary.rows} | {summary.market_count} | "
                f"{time_range} | {events} | {modes} | {sensitive} |"
            )

    if inventory.skipped_files:
        lines.extend(["", "## Skipped files", ""])
        for path in inventory.skipped_files:
            lines.append(f"- `{path}`")

    return "\n".join(lines) + "\n"
