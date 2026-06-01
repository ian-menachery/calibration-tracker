# Instructions for Claude Code

This is a Polymarket calibration analysis project. The full design is in `ARCHITECTURE.md` — read it before doing anything substantive.

## The single most important rule

**Before writing or modifying code, state the plan in 3–5 sentences and wait for confirmation.** No exceptions, even for "small" changes. If I say "go ahead" or "looks good," then implement. If I push back, revise the plan — do not start coding while I'm pushing back.

This is non-negotiable. If you find yourself drafting code in your head before stating a plan, stop and state the plan first.

## Scope rules

- One pipeline stage at a time. Do not modify code in multiple stages (`polymarket/`, `analysis/`, `reporting/`, etc.) in the same change.
- If a single change adds more than ~100 lines of new code, stop and ask whether to split it.
- Prefer editing existing functions over creating new files. New files require justification.
- No new dependencies without asking. The locked stack is in ARCHITECTURE.md §6: httpx, pandas, numpy, matplotlib, sqlite3, pydantic, pytest, ruff. Anything else needs a reason and my approval.

## Module boundaries (enforce these)

- Storage logic stays in `src/calibration/storage/`. No raw SQL outside that module.
- HTTP/API calls stay in `src/calibration/polymarket/`. No `httpx` or `requests` imports anywhere else.
- The math in `src/calibration/analysis/` MUST have unit tests in `tests/`. Brier scores, calibration buckets, and bootstrap intervals all need known-input tests.
- No business logic in `repository.py`. It only reads and writes; analysis decisions live in `analysis/`.

## Things you should not do

- Do not add infrastructure speculatively. No FastAPI, Streamlit, Docker, Postgres, Redis, async beyond what httpx provides, Airflow, Prefect, or dotenv unless I ask.
- Do not "clean up" code I didn't ask you to clean up. If you see something off, mention it; don't fix it silently.
- Do not write mocks for the Polymarket API. They rot. Manual smoke tests against the real API are fine.
- Do not comment out dead code. Delete it. Git history preserves it.
- Do not invent data. If an API call fails or a market has no data at T-7d, surface that — never fill with zeros or estimates without asking.

## Things you should do

- After each substantive change, suggest a commit message. Short, imperative, describes what changed and why (e.g. "phase 1 spike: confirm prices-history returns minute-level data").
- When you finish a piece of work, summarize what changed in 2-3 sentences. I'll update my notes from your summary.
- If you're unsure whether something belongs in v1, default to "ask before adding." v2 features (Kalshi, dashboard, real-time) are explicitly deferred — flag them if you find yourself reaching for them.
- If you discover something in the data that contradicts ARCHITECTURE.md (e.g. the price-history API works differently than assumed), stop and tell me. Do not silently work around it.

## Phase awareness

Always know which phase from ARCHITECTURE.md §9 we're in. If a request seems to belong to a later phase, say so and ask whether to skip ahead or stay focused.

Current phase: **v1.1 — final state of v1.x** (Phase 7 + tag-based categorization, shipped publicly). Headline holds: sports T-7d Brier 0.236, politics 0.106. 84/84 tests; ruff clean. Future work is documented in `ROADMAP.md` and is deferred indefinitely — the project is intentionally finished, not abandoned.
