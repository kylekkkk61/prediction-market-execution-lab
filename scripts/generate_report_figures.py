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
from matplotlib.patches import FancyBboxPatch

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
    fig = plt.gcf()
    fig.tight_layout(rect=(0, 0, 1, 0.88))
    fig.savefig(path, dpi=180, bbox_inches="tight", pad_inches=0.06)
    plt.close(fig)
    return path


def _apply_figure_heading(title: str, subtitle: str) -> None:
    """Add title/subtitle above the axes with preserved internal spacing."""
    ax = plt.gca()
    ax.text(
        0,
        1.13,
        title,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=12.5,
        fontweight="bold",
    )
    ax.text(
        0,
        1.04,
        subtitle,
        transform=ax.transAxes,
        ha="left",
        va="bottom",
        fontsize=9.2,
    )


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
    _apply_figure_heading(
        "Most candidate signals do not become filled exposure",
        "Public sample counts across signal, order, fill, and settlement stages.",
    )
    plt.xticks(rotation=20, ha="right")
    return _save_current("signal_funnel.png")


def plot_spread_distribution() -> Path:
    executions = _read_csv(DATA_DIR / "executions_sample.csv")
    spreads = [value for row in executions if (value := _to_float(row.get("signal_spread"))) is not None]

    plt.figure(figsize=(7, 4.5))
    plt.hist(spreads, bins=20)
    plt.xlabel("Signal spread")
    plt.ylabel("Execution attempts")
    _apply_figure_heading(
        "Spread is visible, but not the whole execution problem",
        "Distribution of observed public-sample signal spreads.",
    )
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
    _apply_figure_heading(
        "Higher apparent edge does not automatically mean better execution",
        "Fill rates by public-sample signal-edge bucket.",
    )
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
    _apply_figure_heading(
        "Extreme probabilities are where confidence becomes fragile",
        "Fair probability buckets compared with realized UP outcomes.",
    )
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
    _apply_figure_heading(
        "Sparse realized exposure creates path-dependent outcomes",
        "Bootstrap terminal normalized PnL from the public settlement sample.",
    )
    return _save_current("monte_carlo_terminal_pnl.png")


def plot_drawdown_distribution() -> Path:
    pnl = load_normalized_pnl(DATA_DIR / "settlements_sample.csv")
    paths = bootstrap_paths(pnl, simulation_count=1000, horizon=len(pnl), seed=42)
    drawdowns = [path.max_drawdown for path in paths]

    plt.figure(figsize=(7, 4.5))
    plt.hist(drawdowns, bins=30)
    plt.xlabel("Max drawdown, normalized units")
    plt.ylabel("Simulated paths")
    _apply_figure_heading(
        "Drawdown risk remains even in a normalized public sample",
        "Bootstrap max drawdown from sampled normalized settlement PnL.",
    )
    return _save_current("monte_carlo_drawdown.png")


def plot_status_breakdown() -> Path:
    executions = _read_csv(DATA_DIR / "executions_sample.csv")
    counts = Counter(row.get("status") or "unknown" for row in executions)
    labels = [label for label, _ in counts.most_common()]
    values = [counts[label] for label in labels]

    plt.figure(figsize=(8, 4.5))
    plt.bar(labels, values)
    plt.ylabel("Execution attempts")
    _apply_figure_heading(
        "Execution states explain where signals fail",
        "Public-sample attempts by recorded execution status.",
    )
    plt.xticks(rotation=25, ha="right")
    return _save_current("execution_status_breakdown.png")


def plot_system_architecture() -> Path:
    """Create a public-facing architecture visual for the research workflow."""
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    path = FIGURE_DIR / "system_architecture.png"

    steps = [
        ("Public sample\ndata", "anonymized\nnormalized"),
        ("Fair probability\nmodel", "reference-price\nestimate"),
        ("Edge\ncalculation", "theoretical\nmispricing"),
        ("Execution\ndiagnostics", "spread / latency\nfills"),
        ("Reports &\nnotebooks", "research\nartifacts"),
        ("Dashboard &\nrisk", "interactive\nreview"),
    ]

    fig, ax = plt.subplots(figsize=(15.5, 4.6))
    fig.subplots_adjust(left=0.025, right=0.975, top=0.82, bottom=0.08)
    ax.axis("off")
    fig.suptitle(
        "Research workflow: from theoretical edge to executable-edge diagnostics",
        x=0.06,
        y=0.86,
        ha="left",
        fontsize=17,
        fontweight="bold",
    )
    fig.text(
        0.06,
        0.77,
        "Public artifacts use anonymized sample data only; no live execution, wallet, signer, or private operations are exposed.",
        ha="left",
        va="top",
        fontsize=11,
    )

    box_width = 0.12
    box_height = 0.39
    start_x = 0.065
    gap = 0.03
    y = 0.29

    for index, (title, subtitle) in enumerate(steps):
        x = start_x + index * (box_width + gap)
        box = FancyBboxPatch(
            (x, y),
            box_width,
            box_height,
            boxstyle="round,pad=0.018,rounding_size=0.018",
            linewidth=1.25,
            facecolor="white",
            edgecolor="black",
            transform=ax.transAxes,
        )
        ax.add_patch(box)
        ax.text(
            x + box_width / 2,
            y + box_height * 0.64,
            title,
            ha="center",
            va="center",
            fontsize=11.5,
            weight="bold",
            linespacing=1.15,
            transform=ax.transAxes,
        )
        ax.text(
            x + box_width / 2,
            y + box_height * 0.30,
            subtitle,
            ha="center",
            va="center",
            fontsize=9.4,
            linespacing=1.2,
            transform=ax.transAxes,
        )
        if index < len(steps) - 1:
            ax.annotate(
                "",
                xy=(x + box_width + gap * 0.74, y + box_height / 2),
                xytext=(x + box_width + gap * 0.18, y + box_height / 2),
                xycoords=ax.transAxes,
                arrowprops={"arrowstyle": "->", "lw": 1.2},
            )

    fig.savefig(path, dpi=180)
    plt.close(fig)
    return path


def main() -> None:
    figures = [
        plot_system_architecture(),
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
