# Deployment

This document explains how to deploy the public dashboard for Prediction Market Execution Lab.

The deployed app is a **public-sample Streamlit dashboard**. It is not a live trading system and does not connect to private ledgers, wallets, signers, exchanges, order-routing systems, or production execution infrastructure.

## Recommended target

The recommended first deployment target is **Streamlit Community Cloud**.

This keeps the public demo simple:

- no Dockerfile
- no Railway configuration
- no secrets
- no database
- no private data volume
- no live market connection

The dashboard reads only tracked public artifacts from the repository:

```text
data/sample/*.csv
reports/*.md
reports/figures/*.png
```

## Streamlit Community Cloud settings

Use these settings when creating the app:

| Setting | Value |
|---|---|
| Repository | `kylekkkk61/prediction-market-execution-lab` |
| Branch | `main` |
| Main file path | `dashboard/app.py` |
| Python version | `3.11` if configurable |
| Secrets | None |

The app should be deployed from the public repository only after private files remain excluded from Git.

## Dependency workflow

The project uses `pyproject.toml` and `uv.lock` for dependency management.

No `requirements.txt` file is required for the first deployment attempt. Runtime dashboard dependencies are declared in `pyproject.toml`, and the lockfile is kept in the repository.

If Streamlit Community Cloud does not install optional dependency groups as expected, the preferred fix is to keep the dashboard runtime dependencies in the base project dependencies rather than introducing a separate root-level `requirements.txt` workflow.

## Local verification

Before deploying, verify the dashboard locally:

```bash
uv sync --extra dev --extra notebook --extra dashboard --extra ml
PYTHONPATH=src uv run pytest
PYTHONPATH=src uv run streamlit run dashboard/app.py
```

The dashboard should load without requiring environment variables or private files.

## Public dashboard URL

After deployment, Streamlit Community Cloud will provide a public app URL under the `streamlit.app` domain.

Do not add a placeholder live URL to the README before the app is actually deployed and verified.

Once verified, update the README dashboard entry with the live app URL.

## Custom domain strategy

This project can use a custom domain in two ways:

1. **Recommended portfolio route:** use the custom domain for a static project landing page, then link from that page to the Streamlit dashboard URL.
2. **Dashboard route:** if the hosting provider supports custom domains directly, point a dashboard subdomain to the hosted app.

For Streamlit Community Cloud, this project should not assume direct custom-domain support unless the deployed app settings explicitly provide it. A stable fallback is:

```text
custom domain landing page → Streamlit Cloud dashboard URL
```

Example future structure:

```text
pm-lab.<your-domain>        # static project landing page
dashboard link              # Streamlit Community Cloud app URL
```

## Deployment safety checklist

Before publishing the dashboard URL, confirm:

- [ ] `private/` is ignored and not tracked by Git.
- [ ] The dashboard loads only `data/sample`, `reports`, and `reports/figures` artifacts.
- [ ] No wallet, signer, allowance, auto-claim, or live taker execution logic is present.
- [ ] No API keys, order IDs, wallet addresses, raw feature JSON, or private model artifacts are exposed.
- [ ] The dashboard starts from `dashboard/app.py` without secrets.
- [ ] The README clearly states that the dashboard is demonstration-only.

## Railway fallback

Railway remains a reasonable fallback if future requirements include:

- direct custom-domain control for the dashboard app
- stronger deployment configuration
- Wait-for-CI style deployment gating
- Docker or Nixpacks-based deployment control

The current public dashboard does not require that extra deployment surface, so Streamlit Community Cloud is the simpler first target.
