# Architecture

This document outlines the planned public architecture for Prediction Market Execution Lab.

## High-Level Flow

```mermaid
flowchart LR
    A[BTC Reference Prices] --> C[Fair Probability Model]
    B[Prediction Market Quotes] --> D[Market Quote Layer]
    C --> E[Edge Calculation]
    D --> E
    E --> F[Execution-Quality Filters]
    F --> G[Research Ledger]
    G --> H[PnL Attribution]
    B --> I[Tick Snapshot Store]
    I --> J[Replay Backtester]
    G --> K[Risk Simulation]
    G --> L[Report and Notebook Outputs]
```

## Planned Public Modules

- `src/data_sources/`: data loading and sample quote ingestion
- `src/models/`: fair probability and optional ML filter logic
- `src/execution_quality/`: spread, edge, fill, and attribution analysis
- `src/backtesting/`: tick replay and walk-forward research utilities
- `src/risk/`: Monte Carlo and path-risk utilities
- `src/utils/`: shared configuration and plotting helpers

## Current Status

This is a scaffold. Module names may change as prototype code is migrated into the public research structure.
