# ROADMAP

v1 and v1.1 of this project are shipped publicly. The headline — Polymarket sports markets are near chance a week before resolution while political and geopolitical markets carry real signal — is in [`reports/v1_calibration.md`](reports/v1_calibration.md) with full code, dataset, and methodology. v1.1 is the intended end state of the v1.x line.

## v2 — measured-edge / favorite-longshot (Phases 0–2 built)

The favorite-longshot bias is now **measured**, not just plotted. The recalibration map `logit(q)=a+b·logit(p)` is fit per horizon and slice (see ARCHITECTURE.md §14, `analysis/recalibration.py`, and the `flb` stage). Result: `b<1` at the tradeable horizons (T-24h `b≈0.88`, T-7d `b≈0.72`), concentrated in sports — politics/geopolitics run `b>1`. A map fit on older markets does not improve Brier out-of-sample, so historical edge ≠ live edge.

- **Phase 3 — sized rule (deferred).** Express the bias as an edge function `e(p)=q̂(p)−p` with fractional-Kelly sizing and a spread/fee cost model. Designed, not built.
- **Phase 4 — forward test (deferred).** Pre-register the frozen map + universe filter + sizing and paper-test on newly resolved markets. The only honest validity check; deliberately not started.

## Other possible future work

- **Phase 6 — multi-outcome decomposition.** Treat each candidate's YES/NO market as a binary calibration target and roll Polymarket's multi-candidate events (including the 2024 US Presidential Election, $1.5B in volume) into the dataset.
- **v2 modeling — predicting miscalibration.** Train a regression on per-market T-7d Brier from T-7d-observable features, with an honest backtest showing fees and spreads kill any apparent trading edge. (Distinct from the FLB measurement above, which uses no model.)
- **Kalshi cross-platform comparison.** Add Kalshi as a second data source and run the same calibration math head-to-head on overlapping markets.

Phase 3/4 and the items above are deferred until explicitly requested. The current state is intentional, not abandoned.
