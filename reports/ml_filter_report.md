# ML Filter Workflow Report

This report demonstrates a public-sample workflow for ML-assisted signal filtering.
It uses anonymized sample data and does not establish production predictive performance or trading profitability.

## Data source

- Source: `data/sample/executions_sample.csv`
- Target label: public sample `filled` flag when available
- Split: chronological train/test split to avoid random look-ahead leakage

## Baseline filter

The public demo uses a transparent learned-threshold baseline rather than a shipped production ML model.
Thresholds are fitted on the earlier sample segment and applied to the later segment.
No private model artifact, raw model score, or production threshold is loaded by this demo.

| Threshold | Value |
|---|---:|
| Minimum edge | 0.315899 |
| Maximum spread | 0.010000 |
| Minimum fill probability | 0.000000 |

## Diagnostics

| Segment | Rows | Passed | Pass rate | Labeled rows | Positive rate all | Positive rate passed | Positive rate rejected |
|---|---:|---:|---:|---:|---:|---:|---:|
| Train | 700 | 281 | 40.14% | 700 | 8.14% | 12.81% | 5.01% |
| Test | 300 | 228 | 76.00% | 300 | 0.33% | 0.44% | 0.00% |

## What the public baseline shows

On the public test segment, the baseline improves the positive label rate: passed rows show 0.44% versus 0.33% overall.

This is useful as a validation example: a filter can be mechanically reasonable, yet fail to improve out-of-sample label quality on the public sample. That is why this project treats ML as a validation workflow, not as an alpha claim.

## Exported private-ledger ML diagnostics

The current public sample includes anonymized ML and fill-probability decision fields exported from the private ledger. It keeps only safe scalar diagnostics and coarse reasons; it does not export model paths, feature lists, raw feature JSON, wallet/order identifiers, or raw responses.

| Metric | Value |
|---|---:|
| Rows inspected | 1000 |
| ML filter enabled rows | 1000 |
| Rows with ML predicted EV | 1000 |
| ML passed rows | 148 |
| ML pass rate | 14.80% |
| Avg ML predicted EV | 0.127598 |
| Avg ML minimum EV threshold | 0.279550 |
| Rows with fill probability | 268 |
| Fill-probability passed rows | 0 |
| Fill-probability pass rate | 0.00% |
| Avg fill probability | 0.309949 |
| Avg fill-probability threshold | 0.750000 |

### ML rejection reasons

| Reason | Count |
|---|---:|
| predicted_ev_below_threshold | 209 |

### Fill-probability rejection reasons

| Reason | Count |
|---|---:|
| predicted_ev_below_threshold | 268 |

## Interpretation limits

- These diagnostics are based on anonymized public sample rows, not the full private ledger.
- The baseline is designed to demonstrate validation workflow, not to prove predictive edge.
- Public sample labels may be sparse or simplified after anonymization.
- The report does not replay the original private ML model or expose raw model scores.
- A future extension can add true ML score and decision diagnostics if fields such as `ml_score`, `ml_passed`, or `blocked_ml_filter` can be safely anonymized and bucketed.
