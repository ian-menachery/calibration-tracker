# Polymarket Calibration Tracker — Project Context

## What I'm building

A data analysis project that answers: when Polymarket prices a binary market at X%, does YES resolve X% of the time?

Concretely: pull resolved Polymarket markets, capture price snapshots at T-1h, T-24h, T-7d before resolution, bucket markets by predicted price, compute realized YES rate per bucket, plot against the 45° line. Add Brier score and log loss, broken down by category and time-to-resolution.

**v1 deliverables:** a writeup with charts + the GitHub repo (the repo IS the reproducibility layer).

**v2 (deferred, do not build now):** Kalshi data + cross-platform comparison, live dashboard, real-time updates, anything related to actually trading on the results.

## Why this project, why now

- I'm a junior at Northeastern (Data Science + Econ), incoming EY Tech Consulting SAP intern Summer 2026.
- Original project was a Kalshi/Polymarket arbitrage scanner. Pivoted because retail arb in these markets is competitive and the realistic ceiling is "lose money slowly." Calibration analysis is a better fit: it's a real analytical question, my stats/econ background applies, and a clean writeup is a portfolio piece that travels.
- This is meant to be a publishable result (a blog post / Twitter thread / GitHub repo), not a product or a money-maker.

## My problem: AI slop

My main failure mode on past projects: I let the LLM write code, accept it without fully understanding it, and within 2 weeks the codebase is incomprehensible to me. The whole project structure is built to fight this.

## Rules for working with Claude Code (these are in CLAUDE.md too)

**The most important rule:** Before writing or modifying code, Claude Code states the plan in 3-5 sentences and waits for confirmation. No exceptions, even for "small" changes. If I find myself approving 100+ lines of code in one shot, something has gone wrong.

**Anti-slop discipline:**
- One pipeline stage at a time. Don't modify multiple stages in one change.
- New files require justification. Prefer editing existing functions.
- If I can't explain a function, it doesn't go in the repo.
- After every working piece: `git diff` to actually read what changed, then commit with a meaningful message.
- No commented-out code. Delete it. Git history preserves it.
- No mocks for the Polymarket API — they rot. Manual smoke tests against the real API are fine.

**Tech stack is locked:** httpx, pandas, numpy, matplotlib, sqlite3, pydantic, pytest, ruff. No FastAPI, Streamlit, Docker, Postgres, Redis, Airflow, dotenv, or async beyond what httpx provides. If Claude Code suggests adding something, I push back and ask why.

**Module boundaries:**
- HTTP/API calls live in `src/calibration/polymarket/`. No httpx imports anywhere else.
- Storage logic in `src/calibration/storage/`. No raw SQL outside.
- Math in `src/calibration/analysis/` MUST have unit tests.

**Scope ceiling:** if v1 codebase exceeds ~1,500 lines of Python, something has gone wrong.

## Architecture summary

Five pipeline stages, each a separate module that reads/writes SQLite. Stages are independently runnable, idempotent, resumable.

```
[1. discovery]        ──► markets table (metadata for resolved markets)
[2. price_fetch]      ──► raw_price_history (full time series per market)
[3. snapshot_extract] ──► price_snapshots (4 snapshots per market)
[4. analysis]         ──► dataframes, charts, metrics
[5. report]           ──► markdown writeup with embedded charts
```

CLI: one entry point per stage (`calibration discover`, `calibration fetch-prices`, etc.).

**Data model:** three SQLite tables — `markets`, `price_snapshots`, `raw_price_history`. Multi-outcome markets modeled as multiple rows in `markets` sharing a `parent_event_id`; each outcome is its own binary YES/NO from a calibration standpoint.

## Phased rollout

