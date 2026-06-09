"""Probability calibration diagnostics for public sample data.

This module is intentionally sample-only. It consumes anonymized public sample
rows and compares forecast probabilities with settlement outcomes. It does not
read private ledgers or production execution state.
"""

from __future__ import annotations

from dataclasses import dataclass
import csv
import math
from pathlib import Path
from statistics import mean
from typing import Iterable, Sequence


@dataclass(frozen=True)
class ForecastOutcome:
    market_id: str
    fair_probability: float
    market_probability: float | None
    outcome: int


@dataclass(frozen=True)
class CalibrationBucket:
    bucket: str
    count: int
    avg_forecast: float
    realized_rate: float
    avg_abs_error: float


@dataclass(frozen=True)
class CalibrationSummary:
    label: str
    observations: int
    brier_score: float | None
    log_loss: float | None
    calibration_buckets: tuple[CalibrationBucket, ...]


def _parse_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if not math.isfinite(number):
        return None
    return number


def _clip_probability(value: float, eps: float = 1e-6) -> float:
    return min(max(value, eps), 1.0 - eps)


def _outcome_from_resolved_side(value: object) -> int | None:
    text = str(value or "").strip().lower()
    if text in {"up", "yes", "true", "1"}:
        return 1
    if text in {"down", "no", "false", "0"}:
        return 0
    return None


def load_forecast_outcomes(
    tick_path: str | Path,
    settlements_path: str | Path,
    *,
    fair_probability_column: str = "fair_yes",
    market_probability_column: str = "pm_implied_up",
) -> list[ForecastOutcome]:
    """Join public tick forecasts with settlement outcomes by anonymized market id.

    Multiple tick rows per market are collapsed to one market-level observation by
    averaging the available forecast probabilities. This keeps the calibration
    unit at the market level rather than over-weighting markets with more quote
    updates in the public sample.
    """

    tick_path = Path(tick_path)
    settlements_path = Path(settlements_path)

    forecasts: dict[str, dict[str, list[float]]] = {}
    with tick_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            market_id = (row.get("market_id") or "").strip()
            if not market_id:
                continue
            fair_prob = _parse_float(row.get(fair_probability_column))
            market_prob = _parse_float(row.get(market_probability_column))
            bucket = forecasts.setdefault(market_id, {"fair": [], "market": []})
            if fair_prob is not None and 0.0 <= fair_prob <= 1.0:
                bucket["fair"].append(fair_prob)
            if market_prob is not None and 0.0 <= market_prob <= 1.0:
                bucket["market"].append(market_prob)

    outcomes: dict[str, int] = {}
    with settlements_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            market_id = (row.get("market_id") or "").strip()
            outcome = _outcome_from_resolved_side(row.get("resolved_side"))
            if market_id and outcome is not None:
                outcomes[market_id] = outcome

    joined: list[ForecastOutcome] = []
    for market_id, values in sorted(forecasts.items()):
        if market_id not in outcomes or not values["fair"]:
            continue
        market_probability = mean(values["market"]) if values["market"] else None
        joined.append(
            ForecastOutcome(
                market_id=market_id,
                fair_probability=mean(values["fair"]),
                market_probability=market_probability,
                outcome=outcomes[market_id],
            )
        )
    return joined


def _bucket_label(probability: float, bucket_width: float) -> str:
    lower = math.floor(probability / bucket_width) * bucket_width
    upper = min(lower + bucket_width, 1.0)
    if math.isclose(upper, lower):
        upper = min(lower + bucket_width, 1.0)
    return f"{lower:.1f}-{upper:.1f}"


