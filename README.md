# Prediction Market Execution Lab

**Testing Executable Edge in Polymarket BTC Short-Horizon Markets**

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square&logo=python&logoColor=white)](https://www.python.org/)
[![uv](https://img.shields.io/badge/env-uv-4B32C3?style=flat-square)](https://github.com/astral-sh/uv)
[![pytest](https://img.shields.io/badge/tests-pytest-green?style=flat-square)](https://docs.pytest.org/)
[![Ruff](https://img.shields.io/badge/lint-ruff-261230?style=flat-square)](https://docs.astral.sh/ruff/)
[![Streamlit](https://img.shields.io/badge/dashboard-Streamlit-FF4B4B?style=flat-square&logo=streamlit&logoColor=white)](https://streamlit.io/)
[![Status](https://img.shields.io/badge/status-research%20demo-lightgrey?style=flat-square)](#)

Prediction Market Execution Lab is a public FinTech / market microstructure research project that studies whether apparent prediction-market pricing edge can survive spread, fill probability, latency, order failure, model gates, and settlement outcomes.

This repository is **not** a trading bot, production execution system, or profitable strategy claim. It is a research portfolio project built around executable-edge analysis in Polymarket BTC short-horizon markets.

<div align="center">
  <img src="docs/assets/portfolio_page_overview.png" alt="Portfolio page overview" width="780">
</div>

## TL;DR

- **What I tested:** whether short-horizon Polymarket BTC pricing edge remains tradable after execution frictions.
- **What I found:** the public sample does not support a profitability claim; the strategy did not yet convert theoretical edge into reliable realized PnL.
- **Why it matters:** pure tick replay and simulated backtests can show positive edge, but live-like execution records become much weaker once failed order submission, latency, quote staleness, fill probability, model gates, and settlement outcomes are included.
- **Core contribution:** a public-safe research workflow for separating theoretical edge from executable edge.

## Key Findings

1. **Simulation-to-live gap is the central problem.**  
   Pure tick replay can show positive edge, but live-like ledger records gave a different answer after order-submission failure, latency, quote staleness, fill probability, model gates, and settlement outcomes were included.

2. **The bottleneck is the execution funnel, not only spread.**  
   Spread matters, but the larger issue is whether a signal survives acceptance, fill probability, ML EV filtering, order submission, and settlement.

3. **Extreme probability buckets are fragile.**  
   Very low and very high probability buckets are less stable in the public sample, especially around the final resolution window where small price changes can cause large binary-outcome errors.

4. **ML is an execution-quality gate, not a magic alpha model.**  
   The private workflow uses ML EV and fill-probability gates to improve candidate quality after edge detection. The public demo exports only safe scalar diagnostics and does not ship model artifacts or raw feature JSON.

5. **Risk is sparse and path-dependent.**  
   The public sample looks zero-inflated rather than like smooth edge capture: many markets produce no positive normalized PnL because the strategy often does not form a matched position.

## Explore the Project

| Artifact | Description |
|---|---|
| [Portfolio Page](https://pm-lab.kylekkkk.com/) | Static public portfolio landing page for the project. |
| [Live Dashboard](https://prediction-market-execution-lab-4byaayq2atzengbe26nkfb.streamlit.app/) | Streamlit dashboard for public-sample execution diagnostics. |
| [`reports/execution_quality_report.md`](reports/execution_quality_report.md) | Signal funnel, rejection reasons, edge before/after execution, settlement PnL, author takeaways. |
| [`reports/probability_calibration_report.md`](reports/probability_calibration_report.md) | Fair probability vs market-implied calibration, tail-bucket instability, Binance reference-price assumption. |
| [`reports/ml_filter_report.md`](reports/ml_filter_report.md) | ML EV gate, fill-probability diagnostics, walk-forward validation, overfitting limitations. |
| [`reports/risk_simulation_report.md`](reports/risk_simulation_report.md) | Monte Carlo terminal PnL, drawdown, losing-streak, and path-dependency diagnostics. |
| [`notebooks/`](notebooks/) | Six-notebook research walkthrough covering sample data, execution quality, reference price, calibration, ML diagnostics, and risk simulation. See the [`notebooks/README.md`](notebooks/README.md) guide. |
| [`docs/methodology.md`](docs/methodology.md) | Methodology details, fair probability formula, reference-price assumptions, gate sequence. |
| [`docs/limitations.md`](docs/limitations.md) | Scope limits, replay/live gap, reference-lag assumption, ML/filter caveats. |

## Visual Summary

<table align="center">
  <tr>
    <td align="center">
      <img src="reports/figures/signal_funnel.png" alt="Signal funnel" width="360"><br>
      <em>Execution funnel: where theoretical edge is lost before filled exposure.</em>
    </td>
    <td align="center">
      <img src="reports/figures/execution_status_breakdown.png" alt="Execution status breakdown" width="360"><br>
      <em>Status breakdown: how public-sample attempts split across execution states.</em>
    </td>
  </tr>
</table>

## Dashboard Preview

The live dashboard provides an interactive public-sample walkthrough for execution-quality diagnostics, ML/filter checks, report previews, and sample tables.

<div align="center">
  <img src="docs/assets/dashboard_demo.gif" alt="Dashboard demo preview" width="780">
</div>

## Research Question

> Can apparent short-horizon prediction-market pricing edges survive real execution frictions such as bid-ask spread, slippage, fill probability, latency, position limits, and settlement outcomes?

The project separates two concepts:

- **Theoretical edge:** the difference between a fair probability estimate and a market-implied probability.
- **Executable edge:** the portion of that edge that remains after execution frictions and settlement outcomes are incorporated.

## Why Prediction Markets

Prediction-market prices can be interpreted as market-implied probabilities. That makes them useful for studying the gap between estimated fair probability and executable trading outcomes.

Short-horizon BTC markets are especially useful because they combine:

- rapidly changing reference prices
- discrete binary settlement outcomes
- CLOB-style bid-ask dynamics
- time-to-resolution effects
- liquidity and fill constraints
- final-window reversal risk

The fair-probability workflow uses Binance BTCUSDT spot ticks as the faster reference layer and Binance-derived bucket open prices as the opening-anchor proxy. Polymarket BTC markets settle against an oracle-style reference rather than Binance directly. My working assumption, consistent with common player observations in these markets, is that the resolution-linked reference tends to follow Binance-style spot movement with a short delay. This repository does not yet include a dedicated lead-lag validation study, so the lag is treated as a domain-informed assumption rather than a proven empirical claim.

## Methodology Snapshot

```text
public sample data
→ fair probability and market-implied probability analysis
→ candidate edge calculation
→ tick replay and execution-quality diagnostics
→ ML EV / fill-probability gate diagnostics
→ sample-backed reports and figures
→ Monte Carlo risk simulation
→ Streamlit dashboard
```

Main components:

- **Fair probability modeling:** estimate outcome probability from Binance-style reference price movement, volatility, and time to resolution.
- **Executable edge calculation:** adjust apparent edge for spread, slippage, fill probability, and execution assumptions.
- **Tick-level replay:** test whether signals remain actionable under historical quote snapshots.
- **Execution-quality diagnostics:** analyze candidate signals, rejected signals, fills, latency, edge decay, and settlement outcomes.
- **Probability calibration:** compare fair and market-implied probabilities with realized outcomes.
- **ML-assisted filtering workflow:** evaluate public-safe ML EV and fill-probability diagnostics without exposing model artifacts.
- **Risk simulation:** bootstrap normalized public-sample outcomes to inspect terminal PnL, drawdown, and path dependency.

See [`docs/methodology.md`](docs/methodology.md) for the full methodology.

## Skills Demonstrated

- **Market microstructure reasoning:** separate theoretical pricing edge from executable exposure.
- **Probability modeling:** estimate fair probability and compare it with market-implied probability.
- **Execution-quality diagnostics:** analyze spread, fill probability, latency, rejected orders, failed fills, and settlement outcomes.
- **Backtesting discipline:** compare positive tick-replay results with weaker live-like execution records.
- **ML evaluation:** use ML EV and fill-probability gates as signal-quality filters rather than profit guarantees.
- **Risk analysis:** use Monte Carlo simulation to inspect sparse, path-dependent PnL outcomes.
- **Public-safe research engineering:** convert private trading experiments into anonymized reports, notebooks, dashboards, and portfolio artifacts.

## Tech Stack

| Area | Tools / Methods |
|---|---|
| Language | Python 3.11+ |
| Environment | `uv`, `pyproject.toml`, `uv.lock` |
| Data workflow | pandas, NumPy, public-safe anonymized CSV samples |
| Probability modeling | fair probability model, implied probability handling, calibration diagnostics |
| Backtesting | tick-level replay, execution-quality simulation |
| ML diagnostics | public-safe ML EV gate, fill-probability gate, chronological validation workflow |
| Risk | Monte Carlo / bootstrap simulation, drawdown and losing-streak diagnostics |
| Visualization | matplotlib report figures, Streamlit dashboard |
| Quality | pytest, ruff |

## Data and Sample Policy

Private raw ledger data, raw tick snapshots, wallet identifiers, order IDs, signer logic, allowance logic, deployment details, live execution runbooks, raw model artifacts, and feature JSON are intentionally excluded from the public workflow.

Public sample files under [`data/sample/`](data/sample/) are:

- anonymized
- downsampled
- normalized where needed
- small enough for review and deterministic demo runs
- intended for reproducible demonstrations, not full historical analysis

Public sample files:

```text
data/sample/candidates_sample.csv
data/sample/executions_sample.csv
data/sample/rejections_sample.csv
data/sample/settlements_sample.csv
data/sample/tick_snapshots_sample.csv
```

The sample-generation policy is documented in [`docs/data_preparation.md`](docs/data_preparation.md), and the sample schema is documented in [`docs/sample_data_schema.md`](docs/sample_data_schema.md).

## Quickstart

Install the environment, run tests, and launch the public-sample dashboard:

```bash
uv sync --extra dev --extra notebook --extra dashboard --extra ml
PYTHONPATH=src uv run pytest
PYTHONPATH=src uv run streamlit run dashboard/app.py
```

The dashboard reads only public sample files and generated report artifacts from the repository. It does not connect to live markets, private ledgers, wallets, signers, or execution APIs.

<details>
<summary>Regenerate reports and figures</summary>

```bash
PYTHONPATH=src uv run python scripts/run_execution_quality_report.py
PYTHONPATH=src uv run python scripts/run_probability_calibration_report.py
PYTHONPATH=src uv run python scripts/run_monte_carlo_simulation.py
PYTHONPATH=src uv run python scripts/run_ml_filter_demo.py
PYTHONPATH=src uv run python scripts/generate_report_figures.py
```

</details>

<details>
<summary>Run optional demos and local sample preparation</summary>

Optional tick replay demo:

```bash
PYTHONPATH=src uv run python scripts/run_tick_replay_backtest.py
```

Optional public sample regeneration from local private inputs:

```bash
PYTHONPATH=src uv run python scripts/prepare_public_sample_data.py
```

Sample regeneration requires local private raw inputs that are excluded from the repository. Do not commit files under `private/`.

</details>

## Repository Structure

```text
prediction-market-execution-lab/
├── data/sample/                  # Public-safe anonymized and downsampled demo datasets
├── docs/                         # Project brief, methodology, architecture, limitations, data notes
├── reports/                      # Demonstration reports and generated figures
├── scripts/                      # Demo-safe report, figure, sample, and simulation runners
├── src/                          # Public research modules
│   ├── backtesting/              # Tick-level replay logic
│   ├── data_sources/             # Public sample loading and local source-inspection helpers
│   ├── execution_quality/        # Edge and fill-quality calculations
│   ├── models/                   # Fair probability, calibration, and ML-filter demos
│   ├── risk/                     # Monte Carlo risk simulation
│   └── utils/                    # Anonymization and shared utilities
├── tests/                        # Unit tests for public-safe modules and scripts
├── dashboard/                    # Streamlit public-sample demo dashboard
├── pyproject.toml                # Project metadata and dependencies
└── uv.lock                       # Locked environment
```

## Limitations

This repository is designed for transparent research demonstration. Important limitations include:

- Public samples are anonymized, downsampled, and normalized.
- Demonstration reports do not represent complete historical empirical performance.
- Backtests and tick replays are not equivalent to live execution.
- Fill assumptions may differ from actual venue behavior.
- Latency, quote staleness, market-depth changes, and order-submission failure can materially alter realized outcomes.
- ML-assisted filtering can overfit and must be validated out of sample before any serious use.
- The project does not include wallet operations, signer logic, live taker execution, allowance maintenance, auto-claim logic, or production deployment instructions.

See [`docs/limitations.md`](docs/limitations.md) for more detail.

## Disclaimer

This project is for research, educational, and portfolio demonstration purposes only. It is not financial advice, trading advice, investment advice, or a recommendation to participate in any market.

The repository does not claim to provide a profitable strategy, does not claim to predict BTC, and does not provide a live trading or betting system. All public outputs should be interpreted as demonstration-only analysis built on public-safe sample data.
