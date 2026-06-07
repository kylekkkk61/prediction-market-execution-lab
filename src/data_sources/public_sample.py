"""Utilities for preparing public-safe sample data from private raw inputs.

This module reads local private data and writes small anonymized samples. It is
not intended to preserve every raw field. It keeps only the fields needed for
public demo notebooks, replay backtests, and execution-quality reports.
"""

from __future__ import annotations

import csv
import gzip
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from utils.anonymize import (
    bucket_amount,
    normalize_signed_amount,
    safe_numeric,
    safe_probability,
    stable_hash,
)

DEFAULT_PRIVATE_LEDGER_DIR = Path("private/raw_data/ledger")
DEFAULT_PRIVATE_TICK_DIR = Path("private/raw_data/tick_snapshots")
DEFAULT_PUBLIC_SAMPLE_DIR = Path("data/sample")

LEDGER_SAMPLE_FILES = {
    "raw_candidates.csv": "candidates_sample.csv",
    "execution_attempts.csv": "executions_sample.csv",
    "market_settlements.csv": "settlements_sample.csv",
    "signal_rejections.csv": "rejections_sample.csv",
}

TICK_SAMPLE_COLUMNS = [
    "timestamp",
    "market_id",
    "current_price",
    "open_anchor_price",
    "sigma_short",
    "sigma_long",
    "remaining_seconds",
    "up_bid",
    "up_ask",
    "down_bid",
    "down_ask",
    "ts",
    "market_slug",
    "event",
    "runtime_mode",
    "bn_price",
    "pm_open_price",
    "bn_open_price",
    "yes_bid",
    "yes_ask",
    "yes_mid",
    "yes_spread",
    "down_mid",
    "down_spread",
    "pm_implied_up",
    "pm_implied_down",
    "fair_yes",
    "fair_no",
    "sigma_eff",
    "tau_seconds",
    "z",
    "quote_complete",
]

CANDIDATE_COLUMNS = [
    "recorded_at",
    "candidate_id",
    "market_id",
    "market_slug",
    "side",
    "time_bucket",
    "elapsed_seconds",
    "remaining_seconds",
    "signal_fair",
    "signal_edge",
    "signal_bid",
    "signal_ask",
    "signal_spread",
    "limit_price",
    "edge_after_fill_estimate",
    "fill_probability",
    "fill_prob_passed",
]

EXECUTION_COLUMNS = [
    "recorded_at",
    "candidate_id",
    "market_id",
    "market_slug",
    "side",
    "status",
    "attempt_stage",
    "time_bucket",
    "elapsed_seconds",
    "remaining_seconds",
    "amount_bucket",
    "order_type",
    "exec_price_mode",
    "signal_fair",
    "signal_edge",
    "signal_spread",
    "limit_price",
    "edge_after_fill_estimate",
    "order_sent",
    "order_accepted",
    "filled",
    "fill_amount_bucket",
    "fill_avg_price",
    "fill_ratio",
    "latency_ms",
    "failure_category",
]

SETTLEMENT_COLUMNS = [
    "market_id",
    "market_slug",
    "market_start_utc",
    "market_end_utc",
    "open_price",
    "resolution_price",
    "resolved_side",
    "yes_orders",
    "down_orders",
    "yes_cost_bucket",
    "down_cost_bucket",
    "total_cost_bucket",
    "gross_payout_bucket",
    "net_pnl_normalized",
    "pnl_if_up_normalized",
    "pnl_if_down_normalized",
    "mode_observed",
]

REJECTION_COLUMNS = [
    "recorded_at",
    "market_id",
    "market_slug",
    "side",
    "rejection_stage",
    "rejection_reason_category",
    "time_bucket",
    "remaining_seconds",
    "signal_fair",
    "signal_edge",
    "signal_spread",
    "tau_seconds",
    "z",
]


@dataclass(frozen=True)
class SampleGenerationSummary:
    """Summary for one generated public sample file."""

    output_path: str
    rows_written: int
    columns: tuple[str, ...]