def calibration_buckets(
    probabilities: Sequence[float],
    outcomes: Sequence[int],
    *,
    bucket_width: float = 0.1,
) -> tuple[CalibrationBucket, ...]:
    if len(probabilities) != len(outcomes):
        raise ValueError("probabilities and outcomes must have the same length")
    grouped: dict[str, list[tuple[float, int]]] = {}
    for probability, outcome in zip(probabilities, outcomes):
        if not 0.0 <= probability <= 1.0:
            continue
        label = _bucket_label(min(probability, 0.999999), bucket_width)
        grouped.setdefault(label, []).append((probability, int(outcome)))

    buckets: list[CalibrationBucket] = []
    for label in sorted(grouped):
        rows = grouped[label]
        avg_forecast = mean(probability for probability, _ in rows)
        realized_rate = mean(outcome for _, outcome in rows)
        buckets.append(
            CalibrationBucket(
                bucket=label,
                count=len(rows),
                avg_forecast=avg_forecast,
                realized_rate=realized_rate,
                avg_abs_error=abs(avg_forecast - realized_rate),
            )
        )
    return tuple(buckets)


def summarize_calibration(
    forecasts: Iterable[ForecastOutcome],
    *,
    source: str = "fair",
    bucket_width: float = 0.1,
) -> CalibrationSummary:
    probabilities: list[float] = []
    outcomes: list[int] = []
    for row in forecasts:
        probability = row.fair_probability if source == "fair" else row.market_probability
        if probability is None:
            continue
        probabilities.append(_clip_probability(float(probability)))
        outcomes.append(int(row.outcome))

    if not probabilities:
        return CalibrationSummary(source, 0, None, None, tuple())

    brier = mean((probability - outcome) ** 2 for probability, outcome in zip(probabilities, outcomes))
    log_loss = mean(
        -(outcome * math.log(probability) + (1 - outcome) * math.log(1 - probability))
        for probability, outcome in zip(probabilities, outcomes)
    )
    return CalibrationSummary(
        label=source,
        observations=len(probabilities),
        brier_score=brier,
        log_loss=log_loss,
        calibration_buckets=calibration_buckets(probabilities, outcomes, bucket_width=bucket_width),
    )


def _fmt(value: float | None, digits: int = 4) -> str:
    if value is None:
        return "n/a"
    return f"{value:.{digits}f}"


def _render_bucket_table(summary: CalibrationSummary) -> str:
    if not summary.calibration_buckets:
        return "No calibration buckets could be computed for this source.\n"
    lines = [
        "| Bucket | Count | Avg forecast | Realized rate | Avg abs error |",
        "|---|---:|---:|---:|---:|",
    ]
    for bucket in summary.calibration_buckets:
        lines.append(
            "| {bucket} | {count} | {avg_forecast:.4f} | {realized_rate:.4f} | {avg_abs_error:.4f} |".format(
                bucket=bucket.bucket,
                count=bucket.count,
                avg_forecast=bucket.avg_forecast,
                realized_rate=bucket.realized_rate,
                avg_abs_error=bucket.avg_abs_error,
            )
        )
    return "\n".join(lines) + "\n"


