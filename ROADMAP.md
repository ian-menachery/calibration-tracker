# ROADMAP

v1 and v1.1 of this project are shipped publicly. The headline — Polymarket sports markets are near chance a week before resolution while political and geopolitical markets carry real signal — is in [`reports/v1_calibration.md`](reports/v1_calibration.md) with full code, dataset, and methodology. v1.1 is the intended end state of the v1.x line; the project is complete as a portfolio piece and is not under active development.

## Possible future work

- **Phase 6 — multi-outcome decomposition.** Treat each candidate's YES/NO market as a binary calibration target and roll Polymarket's multi-candidate events (including the 2024 US Presidential Election, $1.5B in volume) into the dataset.
- **v2 modeling — predicting miscalibration.** Train a regression on per-market T-7d Brier from T-7d-observable features, with an honest backtest showing fees and spreads kill any apparent trading edge.
- **Kalshi cross-platform comparison.** Add Kalshi as a second data source and run the same calibration math head-to-head on overlapping markets.

These are deferred indefinitely. The current state is intentional, not abandoned.
