# Sample Data Schema

This document describes the public sample-data schema used by the demo scripts, reports, notebooks, and dashboard.

The sample data is anonymized, downsampled, and normalized. It is designed to make the public workflow reproducible without exposing private ledger data, wallet identifiers, raw order IDs, or production execution records.

## `data/sample/tick_snapshots_sample.csv`

Each row represents one market snapshot for a binary short-horizon BTC prediction market.

| Column | Type | Description |
|---|---:|---|
| `timestamp` | string | ISO-8601 timestamp for the snapshot. |
| `market_id` | string | Anonymized market identifier. |
| `market_slug` | string | Anonymized market slug. |
| `current_price` | float | BTC reference price at the snapshot time. In the public sample this mirrors the Binance-style reference field when available. |
| `open_anchor_price` | float | Market opening anchor used for UP/DOWN settlement logic. |
| `bn_price` | float | Binance BTCUSDT-style reference price used as the high-frequency BTC proxy. |
| `bn_open_price` | float | Binance-style opening anchor price when available. |
| `pm_open_price` | float | Prediction-market opening reference price when available. |
| `remaining_seconds` | float | Seconds remaining until market resolution. |
| `yes_bid` / `yes_ask` | float | YES-side bid and ask probabilities. |
| `down_bid` / `down_ask` | float | DOWN-side bid and ask probabilities. |
| `yes_mid` / `down_mid` | float | Midpoint probabilities. |
| `yes_spread` / `down_spread` | float | Bid-ask spread by side. |
| `pm_implied_up` / `pm_implied_down` | float | Market-implied probabilities. |
| `fair_yes` / `fair_no` | float | Model-estimated fair probabilities. |
| `sigma_eff` | float | Effective volatility estimate used by the fair probability workflow. |
| `tau_seconds` | float | Time-to-expiry value used by the model. |
| `z` | float | Standardized distance from the market anchor. |
| `quote_complete` | bool | Whether required quote fields are available. |

## `data/sample/candidates_sample.csv`

Each row represents an anonymized candidate signal.

| Column | Type | Description |
|---|---:|---|
| `recorded_at` | string | Signal timestamp. |
| `candidate_id` | string | Anonymized candidate identifier. |
| `market_id` | string | Anonymized market identifier. |
| `market_slug` | string | Anonymized market slug. |
| `side` | string | Candidate side, such as UP or DOWN. |
| `time_bucket` | string | Time-to-expiry bucket. |
| `signal_fair` | float | Model fair probability at signal time. |
| `signal_edge` | float | Estimated theoretical edge. |
| `signal_bid` / `signal_ask` | float | Quote values observed at signal time. |
| `signal_spread` | float | Bid-ask spread at signal time. |
| `limit_price` | float | Demonstration limit price field after anonymization/filtering. |
| `ml_filter_enabled` | bool | Whether the private-ledger ML filter was enabled for this sample row. |
| `ml_predicted_ev` | float | Public-safe scalar predicted EV diagnostic from the private ledger. |
| `ml_min_ev` | float | Public-safe scalar minimum EV threshold used for the ML decision. |
| `ml_passed` | bool | Whether the row passed the private-ledger ML decision threshold. |
| `ml_reason` | string | Coarse public-safe ML decision reason. |
| `fill_probability` | float | Fill-probability estimate retained as a scalar diagnostic. |
| `fill_prob_min_probability` | float | Public-safe scalar fill-probability threshold. |
| `fill_prob_passed` | bool | Whether the sample row passed the fill-probability diagnostic threshold. |
| `fill_prob_reason` | string | Coarse public-safe fill-probability decision reason. |

## `data/sample/executions_sample.csv`

Each row represents an anonymized execution-attempt or execution-state sample.

