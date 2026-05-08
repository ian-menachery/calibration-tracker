# Project Notes

Operational facts and gotchas discovered while building. Append-only; date entries
so we know when they were learned.

## API Gotchas

### Gamma /markets defaults to active markets only
Discovered: 2026-05-06, Phase 1 spike
Querying for resolved markets requires `closed=true`. Without it, the
endpoint returns an empty array even for a valid slug. Will matter for
Stage 1 discovery — the resolved-markets query must include this filter.

### endDate is scheduled, not actual
Discovered: 2026-05-06, Phase 1 spike
Gamma's `endDate` field is when the market was scheduled to end, not
when it resolved. For snapshot anchoring (T-1h, T-24h, T-7d), use
`umaEndDate` or `closedTime` instead — these reflect actual resolution.
For the Trump 2024 market: endDate=2024-11-05T12:00:00Z but actual
resolution was 2024-11-06T15:17:41Z, a 27-hour gap.

### CLOB prices-history caps the time window (~14 days)
Discovered: 2026-05-06, Phase 1 spike
A `startTs`/`endTs` window longer than ~14 days returns 400 regardless of `fidelity`.
14 days at fidelity=1 (1-min resolution, ~20k ticks) returns in ~1.2s. Stage 2 must
chunk full-history fetches by no more than 14-day spans.

### CLOB `interval=max|1d|1h` returns empty for resolved markets
Discovered: 2026-05-06, Phase 1 spike
Calling prices-history with `interval=max` (or `1d`, `1h`) on a resolved-market
token returns 200 with `history: []`. Use a `startTs`/`endTs` window instead.
Unclear whether this is a bug or intended; not investigated further since
windowed fetch works.

### Gamma market start date != first CLOB tick
Discovered: 2026-05-06, Phase 1 spike
A market's listing/start date in Gamma is not the same as the earliest CLOB
tick. Trump 2024 was listed 2024-01-04 per Gamma but the first CLOB tick
is around 2024-01-31 (probe at 2024-01-04 returned 0 ticks; probe at
2024-02-01 returned 24 ticks with the earliest at 2024-01-31T19:00:02Z).
Stage 1 must derive snapshot-eligibility from CLOB data, not from Gamma's
start date field — otherwise we'll over-count markets as having T-7d data.

### CLOB drops connections occasionally during long backfills
Discovered: 2026-05-07, Phase 3 backfill
Mid-run, the CLOB `/prices-history` endpoint occasionally drops the
connection without sending a response (httpx.RemoteProtocolError). It is
NOT a 4xx/5xx response — it's a connection-level disconnect, so catching
only httpx.HTTPStatusError will let it escape and kill the run. Catch
httpx.HTTPError (the base class — covers HTTPStatusError, ConnectError,
ReadTimeout, RemoteProtocolError, etc.). Per-market commits plus
INSERT OR IGNORE mean partial progress is saved; --resume picks up
missing markets on the next run. The full 4513-market backfill survived
exactly one such drop (4512 fetched, 1 skipped).

### Gamma did not persist clob_token_ids in the markets table (Phase 2 oversight)
Discovered: 2026-05-07, before Phase 3b
ARCHITECTURE.md sec 4 doesn't list a token column on the markets table,
so Phase 2's discovery -> Market mapper dropped `clob_token_ids[0]`.
Stage 2 needs that token to call /prices-history. Fixed in commit 3a-fix
(see git log) by adding a nullable `yes_token_id TEXT` column with an
ad-hoc ALTER TABLE migration in init_db, then re-running discover to
backfill existing rows. Future schema additions can follow the same
pattern (PRAGMA table_info check + ALTER TABLE ADD COLUMN).

## Session log

### 2026-05-06
Closed Phase 0 (KEEP_KILL audit), completed Phase 1 spike (prices-history viable,
all three ARCHITECTURE.md sec 3 checks PASS, pushed to private GitHub), and shipped
the first two of three Phase 2 commits — 2a: storage layer with markets table and
6 passing tests; 2b: GammaClient + GammaMarket pydantic model + raw fetcher.
Phase 2c is mid-flight: `cli.py` and `discover_markets()` filter+map are written
but the end-to-end backfill blew up against Gamma's offset=100,000 pagination cap,
because Polymarket has >100k closed markets above $1k volume — the original
ARCHITECTURE.md sec 12.1 $1k floor is far too low.
Immediate next step: pick a volume-floor option (recommended A = $1M floor,
yields ~5k fetched / ~1.5–2.5k binary kept after filter), update CLI default and
probably ARCHITECTURE.md sec 12.1, then re-run and commit 2c.
Volume floor chosen: $1M, with category-bias caveat to be acknowledged in writeup.

