# Public Migration Plan

This document defines how the current experimental Polymarket codebase will be migrated into a public research-oriented project.

The goal of this migration is not to publish a live trading system. The goal is to preserve useful research, analytics, backtesting, reporting, and risk-analysis components while avoiding public exposure of production operation details.

## Project framing

**Public project name:** Prediction Market Execution Lab

**Working subtitle:** Testing Executable Edge in Polymarket BTC Short-Horizon Markets

**Core question:**

> Can apparent short-horizon prediction-market pricing edges survive real execution frictions such as bid-ask spread, slippage, fill probability, latency, position limits, and settlement outcomes?

## Migration principle

The existing root-level scripts should be treated as **legacy reference code** until they are explicitly reviewed and refactored.

Do not delete large groups of files in the first migration PR. Instead:

1. Reframe the project with public-facing documentation.
2. Mark legacy files by category.
3. Extract safe research modules into `src/` one PR at a time.
4. Add sample or anonymized data only after the schema is reviewed.
5. Remove private-operation files only in a later cleanup PR before public release.

## File categories

### A. Keep temporarily as legacy reference

These files may contain useful research logic, but they should not be treated as public-facing modules yet.

Examples:

- `bot.py`
- `backtest_ticks.py`
- `backtest_take_profit.py`
- `backtest_ml_filter.py`
- `backtest_ml_walkforward_ticks.py`
- `build_ml_signal_dataset.py`
- `train_ml_filter.py`
- `train_live_candidate_model.py`
- `validate_ml_on_live_executions.py`
- `attribute_live_pnl.py`
- `monte_carlo_ledger.py`
- `ml_filter.py`

Expected action:

- Keep them in place for now.
- Do not link to them from the public README as finished public modules.
- Use them as references when extracting clean modules into `src/`.

### B. Extract into public research modules

These concepts are suitable for the public repo after refactoring and simplification:

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

Expected target structure:

```text
src/
├── data_sources/
├── models/
├── execution_quality/
├── backtesting/
├── risk/
└── utils/
```

### C. Remove before public release

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

Expected action:

- Do not remove them in the first documentation PR.
- Add them to the cleanup checklist.
- Remove or mock them in a dedicated pre-public-release PR.

### D. Replace with public demo artifacts

These should be added later as safe public substitutes:

- `.env.example` with demo-only variables
- Anonymized sample data
- Mock execution records
- Sample market data schema
- Demo report generation scripts
- Streamlit dashboard using sample data only

## Recommended PR sequence

### PR 1 — public migration plan

**Branch:** `docs/public-migration-plan`

**Commit:** `docs: add public migration plan`

Scope:

- Add this migration plan.
- Do not modify README.
- Do not delete files.
- Do not move Python code.

Acceptance criteria:

- Only documentation is added.
- Existing source files remain unchanged.

### PR 2 — public research framing

**Branch:** `docs/public-research-framing`

**Commit:** `docs: reframe project as public research lab`

Scope:

- Rewrite README around the research-lab framing.
- Add `docs/project_brief.md`.
- Add `docs/methodology.md`.
- Add `docs/architecture.md`.
- Add `docs/limitations.md`.
- Add safe `.gitignore`, `.env.example`, and `pyproject.toml`.
- Add folder skeleton with `.gitkeep` files.

Acceptance criteria:

- No root-level Python files are deleted.
- The README does not position the project as a live trading or betting tool.
- The README clearly states that outputs are currently planned/scaffolded if no empirical report exists yet.

### PR 3 — extract fair probability and edge modules

**Branch:** `refactor/extract-fair-probability-model`

**Commit:** `refactor: extract fair probability model`

Scope:

- Create `src/models/fair_probability.py`.
- Create `src/execution_quality/edge.py`.
- Add basic unit tests.
- Use existing code only as reference, not as a blind copy.

Acceptance criteria:

- No live execution logic is included.
- Tests cover basic probability and edge calculations.

### PR 4 — extract tick replay backtesting

**Branch:** `refactor/extract-tick-replay-backtest`

**Commit:** `refactor: extract tick replay backtesting`

Scope:

- Create `src/backtesting/tick_replay.py`.
- Add a demo script for replaying sample data.
- Define sample data schema.

Acceptance criteria:

- Backtest runs on sample or synthetic data only.
- No private ledger or wallet data is required.

### PR 5 — add execution quality report scaffold

**Branch:** `feat/add-execution-quality-report-scaffold`

**Commit:** `feat: add execution quality report scaffold`

Scope:

- Create `reports/execution_quality_report.md`.
- Create `scripts/run_execution_quality_report.py`.
- Add placeholders for signal funnel, spread distribution, edge decay, fill-rate buckets, and PnL attribution.

Acceptance criteria:

- The report clearly labels planned sections and any sample-only results.
- No unsupported performance claims are made.

### PR 6 — add risk and ML methodology modules

**Branch:** `refactor/add-risk-and-ml-methodology`

**Commit:** `refactor: add risk and ml methodology modules`

Scope:

- Add simplified Monte Carlo risk module.
- Add ML filter methodology or demo scaffold.
- Add documentation explaining validation limitations.

Acceptance criteria:

- ML is presented as a signal-quality filter, not as a guaranteed profit model.
- Walk-forward or out-of-sample validation assumptions are documented.

### PR 7 — pre-public cleanup

**Branch:** `chore/remove-private-operation-files`

**Commit:** `chore: remove private operation files from public release`

Scope:

- Remove private-operation files.
- Remove private model artifacts.
- Remove or anonymize any private data.
- Confirm public README no longer references private scripts.

Acceptance criteria:

- Repo can be made public without wallet, signer, private execution, or sensitive operational details.
- Public code paths run on sample or synthetic data.

## Current immediate next step

The next approved step is PR 1 only:

```text
Branch: docs/public-migration-plan
Commit: docs: add public migration plan
Scope: add this file only
```

No production files, root-level Python scripts, model artifacts, or README content should be deleted in this step.