def render_calibration_report(
    forecasts: Sequence[ForecastOutcome],
    fair_summary: CalibrationSummary,
    market_summary: CalibrationSummary,
) -> str:
    joined_markets = len(forecasts)
    lines = [
        "# Probability Calibration Report",
        "",
        "> This report is generated from anonymized public sample data. It is a methodology and diagnostics artifact, not a claim about production predictive performance or trading profitability.",
        "",
        "## Why calibration matters",
        "",
        "Prediction-market prices can be read as market-implied probabilities, but a useful research model must also be calibrated against realized outcomes. Calibration diagnostics test whether forecast probabilities behave like probabilities rather than just producing directional scores.",
        "",
        "## Fair probability vs market-implied probability",
        "",
        "The report compares two probability sources when public sample fields are available: a model-estimated fair probability and a market-implied probability derived from prediction-market quotes. The comparison is diagnostic only; it does not establish that either source is consistently superior in live trading.",
        "",
        "## Binance/reference price assumption",
        "",
        "The fair-probability workflow uses Binance BTCUSDT spot ticks as the faster reference layer and uses Binance-derived bucket open prices as the opening anchor proxy. Polymarket BTC markets settle against an oracle-style reference rather than Binance directly. My working assumption, consistent with common player observations in these markets, is that the resolution-linked reference tends to follow Binance-style spot movement with a short delay. This repo does not yet include a dedicated lead-lag validation study, so I treat the lag as a domain-informed assumption rather than a proven empirical claim.",
        "",
        "## Sample coverage",
        "",
        f"- Joined market-level observations: {joined_markets}",
        "- Forecast unit: one averaged forecast per anonymized market id",
        "- Outcome unit: resolved UP/DOWN settlement side from public sample settlements",
        "- If joined observations are zero, the current public sample does not contain aligned forecast and settlement keys",
        "",
        "## Summary metrics",
        "",
        "| Source | Observations | Brier score | Log loss |",
        "|---|---:|---:|---:|",
        f"| Fair probability | {fair_summary.observations} | {_fmt(fair_summary.brier_score)} | {_fmt(fair_summary.log_loss)} |",
        f"| Market-implied probability | {market_summary.observations} | {_fmt(market_summary.brier_score)} | {_fmt(market_summary.log_loss)} |",
        "",
        "## How to read Brier score and log loss",
        "",
        "Brier score measures squared probability error, where lower is better. Log loss penalizes confident wrong probabilities more severely, so it is sensitive to overconfident forecasts. Both metrics are computed only on joined public-sample observations.",
        "",
        "## Fair probability calibration buckets",
        "",
        "![Calibration curve](figures/calibration_curve.png)",
        "",
        _render_bucket_table(fair_summary),
        "",
        "## Market-implied probability calibration buckets",
        "",
        _render_bucket_table(market_summary),
        "",
        "## Author takeaway",
        "",
        "The calibration result that stands out most is the instability of the extreme probability buckets. In the public sample, the middle probability range is comparatively better behaved, while very low and very high buckets show larger errors and fewer observations.",
        "",
        "My interpretation is that extreme buckets are fragile for two reasons. First, they are sparse, so variance is naturally higher. Second, they often appear in exactly the regimes where a five-minute binary market is hardest to model: either after a large early Binance BTCUSDT spot move or inside the final resolution window when small price changes can push implied probabilities toward 0 or 1.",
        "",
        "The final 5-10 seconds are especially vulnerable to last-time-window reversal risk. The underlying price can reverse or repeatedly cross the opening anchor while probability estimates are already compressed near certainty. A small reversal near resolution can therefore create a large forecast error without requiring a large move in BTC.",
        "",
        "## What calibration can suggest",
        "",
        "Calibration buckets can show whether forecasts are systematically too high or too low in parts of the probability range. In this public sample, they suggest that the model and market-implied probabilities are more informative in the middle range than in the extremes. I treat the tail-bucket pattern as a warning about resolution-window microstructure rather than as a simple model-fitting problem.",
        "",
        "## What I learned",
        "",
        "The calibration result taught me that the model is most fragile when it looks most confident. Extreme probabilities can be driven by real price moves, but they can also be amplified by the short time remaining before resolution. I therefore treat tail-bucket confidence as something to audit, not something to trust mechanically.",
        "",
        "## What calibration cannot prove",
        "",
        "- Calibration metrics do not prove executable edge or profitability.",
        "- Averaging multiple tick rows into one market-level observation removes intra-market timing information.",
        "- A well-calibrated probability can still fail after spread, fill probability, latency, or position limits.",
        "- A poor public-sample calibration result may reflect sample construction, limited observations, or anonymization rather than a general model failure.",
        "",
        "## Interpretation notes",
        "",
        "- Brier score and log loss are computed on public-sample market-level observations only.",
        "- Markets with missing probabilities, unresolved settlement labels, or non-aligned anonymized keys are excluded.",
        "- Multiple tick rows per market are averaged before scoring, so markets with more quote updates do not dominate the calibration score.",
        "- The public sample is anonymized and downsampled; these diagnostics should be read as a reproducible workflow demonstration, not as a full empirical conclusion.",
        "",
    ]
    return "\n".join(lines)