### 2026-05-08
Shipped v1 end-to-end. Phase 4 (Stage 4 calibration analysis) landed in
three commits — 4a (`metrics.py`: brier_score, log_loss, bootstrap_ci with
13 known-input tests), 4b (`calibration.py`: load_calibration_frame, slug-
heuristic categorize_slug, bucket / bucket_decile / bucket_5pct with both
market- and volume-weighting, 25 tests), 4c (`reporting/charts.py` +
`analyze` CLI subcommand). End-to-end run on the 4,522-market dataset
produced overall Brier 0.0001 / 0.0018 / 0.163 / 0.185 across close / 1h /
24h / 7d. **Headline finding:** sports at T-7d sit at Brier 0.238 (near
the 0.25 chance baseline) while politics and geopolitics carry real signal
at 0.116 and 0.129. Sports is also 54.5% of the dataset by count, so the
overall T-7d number is dragged toward the sports number — the category
breakdown is the load-bearing slice. Phase 5 landed the writeup
(reports/v1_calibration.md, ~1,700 words, embeds the four PNGs from
Phase 4). Phase 7 closed v1: README + MIT LICENSE, polish pass on the
writeup (correctness fixes against calibration_metrics.csv — date typo,
volume-quartile boundaries, "other" percentage from a guessed 20-30% to
the measured 16%, "bars" → "buckets" wording), Polymarket-comparison
amendment after the user surfaced https://polymarket.com/accuracy as
directly comparable prior work, and repo flipped public at
github.com/ian-menachery/calibration-tracker. 61/61 tests pass; ruff
clean. Posting to HN/X/blog is the last ARCHITECTURE.md §9 done-when item
and is a user action — everything else is shipped.

### 2026-05-07
Wrapped Phase 3: Stages 2-3 implemented, tested, and backfilled end-to-end.
data/markets.db now holds 4,522 markets (7.16M raw ticks at hourly+minute
split fidelity, ~700 MB) plus 16,341 snapshots in price_snapshots — 100%
of markets have at least one snapshot, 64.2% have all four (the 7d slot is
the constraint, expected for sports / short-duration markets). Six new
commits on main: 3a (schema + repo helpers), 3a-fix (yes_token_id retro-
add — Phase 2 dropped clob_token_ids; see new gotcha above), 3b (CLOB
client + fetch-prices CLI), 3b-fix (broaden to httpx.HTTPError after a
RemoteProtocolError mid-backfill; see new gotcha above), 3c (snapshot
extraction in src/calibration/analysis/snapshots.py with 7 unit tests),
plus this docs commit. Headline preview at T-1h: 2,579 markets priced
[0.0, 0.1) realized 0.0% and 1,914 markets priced [0.9, 1.0) realized
99.9% — extreme-bucket calibration looks essentially perfect, but middle
buckets are very thin (5-6 markets each) since most markets have already
collapsed to ~0 or ~1 by the final hour. The interesting calibration
tension will live at T-7d, which is Phase 4 territory. Three throwaway
viewer scripts left untracked in the working tree (_view_markets_temp.py,
_view_snapshots_temp.py, _view_phase3_temp.py) — useful for ad-hoc DB
inspection but not load-bearing; safe to delete or keep.

## v2 Considerations

### Lower volume floor to $100k for category diversity
The v1 $1M floor heavily concentrates the dataset in elections, crypto, and major
sports. v2 should consider lowering to $100k (likely chunking discovery by
end_date_max windows to fit under Gamma's 100k offset cap) for broader category
coverage.

### Replace slug-heuristic categorization with Gamma `events` tags
Phase 4's `categorize_slug` is a regex/prefix heuristic (sports / politics /
geopolitics / crypto / entertainment / other). It's coarse — markets that
don't match a known prefix land in "other" (~16% of the dataset on the v1
data, lower than the 20-30% I'd guessed before measuring). There's also
likely some leakage between the named categories (e.g. an Iran-sanctions
market might match the `politics` regex before `geopolitics` because order
matters in `_CATEGORY_PATTERNS`). v2 should backfill from Gamma's `events`
field, which contains Polymarket's own category tags. Will require:
(1) ALTER TABLE markets ADD COLUMN tags TEXT (or a separate market_tags
table), (2) re-run discover with the events field captured by the
GammaMarket pydantic model, (3) flip `analyze` to read canonical tags
instead of calling categorize_slug. Math layer stays the same.
