# Session Notes

Per-session handoff: what got done, where things stand, what to pick up next.
For the running list of API gotchas and v2 considerations, see `NOTES.md`.

## 2026-05-08 — v1.1 done (tag-based categorization shipped)

### Summary
Replaced the v1 slug-heuristic categorizer with Polymarket's own `tags`
taxonomy via the Gamma `/events/{id}` endpoint. Three sub-commits in
one session: **v1.1a** (storage foundation: `market_tags` table +
`markets.gamma_event_id` migration + repo helpers), **v1.1b** (new
resumable `fetch-tags` stage; full backfill of 4,527 markets in
~15 min — 20,267 tag rows, 744 distinct slugs, 0 errors), **v1.1c**
(`_CATEGORY_MAPPING` + flipped `load_calibration_frame` to use tags
with slug-heuristic fallback). Re-ran `analyze`, refreshed the
writeup and README. Headline holds: sports T-7d Brier 0.238 → 0.236,
politics 0.116 → 0.106; the "other" bucket shrank from 370 to 83 at
T-7d (the v1.1 win).

### Current state
**Complete:**
- v1.1 fully shipped. Five commits pushed:
  `4a2240f` (v1.1a storage),
  `0051983` (v1.1b fetch-tags),
  `764fb0e` (v1.1c analyze flip + writeup),
  `f9918cd` (CLAUDE.md phase marker),
  plus the v1.1 docs commit landing now.
- 84/84 tests pass; ruff clean.
- 4,532 markets all have `gamma_event_id` + at least one tag.
- Public repo at github.com/ian-menachery/calibration-tracker reflects
  the v1.1 numbers in both README and writeup.

**In-progress:** none. v1.1 is done.

### Worth flagging
- Headline finding is robust to the categorization swap. Numbers moved
  by ~0.01-0.02 across categories; the qualitative story didn't shift.
- Entertainment cohort at T-7d went 0.077 → 0.154 with n=20 — flagged
  in the writeup as small-sample noise.
- `_CATEGORY_MAPPING` is conservative (~30-50 known tags per bucket,
  curated from the top 25 most common slugs). The long-tail mapping
  could be refined as part of any future v1.2 polish.
- `categorize_slug` + `_CATEGORY_PATTERNS` are kept as the fallback
  path for markets whose tags only match meta-slugs.
- One throwaway file at root: `phase1_spike.py` — kept by user request
  as a Phase 1 reference.

### Next steps (v2 backlog, no work in flight)
1. **Phase 6: multi-outcome / negRisk decomposition.** Adds the Trump
   2024 election ($1.5B in volume, currently excluded) and other big
   multi-candidate events. Largest single dataset expansion. 1-2
   weekends.
2. **Hit-rate metric** for apples-to-apples comparison with
   Polymarket's accuracy page (their 96.7% / 90.4% headline). ~1 hour.
3. **More horizons** (4h / 12h / 1mo) to match Polymarket's set. The
   1mo horizon needs Stage 2 to chunk past CLOB's 14-day window cap.
4. **Lower volume floor** to ~$100k for category diversity. Would need
   chunked discovery to fit under Gamma's 100k offset cap.
5. **GitHub Actions CI** running `pytest` on push (~30 min of work).
6. **Kalshi cross-platform comparison** (deferred to v2 — biggest scope).

### Useful commands
```
.venv\Scripts\python.exe -m pytest tests/ -q                                   # 84/84
.venv\Scripts\python.exe -m calibration.cli analyze --db data/markets.db       # rerun stage 4
.venv\Scripts\python.exe -m calibration.cli fetch-tags --db data/markets.db    # idempotent v1.1b
```

## 2026-05-08 — v1 shipped (Phases 4, 5, 7 done; repo public)

### Summary
Closed v1 end-to-end. Phase 4 produced the calibration analysis (overall
Brier 0.0001 / 0.0018 / 0.163 / 0.185 across close / 1h / 24h / 7d; headline
finding is sports at T-7d at Brier 0.238 — near the 0.25 chance baseline —
while politics and geopolitics carry real signal at 0.116 / 0.129).
Phase 5 landed the ~1,700-word writeup at `reports/v1_calibration.md` with
embedded charts. Phase 7 wrapped: README + MIT LICENSE, writeup polish
pass, Polymarket-comparison amendment after the user surfaced
<https://polymarket.com/accuracy>, and repo flipped public at
<https://github.com/ian-menachery/calibration-tracker>.

### Current state
**Complete:**
- All v1 phases (0 → 7). Pipeline, analysis, writeup, README, public repo.
- 61/61 tests pass; `ruff check src tests` clean.
- `data/markets.db` (4,522 markets, 7.16 M ticks, 16,341 snapshots) intact.
- All commits pushed to `origin/main`; working tree clean.

**In-progress:** none. v1 is shipped.

### Worth flagging
- **Posting the writeup** is the last item from ARCHITECTURE.md §9 done-when
  for Phase 7 ("writeup posted"). User action — HN, X, blog of choice.
- **One missing market** (4,522 of 4,523 carry price history) — left over
  from the transient HTTPError mid-backfill on 2026-05-07. Pickable up by
  another `--resume` run; wasn't worth re-running for 0.02 % of the dataset.
- **Throwaway viewer scripts** still in working tree (gitignored): four
  `_view_*_temp.py` files. Safe to delete any time.
- **Polymarket comparison** in the writeup names what's novel here vs
  their official accuracy page (category breakdown, log loss, bootstrap
  CIs, open code) — this is what makes the post non-redundant.
- **v2 backlog** lives in `NOTES.md` `## v2 Considerations`: lower volume
  floor to ~$100k for category diversity, replace slug-heuristic
  categorizer with Gamma `events` tags, plus Phase 6 (multi-outcome /
  negRisk decomposition) and Kalshi cross-platform comparison.

### Next steps
1. **Post the writeup** (HN: "Show HN: …", X thread leading with the
   T-7d sports-vs-everything-else finding + the chart, or personal blog).
2. *(Optional)* **Phase 6** — multi-outcome decomposition. Adds the Trump
   2024 election ($1.5 B in volume, currently excluded) and other big
   multi-candidate events to the dataset. Largest single expansion.
3. *(Optional)* **Replace slug heuristic** with Gamma `events` tags —
   cleaner category breakdown for v1.1.
4. *(Optional)* **Lower volume floor** to ~$100k — broadens category
   coverage; requires chunking discovery to fit under Gamma's 100k offset
   cap. Pair with #3 above.
5. *(Optional)* **Add hit-rate metric** to `analyze` so the writeup can
   compare apples-to-apples with Polymarket's reported 96.7% / 90.4%.

### Useful commands
```
.venv\Scripts\python.exe -m pytest tests/ -q                                   # run tests (61)
.venv\Scripts\python.exe -m calibration.cli analyze --db data/markets.db       # rerun stage 4
.venv\Scripts\python.exe _view_phase3_temp.py                                  # quick DB summary
```

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
