# Methodology

This document describes the public methodology used by Prediction Market Execution Lab. The workflow is designed for reproducible sample-backed diagnostics, not live execution or strategy deployment.

## 1. Market Price as Implied Probability

Prediction-market contract prices can be interpreted as market-implied probabilities, subject to liquidity, spread, fees, and market design constraints.

The project distinguishes between:

- quoted market prices
- executable prices
- model-estimated fair probabilities
- realized settlement outcomes

## 2. Reference Price Assumption

The fair-probability workflow uses Binance BTCUSDT spot ticks as the faster reference layer and Binance-derived bucket open prices as the opening-anchor proxy. Polymarket BTC markets settle against an oracle-style reference rather than Binance directly. The research motivation is that centralized exchange prices can update faster than prediction-market quotes and resolution-linked reference mechanisms.

This assumption is used to build fair probability and replay diagnostics. It reflects a common player-observed reference-lag hypothesis in these markets, but this repository does not yet include a dedicated lead-lag validation study.

The simplified fair-probability form is:

```text
Fair_yes = Phi(max(min(ln(p_now / p_open) / (sigma_eff * sqrt(tau)), Z_CAP), -Z_CAP))
```

where `p_now` is the Binance BTCUSDT spot tick proxy, `p_open` is the Binance-derived opening anchor proxy, `sigma_eff` is the effective volatility input, and `tau` is time to resolution.

## 3. Fair Probability Model

The fair probability model estimates the probability of a short-horizon BTC outcome using reference-market features and remaining time to expiry.

The public implementation prioritizes clarity, reproducibility, and interpretability over strategy optimization.

## 4. Edge Definition

The project separates:

- **theoretical edge**: model fair probability compared with observed market price
- **executable edge**: remaining edge after spread, slippage, fill assumptions, and timing constraints

This distinction is central to the project.

## 5. Execution-Quality Analysis

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

## 6. Tick-Level Replay Backtesting

Tick-level replay evaluates whether a signal would still be actionable when replayed against historical market snapshots.

The goal is not to claim live performance, but to diagnose how market conditions affect signal viability.

## 7. PnL Attribution

PnL attribution decomposes outcomes by research dimensions such as:

- edge bucket
- spread bucket
- time-to-expiry bucket
- volatility regime
- fill quality
- side or market state

## 8. Probability Calibration

Calibration diagnostics compare model-estimated probabilities and market-implied probabilities with realized settlement outcomes.

The public report uses market-level joins over anonymized sample data and reports metrics such as Brier score, log loss, calibration buckets, and realized outcome rates.

## 9. ML-Assisted Filtering Workflow

Machine learning is treated as an optional signal-quality diagnostic layer, not as a black-box alpha engine.

The current public implementation does not ship or load a production ML model artifact. It uses anonymized sample execution records to demonstrate the validation workflow with a transparent learned-threshold baseline:

```text
public sample executions
→ numeric feature extraction
→ chronological train/test split
→ learned threshold baseline
→ pass/reject diagnostics
```

The private workflow uses a gate sequence of `edge gate → fill probability threshold → ML EV filter → order submission`. The fill-probability threshold and ML EV filter are configurable gates that can be enabled, disabled, or run with different threshold values across the sample period. As a result, the seven-day public sample may contain rows produced under different gate states and parameter settings. `ml_predicted_ev` is interpreted as expected PnL per USD, and `ml_min_ev` is the minimum EV threshold for allowing a candidate to proceed. The public sample includes safe scalar decision diagnostics such as `ml_predicted_ev`, `ml_min_ev`, `ml_passed`, `ml_reason`, `fill_probability`, and `fill_prob_passed`, while excluding model paths, feature-name lists, raw feature JSON, raw responses, order IDs, wallet identifiers, and signer/deployment details.

This demo is not evidence of production predictive performance or trading profitability. It should be read as a validation workflow and execution-quality gate analysis.

## 10. Risk Simulation

Monte Carlo and bootstrap-style simulations estimate drawdown, losing streaks, terminal PnL dispersion, and sensitivity to execution assumptions.

The public report uses normalized sample PnL values, not real account-level PnL.

## 11. Limitations

The methodology always distinguishes between backtested, simulated, anonymized, and live-observed evidence. A central project goal is to study the gap between positive tick-replay results and weaker live-like ledger outcomes after failed order submission, latency, quote staleness, fill probability, and execution gates are included.

No public report should imply a reliable profit strategy unless supported by reproducible evidence.