| Column | Type | Description |
|---|---:|---|
| `recorded_at` | string | Sample timestamp. |
| `candidate_id` | string | Anonymized candidate identifier. |
| `market_id` | string | Anonymized market identifier. |
| `side` | string | Candidate side. |
| `status` | string | Sample execution state category. |
| `attempt_stage` | string | Funnel stage. |
| `time_bucket` | string | Time-to-expiry bucket. |
| `amount_bucket` | string | Bucketed amount field. |
| `order_type` | string | Anonymized order-type category retained for diagnostics. |
| `signal_fair` | float | Model fair probability at signal time. |
| `signal_edge` | float | Estimated theoretical edge. |
| `signal_spread` | float | Bid-ask spread at signal time. |
| `ml_filter_enabled` | bool | Whether the private-ledger ML filter was enabled for this sample row. |
| `ml_predicted_ev` | float | Public-safe scalar predicted EV diagnostic from the private ledger. |
| `ml_min_ev` | float | Public-safe scalar minimum EV threshold used for the ML decision. |
| `ml_passed` | bool | Whether the row passed the private-ledger ML decision threshold. |
| `ml_reason` | string | Coarse public-safe ML decision reason. |
| `fill_probability` | float | Fill-probability estimate retained as a scalar diagnostic. |
| `fill_prob_min_probability` | float | Public-safe scalar fill-probability threshold. |
| `fill_prob_passed` | bool | Whether the sample row passed the fill-probability diagnostic threshold. |
| `fill_prob_reason` | string | Coarse public-safe fill-probability decision reason. |
| `order_sent` | bool | Whether the sample row reached an attempted-execution state. |
| `order_accepted` | bool | Whether the sample row was accepted in the anonymized funnel. |
| `filled` | bool | Whether the sample row reached filled state. |
| `fill_amount_bucket` | string | Bucketed fill amount field. |
| `fill_ratio` | float | Fill ratio when available. |
| `latency_ms` | float | Latency diagnostic field when available. |
| `failure_category` | string | Coarse failure category. |

## `data/sample/rejections_sample.csv`

Each row represents an anonymized rejected candidate signal.

| Column | Type | Description |
|---|---:|---|
| `recorded_at` | string | Rejection timestamp. |
| `market_id` | string | Anonymized market identifier. |
| `side` | string | Candidate side. |
| `rejection_stage` | string | Funnel stage where the candidate was rejected. |
| `rejection_reason_category` | string | Coarse rejection reason. |
| `time_bucket` | string | Time-to-expiry bucket. |
| `signal_fair` | float | Model fair probability at signal time. |
| `signal_edge` | float | Estimated theoretical edge. |
| `signal_spread` | float | Bid-ask spread at signal time. |

## `data/sample/settlements_sample.csv`

Each row represents an anonymized market-level settlement sample.

| Column | Type | Description |
|---|---:|---|
| `market_id` | string | Anonymized market identifier. |
| `market_slug` | string | Anonymized market slug. |
| `market_start_utc` | string | Market start timestamp. |
| `market_end_utc` | string | Market end timestamp. |
| `open_price` | float | Reference opening price. |
| `resolution_price` | float | Reference resolution price. |
| `resolved_side` | string | Realized UP/DOWN outcome. |
| `yes_orders` / `down_orders` | int | Sample order-count fields. |
| `total_cost_bucket` | string | Bucketed cost field. |
| `gross_payout_bucket` | string | Bucketed payout field. |
| `net_pnl_normalized` | float | Normalized sample PnL. |
| `pnl_if_up_normalized` / `pnl_if_down_normalized` | float | Counterfactual normalized PnL fields. |
| `mode_observed` | string | Coarse observation-mode category. |

## Interpretation Limits

- Public samples are not full raw history.
- Amount and PnL fields may be bucketed or normalized.
- Identifiers are anonymized and should be used only as join keys inside the public sample.
- ML diagnostics keep only scalar decision fields and coarse reason categories.
- Model paths, feature-name lists, raw feature JSON, raw responses, order IDs, wallet identifiers, and signer/deployment details are intentionally excluded.
- Reports generated from these files are demonstration outputs, not complete empirical performance claims.
