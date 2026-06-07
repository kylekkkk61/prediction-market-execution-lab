# Methodology

This document describes the planned public methodology. The implementation will be extracted gradually from the legacy working codebase into clean, documented research modules.

## 1. Market Price as Implied Probability

Prediction-market contract prices can be interpreted as market-implied probabilities, subject to liquidity, spread, fees, and market design constraints.

The project distinguishes between:

- quoted market prices
- executable prices
- model-estimated fair probabilities
- realized settlement outcomes

## 2. Fair Probability Model

The public version will expose a simplified fair probability model for short-horizon BTC outcome markets.

The model is intended to estimate a fair probability using reference BTC market data and remaining time to expiry. The first public version will prioritize clarity and reproducibility over strategy optimization.

## 3. Edge Definition

The project separates:

- **theoretical edge**: model fair probability compared with observed market price
- **executable edge**: remaining edge after spread, slippage, fill assumptions, and timing constraints

This distinction is central to the project.

## 4. Execution-Quality Analysis

Execution quality will be evaluated using signal and execution-state funnels, such as:

```text
candidate signal
→ passed research filters
→ attempted execution or simulated fill
→ filled or not filled
→ settled outcome
→ attributed PnL or simulated result
```

The public version will use sample or anonymized data where needed.

## 5. Tick-Level Replay Backtesting

Tick-level replay is used to evaluate whether a signal would still be actionable when replayed against historical market snapshots.

The goal is not to claim live performance, but to diagnose how market conditions affect signal viability.

## 6. PnL Attribution

PnL attribution will decompose outcomes by research dimensions such as:

- edge bucket
- spread bucket
- time-to-expiry bucket
- volatility regime
- fill quality
- side or market state

## 7. ML-Assisted Filtering

Machine learning may be used as an optional signal-quality diagnostic layer.

The public project will avoid treating ML as a black-box alpha engine. Any ML component should include validation notes and overfitting limitations.

## 8. Risk Simulation

Monte Carlo and bootstrap-style simulations may be used to estimate drawdown, losing streaks, and sensitivity to execution assumptions.

## 9. Limitations

The methodology should always distinguish between backtested, simulated, anonymized, and live-observed evidence.

No public report should imply a reliable profit strategy unless supported by reproducible evidence.
