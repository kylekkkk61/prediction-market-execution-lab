# Execution Quality Report

> This report is generated from anonymized public sample data. It is a reproducible demo report, not a claim about complete live performance.

## Sample coverage

| Dataset | Rows |
|---|---:|
| Candidate signals | 268 |
| Execution attempts | 1000 |
| Signal rejections | 1000 |
| Market settlements | 1000 |

## Execution funnel

- Accepted rate: **33.50%**
- Fill rate: **33.50%**

### Execution status breakdown

| Status | Count | Share |
|---|---:|---:|
| live_success | 335 | 33.50% |
| live_failed | 325 | 32.50% |
| blocked_exposure | 288 | 28.80% |
| blocked_order_cooldown | 35 | 3.50% |
| blocked_ml_filter | 17 | 1.70% |

## Rejection reason breakdown

| Reason | Count | Share |
|---|---:|---:|
| other | 643 | 64.30% |
| risk_limit | 357 | 35.70% |

## Edge decay

| Metric | Value |
|---|---:|
| Rows with edge fields | 0 |
| Average signal edge | n/a |
| Average edge after fill estimate | n/a |
| Average edge decay | n/a |

## Candidate timing distribution

| Time bucket | Count | Share |
|---|---:|---:|
| 180-210 | 55 | 20.52% |
| 210-240 | 41 | 15.30% |
| 240-270 | 39 | 14.55% |
| 270-300 | 34 | 12.69% |
| 150-180 | 32 | 11.94% |
| 120-150 | 21 | 7.84% |
| 60-90 | 18 | 6.72% |
| 90-120 | 17 | 6.34% |
| 30-60 | 9 | 3.36% |
| 0-30 | 2 | 0.75% |

## Settlement PnL summary

| Metric | Value |
|---|---:|
| Rows with normalized PnL | 1000 |
| Average normalized net PnL | -0.0001 |
| Minimum normalized net PnL | -0.0942 |
| Maximum normalized net PnL | 0.7876 |
| Positive normalized PnL rate | 37.70% |

## Interpretation note

These metrics are intended to demonstrate the analysis pipeline. The public sample is anonymized, downsampled, and field-filtered, so it should not be interpreted as full strategy performance.
