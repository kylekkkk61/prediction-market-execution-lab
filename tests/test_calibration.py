from pathlib import Path

from models.calibration import (
    ForecastOutcome,
    calibration_buckets,
    load_forecast_outcomes,
    render_calibration_report,
    summarize_calibration,
)


ROOT = Path(__file__).resolve().parents[1]


def test_calibration_buckets_group_probabilities():
    buckets = calibration_buckets([0.12, 0.18, 0.82], [0, 1, 1], bucket_width=0.2)
    assert len(buckets) == 2
    assert buckets[0].bucket == "0.0-0.2"
    assert buckets[0].count == 2
    assert 0 <= buckets[0].realized_rate <= 1


def test_summarize_calibration_computes_scores():
    rows = [
        ForecastOutcome("m1", 0.2, 0.3, 0),
        ForecastOutcome("m2", 0.8, 0.7, 1),
    ]
    summary = summarize_calibration(rows, source="fair")
    assert summary.observations == 2
    assert summary.brier_score is not None
    assert summary.log_loss is not None
    assert summary.calibration_buckets


def test_load_forecast_outcomes_on_public_sample_is_safe_when_keys_do_not_align():
    rows = load_forecast_outcomes(
        ROOT / "data" / "sample" / "tick_snapshots_sample.csv",
        ROOT / "data" / "sample" / "settlements_sample.csv",
    )
    assert isinstance(rows, list)
    assert all(0.0 <= row.fair_probability <= 1.0 for row in rows)
    assert {row.outcome for row in rows}.issubset({0, 1})


def test_render_report_discloses_sample_only_scope():
    rows = [ForecastOutcome("m1", 0.2, 0.3, 0), ForecastOutcome("m2", 0.8, 0.7, 1)]
    fair = summarize_calibration(rows, source="fair")
    market = summarize_calibration(rows, source="market")
    report = render_calibration_report(rows, fair, market)
    assert "Probability Calibration Report" in report
    assert "anonymized public sample data" in report
    assert "not as a full empirical conclusion" in report
