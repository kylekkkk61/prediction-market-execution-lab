# Public Migration Plan

This document defines how the experimental Polymarket codebase was migrated into a public research-oriented project.

The goal of this migration is not to publish a live trading system. The goal is to preserve useful research, analytics, backtesting, reporting, dashboard, and risk-analysis components while avoiding public exposure of production operation details.

## Project framing

**Public project name:** Prediction Market Execution Lab

**Working subtitle:** Testing Executable Edge in Polymarket BTC Short-Horizon Markets

**Core question:**

> Can apparent short-horizon prediction-market pricing edges survive real execution frictions such as bid-ask spread, slippage, fill probability, latency, position limits, and settlement outcomes?

## Current public-release boundary

The public repository is organized around sample-backed research modules and demonstration artifacts:

```text
src/                 # Public-safe research modules
scripts/             # Public demo and report runners
reports/             # Sample-backed generated reports
reports/figures/     # Generated demonstration figures
notebooks/           # Public sample analysis notebooks
dashboard/           # Streamlit public-sample dashboard
data/sample/         # Anonymized, downsampled, normalized demo datasets
docs/                # Public methodology, architecture, limitations, and data notes
tests/               # Tests for public-safe code paths
```

Root-level legacy execution and research scripts are not part of the public demo surface. Tracked private model artifacts have also been removed from the public repository.

## Current private raw data status

Private raw data is stored locally only and must not be committed.

Current local private data layout:

```text
private/
├── ledger/
└── tick_snapshots/
```

Current available raw sources:

- Full historical ledger export under `private/ledger/`.
- Seven daily tick snapshot files under `private/tick_snapshots/`, covering 2026-05-29 through 2026-06-04.

Usage policy:

- Use private raw data only as local input for schema inspection, anonymization, sample generation, and report development.
- Do not commit files under `private/`.
- Do not commit raw ledger exports, raw tick snapshots, logs, wallet identifiers, order IDs, raw API responses, private model artifacts, or strategy-sensitive thresholds.
- Public demo data must be generated into `data/sample/` after anonymization, filtering, and size reduction.

## Migration principles

1. Reframe the project as a public prediction-market execution research lab.
2. Extract safe research logic into documented `src/` modules.
3. Replace private raw data with anonymized, downsampled, normalized public samples.
4. Generate reports, figures, notebooks, and dashboard views from public sample data only.
5. Remove production-operation files, root-level legacy scripts, and tracked private model artifacts before public release.
6. Keep wallet, signer, allowance, claim, relayer, deployment, and live taker execution details outside the public repository.

## File categories and final handling

### A. Removed from the public demo surface

The following root-level legacy scripts were useful during migration but are not public demo entry points. They have been removed after their public-safe logic was replaced by `src/`, `scripts/`, `reports/`, `notebooks/`, and `dashboard/` artifacts:

```text
attribute_live_pnl.py
backtest_ml_filter.py
backtest_ml_walkforward_ticks.py
backtest_take_profit.py
backtest_ticks.py
bot.py
build_ml_signal_dataset.py
compress_tick_snapshots.py
ml_filter.py
monte_carlo_ledger.py
train_live_candidate_model.py
train_ml_filter.py
validate_ml_on_live_executions.py
```

Tracked private model artifacts were also removed:

```text
models/live_candidate_research_weekdays_2026-05-21_30/features.json
models/live_candidate_research_weekdays_2026-05-21_30/fill_probability_model.txt
models/signal_filter_lgbm_v1_features.json
models/signal_filter_lgbm_v1.txt
```

### B. Preserved as public research modules

These concepts are represented through public-safe modules, reports, notebooks, and dashboard outputs:

- Fair probability model
- Market-implied probability handling
- Edge calculation
- Bid-ask spread analysis
- Tick-level replay backtesting
- Candidate signal dataset construction
- Execution-quality diagnostics
- PnL attribution methodology
- Monte Carlo risk simulation
- ML-assisted signal filtering methodology
- Probability calibration diagnostics

Target public structure:

```text
src/
├── data_sources/
├── models/
├── execution_quality/
├── backtesting/
├── risk/
└── utils/
```

### C. Excluded from public release

These files or concepts are not suitable for the public release unless converted into safe mock examples:

- `deploy.sh`
- `polymarket_auto_claim.py`
- `polymarket_allowance_maintenance.py`
- Wallet, signer, allowance, relayer, and production execution details
- Real execution logs
- Real ledger files
- Real order IDs, wallet addresses, API keys, or private operational configuration
- Strategy-sensitive live thresholds
- Private model artifacts

### D. Public demo substitutes

The public repository uses safe substitutes instead of private operation files:

- `.env.example` with demo-only variables
- Anonymized sample data
- Mock/anonymized execution records
- Sample market data schema
- Demo report generation scripts
- Streamlit dashboard using sample data only
- Public sample notebooks

## Data preparation strategy

Use raw private data in two stages.

### Stage 1 — raw schema inspection

Purpose:

- Inspect available ledger and tick snapshot schemas.
- Count rows, date ranges, markets, and key status categories.
- Identify sensitive fields before any public sample generation.

Expected local inputs:

```text
private/ledger/
private/tick_snapshots/
```

Expected public output:

- Documentation only.
- No raw rows.
- No private identifiers.

### Stage 2 — public-safe sample generation

Purpose:

- Generate small sample datasets into `data/sample/`.
- Support reproducible notebooks, reports, dashboard views, and demo scripts.
- Preserve analytic structure while removing private or sensitive details.

Expected public outputs:

```text
data/sample/tick_snapshots_sample.csv
data/sample/candidates_sample.csv
data/sample/executions_sample.csv
data/sample/rejections_sample.csv
data/sample/settlements_sample.csv
```

