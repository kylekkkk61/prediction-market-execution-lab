# ML Filter Methodology Report

This report demonstrates a public-sample workflow for ML-assisted signal filtering.
It uses anonymized sample data and does not establish production predictive performance or trading profitability.

## Data source

- Source: `data/sample/executions_sample.csv`
- Target label: public sample `filled` flag when available
- Split: chronological train/test split to avoid random look-ahead leakage

## Baseline filter

The demo uses a transparent threshold-based baseline rather than a production model.
Thresholds are fitted on the earlier sample segment and applied to the later segment.

| Threshold | Value |
|---|---:|
| Minimum edge | 0.283833 |
| Maximum spread | 0.010000 |
| Minimum fill probability | 0.000000 |

## Diagnostics

| Segment | Rows | Passed | Pass rate | Labeled rows | Positive rate all | Positive rate passed | Positive rate rejected |
|---|---:|---:|---:|---:|---:|---:|---:|
| Train | 700 | 281 | 40.14% | 700 | 32.43% | 22.42% | 39.14% |
| Test | 300 | 163 | 54.33% | 300 | 36.00% | 26.38% | 47.45% |

## Interpretation limits

- These diagnostics are based on anonymized public sample rows, not the full private ledger.
- The baseline is designed to demonstrate validation workflow, not to prove predictive edge.
- Public sample labels may be sparse or simplified after anonymization.
- A production ML filter would require stricter walk-forward validation, richer feature audits, and leakage checks on private data.
