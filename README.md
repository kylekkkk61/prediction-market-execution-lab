# Prediction Market Execution Lab

**Testing Executable Edge in Polymarket BTC Short-Horizon Markets**

Prediction Market Execution Lab is a public research-oriented FinTech project for studying prediction-market microstructure, fair probability modeling, and execution quality.

It uses Polymarket BTC short-horizon markets as a case study to ask whether apparent pricing edges can survive real-world execution frictions. The repository is intentionally framed as a research lab, not as a live trading bot, production execution system, or profitable strategy claim.

## Project Overview

Short-horizon prediction markets often move quickly around reference-market prices, liquidity conditions, and settlement boundaries. A contract may look mispriced when compared with a fair probability estimate, but that apparent edge can disappear after accounting for:

- bid-ask spread
- available liquidity and slippage
- fill probability
- latency and quote staleness
- position limits
- settlement outcomes
- post-trade PnL attribution

This project converts that problem into a reproducible public workflow:

```text
public sample data
→ fair probability and implied probability analysis
→ candidate edge calculation
→ tick-level replay and execution-quality diagnostics
→ sample-backed reports and figures
→ risk simulation and ML-assisted filtering demos
```

The current public repository includes demo-safe modules, sample datasets, report scripts, and generated figures. These outputs are demonstration artifacts based on anonymized, downsampled, and normalized public samples. They are not full empirical performance claims.

## Research Question

> Can apparent short-horizon prediction-market pricing edges survive real execution frictions such as bid-ask spread, slippage, fill probability, latency, position limits, and settlement outcomes?

The main distinction is between:

- **Theoretical edge:** the difference between a fair probability estimate and a market-implied probability.
- **Executable edge:** the portion of that edge that remains after execution frictions and settlement are incorporated.

## Why Prediction Markets

Prediction-market prices can be interpreted as market-implied probabilities. That makes them a useful environment for studying the gap between estimated fair probability and executable trading outcomes.

Short-horizon BTC markets are especially useful for this project because they combine:

- rapidly changing reference prices
- discrete settlement outcomes
- CLOB-style bid-ask dynamics
- time-to-expiry effects
- liquidity constraints that can materially change realized edge

The project does not attempt to predict BTC direction as its primary claim. It studies whether apparent prediction-market mispricings remain actionable after microstructure and execution constraints are applied.

## Repository Structure

```text
prediction-market-execution-lab/
├── data/sample/                  # Public-safe anonymized and downsampled demo datasets
├── docs/                         # Project brief, methodology, architecture, limitations, data notes
├── reports/                      # Demonstration reports and generated figures
├── scripts/                      # Demo-safe report, figure, sample, and simulation runners
├── src/                          # Public research modules
│   ├── backtesting/              # Tick-level replay logic
│   ├── data_sources/             # Public sample loading and private inspection helpers
│   ├── execution_quality/        # Edge and fill-quality calculations
│   ├── models/                   # Fair probability, calibration, and ML-filter demos
│   ├── risk/                     # Monte Carlo risk simulation
│   └── utils/                    # Anonymization and shared utilities
├── tests/                        # Unit tests for public-safe modules and scripts
├── dashboard/                    # Streamlit demo placeholder
├── pyproject.toml                # Canonical dependency declaration
└── uv.lock                       # Locked uv environment
```

Some root-level legacy reference scripts may remain until the final cleanup PR. They are not positioned as public demo entry points and should not be interpreted as production-ready modules.

## Data and Sample Policy

Private raw ledger data, raw tick snapshots, wallet identifiers, order IDs, signer logic, allowance logic, deployment details, and live execution runbooks are intentionally excluded from the public workflow.

The public sample files under `data/sample/` are:

- anonymized
- downsampled
- normalized where needed
- small enough for review and deterministic demo runs
- intended for reproducible demonstrations, not full historical analysis

Current public sample files:

```text
data/sample/candidates_sample.csv
data/sample/executions_sample.csv
data/sample/rejections_sample.csv
data/sample/settlements_sample.csv
data/sample/tick_snapshots_sample.csv
```

The sample-generation policy is documented in [`docs/data_preparation.md`](docs/data_preparation.md), and the sample schema is documented in [`docs/sample_data_schema.md`](docs/sample_data_schema.md).

