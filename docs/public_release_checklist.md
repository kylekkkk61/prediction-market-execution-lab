# Public Release Checklist

This checklist records the final public-safety review for the public research version of **Prediction Market Execution Lab**.

The project is intended to be a public FinTech / market microstructure / execution-quality research portfolio. It is not a live trading bot, production execution system, or profitability claim.

## Review scope

Reviewed repository content outside ignored local-only paths:

- Python source modules under `src/`
- scripts under `scripts/`
- public dashboard code under `dashboard/`
- public sample data under `data/sample/`
- reports under `reports/`
- notebooks under `notebooks/`
- documentation under `docs/`
- static portfolio page under `site/`
- GitHub Actions workflows under `.github/workflows/`
- root public configuration files

The local `private/` directory is intentionally ignored by Git and is not part of the public release.

## Sensitive-data exclusion checklist

- [x] No API keys or production credentials are committed.
- [x] No private keys, mnemonics, seed phrases, signer material, or wallet secrets are committed.
- [x] No wallet operation, signer, allowance-maintenance, auto-claim, or live taker execution implementation is exposed.
- [x] No private raw ledger files are committed.
- [x] No private raw tick snapshot files are committed.
- [x] No raw exchange / market API response payloads are committed.
- [x] No private model artifacts, model paths, raw feature JSON, or full feature-name exports are committed.
- [x] No tracked cache files such as `.DS_Store`, `.pytest_cache/`, `.ruff_cache/`, `__pycache__/`, or `*.pyc` are present.
- [x] Public sample files are anonymized, normalized, downsampled, and field-filtered.
- [x] Public reports and notebooks avoid profitability claims and label outputs as public-sample / demonstration-only results.

## Audit commands used

Sensitive-term scan excluding Git internals, local private data, the virtual environment, binary assets, and lockfile noise:

```bash
rg -n -i --hidden \
  --glob '!.git/**' \
  --glob '!private/**' \
  --glob '!.venv/**' \
  --glob '!uv.lock' \
  --glob '!docs/assets/**' \
  --glob '!*.png' \
  --glob '!*.gif' \
  "(private key|api[_-]?key|secret|wallet|signer|allowance|mnemonic|seed phrase|auto[-_ ]?claim|deploy\.sh|live taker|order routing|production execution|raw ledger|real ledger|order id|address|0x[a-f0-9]{40})" .
```

Tracked local-cache scan:

```bash
git ls-files '.DS_Store' 'docs/.DS_Store' 'docs/assets/.DS_Store' '.pytest_cache/**' '.ruff_cache/**' '**/__pycache__/**' '*.pyc'
```

## Reviewed findings

### Sensitive-term matches

The sensitive-term scan still finds deliberate public-safety language in README, docs, reports, dashboard copy, notebooks, and module docstrings. These references are expected because the public project repeatedly states what is intentionally excluded from the release.

Examples of reviewed-safe contexts:

- disclaimers that the project is not a trading bot or production execution system
- statements that wallets, signers, allowance logic, order routing, private ledgers, and raw responses are excluded
- sample-data schema notes describing anonymization and field filtering
- tests using fake strings such as `secret-order` or `btc-updown-secret-market` to verify anonymization behavior

### Local source-data inspection utilities

`src/data_sources/source_inspection.py` and related tests intentionally operate as public-safe schema/inventory utilities. They summarize local private files without emitting raw rows, wallet addresses, order IDs, token IDs, or raw API responses.

These utilities are acceptable in the public repository because they document and test the boundary between local private inputs and public sample artifacts.

### Local cache files

Local cache files may exist in a developer workspace, but they are covered by `.gitignore` and were not tracked at the time of this audit.

## Public-release positioning

The public release should continue to avoid the following claims:

- guaranteed profitability
- stable alpha
- live trading readiness
- automated betting / taker bot positioning
- production execution capability
- complete empirical performance representation

Preferred framing:

- execution-quality research
- public-sample demonstration
- anonymized / normalized data pipeline
- fair probability modeling
- executable-edge diagnostics
- tick replay vs live-like execution gap
- ML-assisted signal filtering as an execution-quality gate
- risk and Monte Carlo simulation as diagnostic tooling

## Release gate

Before broad public sharing, confirm:

- [ ] GitHub Actions CI passes on `main`.
- [ ] Streamlit dashboard loads from the public deployment URL.
- [ ] Static portfolio page loads from the custom domain.
- [ ] README links resolve to the custom portfolio page, live dashboard, reports, notebooks, methodology, and limitations.
- [ ] No new private files or local cache files are staged.
