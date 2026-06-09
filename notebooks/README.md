# Research Notebook Guide

These notebooks provide a public-sample walkthrough of the research workflow. They are meant to help reviewers understand the analysis path without requiring private ledgers, raw tick data, wallet identifiers, model artifacts, or live execution systems.

| Notebook | Focus | Best for |
|---|---|---|
| [`01_data_overview.ipynb`](01_data_overview.ipynb) | Public sample files, schema coverage, and safe exported fields | Understanding what data is included and excluded |
| [`02_execution_quality_analysis.ipynb`](02_execution_quality_analysis.ipynb) | Signal funnel, rejection diagnostics, fill rates, edge buckets, and settlement PnL | Seeing how theoretical edge decays through execution gates |
| [`03_fair_probability_reference_price.ipynb`](03_fair_probability_reference_price.ipynb) | Binance BTCUSDT-style reference proxy, opening anchor, fair probability, and market-implied probability | Reviewing the pricing-model assumptions |
| [`04_probability_calibration.ipynb`](04_probability_calibration.ipynb) | Brier score, log loss, calibration buckets, and extreme-probability interpretation | Evaluating whether probabilities are directionally calibrated |
| [`05_ml_filter_diagnostics.ipynb`](05_ml_filter_diagnostics.ipynb) | ML EV gate, fill-probability diagnostics, chronological validation, and pass/fail behavior | Understanding ML as an execution-quality filter rather than an alpha claim |
| [`06_risk_simulation.ipynb`](06_risk_simulation.ipynb) | Normalized PnL distribution, bootstrap Monte Carlo, terminal PnL, drawdown, and losing streaks | Inspecting sample-path risk and the simulation-to-live gap |

## How to run

From the repository root:

```bash
uv sync --extra dev --extra notebook --extra dashboard --extra ml
PYTHONPATH=src uv run jupyter lab notebooks/
```

To execute one notebook headlessly:

```bash
uv run jupyter nbconvert --to notebook --execute notebooks/04_probability_calibration.ipynb --output-dir /tmp
```

## Interpretation

The notebooks use anonymized, downsampled, and normalized public samples. They demonstrate the analysis workflow and should not be interpreted as complete historical performance or a live trading system.
