#!/usr/bin/env python3
"""Generate report figures from public sample data.

The figures are derived only from anonymized public sample CSVs. They are
intended for README/reports presentation and should not be interpreted as full
live-performance charts.
"""

from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

import matplotlib.pyplot as plt

from models.calibration import load_forecast_outcomes
from risk.monte_carlo import bootstrap_paths, load_normalized_pnl


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data" / "sample"
FIGURE_DIR = ROOT / "reports" / "figures"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as handle:
        return list(csv.DictReader(handle))


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _save_current(name: str) -> Path:
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / name
    plt.tight_layout()
    plt.savefig(path, dpi=160)
    plt.close()
    return path


def plot_signal_funnel() -> Path:
    candidates = _read_csv(DATA_DIR / "candidates_sample.csv")
    executions = _read_csv(DATA_DIR / "executions_sample.csv")
    settlements = _read_csv(DATA_DIR / "settlements_sample.csv")
    order_sent = sum(1 for row in executions if str(row.get("order_sent", "")).lower() == "true")
    accepted = sum(1 for row in executions if str(row.get("order_accepted", "")).lower() == "true")
    filled = sum(1 for row in executions if str(row.get("filled", "")).lower() == "true")

    labels = ["Candidates", "Order sent", "Accepted", "Filled", "Settlements"]
    values = [len(candidates), order_sent, accepted, filled, len(settlements)]

    plt.figure(figsize=(8, 4.5))
    plt.bar(labels, values)
    plt.ylabel("Rows")
    plt.title("Public Sample Signal Funnel")
    plt.xticks(rotation=20, ha="right")
    return _save_current("signal_funnel.png")


def plot_spread_distribution() -> Path:
    executions = _read_csv(DATA_DIR / "executions_sample.csv")
    spreads = [value for row in executions if (value := _to_float(row.get("signal_spread"))) is not None]

    plt.figure(figsize=(7, 4.5))
    plt.hist(spreads, bins=20)
    plt.xlabel("Signal spread")
    plt.ylabel("Execution attempts")
    plt.title("Spread Distribution")
    return _save_current("spread_distribution.png")


def _edge_bucket(edge: float) -> str:
    if edge < 0.25:
        return "<0.25"
    if edge < 0.35:
        return "0.25-0.35"
    if edge < 0.50:
        return "0.35-0.50"
    return ">=0.50"


def plot_fill_rate_by_edge_bucket() -> Path:
    executions = _read_csv(DATA_DIR / "executions_sample.csv")
    buckets: dict[str, list[int]] = defaultdict(list)
    for row in executions:
        edge = _to_float(row.get("signal_edge"))
        if edge is None:
            continue
        filled = 1 if str(row.get("filled", "")).lower() == "true" else 0
        buckets[_edge_bucket(edge)].append(filled)

    labels = ["<0.25", "0.25-0.35", "0.35-0.50", ">=0.50"]
    values = [mean(buckets[label]) if buckets.get(label) else 0.0 for label in labels]

    plt.figure(figsize=(7, 4.5))
    plt.bar(labels, values)
    plt.ylim(0, max(values + [0.05]) * 1.25)
    plt.ylabel("Fill rate")
    plt.xlabel("Signal edge bucket")
    plt.title("Fill Rate by Signal Edge Bucket")
    return _save_current("fill_rate_by_edge_bucket.png")


def plot_calibration_curve() -> Path:
    forecasts = load_forecast_outcomes(
        DATA_DIR / "tick_snapshots_sample.csv",
        DATA_DIR / "settlements_sample.csv",
    )
    grouped: dict[str, list[tuple[float, int]]] = defaultdict(list)
    for row in forecasts:
        lower = int(min(row.fair_probability, 0.999999) * 10) / 10
        label = f"{lower:.1f}-{lower + 0.1:.1f}"
        grouped[label].append((row.fair_probability, row.outcome))

    labels = sorted(grouped)
    avg_forecasts = [mean(prob for prob, _ in grouped[label]) for label in labels]
    realized = [mean(outcome for _, outcome in grouped[label]) for label in labels]

    plt.figure(figsize=(6, 5))
    plt.plot([0, 1], [0, 1], linestyle="--", label="Perfect calibration")
    plt.plot(avg_forecasts, realized, marker="o", label="Fair probability")
    plt.xlabel("Average forecast probability")
    plt.ylabel("Realized UP rate")
    plt.title("Fair Probability Calibration Curve")
    plt.legend()
    return _save_current("calibration_curve.png")


def plot_terminal_pnl_distribution() -> Path:
    pnl = load_normalized_pnl(DATA_DIR / "settlements_sample.csv")
    paths = bootstrap_paths(pnl, simulation_count=1000, horizon=len(pnl), seed=42)
    terminal_values = [path.final_pnl for path in paths]

    plt.figure(figsize=(7, 4.5))
    plt.hist(terminal_values, bins=30)
    plt.xlabel("Final normalized PnL")
    plt.ylabel("Simulated paths")
    plt.title("Monte Carlo Final PnL Distribution")
    return _save_current("monte_carlo_terminal_pnl.png")


def plot_drawdown_distribution() -> Path:
    pnl = load_normalized_pnl(DATA_DIR / "settlements_sample.csv")
    paths = bootstrap_paths(pnl, simulation_count=1000, horizon=len(pnl), seed=42)
    drawdowns = [path.max_drawdown for path in paths]

    plt.figure(figsize=(7, 4.5))
    plt.hist(drawdowns, bins=30)
    plt.xlabel("Max drawdown, normalized units")
    plt.ylabel("Simulated paths")
    plt.title("Monte Carlo Drawdown Distribution")
    return _save_current("monte_carlo_drawdown.png")


def plot_status_breakdown() -> Path:
    executions = _read_csv(DATA_DIR / "executions_sample.csv")
    counts = Counter(row.get("status") or "unknown" for row in executions)
    labels = [label for label, _ in counts.most_common()]
    values = [counts[label] for label in labels]

    plt.figure(figsize=(8, 4.5))
    plt.bar(labels, values)
    plt.ylabel("Execution attempts")
    plt.title("Execution Status Breakdown")
    plt.xticks(rotation=25, ha="right")
    return _save_current("execution_status_breakdown.png")


def main() -> None:
    figures = [
        plot_signal_funnel(),
        plot_status_breakdown(),
        plot_spread_distribution(),
        plot_fill_rate_by_edge_bucket(),
        plot_calibration_curve(),
        plot_terminal_pnl_distribution(),
        plot_drawdown_distribution(),
    ]
    for path in figures:
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
