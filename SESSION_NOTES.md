# Session Notes

Per-session handoff: what got done, where things stand, what to pick up next.
For the running list of API gotchas and v2 considerations, see `NOTES.md`.

## 2026-05-08 — v1.1a started (real-categories foundation)

### Summary
Picked up the v1.1 work the v1 retrospective ranked #1: replace the
slug-heuristic categorization with Polymarket's own tags from Gamma's
`events` field. Shape probe mid-plan revealed `/markets` doesn't carry
tags — they only appear on `/events/{id}` — so the plan was revised to
add a new resumable `fetch-tags` stage between discover and fetch-prices,
mirroring the fetch-prices pattern. v1.1a landed the storage foundation
only.

### Current state
**Complete:**
- v1.1a: `market_tags(market_id, tag_slug)` side-table +
  `markets.gamma_event_id` column, both migrated via PRAGMA + ALTER
  TABLE; `Market` dataclass extended; `insert_market_tags` /
  `get_tags_for_market` / `markets_missing_tags` helpers;
  `_to_market` now captures `events[0].id`. 66/66 tests; ruff clean.
- Cleanup pass: removed `KEEP_KILL.md` (Phase 0 artifact) and four
  `_view_*_temp.py` scratch viewers.
- 4,532 markets (10 more resolved since the morning's full discover)
  all have `gamma_event_id` populated. `market_tags` table is empty
  until v1.1b runs.

**In-progress:** v1.1b (the new fetch-tags stage).

### Worth flagging
- v1.1 plan is in `~/.claude/plans/give-me-the-plan-cozy-snail.md`,
  updated mid-stream after the shape probe.
- v1.1b will run ~4,532 extra Gamma calls × 0.2 s = ~15 min of API
  time on the full backfill.
- v1.1c's writeup update will shift the per-category Brier numbers;
  the qualitative finding (sports much worse than politics at T-7d)
  is almost certainly robust.
- One new market has no `gamma_event_id` if its `events` array is
  empty — none observed yet but the model handles it (Market field is
  Optional, fetch-tags skips via `markets_missing_tags`).

### Next steps — v1.1b (fetch-tags stage)
1. New `src/calibration/polymarket/tags.py` —
   `fetch_event_tags(client, event_id) -> list[str] | None`. Hits
   `/events/{event_id}`, parses `tags[].slug`, returns slug strings.
   Catches `httpx.HTTPError` → None (resumable; matches prices.py).
2. CLI `fetch-tags` subcommand with `--db --limit --all`. Default
   mode reads `markets_missing_tags(conn)`.
3. Smoke test on 5 markets, full backfill on ~4,532, then commit.

### Useful commands
```
.venv\Scripts\python.exe -m pytest tests/ -q                                   # 66/66
.venv\Scripts\python.exe -m calibration.cli discover --since 2024-01-01        # idempotent; backfills gamma_event_id
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
