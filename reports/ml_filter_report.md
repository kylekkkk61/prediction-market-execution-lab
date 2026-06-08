# ML Filter Workflow Report

This report demonstrates a public-sample workflow for ML-assisted signal filtering.
It uses anonymized sample data and does not establish production predictive performance or trading profitability.

## Why add an ML filter

Prediction-market signals can look attractive on theoretical edge alone, but many fail because of fill probability, spread, timing, or execution-state constraints. The ML filter was introduced as a post-edge EV gate: after a candidate passed edge and fill-probability checks, the model estimated expected PnL per USD and blocked trades below the minimum EV threshold. It is diagnostic, not an alpha claim.

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
| `remaining_seconds` | Time remaining until resolution when available in private features. |
| `bn_price` / `bn_open_price` | Binance BTCUSDT spot and opening-anchor proxy features used in the private workflow. |
| volatility / `sigma_*` / `z` | Volatility and standardized-distance features from the fair probability model. |
| order-book costs | Side cost, opposite cost, and total-cost style features when available. |
| rolling quality metrics | Rolling ROI and win-rate style features from private ledger replay. |

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

The current public sample includes anonymized ML and fill-probability decision fields exported from the private ledger. `ml_predicted_ev` represents expected PnL per USD under the private workflow, while `ml_min_ev` is the decision threshold. The export keeps only safe scalar diagnostics and coarse reasons; it does not export model paths, feature lists, raw feature JSON, wallet/order identifiers, or raw responses.

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

## Author takeaway

I do not read the ML filter as a replacement for the fair probability model. Its role is to decide whether a theoretical candidate deserves to become an executable candidate. In longer private ledger replay, this post-edge EV gate appeared to improve trade quality, but the public seven-day sample is too small and too filtered to claim a stable PnL effect.

## Does the filter improve PnL, drawdown, or trade quality?

The public baseline can be evaluated on fill-label quality through the chronological train/test split above. The exported private-ledger ML diagnostics can also show how often model and fill-probability decisions passed. In my private full backtests and live-ledger replay, the ML EV filter improved the strategy relative to running the edge logic without that gate. However, the selected seven-day public sample cannot fully reproduce that improvement because it does not reconstruct full trade-level capital, fees, account-level path dependency, or the broader parameter history. Any PnL comparison by ML decision in this public report should therefore be treated as indicative rather than causal proof.

## Fill-probability gate interpretation

The fill-probability gate is the strictest and least mature gate in the current public sample. It was added late in the experiment and was initially configured with a high threshold because private ledger replay suggested quality improvement. In subsequent live-like operation, that threshold appeared too conservative and suppressed nearly all trade flow. I treat it as an unfinished but important execution-quality control rather than a settled model.

## Overfitting and leakage limitations

- These diagnostics are based on anonymized public sample rows, not the full private ledger.
- The baseline is designed to demonstrate validation workflow, not to prove predictive edge.
- Public sample labels may be sparse or simplified after anonymization.
- The report does not replay the original private ML model or expose raw model scores.
- Chronological splitting reduces random look-ahead leakage but does not solve regime shift, feature drift, or label-quality problems.
- A production ML filter would require stricter walk-forward validation, feature-audit trails, leakage checks, and out-of-sample stress testing on private data.
