# Risk Simulation Report

This report is generated from anonymized public sample data only. All PnL values are normalized sample units, not real currency PnL, and should not be interpreted as live trading performance.

## Input

| Metric | Value |
|---|---:|
| Normalized PnL observations | 1000 |
| Monte Carlo simulations | 1000 |
| Path horizon | 1000 |
| Random seed | 42 |

## Final normalized PnL distribution

| Metric | Value |
|---|---:|
| Mean final PnL | -0.1079 |
| Median final PnL | -0.1077 |
| 5th percentile final PnL | -2.8020 |
| 95th percentile final PnL | 2.5592 |

## Drawdown and losing-streak diagnostics

| Metric | Value |
|---|---:|
| Mean max drawdown | 1.9296 |
| 95th percentile max drawdown | 3.4702 |
| Mean longest losing streak | 5.27 |
| 95th percentile longest losing streak | 7.00 |

## Interpretation limits

- This is a bootstrap diagnostic over public sample rows, not a complete account-level risk model.
- The sample is anonymized, downsampled, and normalized.
- Position sizing, real capital constraints, fees, and live fill dynamics are not reconstructed here.
- Use this report to inspect sample-path sensitivity, not to claim strategy profitability.
