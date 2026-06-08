"""Public-sample ML-assisted signal filtering workflow demo.

This module intentionally implements a lightweight, deterministic learned-threshold
baseline rather than a production ML model. It demonstrates feature preparation,
chronological splitting, scoring, and diagnostic reporting on anonymized public
sample data.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
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
class PublicModelDecisionDiagnostics:
    """Public-safe diagnostics for exported ML and fill-probability decisions."""

    row_count: int
    ml_enabled_count: int
    ml_scored_count: int
    ml_passed_count: int
    ml_pass_rate: float | None
    avg_ml_predicted_ev: float | None
    avg_ml_min_ev: float | None
    ml_reason_counts: tuple[tuple[str, int], ...]
    fill_probability_count: int
    fill_prob_passed_count: int
    fill_prob_pass_rate: float | None
    avg_fill_probability: float | None
    avg_fill_prob_min_probability: float | None
    fill_prob_reason_counts: tuple[tuple[str, int], ...]


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


def _parse_bool(value: object) -> bool | None:
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"true", "1", "yes", "y", "passed", "accepted", "filled"}:
        return True
    if text in {"false", "0", "no", "n", "rejected"}:
        return False
    return None


def _mean_optional(values: Sequence[float]) -> float | None:
    return mean(values) if values else None


def load_public_model_decision_diagnostics(
    path: str | Path,
) -> PublicModelDecisionDiagnostics:
    """Load public-safe ML decision diagnostics from an exported sample CSV."""

    rows: list[dict[str, str]] = []
    csv_path = Path(path)
    if csv_path.exists():
        with csv_path.open(newline="") as handle:
            rows = list(csv.DictReader(handle))

    ml_enabled = 0
    ml_scored_values: list[float] = []
    ml_min_values: list[float] = []
    ml_passed = 0
    ml_labeled = 0
    ml_reasons: Counter[str] = Counter()

    fill_prob_values: list[float] = []
    fill_prob_min_values: list[float] = []
    fill_prob_passed = 0
    fill_prob_labeled = 0
    fill_prob_reasons: Counter[str] = Counter()

    for row in rows:
        if _parse_bool(row.get("ml_filter_enabled")) is True:
            ml_enabled += 1
        if (value := _parse_float(row.get("ml_predicted_ev"))) is not None:
            ml_scored_values.append(value)
        if (value := _parse_float(row.get("ml_min_ev"))) is not None:
            ml_min_values.append(value)
        if (passed := _parse_bool(row.get("ml_passed"))) is not None:
            ml_labeled += 1
            ml_passed += int(passed)
        reason = str(row.get("ml_reason") or "").strip()
        if reason and reason != "none":
            ml_reasons[reason] += 1

        if (value := _parse_float(row.get("fill_probability"))) is not None:
            fill_prob_values.append(value)
        if (value := _parse_float(row.get("fill_prob_min_probability"))) is not None:
            fill_prob_min_values.append(value)
        if (passed := _parse_bool(row.get("fill_prob_passed"))) is not None:
            fill_prob_labeled += 1
            fill_prob_passed += int(passed)
        reason = str(row.get("fill_prob_reason") or "").strip()
        if reason and reason != "none":
            fill_prob_reasons[reason] += 1

    return PublicModelDecisionDiagnostics(
        row_count=len(rows),
        ml_enabled_count=ml_enabled,
        ml_scored_count=len(ml_scored_values),
        ml_passed_count=ml_passed,
        ml_pass_rate=(ml_passed / ml_labeled) if ml_labeled else None,
        avg_ml_predicted_ev=_mean_optional(ml_scored_values),
        avg_ml_min_ev=_mean_optional(ml_min_values),
        ml_reason_counts=tuple(ml_reasons.most_common(8)),
        fill_probability_count=len(fill_prob_values),
        fill_prob_passed_count=fill_prob_passed,
        fill_prob_pass_rate=(fill_prob_passed / fill_prob_labeled) if fill_prob_labeled else None,
        avg_fill_probability=_mean_optional(fill_prob_values),
        avg_fill_prob_min_probability=_mean_optional(fill_prob_min_values),
        fill_prob_reason_counts=tuple(fill_prob_reasons.most_common(8)),
    )


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
    *,
    source_path: str = "data/sample/executions_sample.csv",
    model_diagnostics: PublicModelDecisionDiagnostics | None = None,
) -> str:
    """Render a sample-only ML filter workflow report."""

    thresholds = test.thresholds
    test_note = _filter_interpretation_note(test)
    model_diagnostics = model_diagnostics or load_public_model_decision_diagnostics(source_path)
    return "\n".join(
        [
            "# ML Filter Workflow Report",
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
            "The public demo uses a transparent learned-threshold baseline rather than a shipped production ML model.",
            "Thresholds are fitted on the earlier sample segment and applied to the later segment.",
            "No private model artifact, raw model score, or production threshold is loaded by this demo.",
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
            "## What the public baseline shows",
            "",
            test_note,
            "",
            "This is useful as a validation example: a filter can be mechanically reasonable, yet fail to improve out-of-sample label quality on the public sample. That is why this project treats ML as a validation workflow, not as an alpha claim.",
            "",
            "## Exported private-ledger ML diagnostics",
            "",
            "The current public sample includes anonymized ML and fill-probability decision fields exported from the private ledger. It keeps only safe scalar diagnostics and coarse reasons; it does not export model paths, feature lists, raw feature JSON, wallet/order identifiers, or raw responses.",
            "",
            "| Metric | Value |",
            "|---|---:|",
            f"| Rows inspected | {model_diagnostics.row_count} |",
            f"| ML filter enabled rows | {model_diagnostics.ml_enabled_count} |",
            f"| Rows with ML predicted EV | {model_diagnostics.ml_scored_count} |",
            f"| ML passed rows | {model_diagnostics.ml_passed_count} |",
            f"| ML pass rate | {format_rate(model_diagnostics.ml_pass_rate)} |",
            f"| Avg ML predicted EV | {_format_decimal(model_diagnostics.avg_ml_predicted_ev)} |",
            f"| Avg ML minimum EV threshold | {_format_decimal(model_diagnostics.avg_ml_min_ev)} |",
            f"| Rows with fill probability | {model_diagnostics.fill_probability_count} |",
            f"| Fill-probability passed rows | {model_diagnostics.fill_prob_passed_count} |",
            f"| Fill-probability pass rate | {format_rate(model_diagnostics.fill_prob_pass_rate)} |",
            f"| Avg fill probability | {_format_decimal(model_diagnostics.avg_fill_probability)} |",
            f"| Avg fill-probability threshold | {_format_decimal(model_diagnostics.avg_fill_prob_min_probability)} |",
            "",
            "### ML rejection reasons",
            "",
            *_reason_table(model_diagnostics.ml_reason_counts),
            "",
            "### Fill-probability rejection reasons",
            "",
            *_reason_table(model_diagnostics.fill_prob_reason_counts),
            "",
            "## Interpretation limits",
            "",
            "- These diagnostics are based on anonymized public sample rows, not the full private ledger.",
            "- The baseline is designed to demonstrate validation workflow, not to prove predictive edge.",
            "- Public sample labels may be sparse or simplified after anonymization.",
            "- The report does not replay the original private ML model or expose raw model scores.",
            "- A future extension can add true ML score and decision diagnostics if fields such as `ml_score`, `ml_passed`, or `blocked_ml_filter` can be safely anonymized and bucketed.",
        ]
    ) + "\n"


def _format_decimal(value: float | None, digits: int = 6) -> str:
    """Format nullable decimal values for Markdown reports."""

    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _reason_table(reason_counts: tuple[tuple[str, int], ...]) -> list[str]:
    """Render reason counts as a compact Markdown table."""

    lines = ["| Reason | Count |", "|---|---:|"]
    if not reason_counts:
        lines.append("| n/a | 0 |")
        return lines
    lines.extend(f"| {reason} | {count} |" for reason, count in reason_counts)
    return lines


def _filter_interpretation_note(diagnostics: FilterDiagnostics) -> str:
    """Return a concise public interpretation of test-segment filter diagnostics."""

    if (
        diagnostics.positive_rate_all is None
        or diagnostics.positive_rate_passed is None
        or diagnostics.positive_rate_rejected is None
    ):
        return (
            "The public sample does not contain enough labels to evaluate whether "
            "the baseline improves the target label rate."
        )
    if diagnostics.positive_rate_passed <= diagnostics.positive_rate_all:
        return (
            "On the public test segment, the baseline does not improve the positive "
            "label rate: passed rows show "
            f"{format_rate(diagnostics.positive_rate_passed)} versus "
            f"{format_rate(diagnostics.positive_rate_all)} overall."
        )
    return (
        "On the public test segment, the baseline improves the positive label rate: "
        f"passed rows show {format_rate(diagnostics.positive_rate_passed)} versus "
        f"{format_rate(diagnostics.positive_rate_all)} overall."
    )


def _diagnostic_row(name: str, diagnostics: FilterDiagnostics) -> str:
    return (
        f"| {name} | {diagnostics.row_count} | {diagnostics.passed_count} | "
        f"{format_rate(diagnostics.pass_rate)} | {diagnostics.labeled_count} | "
        f"{format_rate(diagnostics.positive_rate_all)} | "
        f"{format_rate(diagnostics.positive_rate_passed)} | "
        f"{format_rate(diagnostics.positive_rate_rejected)} |"
    )
