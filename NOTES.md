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
