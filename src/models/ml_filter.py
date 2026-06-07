"""Public-sample ML-assisted signal filtering demo.

This module intentionally implements a lightweight, deterministic baseline rather
than a production ML model. It demonstrates feature preparation, chronological
splitting, scoring, and diagnostic reporting on anonymized public sample data.
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence


FEATURE_COLUMNS = (
    "signal_edge",
    "signal_spread",
    "signal_fair",
    "limit_price",
    "fill_probability",
    "elapsed_seconds",
)


@dataclass(frozen=True)
class SignalExample:
    """One public-sample candidate or execution row for filter diagnostics."""

    recorded_at: str
    side: str
    time_bucket: str
    features: dict[str, float]
    label: int | None


@dataclass(frozen=True)
class FilterThresholds:
    """Simple threshold parameters learned from earlier sample rows."""

    min_edge: float
    max_spread: float
    min_fill_probability: float


@dataclass(frozen=True)
class FilterDiagnostics:
    """Summary diagnostics for a pass/reject filter on sample rows."""

    row_count: int
    passed_count: int
    pass_rate: float
    labeled_count: int
    positive_rate_all: float | None
    positive_rate_passed: float | None
    positive_rate_rejected: float | None
    thresholds: FilterThresholds


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if math.isnan(number) or math.isinf(number):
        return None
    return number


def _parse_bool_label(value: object) -> int | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "filled", "accepted"}:
        return 1
    if text in {"false", "0", "no", "rejected"}:
        return 0
    return None


def load_signal_examples(path: str | Path, *, label_column: str = "filled") -> list[SignalExample]:
    """Load public-sample rows into numeric feature examples.

    Rows with no numeric edge/spread are skipped because they cannot be scored.
    Missing optional features are imputed to zero inside the feature vector.
    """

    examples: list[SignalExample] = []
    with Path(path).open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            edge = _parse_float(row.get("signal_edge"))
            spread = _parse_float(row.get("signal_spread"))
            if edge is None or spread is None:
                continue
            features: dict[str, float] = {}
            for column in FEATURE_COLUMNS:
                value = _parse_float(row.get(column))
                features[column] = 0.0 if value is None else value
            examples.append(
                SignalExample(
                    recorded_at=str(row.get("recorded_at", "")),
                    side=str(row.get("side", "unknown")),
                    time_bucket=str(row.get("time_bucket", "unknown")),
                    features=features,
                    label=_parse_bool_label(row.get(label_column)),
                )
            )
    return sorted(examples, key=lambda item: item.recorded_at)


def chronological_split(
    examples: Sequence[SignalExample], *, train_fraction: float = 0.7
) -> tuple[list[SignalExample], list[SignalExample]]:
    """Split examples chronologically to avoid random look-ahead leakage."""

    if not 0 < train_fraction < 1:
        raise ValueError("train_fraction must be between 0 and 1")
    if len(examples) < 2:
        return list(examples), []
    split_at = max(1, min(len(examples) - 1, int(len(examples) * train_fraction)))
    return list(examples[:split_at]), list(examples[split_at:])


def fit_baseline_thresholds(examples: Sequence[SignalExample]) -> FilterThresholds:
    """Fit simple thresholds from earlier sample rows.

    This is a transparent baseline filter, not a production predictive model.
    """

    if not examples:
        return FilterThresholds(min_edge=0.0, max_spread=1.0, min_fill_probability=0.0)

    edges = sorted(item.features["signal_edge"] for item in examples)
    spreads = sorted(item.features["signal_spread"] for item in examples)
    fill_probs = sorted(item.features["fill_probability"] for item in examples)

    def quantile(values: Sequence[float], q: float) -> float:
        if not values:
            return 0.0
        index = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
        return float(values[index])

    return FilterThresholds(
        min_edge=quantile(edges, 0.60),
        max_spread=quantile(spreads, 0.75),
        min_fill_probability=quantile(fill_probs, 0.40),
    )


def score_signal(example: SignalExample, thresholds: FilterThresholds) -> float:
    """Return a simple pass score where positive values pass the filter."""

    edge_component = example.features["signal_edge"] - thresholds.min_edge
    spread_component = thresholds.max_spread - example.features["signal_spread"]
    fill_component = example.features["fill_probability"] - thresholds.min_fill_probability
    return edge_component + 0.5 * spread_component + 0.25 * fill_component


def passes_filter(example: SignalExample, thresholds: FilterThresholds) -> bool:
    """Apply the baseline filter to one sample row."""

    return score_signal(example, thresholds) >= 0


def evaluate_filter(
    examples: Sequence[SignalExample], thresholds: FilterThresholds
) -> FilterDiagnostics:
    """Evaluate pass/reject diagnostics on sample rows."""

    if not examples:
        return FilterDiagnostics(0, 0, 0.0, 0, None, None, None, thresholds)

    passed = [item for item in examples if passes_filter(item, thresholds)]
    rejected = [item for item in examples if not passes_filter(item, thresholds)]
    labeled = [item for item in examples if item.label is not None]

    def positive_rate(items: Iterable[SignalExample]) -> float | None:
        labels = [item.label for item in items if item.label is not None]
        if not labels:
            return None
        return mean(float(label) for label in labels)

    return FilterDiagnostics(
        row_count=len(examples),
        passed_count=len(passed),
        pass_rate=len(passed) / len(examples),
        labeled_count=len(labeled),
        positive_rate_all=positive_rate(examples),
        positive_rate_passed=positive_rate(passed),
        positive_rate_rejected=positive_rate(rejected),
        thresholds=thresholds,
    )


def run_walk_forward_demo(
    examples: Sequence[SignalExample], *, train_fraction: float = 0.7
) -> tuple[FilterDiagnostics, FilterDiagnostics]:
    """Fit thresholds on earlier rows and evaluate on later rows."""

    train, test = chronological_split(examples, train_fraction=train_fraction)
    thresholds = fit_baseline_thresholds(train)
    return evaluate_filter(train, thresholds), evaluate_filter(test, thresholds)


def format_rate(value: float | None) -> str:
    """Format nullable rates for Markdown reports."""

    if value is None:
        return "n/a"
    return f"{value:.2%}"


def render_ml_filter_report(
    train: FilterDiagnostics,
    test: FilterDiagnostics,
    *, source_path: str = "data/sample/executions_sample.csv",
) -> str:
    """Render a sample-only ML filter methodology report."""

    thresholds = test.thresholds
    return "\n".join(
        [
            "# ML Filter Methodology Report",
            "",
            "This report demonstrates a public-sample workflow for ML-assisted signal filtering.",
            "It uses anonymized sample data and does not establish production predictive performance or trading profitability.",
            "",
            "## Data source",
            "",
            f"- Source: `{source_path}`",
            "- Target label: public sample `filled` flag when available",
            "- Split: chronological train/test split to avoid random look-ahead leakage",
            "",
            "## Baseline filter",
            "",
            "The demo uses a transparent threshold-based baseline rather than a production model.",
            "Thresholds are fitted on the earlier sample segment and applied to the later segment.",
            "",
            "| Threshold | Value |",
            "|---|---:|",
            f"| Minimum edge | {thresholds.min_edge:.6f} |",
            f"| Maximum spread | {thresholds.max_spread:.6f} |",
            f"| Minimum fill probability | {thresholds.min_fill_probability:.6f} |",
            "",
            "## Diagnostics",
            "",
            "| Segment | Rows | Passed | Pass rate | Labeled rows | Positive rate all | Positive rate passed | Positive rate rejected |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
            _diagnostic_row("Train", train),
            _diagnostic_row("Test", test),
            "",
            "## Interpretation limits",
            "",
            "- These diagnostics are based on anonymized public sample rows, not the full private ledger.",
            "- The baseline is designed to demonstrate validation workflow, not to prove predictive edge.",
            "- Public sample labels may be sparse or simplified after anonymization.",
            "- A production ML filter would require stricter walk-forward validation, richer feature audits, and leakage checks on private data.",
        ]
    ) + "\n"


def _diagnostic_row(name: str, diagnostics: FilterDiagnostics) -> str:
    return (
        f"| {name} | {diagnostics.row_count} | {diagnostics.passed_count} | "
        f"{format_rate(diagnostics.pass_rate)} | {diagnostics.labeled_count} | "
        f"{format_rate(diagnostics.positive_rate_all)} | "
        f"{format_rate(diagnostics.positive_rate_passed)} | "
        f"{format_rate(diagnostics.positive_rate_rejected)} |"
    )
