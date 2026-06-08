# ML Filter Workflow Report

This report demonstrates a public-sample workflow for ML-assisted signal filtering.
It uses anonymized sample data and does not establish production predictive performance or trading profitability.

## Why add an ML filter

Prediction-market signals can look attractive on theoretical edge alone, but many fail because of fill probability, spread, timing, or execution-state constraints. The ML-filter workflow is included to test whether a filter can improve signal quality after accounting for those observable features. It is diagnostic, not an alpha claim.

## Data source

- Source: `data/sample/executions_sample.csv`
- Target label: public sample `filled` flag when available
- Split: chronological train/test split to avoid random look-ahead leakage
- Public-safe exported private-ledger fields: `ml_predicted_ev`, `ml_min_ev`, `ml_passed`, `ml_reason`, `fill_probability`, `fill_prob_min_probability`, `fill_prob_passed`, `fill_prob_reason`

## Features used by the public baseline

The public baseline uses only scalar, public-safe features that are already present in the anonymized sample. It does not load private feature JSON or production model artifacts.

| Feature | Interpretation |
|---|---|
| `signal_edge` | Estimated signal-time theoretical edge. |
| `signal_spread` | Bid-ask spread observed at signal time. |
| `signal_fair` | Model-estimated fair probability. |
| `limit_price` | Public-safe limit-price diagnostic field. |
| `fill_probability` | Public-safe fill-probability diagnostic. |
| `elapsed_seconds` | Timing feature from market start or sample clock. |

## Walk-forward validation setup

Rows are sorted chronologically. Thresholds are fitted on the earlier sample segment and then evaluated on the later segment. This prevents random train/test leakage and shows whether the filter generalizes to later public-sample rows.

## Baseline filter

The public demo uses a transparent learned-threshold baseline rather than a shipped production ML model.
Thresholds are fitted on the earlier sample segment and applied to the later segment.
No private model artifact, raw model score, or production threshold is loaded by this demo.

| Threshold | Value |
|---|---:|
| Minimum edge | 0.315899 |
| Maximum spread | 0.010000 |
| Minimum fill probability | 0.000000 |

## Before / after comparison

The table compares all labeled rows with rows that passed the public baseline filter. Positive rate uses the public `filled` label when available. This is a trade-quality proxy, not a profitability metric.

| Segment | Rows | Passed | Pass rate | Labeled rows | Positive rate all | Positive rate passed | Positive rate rejected |
|---|---:|---:|---:|---:|---:|---:|---:|
| Train | 700 | 281 | 40.14% | 700 | 8.14% | 12.81% | 5.01% |
| Test | 300 | 228 | 76.00% | 300 | 0.33% | 0.44% | 0.00% |

## What the public baseline shows

On the public test segment, the baseline improves the positive label rate: passed rows show 0.44% versus 0.33% overall.

This is useful as a validation example: a filter can be mechanically reasonable, yet fail to improve out-of-sample label quality on the public sample. That is why this project treats ML as a validation workflow, not as an alpha claim.

## Private-ledger decision diagnostics

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

## Does the filter improve PnL, drawdown, or trade quality?

The public baseline can be evaluated on fill-label quality through the chronological train/test split above. The exported private-ledger ML diagnostics can also show how often model and fill-probability decisions passed. However, this report does not make a causal PnL or drawdown claim from the ML filter because the public sample does not reconstruct full trade-level capital, fees, and account-level path dependency. Any PnL comparison by ML decision would be indicative only unless supported by stricter trade-level attribution.

## Overfitting and leakage limitations

- These diagnostics are based on anonymized public sample rows, not the full private ledger.
- The baseline is designed to demonstrate validation workflow, not to prove predictive edge.
- Public sample labels may be sparse or simplified after anonymization.
- The report does not replay the original private ML model or expose raw model scores.
- Chronological splitting reduces random look-ahead leakage but does not solve regime shift, feature drift, or label-quality problems.
- A production ML filter would require stricter walk-forward validation, feature-audit trails, leakage checks, and out-of-sample stress testing on private data.
