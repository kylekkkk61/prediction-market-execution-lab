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
from typing import Callable, Iterable


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
class GroupedExecutionMetric:
    """Execution-quality metrics grouped by a categorical bucket."""

    label: str
    rows: int
    accepted_rate: float | None
    fill_rate: float | None
    avg_signal_edge: float | None
    avg_signal_spread: float | None
    avg_latency_ms: float | None


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
    side_metrics: list[GroupedExecutionMetric]
    time_bucket_metrics: list[GroupedExecutionMetric]
    edge_bucket_metrics: list[GroupedExecutionMetric]
    spread_bucket_metrics: list[GroupedExecutionMetric]


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


def _mean_or_none(values: Iterable[float]) -> float | None:
    values_list = list(values)
    return mean(values_list) if values_list else None


def _bucket_edge(row: dict[str, str]) -> str:
    value = _safe_float(row.get("signal_edge"))
    if value is None:
        return "unknown"
    if value < 0.25:
        return "<0.25"
    if value < 0.35:
        return "0.25-0.35"
    if value < 0.50:
        return "0.35-0.50"
    return ">=0.50"


def _bucket_spread(row: dict[str, str]) -> str:
    value = _safe_float(row.get("signal_spread"))
    if value is None:
        return "unknown"
    if value <= 0.01:
        return "<=0.01"
    if value <= 0.02:
        return "0.01-0.02"
    return ">0.02"


def _execution_group_metrics(
    execution_rows: Iterable[dict[str, str]],
    labeler: Callable[[dict[str, str]], str],
    *,
    limit: int | None = None,
) -> list[GroupedExecutionMetric]:
    groups: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in execution_rows:
        label = labeler(row) or "unknown"
        groups[label].append(row)

    sorted_groups = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    if limit is not None:
        sorted_groups = sorted_groups[:limit]

    metrics: list[GroupedExecutionMetric] = []
    for label, rows in sorted_groups:
        total = len(rows)
        accepted = sum(1 for row in rows if _truthy(row.get("order_accepted")))
        filled = sum(1 for row in rows if _truthy(row.get("filled")))
        signal_edges = [
            value for row in rows if (value := _safe_float(row.get("signal_edge"))) is not None
        ]
        signal_spreads = [
            value for row in rows if (value := _safe_float(row.get("signal_spread"))) is not None
        ]
        latencies = [
            value for row in rows if (value := _safe_float(row.get("latency_ms"))) is not None
        ]

        metrics.append(
            GroupedExecutionMetric(
                label=label,
                rows=total,
                accepted_rate=(accepted / total) if total else None,
                fill_rate=(filled / total) if total else None,
                avg_signal_edge=_mean_or_none(signal_edges),
                avg_signal_spread=_mean_or_none(signal_spreads),
                avg_latency_ms=_mean_or_none(latencies),
            )
        )
    return metrics


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
        side_metrics=_execution_group_metrics(executions, lambda row: row.get("side") or "unknown"),
        time_bucket_metrics=_execution_group_metrics(
            executions, lambda row: row.get("time_bucket") or "unknown"
        ),
        edge_bucket_metrics=_execution_group_metrics(executions, _bucket_edge),
        spread_bucket_metrics=_execution_group_metrics(executions, _bucket_spread),
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


def metric_to_ms(value: float | None) -> str:
    """Format an optional millisecond value."""

    if value is None:
        return "n/a"
    return f"{value:.1f}"


