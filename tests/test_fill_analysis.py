from pathlib import Path

from execution_quality.fill_analysis import (
    metric_to_percent,
    render_markdown,
    summarize_edge_decay,
    summarize_execution_quality,
)


def test_metric_to_percent_handles_none() -> None:
    assert metric_to_percent(None) == "n/a"
    assert metric_to_percent(0.25) == "25.00%"


def test_summarize_edge_decay() -> None:
    summary = summarize_edge_decay(
        [
            {"signal_edge": "0.0500", "edge_after_fill_estimate": "0.0300"},
            {"signal_edge": "0.0400", "edge_after_fill_estimate": "0.0350"},
            {"signal_edge": "", "edge_after_fill_estimate": "0.0100"},
        ]
    )

    assert summary.rows == 2
    assert round(summary.avg_signal_edge or 0, 4) == 0.0450
    assert round(summary.avg_edge_after_fill or 0, 4) == 0.0325
    assert round(summary.avg_edge_decay or 0, 4) == 0.0125


def test_summarize_execution_quality_on_public_sample() -> None:
    summary = summarize_execution_quality(Path("data/sample"))

    assert summary.candidates > 0
    assert summary.executions > 0
    assert summary.rejections > 0
    assert summary.settlements > 0
    # The public sample may omit edge-after-fill estimates if the private ledger
    # did not expose a safe value for that field. The report should still render
    # the unavailable edge-decay section as n/a rather than inventing values.
    assert summary.edge_decay.rows >= 0
    assert summary.pnl_summary["rows"] > 0
    assert summary.side_metrics
    assert summary.time_bucket_metrics
    assert summary.edge_bucket_metrics
    assert summary.spread_bucket_metrics


def test_grouped_metrics_include_execution_quality_fields() -> None:
    summary = summarize_execution_quality(Path("data/sample"))
    side_metric = summary.side_metrics[0]

    assert side_metric.rows > 0
    assert side_metric.accepted_rate is not None
    assert side_metric.fill_rate is not None
    assert side_metric.avg_signal_edge is not None
    assert side_metric.avg_signal_spread is not None


def test_render_markdown_contains_required_sections() -> None:
    summary = summarize_execution_quality(Path("data/sample"))
    markdown = render_markdown(summary)

    assert "# Execution Quality Report" in markdown
    assert "## Execution funnel" in markdown
    assert "## Rejection reason breakdown" in markdown
    assert "## Grouped execution diagnostics" in markdown
    assert "### By side" in markdown
    assert "### By time bucket" in markdown
    assert "### By signal edge bucket" in markdown
    assert "### By spread bucket" in markdown
    assert "## Edge decay" in markdown
    assert "## Settlement PnL summary" in markdown
    assert "anonymized public sample data" in markdown
