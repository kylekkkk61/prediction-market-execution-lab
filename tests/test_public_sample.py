from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from data_sources.public_sample import generate_public_samples
from utils.anonymize import bucket_amount, normalize_signed_amount, stable_hash


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = sorted({key for row in rows for key in row.keys()})
    with path.open("w", encoding="utf-8", newline="") as file_obj:
        writer = csv.DictWriter(file_obj, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def test_anonymize_helpers_are_deterministic_and_bucket_amounts() -> None:
    assert stable_hash("market-a", prefix="market") == stable_hash("market-a", prefix="market")
    assert stable_hash("market-a", prefix="market") != stable_hash("market-b", prefix="market")
    assert bucket_amount("0") == "zero"
    assert bucket_amount("7.5") == "lt_10"
    assert bucket_amount("75") == "50_100"
    assert normalize_signed_amount("-25", scale=100) == -0.25


def test_generate_public_samples_filters_sensitive_fields(tmp_path: Path) -> None:
    ledger_dir = tmp_path / "private" / "raw_data" / "ledger"
    tick_dir = tmp_path / "private" / "raw_data" / "tick_snapshots"
    output_dir = tmp_path / "data" / "sample"

    _write_csv(
        ledger_dir / "raw_candidates.csv",
        [
            {
                "recorded_at": "2026-06-01T00:00:00Z",
                "candidate_id": "candidate-secret-1",
                "market_slug": "btc-updown-secret-market",
                "side": "UP",
                "signal_fair": "0.61",
                "signal_edge": "0.04",
                "signal_ask": "0.57",
                "signal_spread": "0.02",
                "token_id": "token-secret",
                "raw_response": "do-not-export",
            }
        ],
    )
    _write_csv(
        ledger_dir / "execution_attempts.csv",
        [
            {
                "recorded_at": "2026-06-01T00:00:01Z",
                "candidate_id": "candidate-secret-1",
                "market_slug": "btc-updown-secret-market",
                "side": "UP",
                "status": "filled",
                "amount_usd": "123.45",
                "fill_amount_usd": "50",
                "response_order_id": "order-secret",
                "raw_response": "do-not-export",
            }
        ],
    )
    _write_csv(
        ledger_dir / "market_settlements.csv",
        [
            {
                "market_slug": "btc-updown-secret-market",
                "market_start_utc": "2026-06-01T00:00:00Z",
                "market_end_utc": "2026-06-01T00:05:00Z",
                "open_price": "100000",
                "resolution_price": "100100",
                "resolved_side": "UP",
                "total_cost": "80",
                "net_pnl_estimate": "12.5",
            }
        ],
    )
    _write_csv(
        ledger_dir / "signal_rejections.csv",
        [
            {
                "recorded_at": "2026-06-01T00:00:02Z",
                "market_slug": "btc-updown-secret-market",
                "side": "DOWN",
                "rejection_reason": "spread too wide",
                "signal_edge": "0.01",
            }
        ],
    )

    tick_dir.mkdir(parents=True, exist_ok=True)
    with gzip.open(tick_dir / "2026-06-01.jsonl.gz", "wt", encoding="utf-8") as file_obj:
        file_obj.write(
            json.dumps(
                {
                    "ts": "2026-06-01T00:00:00Z",
                    "market_slug": "btc-updown-secret-market",
                    "event": "pm_best_bid_ask",
                    "runtime_mode": "live",
                    "bn_price": 100050,
                    "bn_open_price": 100000,
                    "yes_bid": 0.55,
                    "yes_ask": 0.57,
                    "down_bid": 0.43,
                    "down_ask": 0.45,
                    "remaining_seconds": 240,
                    "sigma_short": 0.0012,
                    "sigma_long": 0.0010,
                    "fair_yes": 0.61,
                    "token_id": "token-secret",
                    "config": {"do": "not-export"},
                }
            )
            + "\n"
        )

    summaries = generate_public_samples(
        ledger_dir=ledger_dir,
        tick_dir=tick_dir,
        output_dir=output_dir,
        max_tick_files=1,
        max_tick_rows_per_file=10,
        max_ledger_rows_per_file=10,
    )

    assert {Path(summary.output_path).name for summary in summaries} == {
        "candidates_sample.csv",
        "executions_sample.csv",
        "settlements_sample.csv",
        "rejections_sample.csv",
        "tick_snapshots_sample.csv",
    }

    candidates = _read_csv(output_dir / "candidates_sample.csv")
    assert candidates[0]["candidate_id"].startswith("candidate_")
    assert candidates[0]["market_slug"].startswith("slug_")
    assert "token_id" not in candidates[0]
    assert "raw_response" not in candidates[0]
    assert "btc-updown-secret-market" not in str(candidates[0])

    executions = _read_csv(output_dir / "executions_sample.csv")
    assert executions[0]["amount_bucket"] == "100_250"
    assert executions[0]["fill_amount_bucket"] == "50_100"
    assert "response_order_id" not in executions[0]

    ticks = _read_csv(output_dir / "tick_snapshots_sample.csv")
    assert ticks[0]["market_id"].startswith("market_")
    assert ticks[0]["market_slug"].startswith("slug_")
    assert "token_id" not in ticks[0]
    assert "config" not in ticks[0]

    settlements = _read_csv(output_dir / "settlements_sample.csv")
    assert settlements[0]["market_id"] == ticks[0]["market_id"]
    assert settlements[0]["market_slug"] == ticks[0]["market_slug"]
