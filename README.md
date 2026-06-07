# Prediction Market Execution Lab

**Testing Executable Edge in Polymarket BTC Short-Horizon Markets**

This repository is being reorganized into a public research-oriented FinTech project about prediction-market microstructure and execution quality.

The core question is:

> When a short-horizon prediction market appears to offer a pricing edge, how much of that edge remains after accounting for bid-ask spread, slippage, fill probability, latency, position limits, and settlement outcomes?

This project uses Polymarket BTC short-horizon markets as a case study, but the public version is framed as a market-data and execution-quality research lab rather than an automated trading system.

## Project Status

This repository is currently in the migration stage.

The original private working codebase contained live-operation scripts, research scripts, backtesting utilities, model artifacts, and post-trade analysis tools. The public version is being rebuilt gradually so that only research, analytics, backtesting, reporting, and demo-safe components remain.

Current status:

- Public project framing is in progress.
- Legacy scripts are still present as migration references.
- Public `src/` modules have not yet been extracted.
- Reports, notebooks, figures, and dashboard components are planned but not yet complete.
- No performance claims or production trading claims are made in the public version.

## What This Project Is About

The project focuses on the difference between theoretical edge and executable edge.

A model may estimate that a prediction-market contract is mispriced. However, that apparent mispricing may disappear once the analysis accounts for market microstructure frictions such as:

- bid-ask spread
- available depth
- slippage
- fill probability
- timing and latency
- position limits
- settlement results

The goal is to build a reproducible research workflow that can diagnose where apparent edge is created, filtered, executed, or lost.

## Planned Public Components

The public version is planned to include:

```text
src/
├── data_sources/
├── models/
├── execution_quality/
├── backtesting/
├── risk/
└── utils/

docs/
├── project_brief.md
├── methodology.md
├── architecture.md
├── limitations.md
└── public_migration_plan.md

reports/
├── execution_quality_report.md
└── figures/

notebooks/
dashboard/
data/sample/
scripts/
tests/
```

## Planned Analysis Areas

1. **Fair Probability Modeling**  
   Estimate a fair probability for short-horizon BTC outcome markets using reference market data.

2. **Executable Edge Analysis**  
   Compare theoretical edge with executable edge after spread, slippage, and fill assumptions.

3. **Execution-Quality Diagnostics**  
   Analyze candidate signals, rejected signals, attempted fills, realized fills, and settlement outcomes.

4. **Tick-Level Replay Backtesting**  
   Replay market snapshots to evaluate whether a signal would have remained actionable under realistic timing and liquidity assumptions.

5. **PnL Attribution**  
   Decompose outcomes by signal quality, spread, timing bucket, volatility regime, and execution quality.

6. **ML-Assisted Signal Filtering**  
   Use machine-learning filters only as optional diagnostics, not as the primary project narrative.

7. **Risk and Monte Carlo Simulation**  
   Analyze drawdown, losing streaks, and sensitivity to execution assumptions.

## Repository Migration Plan

See [`docs/public_migration_plan.md`](docs/public_migration_plan.md) for the current migration sequence.

The key principle is:

> Preserve legacy code as a reference first, extract public research modules second, and remove private operation files only near public release.

## Disclaimer

This project is for research, educational, and portfolio demonstration purposes only. It is not financial advice, trading advice, or a recommendation to participate in any market.

The public version intentionally avoids exposing wallet operations, private keys, production deployment details, live execution runbooks, or private trading records.
