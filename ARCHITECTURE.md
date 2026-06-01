# Polymarket Calibration Tracker — Architecture

## 1. The Question

When Polymarket prices a binary market at X%, does YES resolve X% of the time?

Concretely: bucket every resolved market by its price at T minutes before resolution, compute the realized YES rate per bucket, and plot the result against the 45° line. Quantify miscalibration with Brier score and log loss. Break it down by category (politics, sports, crypto, etc.) and by how far before resolution the price snapshot was taken.

This is a real, citable analytical question. Existing public answers are sparse, dated, or methodologically thin. A clean dataset and a careful writeup is a portfolio piece worth having.

## 2. Goals and Non-Goals

**v1 goals:**
- Produce a reproducible dataset of resolved Polymarket markets with price snapshots at T-1h, T-24h, and T-7d before resolution.
- Compute calibration curves and scoring rules (Brier, log loss) overall and by category.
- Publish a writeup of the results with charts.
- Open-source the repo so the analysis is reproducible.

**v1 non-goals (defer to v2 or kill):**
- Kalshi data and cross-platform comparison. Adds API surface, normalization work, and a second resolution-semantics problem. v2.
- Live dashboard. Requires hosting, scheduled data collection, monitoring. v2 at earliest.
- Trading on miscalibration. Out of scope. Forever.
- Real-time updates. The dataset is built from resolved markets; nothing about this needs to be live.
- Sophisticated NLP for matching markets across categories. v1 uses Polymarket's own category tags.

**Explicit scope ceiling:** if the v1 codebase exceeds ~1,500 lines of Python, something has gone wrong. The analysis logic is small; most lines should be data plumbing.

## 3. The Critical Technical Risk (Address First)

The whole project depends on getting historical price snapshots for resolved markets. Polymarket's CLOB API exposes a `prices-history` endpoint that returns time series for a given token. Before writing anything else, verify:

1. The endpoint returns data going back at least 6 months for resolved markets.
2. Resolution is fine enough to extract a meaningful T-1h snapshot (i.e., not just daily candles).
3. The rate limit lets you fetch a few hundred markets without taking a week.

This is **Phase 1, the spike.** Write a 50-line script that pulls one resolved market's full price history and validates the above. If the data isn't usable, the whole architecture changes (e.g., switch to closing-price-only). Do not build the rest of the pipeline before confirming this.

## 4. Data Model

Three tables in SQLite. SQLite is correct for this — single-writer, file-based, the dataset is small enough that Postgres is overkill.

```
markets
  market_id          TEXT PRIMARY KEY     -- Polymarket condition_id or slug
  slug               TEXT
  question           TEXT
  category           TEXT                 -- from Polymarket's tags
  market_type        TEXT                 -- 'binary' or 'multi'
  parent_event_id    TEXT NULL            -- groups multi-outcome markets
  end_date           TIMESTAMP            -- resolution time
  resolved_outcome   TEXT                 -- 'YES', 'NO', or outcome name for multi
  resolved_value     REAL                 -- 1.0 for YES, 0.0 for NO
  total_volume_usd   REAL
  fetched_at         TIMESTAMP

price_snapshots
  market_id          TEXT
  snapshot_type      TEXT    -- 'close', '1h', '24h', '7d'
  price              REAL    -- YES probability in [0, 1]
  observed_at        TIMESTAMP
  PRIMARY KEY (market_id, snapshot_type)
  FOREIGN KEY (market_id) REFERENCES markets(market_id)

raw_price_history    -- raw cached time series, for debugging and re-derivation
  market_id          TEXT
  timestamp          TIMESTAMP
  price              REAL
  PRIMARY KEY (market_id, timestamp)
```

Multi-outcome markets are modeled as multiple rows in `markets` sharing a `parent_event_id`. Each outcome is its own binary YES/NO from a calibration standpoint ("does this candidate win"), which keeps the analysis math identical to the binary case. This is the right call — don't try to invent a separate calibration framework for multi-outcome.

## 5. Pipeline Stages

Each stage is a separate module that reads from and writes to SQLite. Stages are independently runnable, idempotent, and resumable. This matters because API failures will happen and you do not want to restart from scratch.

```
[1. discovery] ──► markets table (metadata only, no prices yet)
[2. price_fetch] ──► raw_price_history (full time series per market)
[3. snapshot_extract] ──► price_snapshots (the 4 snapshots per market)
[4. analysis] ──► dataframes, charts, metrics, and the markdown writeup
```

(The original design had a separate Stage 5 "report" module; in practice the writeup is hand-edited markdown that embeds the charts produced by stage 4, so there is no separate reporting stage.)

**Stage 1 — Discovery.** Hit Polymarket's Gamma API for resolved markets. Filter to markets that actually resolved (not canceled, not pending), have non-trivial volume (set a floor like $1k to filter joke markets), and fall in the time window. Store metadata only. Run this once weekly to catch newly resolved markets.

