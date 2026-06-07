# Sample Data Schema

This document defines the initial public sample-data schema used by the tick replay demo.

The sample data is synthetic and simplified. It is designed to make the public replay workflow reproducible without exposing private ledger data, wallet identifiers, order IDs, or production execution records.

## `data/sample/tick_snapshots_sample.csv`

Each row represents one market snapshot for a binary short-horizon BTC prediction market.

| Column | Type | Description |
|---|---:|---|
| `timestamp` | string | ISO-8601 timestamp for the snapshot. |
| `market_id` | string | Demo market identifier. |
| `current_price` | float | BTC reference price at the snapshot time. |
| `open_anchor_price` | float | Market opening anchor used for UP/DOWN settlement logic. |
| `sigma_short` | float | Short-window volatility estimate using the same time unit as `remaining_seconds`. |
| `sigma_long` | float | Long-window volatility estimate using the same time unit as `remaining_seconds`. |
| `remaining_seconds` | float | Seconds remaining until market resolution. |
| `up_bid` | float | Current UP-side bid probability. |
| `up_ask` | float | Current UP-side ask probability. |
| `down_bid` | float | Current DOWN-side bid probability. |
| `down_ask` | float | Current DOWN-side ask probability. |

## Current limitations

- The current file is a minimal synthetic dataset for validating code paths.
- It is not evidence of live performance.
- It does not include fill outcomes, settlement labels, latency, or full order-book depth.
- Future PRs should add separate sample schemas for candidate signals, execution attempts, settlements, and report-ready attribution tables.
