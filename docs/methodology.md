# Methodology

This document describes the public methodology used by Prediction Market Execution Lab. The workflow is designed for reproducible sample-backed diagnostics, not live execution or strategy deployment.

## 1. Market Price as Implied Probability

Prediction-market contract prices can be interpreted as market-implied probabilities, subject to liquidity, spread, fees, and market design constraints.

The project distinguishes between:

- quoted market prices
- executable prices
- model-estimated fair probabilities
- realized settlement outcomes

## 2. Fair Probability Model

The fair probability model estimates the probability of a short-horizon BTC outcome using reference-market features and remaining time to expiry.

The public implementation prioritizes clarity, reproducibility, and interpretability over strategy optimization.

## 3. Edge Definition

The project separates:

- **theoretical edge**: model fair probability compared with observed market price
- **executable edge**: remaining edge after spread, slippage, fill assumptions, and timing constraints

This distinction is central to the project.

## 4. Execution-Quality Analysis

Execution quality is evaluated using signal and execution-state funnels, such as:

```text
candidate signal
→ passed research filters
→ attempted execution or simulated fill
→ filled or not filled
→ settled outcome
→ attributed PnL or simulated result
```

The public workflow uses anonymized sample data where private execution records would otherwise be required.

## 5. Tick-Level Replay Backtesting

Tick-level replay evaluates whether a signal would still be actionable when replayed against historical market snapshots.

The goal is not to claim live performance, but to diagnose how market conditions affect signal viability.

## 6. PnL Attribution

PnL attribution decomposes outcomes by research dimensions such as:

- edge bucket
- spread bucket
- time-to-expiry bucket
- volatility regime
- fill quality
- side or market state

## 7. Probability Calibration

Calibration diagnostics compare model-estimated probabilities and market-implied probabilities with realized settlement outcomes.

The public report uses market-level joins over anonymized sample data and reports metrics such as Brier score, log loss, calibration buckets, and realized outcome rates.

## 8. ML-Assisted Filtering

Machine learning is treated as an optional signal-quality diagnostic layer.

The project avoids treating ML as a black-box alpha engine. Any ML component should include validation notes and overfitting limitations.

The public implementation uses anonymized sample execution records to demonstrate the validation workflow:

```text
public sample executions
→ numeric feature extraction
→ chronological train/test split
→ transparent baseline filter
→ pass/reject diagnostics
```

This demo is not evidence of production predictive performance or trading profitability. Its purpose is to show how signal filtering can be structured, validated, and documented without leaking private strategy details.

## 9. Risk Simulation

Monte Carlo and bootstrap-style simulations estimate drawdown, losing streaks, terminal PnL dispersion, and sensitivity to execution assumptions.

The public report uses normalized sample PnL values, not real account-level PnL.

## 10. Limitations

The methodology always distinguishes between backtested, simulated, anonymized, and live-observed evidence.

No public report should imply a reliable profit strategy unless supported by reproducible evidence.
