# KEEP_KILL.md — Audit of arb-scanner

Audited the old arb-scanner codebase before starting the calibration tracker.
Conclusion: nothing worth copying verbatim. The two projects have different
shapes — arb scans active markets across platforms; calibration analyzes
resolved markets on one platform. Carrying old code over would force more
refactoring than rewriting.

Original repo preserved at: Not preserved — old folder deleted locally without remote backup.

## File-by-file verdict

| File | Verdict | Reason |
|---|---|---|
| `kalshi_client.py` | KILL | Kalshi deferred to v2. Don't carry over preemptively. |
| `matcher.py` | KILL | Cross-platform fuzzy matching is not in scope. |
| `arbitrage.py` | KILL | Arb detection is out of scope. |
| `main.py` | KILL | Wrong pipeline shape. New entry point per ARCHITECTURE.md §7. |
| `models.py` | KILL | Wrong schema. Calibration needs resolved_outcome, end_date, and snapshot prices. |
| `config.py` | KILL | Trivial to rewrite. |
| `polymarket_client.py` | KILL (extract one lesson, see below) | Wrong API endpoints, wrong filter, wrong HTTP library. |
| `requirements.txt` | KILL | Wrong deps. New stack: httpx, pandas, numpy, matplotlib, sqlite3, pydantic, pytest. |
| `.env.example` | KILL | No credentials needed. Public Polymarket APIs only. |

## Knowledge worth preserving

One non-obvious thing from the old polymarket_client that the new client must
preserve:

**Polymarket returns `outcomePrices` and `outcomes` as JSON-encoded strings,
not arrays.** They look like `'["0.55", "0.45"]'` and `'["Yes", "No"]'`.
You have to call `json.loads` on them even though they came back from a
JSON response. The new client should add a comment about this where it
parses Gamma API responses.

## What's different about the new project

For reference when reading the old code:

- New project uses **resolved markets only** (`closed=true` filter), not active.
- New project hits the **CLOB API** (`prices-history` endpoint) for time series.
  The old code never used CLOB.
- New project uses **httpx**, not requests.
- New project's market model includes `resolved_outcome`, `resolved_value`,
  `end_date`, and ties to a `price_snapshots` table. None of that existed before.
- No more YES/NO price fields on the market model; those live in `price_snapshots`
  with a snapshot_type ('close' / '1h' / '24h' / '7d').

## Action

- [x] Delete local arb-scanner folder.
- [x] Begin Phase 1 in new repo from a clean slate.
