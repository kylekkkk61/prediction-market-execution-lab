"""Monte Carlo risk diagnostics for public sample data.

This module only operates on anonymized / normalized public sample data. It does
not read private ledger files and does not reconstruct real account-level PnL.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import math
import random
from statistics import mean


@dataclass(frozen=True)
class EquityPathStats:
    """Summary statistics for one simulated cumulative PnL path."""

    final_pnl: float
    max_drawdown: float
    longest_losing_streak: int


@dataclass(frozen=True)
class MonteCarloSummary:
    """Aggregate diagnostics across Monte Carlo paths."""

    sample_count: int
    simulation_count: int
    horizon: int
    seed: int
    mean_final_pnl: float
    median_final_pnl: float
    p05_final_pnl: float
    p95_final_pnl: float
    mean_max_drawdown: float
    p95_max_drawdown: float
    mean_longest_losing_streak: float
    p95_longest_losing_streak: float


def load_normalized_pnl(path: str | Path, column: str = "net_pnl_normalized") -> list[float]:
    """Load normalized PnL observations from a public sample CSV.

    Blank, missing, and non-finite values are skipped. The returned values are
    normalized public-sample units, not real currency PnL.
    """

    pnl_values: list[float] = []
    with Path(path).open(newline="") as f:
        reader = csv.DictReader(f)
        if column not in (reader.fieldnames or []):
            raise ValueError(f"Missing required PnL column: {column}")
        for row in reader:
            raw_value = row.get(column, "")
            if raw_value in (None, ""):
                continue
            try:
                value = float(raw_value)
            except ValueError:
                continue
            if math.isfinite(value):
                pnl_values.append(value)
    return pnl_values


def max_drawdown(cumulative_pnl: list[float]) -> float:
    """Return the maximum peak-to-trough drawdown for a cumulative PnL path."""

    peak = 0.0
    worst_drawdown = 0.0
    for value in cumulative_pnl:
        peak = max(peak, value)
        worst_drawdown = max(worst_drawdown, peak - value)
    return worst_drawdown


def longest_losing_streak(pnl_values: list[float]) -> int:
    """Return the longest consecutive run of negative PnL observations."""

    longest = 0
    current = 0
    for value in pnl_values:
        if value < 0:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def summarize_path(pnl_values: list[float]) -> EquityPathStats:
    """Summarize one sequence of normalized PnL values."""

    cumulative: list[float] = []
    running = 0.0
    for value in pnl_values:
        running += value
        cumulative.append(running)

    return EquityPathStats(
        final_pnl=running,
        max_drawdown=max_drawdown(cumulative),
        longest_losing_streak=longest_losing_streak(pnl_values),
    )


def percentile(values: list[float], pct: float) -> float:
    """Return a linear-interpolated percentile for a non-empty list."""

    if not values:
        raise ValueError("Cannot compute percentile of an empty list")
    if not 0 <= pct <= 100:
        raise ValueError("Percentile must be between 0 and 100")

    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]

    rank = (len(ordered) - 1) * pct / 100
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return ordered[int(rank)]
    lower_value = ordered[lower]
    upper_value = ordered[upper]
    weight = rank - lower
    return lower_value + (upper_value - lower_value) * weight


def bootstrap_paths(
    pnl_values: list[float],
    *,
    simulation_count: int = 1000,
    horizon: int | None = None,
    seed: int = 42,
) -> list[EquityPathStats]:
    """Bootstrap normalized PnL paths with replacement.

    The default horizon equals the number of input observations.
    """

    if not pnl_values:
        raise ValueError("At least one PnL observation is required")
    if simulation_count <= 0:
        raise ValueError("simulation_count must be positive")

    path_horizon = horizon or len(pnl_values)
    if path_horizon <= 0:
        raise ValueError("horizon must be positive")

    rng = random.Random(seed)
    paths: list[EquityPathStats] = []
    for _ in range(simulation_count):
        sampled = [rng.choice(pnl_values) for _ in range(path_horizon)]
        paths.append(summarize_path(sampled))
    return paths


def summarize_monte_carlo(
    pnl_values: list[float],
    *,
    simulation_count: int = 1000,
    horizon: int | None = None,
    seed: int = 42,
) -> MonteCarloSummary:
    """Run bootstrap Monte Carlo and return aggregate risk diagnostics."""

    path_horizon = horizon or len(pnl_values)
    paths = bootstrap_paths(
        pnl_values,
        simulation_count=simulation_count,
        horizon=path_horizon,
        seed=seed,
    )
    finals = [p.final_pnl for p in paths]
    drawdowns = [p.max_drawdown for p in paths]
    streaks = [float(p.longest_losing_streak) for p in paths]

    return MonteCarloSummary(
        sample_count=len(pnl_values),
        simulation_count=simulation_count,
        horizon=path_horizon,
        seed=seed,
        mean_final_pnl=mean(finals),
        median_final_pnl=percentile(finals, 50),
        p05_final_pnl=percentile(finals, 5),
        p95_final_pnl=percentile(finals, 95),
        mean_max_drawdown=mean(drawdowns),
        p95_max_drawdown=percentile(drawdowns, 95),
        mean_longest_losing_streak=mean(streaks),
        p95_longest_losing_streak=percentile(streaks, 95),
    )


def render_risk_report(summary: MonteCarloSummary) -> str:
    """Render a Markdown report for sample-only Monte Carlo diagnostics."""

    return f"""# Risk Simulation Report

