#!/usr/bin/env python3
"""Generate the public-sample probability calibration report."""

from __future__ import annotations

from pathlib import Path

from models.calibration import (
    load_forecast_outcomes,
    render_calibration_report,
    summarize_calibration,
)


ROOT = Path(__file__).resolve().parents[1]
TICK_SAMPLE = ROOT / "data" / "sample" / "tick_snapshots_sample.csv"
SETTLEMENTS_SAMPLE = ROOT / "data" / "sample" / "settlements_sample.csv"
OUTPUT = ROOT / "reports" / "probability_calibration_report.md"


def main() -> None:
    forecasts = load_forecast_outcomes(TICK_SAMPLE, SETTLEMENTS_SAMPLE)
    fair_summary = summarize_calibration(forecasts, source="fair")
    market_summary = summarize_calibration(forecasts, source="market")
    OUTPUT.write_text(render_calibration_report(forecasts, fair_summary, market_summary), encoding="utf-8")
    print(f"Loaded joined market observations: {len(forecasts)}")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