## Methodology Summary

The public research workflow is organized around the following components.

1. **Fair probability modeling**
   Estimate a fair probability for short-horizon BTC outcome markets using reference-market features and time-to-expiry inputs.

2. **Market-implied probability handling**
   Convert prediction-market prices into implied probabilities while preserving the distinction between bid, ask, midpoint, and executable price assumptions.

3. **Executable edge calculation**
   Compare fair probability with market-implied probability, then apply execution frictions such as spread, slippage, and fill assumptions.

4. **Tick-level replay backtesting**
   Replay public sample tick snapshots to test whether candidate signals would remain actionable under time, quote, and liquidity constraints.

5. **Execution-quality diagnostics**
   Analyze candidate signals, risk-gate filtering, attempted fills, realized fills, rejected signals, spread distribution, fill-rate buckets, and settlement outcomes.

6. **Probability calibration**
   Compare fair probabilities and market-implied probabilities with realized sample settlement outcomes using calibration-style diagnostics.

7. **Risk and Monte Carlo simulation**
   Use demonstration-only trade outcome samples to estimate drawdown, terminal PnL dispersion, and sensitivity to execution assumptions.

8. **ML-assisted signal filtering**
   Present ML as an optional signal-quality diagnostic layer. It is not framed as a guaranteed alpha model or standalone trading strategy.

See [`docs/methodology.md`](docs/methodology.md) for a fuller explanation.

## Reports and Figures

The repository includes sample-backed demonstration reports:

```text
reports/execution_quality_report.md
reports/probability_calibration_report.md
reports/risk_simulation_report.md
reports/ml_filter_report.md
```

Generated figures are stored in:

```text
reports/figures/
```

Current figure outputs include signal funnel, spread distribution, fill-rate buckets, calibration curve, and Monte Carlo risk visualizations. These are demonstration outputs generated from public sample data. They should not be read as complete historical performance results or production strategy validation.

## How to Run Demo Using uv

This project uses `uv` as the canonical environment and command runner. Dependencies are declared in `pyproject.toml` and locked in `uv.lock`. The repository intentionally does not maintain a `requirements.txt` workflow.

Set up the environment with demo and testing extras:

```bash
uv sync --extra dev --extra ml
```

Run the test suite:

```bash
PYTHONPATH=src uv run pytest
```

Run the public demo scripts:

```bash
PYTHONPATH=src uv run python scripts/run_execution_quality_report.py
PYTHONPATH=src uv run python scripts/run_probability_calibration_report.py
PYTHONPATH=src uv run python scripts/run_monte_carlo_simulation.py
PYTHONPATH=src uv run python scripts/run_ml_filter_demo.py
PYTHONPATH=src uv run python scripts/generate_report_figures.py
```

Optional tick replay demo:

```bash
PYTHONPATH=src uv run python scripts/run_tick_replay_backtest.py
```

Optional public sample regeneration from local private inputs:

```bash
PYTHONPATH=src uv run python scripts/prepare_public_sample_data.py
```

This command requires local private raw inputs that are excluded from the repository. Do not commit files under `private/`.

## Limitations

This repository is designed for transparent research demonstration. Important limitations include:

- Public samples are anonymized, downsampled, and normalized.
- Demonstration reports do not represent complete historical empirical performance.
- Backtests and tick replays are not equivalent to live execution.
- Fill assumptions may differ from actual venue behavior.
- Latency, quote staleness, and market-depth changes can materially alter realized outcomes.
- ML-assisted filtering can overfit and must be validated out of sample before any serious use.
- The project does not include wallet operations, signer logic, live taker execution, allowance maintenance, auto-claim logic, or production deployment instructions.

See [`docs/limitations.md`](docs/limitations.md) for more detail.

## Disclaimer

This project is for research, educational, and portfolio demonstration purposes only. It is not financial advice, trading advice, investment advice, or a recommendation to participate in any market.

The repository does not claim to provide a profitable strategy, does not claim to predict BTC, and does not provide a live trading or betting system. All public outputs should be interpreted as demonstration-only analysis built on public-safe sample data.
