# Project Brief

## Project Name

**Prediction Market Execution Lab**

## Subtitle

**Testing Executable Edge in Polymarket BTC Short-Horizon Markets**

## Purpose

This project studies whether apparent pricing edges in short-horizon prediction markets can survive real execution frictions.

It is designed as a FinTech, market microstructure, and execution-quality research project. It is not positioned as an automated trading bot or production execution system.

## Research Question

When a model detects a potential short-horizon prediction-market mispricing, does that theoretical edge remain after accounting for:

- bid-ask spread
- slippage
- fill probability
- timing and latency
- position limits
- settlement outcomes

## Case Study Scope

The case study uses Polymarket BTC short-horizon markets and BTC reference market data.

This scope is intentionally narrow so that the project can focus on execution quality, probability modeling, replayable analysis, and post-trade diagnostics.

## Public Deliverables

The repository includes:

- reproducible research modules under `src/`
- anonymized public sample data under `data/sample/`
- execution-quality and methodology reports under `reports/`
- explanatory notebooks under `notebooks/`
- a lightweight Streamlit dashboard under `dashboard/`
- project documentation under `docs/`

## Public-Safe Boundary

The project excludes private raw ledgers, raw tick snapshots, wallet identifiers, order IDs, signer logic, allowance logic, deployment details, live execution runbooks, and private model artifacts.

Public outputs are demonstration artifacts based on anonymized, downsampled, and normalized sample data. They are intended to show the research workflow, not to claim complete historical performance or production readiness.
