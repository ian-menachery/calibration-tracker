# ROADMAP

v1 and v1.1 of this project are shipped publicly. The headline — Polymarket sports markets are near chance a week before resolution while political and geopolitical markets carry real signal — is in [`reports/v1_calibration.md`](reports/v1_calibration.md) with full code, dataset, and methodology. v1.1 is the intended end state of the v1.x line.

## v2 — measured-edge / favorite-longshot (Phases 0–2 built)

The favorite-longshot bias is now **measured**, not just plotted. The recalibration map `logit(q)=a+b·logit(p)` is fit per horizon and slice (see ARCHITECTURE.md §14, `analysis/recalibration.py`, and the `flb` stage). Result: `b<1` at the tradeable horizons (T-24h `b≈0.88`, T-7d `b≈0.72`), concentrated in sports — politics/geopolitics run `b>1`. A map fit on older markets does not improve Brier out-of-sample, so historical edge ≠ live edge.

- **Phase 3 — sized rule (built).** Edge `e(p)=q̂(p)−p`, fractional-Kelly off the conservative q bound, spread/fee cost model (`analysis/edge.py`, `backtest-rule`, `freeze-rule`). Backtest verdict: gross edge dies between 1–2¢ half-spread; only sports@24h / crypto@7d clear the eligibility gate.
- **Phase 4 — forward test (built, accruing).** Pre-registered frozen rule + live-book realizable paper fills (`forward_signals`, `forward-scan`/`forward-settle`). Tracks realized-minus-predicted edge. P&L accrues on the calendar; **paper only, no live capital.**
- **Phase 5 — Kalshi cross-venue (built).** `venue` column + `kalshi/` module + `cross-venue` + `venue-difftest`. Finding (pooled interaction test): Polymarket sports@24h slope 0.834 vs Kalshi 0.962; cross-venue difference **b3=0.128, 95% CI [−0.034, 0.305]** — includes 0, so the venue slope difference is **not statistically significant**. FLB is significant on Polymarket alone and not on Kalshi alone, but the venues are indistinguishable; we do not claim a venue effect. **Deferred follow-up:** a matched **politics/geopolitics** cross-venue sweep — Kalshi fragments these into ~2,052 Politics / 151 World single-question series, so it needs category-based discovery (iterate series within a Kalshi category) rather than per-series enumeration.

## Other possible future work

- **Phase 6 — multi-outcome decomposition.** Treat each candidate's YES/NO market as a binary calibration target and roll Polymarket's multi-candidate events (including the 2024 US Presidential Election, $1.5B in volume) into the dataset.
- **v2 modeling — predicting miscalibration.** Train a regression on per-market T-7d Brier from T-7d-observable features, with an honest backtest showing fees and spreads kill any apparent trading edge. (Distinct from the FLB measurement above, which uses no model.)
- **Live trading of the rule.** The Phase 4 forward test is paper-only; deploying real capital is a separate decision, not in scope.

(Kalshi cross-platform comparison, originally listed here, shipped as Phase 5.) The items above are deferred until explicitly requested. The current state is intentional, not abandoned.
