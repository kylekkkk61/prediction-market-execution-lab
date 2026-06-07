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

![Monte Carlo terminal PnL distribution](figures/monte_carlo_terminal_pnl.png)

| Metric | Value |
|---|---:|
| Mean final PnL | -1.3117 |
| Median final PnL | -1.3404 |
| 5th percentile final PnL | -5.4459 |
| 95th percentile final PnL | 2.8680 |

## Drawdown and losing-streak diagnostics

![Monte Carlo drawdown distribution](figures/monte_carlo_drawdown.png)

| Metric | Value |
|---|---:|
| Mean max drawdown | 3.6700 |
| 95th percentile max drawdown | 6.4877 |
| Mean longest losing streak | 3.87 |
| 95th percentile longest losing streak | 5.00 |

## Interpretation limits

- This is a bootstrap diagnostic over public sample rows, not a complete account-level risk model.
- The sample is anonymized, downsampled, and normalized.
- Position sizing, real capital constraints, fees, and live fill dynamics are not reconstructed here.
- Use this report to inspect sample-path sensitivity, not to claim strategy profitability.
