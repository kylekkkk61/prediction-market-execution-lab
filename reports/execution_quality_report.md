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

## Grouped execution diagnostics

These grouped metrics are calculated on anonymized execution-attempt samples and are intended to diagnose execution quality by observable sample features.

### By side

| Group | Rows | Accepted rate | Fill rate | Avg signal edge | Avg spread | Avg latency ms |
|---|---:|---:|---:|---:|---:|---:|
| UP | 586 | 34.30% | 34.30% | 0.3249 | 0.0105 | 1184.4 |
| DOWN | 414 | 32.37% | 32.37% | 0.3155 | 0.0105 | 1573.1 |

### By time bucket

| Group | Rows | Accepted rate | Fill rate | Avg signal edge | Avg spread | Avg latency ms |
|---|---:|---:|---:|---:|---:|---:|
| 270-300 | 208 | 34.13% | 34.13% | 0.4233 | 0.0111 | 498.9 |
| 240-270 | 170 | 34.12% | 34.12% | 0.3507 | 0.0108 | 911.1 |
| 210-240 | 151 | 23.18% | 23.18% | 0.2960 | 0.0103 | 1610.2 |
| 180-210 | 101 | 34.65% | 34.65% | 0.2826 | 0.0106 | 1651.9 |
| 120-150 | 99 | 44.44% | 44.44% | 0.2745 | 0.0101 | 1334.4 |
| 150-180 | 99 | 29.29% | 29.29% | 0.2737 | 0.0103 | 1755.8 |
| 90-120 | 66 | 50.00% | 50.00% | 0.2607 | 0.0103 | 1158.1 |
| 60-90 | 49 | 38.78% | 38.78% | 0.2629 | 0.0100 | 1842.0 |
| 30-60 | 47 | 23.40% | 23.40% | 0.2770 | 0.0102 | 2266.0 |
| 0-30 | 10 | 0.00% | 0.00% | 0.2748 | 0.0100 | 3642.6 |

### By signal edge bucket

| Group | Rows | Accepted rate | Fill rate | Avg signal edge | Avg spread | Avg latency ms |
|---|---:|---:|---:|---:|---:|---:|
| 0.25-0.35 | 555 | 34.59% | 34.59% | 0.2832 | 0.0104 | 1483.4 |
| <0.25 | 225 | 43.11% | 43.11% | 0.2444 | 0.0104 | 1247.1 |
| 0.35-0.50 | 135 | 21.48% | 21.48% | 0.4169 | 0.0110 | 1255.4 |
| >=0.50 | 85 | 20.00% | 20.00% | 0.6181 | 0.0109 | 964.5 |

### By spread bucket

| Group | Rows | Accepted rate | Fill rate | Avg signal edge | Avg spread | Avg latency ms |
|---|---:|---:|---:|---:|---:|---:|
| <=0.01 | 946 | 33.30% | 33.30% | 0.3187 | 0.0100 | 1381.7 |
| 0.01-0.02 | 54 | 37.04% | 37.04% | 0.3607 | 0.0200 | 1180.9 |

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