Rules:

- Hash or replace market identifiers when needed.
- Remove wallet, order, token, API response, relayer, and model-path fields.
- Bucket or normalize cost and PnL fields if they reveal private scale.
- Downsample tick data to a small number of representative markets and rows.
- Clearly label public samples as anonymized, filtered, and not full raw history.

## Completed PR sequence

### PR 1 — public migration plan

**Branch:** `docs/public-migration-plan`

**Commit:** `docs: add public migration plan`

Status: merged.

Scope:

- Add the initial migration plan.
- Do not modify README.
- Do not delete files.
- Do not move Python code.

### PR 2 — public research framing

**Branch:** `docs/public-research-framing`

**Commit:** `docs: add public research framing scaffold`

Status: merged.

Scope:

- Rewrite README around the research-lab framing.
- Add `docs/project_brief.md`.
- Add `docs/methodology.md`.
- Add `docs/architecture.md`.
- Add `docs/limitations.md`.
- Add safe `.gitignore`, `.env.example`, and `pyproject.toml`.

### PR 3 — extract fair probability and edge modules

**Branch:** `refactor/extract-fair-probability-model`

**Commit:** `refactor: extract fair probability and edge modules`

Status: merged.

Scope:

- Create `src/models/fair_probability.py`.
- Create `src/execution_quality/edge.py`.
- Add basic unit tests.
- Use existing code only as reference, not as a blind copy.

### PR 4 — extract tick replay backtesting

**Branch:** `refactor/extract-tick-replay-backtest`

**Commit:** `refactor: extract tick replay backtesting`

Status: merged.

Scope:

- Create `src/backtesting/tick_replay.py`.
- Add a demo script for replaying sample data.
- Define sample data schema.
- Connect tick replay to the fair probability and edge modules.

### PR 5 — update data preparation plan

**Branch:** `docs/update-data-preparation-plan`

**Commit:** `docs: update data preparation plan`

Status: merged.

Scope:

- Update the migration plan with the local private data layout.
- Add `docs/data_preparation.md`.
- Confirm `.gitignore` excludes `private/` and private raw data.
- Do not generate public sample data yet.

### PR 6 — add private data inspection utilities

**Branch:** `feat/add-private-data-inspection-utilities`

**Commit:** `feat: add private data inspection utilities`

Status: merged.

Scope:

- Add `scripts/inspect_private_ledger.py`.
- Add `scripts/inspect_private_ticks.py`.
- Add schema summary helpers under `src/data_sources/`.
- Read from `private/ledger/` and `private/tick_snapshots/` only when run locally.

### PR 7 — add public sample data preparation utilities

**Branch:** `feat/add-public-sample-data-preparation`

**Commit:** `feat: add public sample data preparation utilities`

Status: merged.

Scope:

- Add anonymization helpers.
- Add `scripts/prepare_public_sample_data.py`.
- Generate small public-safe sample CSV files into `data/sample/`.
- Use private input locally, but commit only anonymized samples.

### PR 8 — add execution quality report scaffold

**Branch:** `feat/add-execution-quality-report-scaffold`

**Commit:** `feat: add execution quality report scaffold`

Status: merged.

Scope:

- Create `reports/execution_quality_report.md`.
- Create `scripts/run_execution_quality_report.py`.
- Add sample-backed outputs for signal funnel, spread distribution, edge decay, fill-rate buckets, and PnL attribution.

### PR 9 — add risk and ML methodology modules

**Branch:** `refactor/add-risk-and-ml-methodology`

**Commit:** `refactor: add risk and ml methodology modules`

Status: merged.

Scope:

- Add simplified Monte Carlo risk module.
- Add ML filter methodology or demo scaffold.
- Add documentation explaining validation limitations.

### PR 10 — first pre-public cleanup

**Branch:** `chore/remove-private-operation-files`

**Commit:** `chore: remove private operation files from public release`

Status: merged.

Scope:

- Remove clearly unsafe production-operation files when present.
- Keep broader legacy research scripts temporarily for later audit.
- Keep private raw data ignored by git.

### PR 11+ — reports, figures, notebooks, README, and dashboard packaging

Status: merged through dashboard packaging.

Scope:

- Add probability calibration reporting.
- Add seven-day public sample alignment and report figures.
- Migrate to `uv` workflow.
- Update README to final demo instructions.
- Add public sample notebooks.
- Add Streamlit public-sample dashboard.
- Remove unnecessary `.gitkeep` placeholders.

### PR 22 — remaining legacy reference cleanup

**Branch:** `chore/remove-remaining-legacy-reference-scripts`

**Commit:** `chore: remove remaining legacy reference scripts`

Status: in progress.

Scope:

- Remove remaining root-level legacy reference scripts from the public demo surface.
- Remove tracked private model artifacts.
- Update public docs so they no longer describe the repository as still containing root-level legacy scripts.
- Keep `private/` ignored and untouched.

Acceptance criteria:

- Public demo paths run from `scripts/`, `src/`, `notebooks/`, `reports/`, and `dashboard/`.
- No root-level legacy Python scripts remain tracked.
- No tracked private model artifact remains.
- README and docs do not instruct users to run legacy scripts.
- Tests and lint checks still pass.

## Current project status

The project now has public sample generation, tick replay, execution-quality reporting, probability calibration diagnostics, report figures, Monte Carlo risk simulation, ML filter methodology demo, public notebooks, final README demo instructions, and a Streamlit public-sample dashboard.

After remaining legacy reference cleanup, the next public-packaging tasks are LinkedIn/CV narrative preparation and any final release review before making the repository public or sharing it externally.
