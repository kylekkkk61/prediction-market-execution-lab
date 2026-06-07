"""Execution-quality analysis utilities for public sample data.

These helpers operate on anonymized/sample CSV exports. They deliberately avoid
wallets, order IDs, raw exchange responses, or live execution concerns.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable


@dataclass(frozen=True)
class CountMetric:
    """Simple count plus percentage of a known total."""

    label: str
    count: int
    pct_of_total: float


@dataclass(frozen=True)
class EdgeDecayMetric:
    """Summary of theoretical edge versus execution-adjusted edge."""

    rows: int
    avg_signal_edge: float | None
    avg_edge_after_fill: float | None
    avg_edge_decay: float | None


@dataclass(frozen=True)
class ExecutionQualitySummary:
    """Aggregated execution-quality metrics for sample data."""

    candidates: int
    executions: int
    rejections: int
    settlements: int
    execution_status: list[CountMetric]
    rejection_reasons: list[CountMetric]
    fill_rate: float | None
    accepted_rate: float | None
    edge_decay: EdgeDecayMetric
    pnl_summary: dict[str, float | int | None]
    time_bucket_counts: list[CountMetric]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    """Read CSV rows as dictionaries."""

    if not path.exists():
        return []
    with path.open(newline="") as file_obj:
        return list(csv.DictReader(file_obj))


def _safe_float(value: object) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _truthy(value: object) -> bool:
    if value is None:
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y", "filled", "accepted"}


def _count_metrics(counter: Counter[str], total: int, limit: int | None = None) -> list[CountMetric]:
    items = counter.most_common(limit)
    if total <= 0:
        return [CountMetric(label=label, count=count, pct_of_total=0.0) for label, count in items]
    return [
        CountMetric(label=label, count=count, pct_of_total=count / total)
        for label, count in items
    ]


def summarize_edge_decay(execution_rows: Iterable[dict[str, str]]) -> EdgeDecayMetric:
    """Compare signal edge with execution-adjusted edge estimate."""

    signal_edges: list[float] = []
    after_fill_edges: list[float] = []
    decays: list[float] = []

    for row in execution_rows:
        signal_edge = _safe_float(row.get("signal_edge"))
        after_fill = _safe_float(row.get("edge_after_fill_estimate"))
        if signal_edge is None or after_fill is None:
            continue
        signal_edges.append(signal_edge)
        after_fill_edges.append(after_fill)
        decays.append(signal_edge - after_fill)

    rows = len(signal_edges)
    return EdgeDecayMetric(
        rows=rows,
        avg_signal_edge=mean(signal_edges) if signal_edges else None,
        avg_edge_after_fill=mean(after_fill_edges) if after_fill_edges else None,
        avg_edge_decay=mean(decays) if decays else None,
    )


def summarize_pnl(settlement_rows: Iterable[dict[str, str]]) -> dict[str, float | int | None]:
    """Summarize normalized PnL columns from settlement samples."""

    values = [
        value
        for row in settlement_rows
        if (value := _safe_float(row.get("net_pnl_normalized"))) is not None
    ]
    if not values:
        return {
            "rows": 0,
            "avg_net_pnl_normalized": None,
            "min_net_pnl_normalized": None,
            "max_net_pnl_normalized": None,
            "positive_rate": None,
        }
    return {
        "rows": len(values),
        "avg_net_pnl_normalized": mean(values),
        "min_net_pnl_normalized": min(values),
        "max_net_pnl_normalized": max(values),
        "positive_rate": sum(1 for value in values if value > 0) / len(values),
    }


def summarize_execution_quality(sample_dir: Path) -> ExecutionQualitySummary:
    """Build an execution-quality summary from anonymized public sample CSVs."""

    candidates = read_csv_rows(sample_dir / "candidates_sample.csv")
    executions = read_csv_rows(sample_dir / "executions_sample.csv")
    rejections = read_csv_rows(sample_dir / "rejections_sample.csv")
    settlements = read_csv_rows(sample_dir / "settlements_sample.csv")

    status_counter: Counter[str] = Counter(
        row.get("status") or row.get("attempt_stage") or "unknown" for row in executions
    )
    rejection_counter: Counter[str] = Counter(
        row.get("rejection_reason_category") or "unknown" for row in rejections
    )
    time_bucket_counter: Counter[str] = Counter(
        row.get("time_bucket") or "unknown" for row in candidates
    )

    filled = sum(1 for row in executions if _truthy(row.get("filled")))
    accepted = sum(1 for row in executions if _truthy(row.get("order_accepted")))
    execution_total = len(executions)

    return ExecutionQualitySummary(
        candidates=len(candidates),
        executions=execution_total,
        rejections=len(rejections),
        settlements=len(settlements),
        execution_status=_count_metrics(status_counter, execution_total),
        rejection_reasons=_count_metrics(rejection_counter, len(rejections), limit=10),
        fill_rate=(filled / execution_total) if execution_total else None,
        accepted_rate=(accepted / execution_total) if execution_total else None,
        edge_decay=summarize_edge_decay(executions),
        pnl_summary=summarize_pnl(settlements),
        time_bucket_counts=_count_metrics(time_bucket_counter, len(candidates)),
    )


def metric_to_percent(value: float | None) -> str:
    """Format an optional ratio as a percentage string."""

    if value is None:
        return "n/a"
    return f"{value:.2%}"


def metric_to_decimal(value: float | int | None, digits: int = 4) -> str:
    """Format an optional numeric value."""

    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def render_markdown(summary: ExecutionQualitySummary) -> str:
    """Render a Markdown report from execution-quality metrics."""

    edge = summary.edge_decay
    pnl = summary.pnl_summary

    lines = [
        "# Execution Quality Report",
        "",
        "> This report is generated from anonymized public sample data. It is a reproducible demo report, not a claim about complete live performance.",
        "",
        "## Sample coverage",
        "",
        "| Dataset | Rows |",
        "|---|---:|",
        f"| Candidate signals | {summary.candidates} |",
        f"| Execution attempts | {summary.executions} |",
        f"| Signal rejections | {summary.rejections} |",
        f"| Market settlements | {summary.settlements} |",
        "",
        "## Execution funnel",
        "",
        f"- Accepted rate: **{metric_to_percent(summary.accepted_rate)}**",
        f"- Fill rate: **{metric_to_percent(summary.fill_rate)}**",
        "",
        "### Execution status breakdown",
        "",
        "| Status | Count | Share |",
        "|---|---:|---:|",
    ]
    lines.extend(
        f"| {metric.label} | {metric.count} | {metric_to_percent(metric.pct_of_total)} |"
        for metric in summary.execution_status
    )

    lines.extend([
        "",
        "## Rejection reason breakdown",
        "",
        "| Reason | Count | Share |",
        "|---|---:|---:|",
    ])
    lines.extend(
        f"| {metric.label} | {metric.count} | {metric_to_percent(metric.pct_of_total)} |"
        for metric in summary.rejection_reasons
    )

    lines.extend([
        "",
        "## Edge decay",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Rows with edge fields | {edge.rows} |",
        f"| Average signal edge | {metric_to_decimal(edge.avg_signal_edge)} |",
        f"| Average edge after fill estimate | {metric_to_decimal(edge.avg_edge_after_fill)} |",
        f"| Average edge decay | {metric_to_decimal(edge.avg_edge_decay)} |",
        "",
        "## Candidate timing distribution",
        "",
        "| Time bucket | Count | Share |",
        "|---|---:|---:|",
    ])
    lines.extend(
        f"| {metric.label} | {metric.count} | {metric_to_percent(metric.pct_of_total)} |"
        for metric in summary.time_bucket_counts
    )

    lines.extend([
        "",
        "## Settlement PnL summary",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Rows with normalized PnL | {pnl['rows']} |",
        f"| Average normalized net PnL | {metric_to_decimal(pnl['avg_net_pnl_normalized'])} |",
        f"| Minimum normalized net PnL | {metric_to_decimal(pnl['min_net_pnl_normalized'])} |",
        f"| Maximum normalized net PnL | {metric_to_decimal(pnl['max_net_pnl_normalized'])} |",
        f"| Positive normalized PnL rate | {metric_to_percent(pnl['positive_rate'] if isinstance(pnl['positive_rate'], float) else None)} |",
        "",
        "## Interpretation note",
        "",
        "These metrics are intended to demonstrate the analysis pipeline. The public sample is anonymized, downsampled, and field-filtered, so it should not be interpreted as full strategy performance.",
        "",
    ])
    return "\n".join(lines)