This report is generated from anonymized public sample data only. All PnL values are normalized sample units, not real currency PnL, and should not be interpreted as live trading performance.

## Why Monte Carlo is included

Execution-quality analysis can show average outcomes, but average PnL is not enough to understand risk. A strategy or research signal can have weak mean performance, unstable path dependency, long losing streaks, or downside tails that are hidden by point estimates. Monte Carlo simulation is included to inspect the distribution of possible sample paths under resampling assumptions.

## Input sample distribution

The simulation bootstraps normalized public-sample PnL observations with replacement. This preserves the empirical public-sample outcome distribution while randomizing order across simulated paths. It does not reconstruct trade sizing, account equity, or live execution state.

| Metric | Value |
|---|---:|
| Normalized PnL observations | {summary.sample_count} |
| Monte Carlo simulations | {summary.simulation_count} |
| Path horizon | {summary.horizon} |
| Random seed | {summary.seed} |

## Final normalized PnL distribution

![Monte Carlo terminal PnL distribution](figures/monte_carlo_terminal_pnl.png)

| Metric | Value |
|---|---:|
| Mean final PnL | {summary.mean_final_pnl:.4f} |
| Median final PnL | {summary.median_final_pnl:.4f} |
| 5th percentile final PnL | {summary.p05_final_pnl:.4f} |
| 95th percentile final PnL | {summary.p95_final_pnl:.4f} |

## How to read terminal PnL dispersion

The 5th and 95th percentile terminal PnL values describe downside and upside dispersion across resampled public-sample paths. Wide dispersion means realized path order can matter even when the same set of normalized outcomes is used.

## Drawdown and losing-streak diagnostics

![Monte Carlo drawdown distribution](figures/monte_carlo_drawdown.png)

| Metric | Value |
|---|---:|
| Mean max drawdown | {summary.mean_max_drawdown:.4f} |
| 95th percentile max drawdown | {summary.p95_max_drawdown:.4f} |
| Mean longest losing streak | {summary.mean_longest_losing_streak:.2f} |
| 95th percentile longest losing streak | {summary.p95_longest_losing_streak:.2f} |

## Downside-risk interpretation

Drawdown and losing-streak statistics show how unfavorable sample paths can compound. They are especially important for short-horizon execution strategies because many small negative outcomes can accumulate before any large positive outcome appears.

## Execution-assumption sensitivity

These results are sensitive to what enters the public PnL sample. If fill probability, slippage, latency, fees, or position limits change, the input outcome distribution changes as well. This simulation should be read alongside the execution-quality report rather than as a standalone capital-allocation model.

## Why this is not a live capital-allocation model

- This is a bootstrap diagnostic over public sample rows, not a complete account-level risk model.
- The sample is anonymized, downsampled, and normalized.
- Position sizing, real capital constraints, fees, and live fill dynamics are not reconstructed here.
- The simulation assumes resampled public-sample outcomes are representative enough for demonstration, which may not hold across market regimes.
- Use this report to inspect sample-path sensitivity, not to claim strategy profitability.
"""
