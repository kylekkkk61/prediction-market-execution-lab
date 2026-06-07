# Probability Calibration Report

> This report is generated from anonymized public sample data. It is a methodology and diagnostics artifact, not a claim about production predictive performance or trading profitability.

## Sample coverage

- Joined market-level observations: 0
- Forecast unit: one averaged forecast per anonymized market id
- Outcome unit: resolved UP/DOWN settlement side from public sample settlements
- If joined observations are zero, the current public sample does not contain aligned forecast and settlement keys

## Summary metrics

| Source | Observations | Brier score | Log loss |
|---|---:|---:|---:|
| Fair probability | 0 | n/a | n/a |
| Market-implied probability | 0 | n/a | n/a |

## Fair probability calibration buckets

No calibration buckets could be computed for this source.


## Market-implied probability calibration buckets

No calibration buckets could be computed for this source.


## Interpretation notes

- Brier score and log loss are computed on public-sample market-level observations only.
- Markets with missing probabilities, unresolved settlement labels, or non-aligned anonymized keys are excluded.
- Multiple tick rows per market are averaged before scoring, so markets with more quote updates do not dominate the calibration score.
- A future public sample generation pass should preserve a consistent anonymized market key across tick and settlement samples before interpreting calibration metrics.
- The public sample is anonymized and downsampled; these diagnostics should be read as a reproducible workflow demonstration, not as a full empirical conclusion.
