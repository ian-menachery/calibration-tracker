# Session Notes

Per-session handoff: what got done, where things stand, what to pick up next.
For the running list of API gotchas and v2 considerations, see `NOTES.md`.

## 2026-05-07 — Phase 3 done end-to-end

### Summary
Implemented and ran Stages 2 (CLOB price fetch) and 3 (snapshot extraction);
`data/markets.db` now holds 4,522 markets, 7.16 M raw price ticks, and
16,341 calibration snapshots. Six new commits on `main`, all pushed.

### Current state
**Complete:**
- Phases 0 → 3. Stages 1, 2, 3 of the pipeline are live; the dataset
  Phase 4 needs is sitting in `data/markets.db`.
- 21/21 tests pass; `ruff check src tests` clean.
- All commits pushed to `origin/main`. Working tree clean.

**In-progress:** none. Phase 3 is fully landed.

### Worth flagging
- **One market** (out of 4,523) has no price history — skipped during the
  full backfill on a transient `httpx.RemoteProtocolError`. Re-run with
  default `--resume` semantics would pick it up if 99.98 % coverage isn't
  enough for Phase 4.
- **No README** at repo root yet; ARCHITECTURE.md §7 lists one but it has
  never been written. Probably belongs in Phase 7 (polish + publish).
- **Four throwaway viewer scripts** in working tree, all untracked, named
  `_view_*_temp.py`. Useful for ad-hoc DB inspection, not load-bearing.
  Safe to delete any time.
- **Headline calibration preview** (recorded in `NOTES.md`'s session log):
  at T-1h, extreme buckets [0.0, 0.1) and [0.9, 1.0) hold ~99 % of markets
  and are essentially perfectly calibrated (0 % and 99.9 % realized).
  Middle buckets are very thin since markets collapse to ~0/1 by the final
  hour. The interesting calibration tension will live at T-7d.

### Next steps — Phase 4 (calibration analysis)
Per ARCHITECTURE.md §5 / §9, Stage 4 is pure pandas math:
1. Load `markets` joined with `price_snapshots` into a DataFrame.
2. Bucket markets by predicted price (decile + 5 % buckets).
3. Compute realized rate per bucket; per snapshot type.
4. Compute Brier score and log loss overall and by subgroup.
5. Bootstrap CIs for per-bucket realized rates (uneven bucket counts).
6. Per CLAUDE.md, the math in `src/calibration/analysis/` MUST have unit
   tests with known inputs and known scores.

Plan Phase 4 via `/plan` like Phase 3 was. Phase 5 (writeup) follows.

### Useful commands
```
.venv\Scripts\python.exe -m pytest tests/ -q                    # run tests
.venv\Scripts\python.exe -m calibration.cli discover --since 2024-01-01    # Stage 1 (idempotent)
.venv\Scripts\python.exe -m calibration.cli fetch-prices         # Stage 2 (resumable)
.venv\Scripts\python.exe -m calibration.cli extract-snapshots    # Stage 3
.venv\Scripts\python.exe _view_phase3_temp.py                    # quick DB summary
```