**Stage 2 — Price fetch.** For each market in `markets` that doesn't yet have full price history, hit `prices-history` and store the raw time series. Rate-limit aggressively — sleep between requests. Cache aggressively — never re-fetch a market you already have. This is the slow stage; expect it to take hours for the first full backfill.

**Stage 3 — Snapshot extract.** Pure SQL/pandas operation, no API calls. For each market, find the closest tick to (end_date − 1h), (end_date − 24h), (end_date − 7d), and the close. Write to `price_snapshots`. This is where you decide how to handle markets with sparse data — e.g., a market with only 3 days of history can't have a 7d snapshot. Mark it null and exclude it from the 7d cohort in analysis.

**Stage 4 — Analysis.** Pure pandas. Bucket markets by predicted price (10 buckets of width 0.1 is the standard; you'll want both decile buckets and finer 5% buckets). Compute realized rate per bucket. Compute Brier score and log loss overall and by subgroup. Bootstrap confidence intervals on the per-bucket realized rates because the bucket counts will be uneven.

**Stage 5 — Report.** Generate the writeup as a single markdown file with charts saved to `reports/figures/`. The writeup is a deliverable, not a side effect — treat it as the actual product.

## 6. Tech Stack (Minimal On Purpose)

```
Python 3.11+
httpx                 # API calls; better than requests for this
pandas, numpy         # analysis
matplotlib            # charts; static, embedded in markdown
sqlite3 (stdlib)      # storage
pydantic              # validate API responses; catches schema drift early
pytest                # tests
ruff                  # linting/formatting
```

That's it. Things that are tempting but you do not need for v1: FastAPI, Streamlit, Docker, Postgres, Redis, async anything beyond what httpx gives you, Airflow/Prefect, Pydantic Settings, dotenv. If Claude Code suggests adding any of these, push back and ask why.

## 7. File Structure

```
calibration-tracker/
├── README.md                 # what this is, how to run it, headline result
├── ARCHITECTURE.md           # this doc
├── CLAUDE.md                 # short instructions to Claude Code (see §11)
├── pyproject.toml
├── data/
│   ├── markets.db            # gitignored
│   └── cache/                # gitignored, raw API responses
├── reports/
│   ├── v1_calibration.md     # the writeup
│   └── figures/              # PNGs referenced by the writeup
├── src/calibration/
│   ├── __init__.py
│   ├── polymarket/
│   │   ├── client.py         # httpx wrapper + rate limiting
│   │   ├── discovery.py      # Stage 1
│   │   └── prices.py         # Stage 2
│   ├── storage/
│   │   ├── schema.sql        # CREATE TABLE statements
│   │   └── repository.py     # read/write helpers, no business logic
│   ├── analysis/
│   │   ├── snapshots.py      # Stage 3
│   │   ├── calibration.py    # bucketing, realized rates
│   │   └── metrics.py        # Brier, log loss, bootstraps
│   ├── reporting/
│   │   └── charts.py         # matplotlib chart functions
│   └── cli.py                # one entry point per stage
└── tests/
    ├── test_calibration.py   # the math has to be right
    ├── test_snapshots.py
    └── test_repository.py
```

The CLI is one argparse command per stage:
```
calibration discover --since 2024-01-01
calibration fetch-tags
calibration fetch-prices
calibration extract-snapshots
calibration analyze
```

(A `fetch-tags` stage was added during implementation to pull per-market category tags from Gamma's `/events/{id}` endpoint into a `market_tags` table; this isn't in the original data model above but is part of the shipped pipeline. The originally-planned `report` stage was folded into `analyze` — see §5.)

This matters because resumability and observability come from being able to run stages independently and inspect the DB between them.

## 8. Testing Posture

Write tests for the math, not the API. Specifically:
- `metrics.py` — known inputs, known Brier scores. This is non-negotiable; if the metric code is wrong, the whole writeup is wrong.
- `calibration.py` — edge cases on bucketing (price exactly at boundary, bucket with zero markets, etc.).
- `snapshots.py` — what happens when a market has no data at T-7d? When end_date is in the future? When timestamps are unsorted?

Don't test API clients with mocks. They rot. Just hit the real API in a manual smoke test occasionally.

## 9. Phased Rollout

| Phase | Goal | Done when |
|------|------|-----------|
| 0 | Read existing arb scanner, decide what to keep | `KEEP_KILL.md` written, dead code deleted |
| 1 | API spike: confirm `prices-history` is usable | One resolved market's full series printed, viability confirmed |
| 2 | Stage 1 + storage | `markets` table populated with ~1000 resolved binary markets |
| 3 | Stage 2 + 3 | Price snapshots exist for those markets |
| 4 | Stage 4 (binary only) | Calibration curve chart exists, Brier score computed |
| 5 | First writeup draft | `reports/v1_calibration.md` exists, postable |
| 6 | Multi-outcome support | Multi-outcome markets included in dataset |
| 7 | Polish + publish | README, repo public, writeup posted |
| --- | --- | --- |
| v2 (deferred) | Kalshi | New data source, comparison analysis |
| v2 (deferred) | Dashboard | Streamlit, hosted, auto-updating |

Phase 0 → Phase 5 is the realistic v1. Estimate honestly: 4-8 weekends of focused work. If you're past week 4 and still on Phase 2, something's wrong — stop and rescope.

## 10. What to Do With the Existing Arb Scanner

*Historical: this was Phase 0 work, completed before the codebase reached its current shape. The `KEEP_KILL.md` file referenced below was removed once Phase 0 was done; the verdicts in the table are preserved here as a record of what was decided.*

You said you don't remember what's in it. Step zero is opening it and writing `KEEP_KILL.md` — one line per file, classifying it as KEEP / ADAPT / KILL. Do this *before* asking Claude Code to do anything else.

Likely classifications:

| Existing code | Verdict | Why |
|---|---|---|
| Polymarket API client/auth | KEEP / ADAPT | Reuse if it exists; arb scanner needed market data too |
| Rate limiting helpers | KEEP | Generic, reusable |
| Market metadata fetcher | ADAPT | Probably wrong filters, but the shape is right |
| SQLite schema for markets | ADAPT | Schema in this doc supersedes whatever's there |
| Kalshi client | KILL (for now) | Not needed v1; archive in a branch |
| Cross-platform matcher | KILL | Whole concept is gone |
| Spread calculator | KILL | Whole concept is gone |
| Order book handling | KILL | Don't need order book data, only trade prices |
| Alert system | KILL | No alerts in this project |
| Real-time/streaming code | KILL | Project is batch over resolved markets |

Rule for KILL: delete the code, don't comment it out. If you want to preserve it, that's what git history is for. Commented-out code becomes stale and confusing within a week.

## 11. CLAUDE.md (separate file, short)

Write a short `CLAUDE.md` at the repo root with these instructions for Claude Code:

```
This is a calibration analysis project. See ARCHITECTURE.md for the full design.

Rules:
- No new dependencies without checking. Tech stack is locked (see §6 in ARCHITECTURE.md).
- One stage at a time. Do not modify multiple pipeline stages in a single change.
- The math in src/calibration/analysis/ MUST have unit tests. No exceptions.
- Storage logic stays in src/calibration/storage/. No raw SQL outside that module.
- API calls stay in src/calibration/polymarket/. No requests/httpx imports elsewhere.
- Before writing code: state the plan in 3-5 sentences and wait for confirmation.
- Prefer editing existing functions over creating new files.
- If you find yourself adding > 100 lines in one go, stop and ask.
```

This is the AI-slop firewall. The "state the plan first" rule especially — it's the single highest-leverage thing for keeping the codebase comprehensible to you.

## 12. Open Questions / Decisions Deferred

These are real but don't block starting:

1. **Volume floor for inclusion.** $1M for v1. (Original guess of $1k was unworkable: Gamma's `/markets` caps pagination at offset=100,000 and Polymarket has >100k closed markets above $1k volume.) Biases v1 toward elections/crypto/major sports — flag in writeup. v2 may revisit the floor based on what v1's category distribution actually looks like.
2. **How to handle markets that resolved by Polymarket's UMA dispute process.** Probably exclude — they're a different population. Tag in metadata, decide at analysis time.
3. **Bootstrap method for confidence intervals.** Standard nonparametric bootstrap on bucket realized rates is fine for v1. Wilson intervals are an alternative; don't overthink.
4. **Time zones.** Polymarket timestamps are UTC. Store everything UTC. Do not convert until display.
5. **Multi-outcome categorization.** Some "events" have many outcomes (e.g., 20+ for "who wins the election"). Decide whether to include all or cap at top-N by volume. Default: include all but flag in metadata.

## 13. Headline Risks (Watch For These)

1. **The price-history API returns thinner data than expected.** Mitigation: Phase 1 spike. If true, fall back to closing-price-only and one earlier snapshot if available.
2. **Resolved markets are biased toward elections + crypto.** Calibration on these may not generalize. Mitigation: be explicit about category breakdown in the writeup; don't claim a universal result.
3. **Selection bias on which markets exist.** Polymarket only lists markets people want to bet on; "popular" markets may be more or less calibrated than rare ones. Mitigation: acknowledge in the writeup, cohort by volume.
4. **Volume-weighted vs market-weighted calibration.** Both are interesting. v1: report both, pick one for the headline chart based on what's more legible.
5. **Scope creep into trading.** If you find yourself thinking "huh, the 80% bucket is actually 73%, that's exploitable" — don't. That's a different project that loses money. Stay analytical.