def _render_grouped_metrics(title: str, metrics: list[GroupedExecutionMetric]) -> list[str]:
    lines = [
        f"### {title}",
        "",
        "| Group | Rows | Accepted rate | Fill rate | Avg signal edge | Avg spread | Avg latency ms |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    if not metrics:
        lines.append("| n/a | 0 | n/a | n/a | n/a | n/a | n/a |")
        return lines
    lines.extend(
        "| "
        + " | ".join(
            [
                metric.label,
                str(metric.rows),
                metric_to_percent(metric.accepted_rate),
                metric_to_percent(metric.fill_rate),
                metric_to_decimal(metric.avg_signal_edge),
                metric_to_decimal(metric.avg_signal_spread),
                metric_to_ms(metric.avg_latency_ms),
            ]
        )
        + " |"
        for metric in metrics
    )
    return lines


def render_markdown(summary: ExecutionQualitySummary) -> str:
    """Render a Markdown report from execution-quality metrics."""

    edge = summary.edge_decay
    pnl = summary.pnl_summary

    lines = [
        "# Execution Quality Report",
        "",
        "> This report is generated from anonymized public sample data. It is a reproducible demo report, not a claim about complete live performance.",
        "",
        "## Research question",
        "",
        "This report asks whether apparent short-horizon prediction-market edge survives the execution funnel. The central distinction is between a signal that looks attractive at quote time and a signal that remains executable after spread, latency, fill probability, rejection logic, and settlement outcomes are applied.",
        "",
        "## Sample and data policy",
        "",
        "The report uses public sample CSV files only. Candidate, execution, rejection, and settlement records are anonymized, downsampled, and field-filtered. Monetary scale is bucketed or normalized where needed, and private operational fields such as wallet identifiers, raw order IDs, signer details, model paths, and raw responses are excluded.",
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
        "The funnel shows how many candidate signals remain after they pass through attempted execution, acceptance, fill, rejection, and settlement-style sample states. This is the key place where theoretical edge can disappear before it becomes executable edge.",
        "",
        "![Signal funnel](figures/signal_funnel.png)",
        "",
        f"- Accepted rate: **{metric_to_percent(summary.accepted_rate)}**",
        f"- Fill rate: **{metric_to_percent(summary.fill_rate)}**",
        "",
        "### Execution status breakdown",
        "",
        "![Execution status breakdown](figures/execution_status_breakdown.png)",
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
        "Rejection categories identify where candidate signals fail before becoming executable. They should be interpreted as execution-quality diagnostics rather than as live trading rules.",
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
        "## Grouped execution diagnostics",
        "",
        "These grouped metrics are calculated on anonymized execution-attempt samples and are intended to diagnose execution quality by observable sample features.",
        "",
    ])
    lines.extend(_render_grouped_metrics("By side", summary.side_metrics))
    lines.append("")
    lines.extend(_render_grouped_metrics("By time bucket", summary.time_bucket_metrics))
    lines.append("")
    lines.extend(["![Fill rate by edge bucket](figures/fill_rate_by_edge_bucket.png)", ""])
    lines.extend(_render_grouped_metrics("By signal edge bucket", summary.edge_bucket_metrics))
    lines.append("")
    lines.extend(["![Spread distribution](figures/spread_distribution.png)", ""])
    lines.extend(_render_grouped_metrics("By spread bucket", summary.spread_bucket_metrics))

    lines.extend([
        "",
        "## Edge before and after execution",
        "",
        "This section compares signal-time edge with an execution-adjusted estimate when the public sample contains the required fields. The difference is a direct diagnostic of how much apparent edge is eroded by fill assumptions and execution constraints.",
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
        "Settlement PnL is reported in normalized public-sample units. It is useful for directionally understanding whether filtered signals translated into favorable outcomes, but it is not account-level PnL and should not be interpreted as complete strategy performance.",
        "",
        "| Metric | Value |",
        "|---|---:|",
        f"| Rows with normalized PnL | {pnl['rows']} |",
        f"| Average normalized net PnL | {metric_to_decimal(pnl['avg_net_pnl_normalized'])} |",
        f"| Minimum normalized net PnL | {metric_to_decimal(pnl['min_net_pnl_normalized'])} |",
        f"| Maximum normalized net PnL | {metric_to_decimal(pnl['max_net_pnl_normalized'])} |",
        f"| Positive normalized PnL rate | {metric_to_percent(pnl['positive_rate'] if isinstance(pnl['positive_rate'], float) else None)} |",
        "",
        "## Author takeaway",
        "",
        "My conclusion from this sample is that the strategy did not yet convert theoretical edge into reliable realized PnL. The most interesting failure mode is not a single cost such as spread; it is the execution funnel itself.",
        "",
        "## What the public sample suggests",
        "",
        "These metrics are intended to demonstrate the analysis pipeline. The public sample is anonymized, downsampled, and field-filtered, so it should not be interpreted as full strategy performance.",
        "",
        "In this public sample, normalized settlement PnL is weak and slightly negative on average, while the positive normalized PnL rate is low. The PnL distribution is also highly zero-inflated: many markets contribute no positive normalized PnL because the strategy often does not form a matched position. This supports the central project lesson: visible signal edge is not equivalent to executable edge after acceptance, fill probability, timing, spread, latency, and settlement outcomes are incorporated.",
        "",
        "## Why filters were necessary",
        "",
        "The filter stack was introduced after the gap between simulation and live-like execution became too large to ignore. Pure tick replay could show positive performance, but live-like ledger replay exposed a different reality: network latency, WebSocket delay, order-book staleness, Polymarket API variability, failed order submission, and lower-than-assumed market-order success probability could erase much of the simulated edge. The filters are therefore not cosmetic; they are an attempt to align simulated edge with realized executable performance.",
        "",
        "## Edge bucket interpretation",
        "",
        "High signal-edge buckets show better execution survival in the public sample, but I do not read that mechanically as proof of alpha. A high edge can mean either an underexploited opportunity or a fair-probability error that other participants correctly avoided. This is exactly why the project separates signal edge, execution quality, and settlement PnL.",
        "",
        "## Time-bucket interpretation",
        "",
        "The `time_bucket` field is elapsed seconds in a five-minute market, so `270-300` represents the final 30 seconds. The final window produces more opportunities because volume and implied-probability movement tend to rise near resolution. However, longer live-ledger replay suggested that late-window opportunities were not meaningfully more profitable; the late window increases both opportunity density and last-time-window reversal risk.",
        "",
        "## Spread interpretation",
        "",
        "Spread still matters as an execution cost, but in this public sample spread is clustered near one cent and is not the most explanatory source of variation. The larger bottleneck is whether a signal survives the gates and becomes a filled position.",
        "",
        "## What I learned",
        "",
        "The main lesson is that apparent edge is cheap to generate but expensive to execute. In this sample, the problem was not only whether the fair probability model found a price discrepancy; it was whether that discrepancy could survive timing, fill probability, model gates, order submission, and settlement. This is why I treat execution quality as the core research object rather than a footnote after signal generation.",
        "",
        "## What cannot be concluded",
        "",
        "- The report does not prove that a live strategy is profitable or unprofitable across all market regimes.",
        "- The sample does not reconstruct full private account history, real capital constraints, fees, or every venue-level fill dynamic.",
        "- Grouped diagnostics can show associations between sample features and outcomes, but they should not be read as causal proof.",
        "- Live execution would require additional latency, market-depth, and operational-risk validation outside this public repository.",
        "",
    ])
    return "\n".join(lines)
