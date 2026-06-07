# Prediction Market Execution Lab

**Testing Executable Edge in Polymarket BTC Short-Horizon Markets**

This repository is being refactored from a private research prototype into a public-facing FinTech research project.

The central question is:

> Do apparent short-horizon prediction-market pricing edges survive real execution frictions such as bid-ask spread, slippage, fill probability, latency, position limits, and settlement outcomes?

The project focuses on prediction-market microstructure, fair probability modeling, executable edge analysis, execution-quality diagnostics, tick-level replay backtesting, PnL attribution, ML-assisted signal filtering, and risk simulation.

## Project Status

This repository is currently in an early public-research scaffold stage.

Existing private prototype code is being reviewed, simplified, and migrated into a cleaner structure suitable for public demonstration. Current documentation and modules should be treated as planned work or scaffolding unless a report, notebook, or script explicitly states that it is complete.

## What This Project Is Not

This repository is not positioned as:

- an automated betting system,
- a stable-profit trading strategy,
- a live taker execution tool,
- a wallet, signer, allowance, or deployment runbook,
- financial, investment, or trading advice.

Public code and documentation will avoid exposing private keys, wallet details, live execution infrastructure, private ledgers, or strategy-sensitive parameters.

## Research Scope

The initial research scope is Polymarket BTC short-horizon markets, using external BTC reference prices and prediction-market quote data to study the gap between theoretical edge and executable edge.

Planned analysis areas:

1. **Fair probability modeling**  
   Estimate fair UP / DOWN probabilities from BTC reference prices and time-to-expiry features.

2. **Executable edge analysis**  
   Compare model-implied fair probabilities with observed prediction-market prices after accounting for transaction frictions.

3. **Execution-quality diagnostics**  
   Study how spread, liquidity, latency, no-fill outcomes, and position limits affect theoretical opportunities.

4. **Tick-level replay backtesting**  
   Replay historical quote snapshots to test whether rules remain robust under market microstructure constraints.

5. **PnL attribution and risk simulation**  
   Attribute outcomes by timing, spread, edge bucket, and signal type; use simulation to evaluate drawdown and path risk.

6. **ML-assisted filtering**  
   Explore whether a lightweight model can improve signal quality, while treating overfitting risk explicitly.

## Planned Repository Structure

```text
prediction-market-execution-lab/
├── README.md
├── docs/
│   ├── project_brief.md
│   ├── methodology.md
│   ├── architecture.md
│   └── limitations.md
├── src/
│   ├── data_sources/
│   ├── models/
│   ├── execution_quality/
│   ├── backtesting/
│   ├── risk/
│   └── utils/
├── scripts/
├── notebooks/
├── reports/
│   └── figures/
├── data/
│   └── sample/
├── dashboard/
├── tests/
├── .env.example
└── pyproject.toml
```

## Planned Outputs

- Public project brief
- Methodology document
- Architecture notes and system diagram
- Execution-quality report
- Probability-calibration report
- Sample-data schema
- Reproducible notebooks
- Optional Streamlit dashboard
- CV and LinkedIn-ready project summary

## Disclaimer

This project is for research, education, and portfolio demonstration only. It does not provide financial advice, trading advice, investment recommendations, or instructions for live market participation.