| Phase | Goal | Done when |
|------|------|-----------|
| 0 | Read existing arb scanner, decide what to keep | KEEP_KILL.md written |
| 1 | API spike: confirm `prices-history` is usable | One market's full series printed, viability confirmed |
| 2 | Stage 1 + storage | `markets` table populated with ~1000 resolved binary markets |
| 3 | Stage 2 + 3 | Price snapshots exist for those markets |
| 4 | Stage 4 (binary only) | Calibration curve chart exists, Brier score computed |
| 5 | First writeup draft | `reports/v1_calibration.md` exists, postable |
| 6 | Multi-outcome support | Multi-outcome markets included in dataset |
| 7 | Polish + publish | README, repo public, writeup posted |

Realistic v1 timeline: 4-8 weekends. If past week 4 and still on Phase 2, stop and rescope.

## Decisions already made

- **Polymarket only for v1.** Kalshi is v2. Adding both at once doubles the data engineering work.
- **Binary + simple multi-outcome.** No scalar/range markets in v1.
- **Multiple snapshots (T-1h, T-24h, T-7d).** Riskier than closing-price-only, but produces a more interesting analysis (markets get more accurate as resolution approaches — by how much?).
- **Output is writeup + GitHub repo.** No dashboard in v1. Build the dashboard in v2 only if the writeup result generates "is this still true today?" demand.
- **Manual file inventory of old code, not automated.** I write KEEP_KILL.md by hand because the point is forcing me to look at my own code.

## Critical technical risk

The whole project depends on Polymarket's CLOB `prices-history` endpoint returning sub-hourly resolution going back at least 6 months for resolved markets. **Phase 1 is a spike to validate this before building anything else.** If the data is too sparse, the architecture changes (fall back to closing-price-only).

## Polymarket API gotchas (already learned)

- Gamma API returns `outcomePrices`, `outcomes`, and `clobTokenIds` as **JSON-encoded strings**, not arrays. Have to call `json.loads` on them even though they came back from a JSON response.
- `prices-history` (CLOB API) takes a token ID, not a market slug or condition_id. Lookup path: slug → Gamma → `clobTokenIds` → token ID → CLOB.
- For binary markets, the YES token is the first ID in `clobTokenIds`.

## Headline risks to watch

1. **Price-history API thinner than expected.** Mitigation: Phase 1 spike. Fall back to closing-price-only if needed.
2. **Resolved markets biased toward elections + crypto.** Calibration may not generalize. Mitigation: be explicit about category breakdown; don't claim universal results.
3. **Selection bias on which markets exist.** Polymarket only lists markets people want to bet on. Mitigation: acknowledge in writeup, cohort by volume.
4. **Volume-weighted vs market-weighted calibration.** Both are interesting. v1: report both, pick one for the headline.
5. **Scope creep into trading.** If I find myself thinking "this bucket is mispriced, I could trade it" — different project, loses money, stay analytical.

## My environment

- Windows, PowerShell, project at `C:\Users\ianme\projects\calibration-tracker`.
- Python venv at `.venv\` (activate with `.venv\Scripts\activate`).
- Repo initialized with git. Files committed: ARCHITECTURE.md, CLAUDE.md, KEEP_KILL.md, .gitignore, requirements.txt.
- Old arb-scanner pushed to private GitHub repo, local folder deleted.
- Will use Claude Code (CLI) for actual development, ideally inside VS Code's integrated terminal.

## Communication preferences

- I prefer direct, no-fluff communication. Push back when I'm wrong.
- I'm a DS/Econ junior, not a software engineer. Explain things at that level — assume I know stats and Python basics, be patient with software engineering conventions.
- When I propose scope expansions, default to "is this scope creep?" and call it out if it is.
- If I ask whether to combine two things or build them in parallel, the answer is almost always no. Force me to do one at a time.
- Bias toward starting smaller than I think.

## Files in the repo

- `ARCHITECTURE.md` — full design (data model, pipeline, file structure, phasing, risks). The reference doc.
- `CLAUDE.md` — persistent instructions for Claude Code (read automatically every session).
- `KEEP_KILL.md` — audit of the old arb-scanner project documenting why nothing was carried over.
- `.gitignore`, `requirements.txt` — standard project files.

## Current status

Phase 1 in progress. About to run the spike on Polymarket's `prices-history` endpoint using the 2024 Trump election market as the test case.
