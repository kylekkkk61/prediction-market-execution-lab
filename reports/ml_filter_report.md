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
| Minimum edge | 0.283833 |
| Maximum spread | 0.010000 |
| Minimum fill probability | 0.000000 |

## Diagnostics

| Segment | Rows | Passed | Pass rate | Labeled rows | Positive rate all | Positive rate passed | Positive rate rejected |
|---|---:|---:|---:|---:|---:|---:|---:|
| Train | 700 | 281 | 40.14% | 700 | 32.43% | 22.42% | 39.14% |
| Test | 300 | 163 | 54.33% | 300 | 36.00% | 26.38% | 47.45% |

## What the public baseline shows

On the public test segment, the baseline does not improve the positive label rate: passed rows show 26.38% versus 36.00% overall.

This is useful as a validation example: a filter can be mechanically reasonable, yet fail to improve out-of-sample label quality on the public sample. That is why this project treats ML as a validation workflow, not as an alpha claim.

## Interpretation limits

- These diagnostics are based on anonymized public sample rows, not the full private ledger.
- The baseline is designed to demonstrate validation workflow, not to prove predictive edge.
- Public sample labels may be sparse or simplified after anonymization.
- The report does not replay the original private ML model or expose raw model scores.
- A future extension can add true ML score and decision diagnostics if fields such as `ml_score`, `ml_passed`, or `blocked_ml_filter` can be safely anonymized and bucketed.
