# Project Brief

## Project Name

**Prediction Market Execution Lab**

## Subtitle

**Testing Executable Edge in Polymarket BTC Short-Horizon Markets**

## Purpose

This project studies whether apparent pricing edges in short-horizon prediction markets can survive real execution frictions.

The public version is designed as a FinTech, market microstructure, and execution-quality research project. It is not positioned as an automated trading bot or production execution system.

## Research Question

When a model detects a potential short-horizon prediction-market mispricing, does that theoretical edge remain after accounting for:

- bid-ask spread
- slippage
- fill probability
- timing and latency
- position limits
- settlement outcomes

## Case Study Scope

The initial case study uses Polymarket BTC short-horizon markets and BTC reference market data.

This scope is intentionally narrow so that the project can focus on execution quality, probability modeling, replayable analysis, and post-trade diagnostics.

## Public Deliverables

Planned public deliverables include:

- reproducible research modules under `src/`
- sample or anonymized data schemas under `data/sample/`
- execution-quality reports under `reports/`
- explanatory notebooks under `notebooks/`
- a lightweight dashboard under `dashboard/`
- project documentation under `docs/`

## Current Status

This repository is currently being migrated from a private experimental working codebase into a public research-oriented portfolio project.

Legacy scripts may still exist in the root directory during migration. They are retained temporarily as references and should not be treated as final public APIs or public-facing modules.
