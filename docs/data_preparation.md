# Data Preparation Plan

This document defines how private raw ledger and tick data should be inspected, anonymized, and converted into public-safe sample data for the Prediction Market Execution Lab.

## Purpose

The project now has local private raw data that can improve the realism of the public research workflow:

```text
private/raw_data/
├── ledger/
└── tick_snapshots/
```

The public repo should not expose the raw data. Instead, raw files are local-only inputs used to generate small, anonymized sample datasets and aggregate reports.

## Available private inputs

### Full ledger export

Location:

```text
private/raw_data/ledger/
```

Expected contents may include:

- order history
- raw candidate signals
- execution attempts
- signal rejections
- market settlements
- bot logs or runtime state files

The full ledger is useful for:

- signal funnel analysis
- rejection reason breakdown
- fill-rate analysis
- edge before and after execution
- settlement and PnL attribution
- risk and drawdown simulation

### Seven days of tick snapshots

Location:

```text
private/raw_data/tick_snapshots/
```

Current window:

```text
2026-05-29 through 2026-06-04
```

The tick snapshots are useful for:

- tick-level replay
- quote completeness checks
- spread distribution analysis
- time-to-expiry analysis
- fair probability versus market-implied probability analysis
- edge decay diagnostics

## Private data rules

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

The `.gitignore` file must continue to exclude `private/`.

## Public sample data target

Public-safe sample data should eventually be written to:

```text
data/sample/
```

Target public sample files:

```text
data/sample/tick_snapshots_sample.csv
data/sample/candidates_sample.csv
data/sample/executions_sample.csv
data/sample/rejections_sample.csv
data/sample/settlements_sample.csv
```

These files should be small, reviewable, and safe to publish.

## Anonymization rules

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
- exact model version details when not needed
- raw configuration snapshots

### Tick data

Tick samples should be downsampled.

Recommended public sample size:

- a small number of markets
- a small number of rows per market
- enough rows to demonstrate tick replay behavior
- not enough rows to reconstruct the full private dataset

## Processing stages

### Stage 1 — inspection only

Goal:

- inspect raw schema locally
- summarize row counts, columns, time ranges, market counts, and status categories
- identify sensitive fields

Output:

- console summaries
- optional documentation updates
- no raw rows committed

### Stage 2 — anonymized sample generation

Goal:

- generate small CSV samples in `data/sample/`
- preserve enough structure for demos and tests
- remove or transform sensitive fields

Output:

- public-safe sample CSV files
- tests proving samples can be loaded
- docs explaining that samples are anonymized and filtered

### Stage 3 — report integration

Goal:

- run execution-quality reports against public sample data
- generate figures from sample data
- clearly label sample-backed results as sample-only

Output:

- `reports/execution_quality_report.md`
- optional figures under `reports/figures/`
- scripts that can be run without private data

## Planned tooling

### Inspection utilities

Planned scripts:

```text
scripts/inspect_private_ledger.py
scripts/inspect_private_ticks.py
```

These scripts should:

- read from `private/raw_data/ledger/` and `private/raw_data/tick_snapshots/`
- print aggregate summaries only
- avoid writing public files by default
- avoid printing sensitive values

Usage:

```bash
PYTHONPATH=src .venv/bin/python scripts/inspect_private_ledger.py
PYTHONPATH=src .venv/bin/python scripts/inspect_private_ticks.py --max-rows-per-file 1000
```

### Sample generation utilities

Planned script:

```text
scripts/prepare_public_sample_data.py
```

This script should:

- read private raw inputs locally
- apply anonymization and filtering rules
- write public-safe samples to `data/sample/`
- be deterministic where practical
- avoid requiring live execution credentials

## Validation requirements

Before committing generated sample files:

1. Confirm `private/` is ignored by git.
2. Confirm `git status` does not show raw private files.
3. Inspect sample files for sensitive columns.
4. Run tests using `.venv`:

```bash
PYTHONPATH=src .venv/bin/python -m pytest
```

5. Run relevant demo scripts against `data/sample/`.

## Documentation rule

Any report, notebook, or README section using public samples must state that:

- the data is anonymized and filtered
- the samples are for reproducibility and demonstration
- sample outputs should not be interpreted as full empirical performance claims