def _open_tick_text(path: Path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", encoding="utf-8")
    return path.open("r", encoding="utf-8")


def _tick_files(tick_dir: Path, max_files: int) -> list[Path]:
    return [
        path
        for path in sorted(tick_dir.iterdir())
        if path.name.lower().endswith(".jsonl") or path.name.lower().endswith(".jsonl.gz")
    ][:max_files]


def collect_tick_market_slugs(tick_dir: Path = DEFAULT_PRIVATE_TICK_DIR, *, max_files: int = 1) -> set[str]:
    """Collect raw market slugs from selected private tick files for alignment.

    Raw slugs are used only in memory to align public settlement samples with
    public tick samples. They are never written to public sample outputs.
    """

    slugs: set[str] = set()
    for path in _tick_files(tick_dir, max_files):
        with _open_tick_text(path) as file_obj:
            for line in file_obj:
                line = line.strip()
                if not line:
                    continue
                try:
                    payload = json.loads(line)
                except json.JSONDecodeError:
                    continue
                slug = payload.get("market_slug") or payload.get("slug")
                if slug:
                    slugs.add(str(slug))
    return slugs


def _write_rows(path: Path, columns: list[str], rows: Iterable[dict[str, Any]]) -> SampleGenerationSummary:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            writer.writerow({column: row.get(column, "") for column in columns})
            count += 1
    return SampleGenerationSummary(str(path), count, tuple(columns))


def _first_present(row: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in row and row[name] not in (None, ""):
            return row[name]
    return None


def _market_id(row: dict[str, Any]) -> str:
    raw = _first_present(row, ("market_slug", "market_id", "condition_id", "question"))
    return stable_hash(raw, prefix="market")


def _candidate_id(row: dict[str, Any]) -> str:
    raw = _first_present(row, ("candidate_id", "recorded_at", "ts", "timestamp"))
    return stable_hash(raw, prefix="candidate")


def _market_slug(row: dict[str, Any]) -> str:
    value = _first_present(row, ("market_slug", "market_id", "condition_id"))
    return stable_hash(value, prefix="slug")


def _category(value: Any) -> str:
    if value is None or value == "":
        return "unknown"
    text = str(value).lower()
    if "spread" in text:
        return "spread_filter"
    if "edge" in text:
        return "edge_filter"
    if "exposure" in text or "cap" in text or "limit" in text:
        return "risk_limit"
    if "time" in text or "bucket" in text:
        return "time_filter"
    if "ml" in text or "model" in text:
        return "model_filter"
    if "fill" in text:
        return "fill_probability_filter"
    return "other"


def sanitize_tick_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Return a public-safe tick row with only replay/reporting fields."""

    timestamp = _first_present(payload, ("ts", "timestamp"))
    current_price = safe_numeric(payload.get("bn_price"), digits=4)
    open_anchor_price = safe_numeric(
        _first_present(payload, ("bn_open_price", "pm_open_price")), digits=4
    )
    up_bid = safe_probability(payload.get("yes_bid"))
    up_ask = safe_probability(payload.get("yes_ask"))

    return {
        "timestamp": timestamp,
        "current_price": current_price,
        "open_anchor_price": open_anchor_price,
        "up_bid": up_bid,
        "up_ask": up_ask,
        "ts": timestamp,
        "market_id": _market_id(payload),
        "market_slug": _market_slug(payload),
        "event": _first_present(payload, ("event", "type")),
        "runtime_mode": payload.get("runtime_mode"),
        "remaining_seconds": safe_numeric(payload.get("remaining_seconds"), digits=3),
        "bn_price": current_price,
        "pm_open_price": safe_numeric(payload.get("pm_open_price"), digits=4),
        "bn_open_price": safe_numeric(payload.get("bn_open_price"), digits=4),
        "yes_bid": up_bid,
        "yes_ask": up_ask,
        "yes_mid": safe_probability(payload.get("yes_mid")),
        "yes_spread": safe_probability(payload.get("yes_spread")),
        "down_bid": safe_probability(payload.get("down_bid")),
        "down_ask": safe_probability(payload.get("down_ask")),
        "down_mid": safe_probability(payload.get("down_mid")),
        "down_spread": safe_probability(payload.get("down_spread")),
        "pm_implied_up": safe_probability(payload.get("pm_implied_up")),
        "pm_implied_down": safe_probability(payload.get("pm_implied_down")),
        "fair_yes": safe_probability(payload.get("fair_yes")),
        "fair_no": safe_probability(payload.get("fair_no")),
        "sigma_short": safe_numeric(payload.get("sigma_short"), digits=8),
        "sigma_long": safe_numeric(payload.get("sigma_long"), digits=8),
        "sigma_eff": safe_numeric(payload.get("sigma_eff"), digits=8),
        "tau_seconds": safe_numeric(payload.get("tau_seconds"), digits=3),
        "z": safe_numeric(payload.get("z"), digits=6),
        "quote_complete": payload.get("quote_complete"),
    }


def _sanitize_candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "recorded_at": _first_present(row, ("recorded_at", "ts", "timestamp")),
        "candidate_id": _candidate_id(row),
        "market_id": _market_id(row),
        "market_slug": _market_slug(row),
        "side": row.get("side"),
        "time_bucket": row.get("time_bucket"),
        "elapsed_seconds": safe_numeric(row.get("elapsed_seconds"), digits=3),
        "remaining_seconds": safe_numeric(row.get("remaining_seconds"), digits=3),
        "signal_fair": safe_probability(_first_present(row, ("signal_fair", "fair", "fair_yes"))),
        "signal_edge": safe_numeric(_first_present(row, ("signal_edge", "edge")), digits=6),
        "signal_bid": safe_probability(_first_present(row, ("signal_bid", "bid"))),
        "signal_ask": safe_probability(_first_present(row, ("signal_ask", "ask"))),
        "signal_spread": safe_probability(_first_present(row, ("signal_spread", "spread"))),
        "limit_price": safe_probability(row.get("limit_price")),
        "edge_after_fill_estimate": safe_numeric(row.get("edge_after_fill_estimate"), digits=6),
        "fill_probability": safe_probability(row.get("fill_probability")),
        "fill_prob_passed": row.get("fill_prob_passed"),
    }


def _sanitize_execution(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "recorded_at": _first_present(row, ("recorded_at", "ts", "timestamp")),
        "candidate_id": _candidate_id(row),
        "market_id": _market_id(row),
        "market_slug": _market_slug(row),
        "side": row.get("side"),
        "status": row.get("status"),
        "attempt_stage": row.get("attempt_stage"),
        "time_bucket": row.get("time_bucket"),
        "elapsed_seconds": safe_numeric(row.get("elapsed_seconds"), digits=3),
        "remaining_seconds": safe_numeric(row.get("remaining_seconds"), digits=3),
        "amount_bucket": bucket_amount(_first_present(row, ("amount_usd", "amount", "cost"))),
        "order_type": row.get("order_type"),
        "exec_price_mode": row.get("exec_price_mode"),
        "signal_fair": safe_probability(_first_present(row, ("signal_fair", "fair", "fair_yes"))),
        "signal_edge": safe_numeric(_first_present(row, ("signal_edge", "edge")), digits=6),
        "signal_spread": safe_probability(_first_present(row, ("signal_spread", "spread"))),
        "limit_price": safe_probability(row.get("limit_price")),
        "edge_after_fill_estimate": safe_numeric(row.get("edge_after_fill_estimate"), digits=6),
        "order_sent": row.get("order_sent"),
        "order_accepted": row.get("order_accepted"),
        "filled": row.get("filled"),
        "fill_amount_bucket": bucket_amount(_first_present(row, ("fill_amount_usd", "fill_amount", "filled_amount"))),
        "fill_avg_price": safe_probability(row.get("fill_avg_price")),
        "fill_ratio": safe_probability(row.get("fill_ratio")),
        "latency_ms": safe_numeric(row.get("latency_ms"), digits=3),
        "failure_category": _category(_first_present(row, ("failed_reason", "failure_reason", "error"))),
    }


def _sanitize_settlement(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "market_id": _market_id(row),
        "market_slug": _market_slug(row),
        "market_start_utc": row.get("market_start_utc"),
        "market_end_utc": row.get("market_end_utc"),
        "open_price": safe_numeric(row.get("open_price"), digits=4),
        "resolution_price": safe_numeric(row.get("resolution_price"), digits=4),
        "resolved_side": row.get("resolved_side"),
        "yes_orders": row.get("yes_orders"),
        "down_orders": row.get("down_orders"),
        "yes_cost_bucket": bucket_amount(row.get("yes_cost")),
        "down_cost_bucket": bucket_amount(row.get("down_cost")),
        "total_cost_bucket": bucket_amount(row.get("total_cost")),
        "gross_payout_bucket": bucket_amount(row.get("gross_payout_estimate")),
        "net_pnl_normalized": normalize_signed_amount(row.get("net_pnl_estimate")),
        "pnl_if_up_normalized": normalize_signed_amount(row.get("pnl_if_up_estimate")),
        "pnl_if_down_normalized": normalize_signed_amount(row.get("pnl_if_down_estimate")),
        "mode_observed": row.get("mode_observed"),
    }


def _sanitize_rejection(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "recorded_at": _first_present(row, ("recorded_at", "ts", "timestamp")),
        "market_id": _market_id(row),
        "market_slug": _market_slug(row),
        "side": row.get("side"),
        "rejection_stage": row.get("rejection_stage"),
        "rejection_reason_category": _category(_first_present(row, ("rejection_reason", "reason", "failed_reason"))),
        "time_bucket": row.get("time_bucket"),
        "remaining_seconds": safe_numeric(row.get("remaining_seconds"), digits=3),
        "signal_fair": safe_probability(_first_present(row, ("signal_fair", "fair", "fair_yes"))),
        "signal_edge": safe_numeric(_first_present(row, ("signal_edge", "edge")), digits=6),
        "signal_spread": safe_probability(_first_present(row, ("signal_spread", "spread"))),
        "tau_seconds": safe_numeric(row.get("tau_seconds"), digits=3),
        "z": safe_numeric(row.get("z"), digits=6),
    }


def generate_tick_sample(
    tick_dir: Path = DEFAULT_PRIVATE_TICK_DIR,
    output_path: Path = DEFAULT_PUBLIC_SAMPLE_DIR / "tick_snapshots_sample.csv",
    *,
    max_files: int = 1,
    max_rows_per_file: int = 250,
) -> SampleGenerationSummary:
    """Generate a small anonymized tick snapshot sample."""

    tick_files = _tick_files(tick_dir, max_files)
    rows: list[dict[str, Any]] = []
    required = (
        "timestamp",
        "current_price",
        "open_anchor_price",
        "remaining_seconds",
        "sigma_short",
        "sigma_long",
        "up_bid",
        "up_ask",
        "down_bid",
        "down_ask",
    )
    # Raw tick files are ordered by event time, so taking the first N rows can
    # over-sample only a few markets. Cap rows per market to make the public
    # sample useful for market-level calibration while preserving replay rows.
    max_rows_per_market = max(1, max_rows_per_file // 300)
    for path in tick_files:
        rows_this_file = 0
        rows_by_market: dict[str, int] = {}
        with _open_tick_text(path) as file_obj:
            for line in file_obj:
                if rows_this_file >= max_rows_per_file:
                    break
                line = line.strip()
                if not line:
                    continue
                row = sanitize_tick_payload(json.loads(line))
                market_id = row.get("market_id")
                if not market_id or not all(row.get(column) not in (None, "") for column in required):
                    continue
                if rows_by_market.get(market_id, 0) >= max_rows_per_market:
                    continue
                rows.append(row)
                rows_this_file += 1
                rows_by_market[market_id] = rows_by_market.get(market_id, 0) + 1
    return _write_rows(output_path, TICK_SAMPLE_COLUMNS, rows)


def generate_ledger_sample(
    ledger_dir: Path = DEFAULT_PRIVATE_LEDGER_DIR,
    output_dir: Path = DEFAULT_PUBLIC_SAMPLE_DIR,
    *,
    max_rows_per_file: int = 250,
    settlement_market_slugs: set[str] | None = None,
) -> tuple[SampleGenerationSummary, ...]:
    """Generate anonymized public ledger samples from selected ledger CSVs.

    If settlement_market_slugs is provided, market_settlements.csv is sampled by
    aligned tick-market membership first. This keeps calibration samples joinable
    without exposing raw market slugs.
    """

    configs = {
        "raw_candidates.csv": ("candidates_sample.csv", CANDIDATE_COLUMNS, _sanitize_candidate),
        "execution_attempts.csv": ("executions_sample.csv", EXECUTION_COLUMNS, _sanitize_execution),
        "market_settlements.csv": ("settlements_sample.csv", SETTLEMENT_COLUMNS, _sanitize_settlement),
        "signal_rejections.csv": ("rejections_sample.csv", REJECTION_COLUMNS, _sanitize_rejection),
    }
    summaries: list[SampleGenerationSummary] = []
    for source_name, (target_name, columns, sanitizer) in configs.items():
        source_path = ledger_dir / source_name
        if not source_path.exists():
            continue
        rows = []
        with source_path.open("r", encoding="utf-8", newline="") as file_obj:
            reader = csv.DictReader(file_obj)
            for row in reader:
                if source_name == "market_settlements.csv" and settlement_market_slugs:
                    if row.get("market_slug") not in settlement_market_slugs:
                        continue
                if len(rows) >= max_rows_per_file:
                    break
                rows.append(sanitizer(row))
        summaries.append(_write_rows(output_dir / target_name, columns, rows))
    return tuple(summaries)


def generate_public_samples(
    ledger_dir: Path = DEFAULT_PRIVATE_LEDGER_DIR,
    tick_dir: Path = DEFAULT_PRIVATE_TICK_DIR,
    output_dir: Path = DEFAULT_PUBLIC_SAMPLE_DIR,
    *,
    max_tick_files: int = 1,
    max_tick_rows_per_file: int = 250,
    max_ledger_rows_per_file: int = 250,
) -> tuple[SampleGenerationSummary, ...]:
    """Generate all public-safe sample CSVs."""

    settlement_market_slugs = collect_tick_market_slugs(tick_dir, max_files=max_tick_files)
    tick_summary = generate_tick_sample(
        tick_dir=tick_dir,
        output_path=output_dir / "tick_snapshots_sample.csv",
        max_files=max_tick_files,
        max_rows_per_file=max_tick_rows_per_file,
    )
    summaries = list(
        generate_ledger_sample(
            ledger_dir=ledger_dir,
            output_dir=output_dir,
            max_rows_per_file=max_ledger_rows_per_file,
            settlement_market_slugs=settlement_market_slugs,
        )
    )
    summaries.append(tick_summary)
    return tuple(summaries)
