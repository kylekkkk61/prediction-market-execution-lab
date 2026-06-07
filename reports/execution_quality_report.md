# Execution Quality Report

> This report is generated from anonymized public sample data. It is a reproducible demo report, not a claim about complete live performance.

## Sample coverage

| Dataset | Rows |
|---|---:|
| Candidate signals | 100 |
| Execution attempts | 100 |
| Signal rejections | 100 |
| Market settlements | 100 |

## Execution funnel

- Accepted rate: **31.00%**
- Fill rate: **31.00%**

### Execution status breakdown

| Status | Count | Share |
|---|---:|---:|
| blocked_exposure | 33 | 33.00% |
| live_failed | 32 | 32.00% |
| live_success | 31 | 31.00% |
| blocked_order_cooldown | 4 | 4.00% |

## Rejection reason breakdown

| Reason | Count | Share |
|---|---:|---:|
| other | 83 | 83.00% |
| risk_limit | 17 | 17.00% |

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
| 270-300 | 22 | 22.00% |
| 150-180 | 17 | 17.00% |
| 240-270 | 16 | 16.00% |
| 120-150 | 9 | 9.00% |
| 210-240 | 9 | 9.00% |
| 180-210 | 8 | 8.00% |
| 90-120 | 8 | 8.00% |
| 60-90 | 5 | 5.00% |
| 30-60 | 5 | 5.00% |
| 0-30 | 1 | 1.00% |

## Settlement PnL summary

| Metric | Value |
|---|---:|
| Rows with normalized PnL | 100 |
| Average normalized net PnL | 0.0029 |
| Minimum normalized net PnL | -0.0938 |
| Maximum normalized net PnL | 0.2664 |
| Positive normalized PnL rate | 39.00% |

## Interpretation note

These metrics are intended to demonstrate the analysis pipeline. The public sample is anonymized, downsampled, and field-filtered, so it should not be interpreted as full strategy performance.
