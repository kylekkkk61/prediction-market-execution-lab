# Data Preparation

This document explains how private raw ledger and tick data are converted into public-safe sample data for Prediction Market Execution Lab.

## Purpose

The public repository should be reproducible without exposing raw trading records or operational details. Private raw files are local-only inputs used to generate small, anonymized sample datasets and aggregate reports.

Expected local private input layout:

```text
private/raw_data/
├── ledger/
└── tick_snapshots/
```

The `private/` directory is ignored by Git and must remain outside the public repository.

## Private Inputs

### Ledger export

Expected local path:

```text
private/raw_data/ledger/
```

A private ledger may contain order history, candidate signals, execution attempts, signal rejections, settlement records, logs, or runtime state files.

These inputs can support:

- signal funnel analysis
- rejection reason breakdown
- fill-rate analysis
- edge before and after execution
- settlement and PnL attribution
- risk and drawdown simulation

### Tick snapshots

Expected local path:

```text
private/raw_data/tick_snapshots/
```

Tick snapshots can support:

- tick-level replay
- quote completeness checks
- spread distribution analysis
- time-to-expiry analysis
- fair probability versus market-implied probability analysis
- edge decay diagnostics

## Private Data Rules

Raw private data must never be committed.

Do not commit:

- files under `private/`
- raw ledger exports
- raw tick snapshot files
- bot logs
- state files
- wallet addresses
- order IDs
- token IDs
- raw API responses
- relayer or signer configuration
- private model artifacts
- strategy-sensitive thresholds

## Public Sample Data

Public-safe sample data lives under:

```text
data/sample/
```

Public sample files:

```text
data/sample/tick_snapshots_sample.csv
data/sample/candidates_sample.csv
data/sample/executions_sample.csv
data/sample/rejections_sample.csv
data/sample/settlements_sample.csv
```

These files are small, reviewable, and safe to publish. They are built for reproducible demonstrations rather than full historical analysis.

## Anonymization Rules

### Identifiers

- Replace internal IDs with deterministic fake IDs where joins are needed.
- Hash or replace market slugs if they expose unwanted private context.
- Remove wallet addresses, raw order IDs, token IDs, API response IDs, and relayer references.

### Monetary values

Use one of the following approaches depending on the field:

- bucket values into ranges
- normalize by total exposure
- round aggressively
- keep only ratios when absolute scale is not needed

Examples:

```text
amount_usd -> amount_bucket
net_pnl_estimate -> pnl_normalized
cost_usd -> cost_bucket
fill_ratio -> keep as ratio
```

### Strategy-sensitive fields

Remove or simplify:

- exact live thresholds
- full feature JSON dumps
- model paths
- model artifacts
- raw configuration snapshots

### Tick data

Tick samples should be downsampled to a small number of representative markets and rows. The goal is to demonstrate replay and quote-diagnostics workflows without exposing the full private dataset.

## Public Sample Generation

The sample generation script reads local private inputs, applies anonymization and filtering rules, and writes public-safe samples to `data/sample/`.

Usage:

```bash
PYTHONPATH=src uv run python scripts/prepare_public_sample_data.py
```

Useful size controls:

```text
--max-tick-files
--max-tick-rows-per-file
--max-ledger-rows-per-file
```

Example:

```bash
PYTHONPATH=src uv run python scripts/prepare_public_sample_data.py \
  --max-tick-files 1 \
  --max-tick-rows-per-file 100 \
  --max-ledger-rows-per-file 100
```

## Private Schema Inspection

Private inspection utilities are local-only helpers for understanding raw data shape without printing or committing sensitive rows.

Usage:

```bash
PYTHONPATH=src uv run python scripts/inspect_private_ledger.py
PYTHONPATH=src uv run python scripts/inspect_private_ticks.py --max-rows-per-file 1000
```

These scripts print aggregate summaries only and should not be used to publish raw data.

## Report Integration

Public reports and figures should run from `data/sample/`:

```bash
PYTHONPATH=src uv run python scripts/run_execution_quality_report.py
PYTHONPATH=src uv run python scripts/run_probability_calibration_report.py
PYTHONPATH=src uv run python scripts/run_monte_carlo_simulation.py
PYTHONPATH=src uv run python scripts/run_ml_filter_demo.py
PYTHONPATH=src uv run python scripts/generate_report_figures.py
```

Reports generated from public samples must be labeled as demonstration outputs, not complete empirical performance claims.
