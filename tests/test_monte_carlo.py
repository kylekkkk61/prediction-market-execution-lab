from pathlib import Path

import pytest

from risk.monte_carlo import (
    bootstrap_paths,
    load_normalized_pnl,
    longest_losing_streak,
    max_drawdown,
    percentile,
    render_risk_report,
    summarize_monte_carlo,
    summarize_path,
)


def test_max_drawdown_uses_peak_to_trough_loss() -> None:
    assert max_drawdown([1.0, 3.0, 2.0, -1.0, 4.0]) == 4.0


def test_longest_losing_streak_counts_consecutive_negative_values() -> None:
    assert longest_losing_streak([1.0, -0.1, -0.2, 0.0, -0.3]) == 2


def test_summarize_path_returns_final_drawdown_and_streak() -> None:
    stats = summarize_path([1.0, -0.5, -0.5, 2.0])
    assert stats.final_pnl == pytest.approx(2.0)
    assert stats.max_drawdown == pytest.approx(1.0)
    assert stats.longest_losing_streak == 2


def test_percentile_interpolates() -> None:
    assert percentile([0.0, 10.0], 50) == pytest.approx(5.0)
    assert percentile([1.0, 2.0, 3.0], 100) == pytest.approx(3.0)


def test_bootstrap_paths_are_seed_deterministic() -> None:
    pnl = [1.0, -1.0, 0.5]
    first = bootstrap_paths(pnl, simulation_count=5, horizon=4, seed=7)
    second = bootstrap_paths(pnl, simulation_count=5, horizon=4, seed=7)
    assert first == second


def test_summarize_monte_carlo_returns_sample_only_diagnostics() -> None:
    summary = summarize_monte_carlo([1.0, -0.5, 0.25], simulation_count=20, horizon=5, seed=1)
    assert summary.sample_count == 3
    assert summary.simulation_count == 20
    assert summary.horizon == 5
    assert summary.p95_max_drawdown >= summary.mean_max_drawdown >= 0


def test_load_normalized_pnl_skips_blank_and_invalid_values(tmp_path: Path) -> None:
    path = tmp_path / "settlements.csv"
    path.write_text(
        "market_id,net_pnl_normalized\n"
        "m1,1.5\n"
        "m2,\n"
        "m3,not_a_number\n"
        "m4,-0.25\n",
        encoding="utf-8",
    )
    assert load_normalized_pnl(path) == [1.5, -0.25]


def test_render_risk_report_labels_normalized_sample_units() -> None:
    summary = summarize_monte_carlo([1.0, -0.5, 0.25], simulation_count=10, seed=2)
    report = render_risk_report(summary)
    assert "anonymized public sample data" in report
    assert "not real currency PnL" in report
    assert "Mean max drawdown" in report


def test_public_settlements_sample_can_drive_monte_carlo_report() -> None:
    pnl = load_normalized_pnl("data/sample/settlements_sample.csv")
    assert len(pnl) > 0
    summary = summarize_monte_carlo(pnl, simulation_count=50, horizon=25, seed=42)
    report = render_risk_report(summary)
    assert "# Risk Simulation Report" in report
    assert summary.sample_count == len(pnl)
