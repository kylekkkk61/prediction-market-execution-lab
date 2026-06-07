import csv
import gzip
import json
from pathlib import Path

from data_sources.private_inspection import (
    detect_sensitive_columns,
    inspect_private_data,
    inventory_to_markdown,
    summarize_csv_file,
    summarize_tick_file,
)


def test_detect_sensitive_columns_flags_private_identifiers() -> None:
    columns = ["market_slug", "response_order_id", "token_id", "edge", "raw_response"]

    flagged = detect_sensitive_columns(columns)

    assert "response_order_id" in flagged
    assert "token_id" in flagged
    assert "raw_response" in flagged
    assert "market_slug" not in flagged


def test_summarize_csv_file_counts_rows_and_columns(tmp_path: Path) -> None:
    csv_path = tmp_path / "execution_attempts.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=["market_slug", "response_order_id", "edge"])
        writer.writeheader()
        writer.writerow({"market_slug": "demo", "response_order_id": "secret-order", "edge": "0.04"})
        writer.writerow({"market_slug": "demo", "response_order_id": "secret-order-2", "edge": "0.05"})

    summary = summarize_csv_file(csv_path)

    assert summary.rows == 2
    assert summary.columns == ("market_slug", "response_order_id", "edge")
    assert summary.sensitive_columns == ("response_order_id",)


def test_summarize_tick_file_counts_aggregate_fields(tmp_path: Path) -> None:
    tick_path = tmp_path / "2026-06-01.jsonl.gz"
    rows = [
        {
            "ts": "2026-06-01T00:00:00Z",
            "event": "pm_price_change",
            "runtime_mode": "live",
            "market_slug": "market-a",
            "yes_bid": 0.51,
        },
        {
            "ts": "2026-06-01T00:00:01Z",
            "event": "pm_best_bid_ask",
            "runtime_mode": "dry_run",
            "market_slug": "market-b",
            "token_id": "private-token",
        },
    ]
    with gzip.open(tick_path, "wt", encoding="utf-8") as file_obj:
        for row in rows:
            file_obj.write(json.dumps(row) + "\n")

    summary = summarize_tick_file(tick_path)

    assert summary.rows == 2
    assert summary.market_count == 2
    assert summary.event_counts == {"pm_best_bid_ask": 1, "pm_price_change": 1}
    assert summary.runtime_mode_counts == {"dry_run": 1, "live": 1}
    assert summary.min_ts == "2026-06-01T00:00:00Z"
    assert summary.max_ts == "2026-06-01T00:00:01Z"
    assert "token_id" in summary.sensitive_columns


def test_inspect_private_data_and_markdown_summary(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "ledger"
    tick_dir = tmp_path / "tick_snapshots"
    ledger_dir.mkdir()
    tick_dir.mkdir()

    csv_path = ledger_dir / "orders.csv"
    csv_path.write_text("market_slug,amount_usd\ndemo,10\n", encoding="utf-8")

    tick_path = tick_dir / "2026-06-01.jsonl"
    tick_path.write_text(
        json.dumps(
            {
                "ts": "2026-06-01T00:00:00Z",
                "event": "interval_heartbeat",
                "runtime_mode": "live",
                "market_slug": "demo",
            }
        )
        + "\n",
        encoding="utf-8",
    )

    inventory = inspect_private_data(ledger_dir=ledger_dir, tick_dir=tick_dir)
    rendered = inventory_to_markdown(inventory)

    assert len(inventory.ledger_csv_files) == 1
    assert len(inventory.tick_files) == 1
    assert "orders.csv" in rendered
    assert "2026-06-01.jsonl" in rendered
    assert "raw rows" in rendered
