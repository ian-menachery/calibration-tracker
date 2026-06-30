# calibration-tracker

A reproducible analysis of how well-calibrated prediction-market prices are — Polymarket as the core dataset, with a Kalshi cross-venue check — broken down by category and time-to-resolution.

## Findings at a glance (v2: is there a tradable edge?)

- **What was measured.** Market calibration only — snapshot **price vs realized outcome** on resolved binary markets across **two venues** (Polymarket and Kalshi). **No model in the loop**; nothing predicts outcomes, we only check whether prices are honest.
- **The bias is real but small.** Polymarket shows a favorite-longshot bias (longshots resolve YES less often than priced): the recalibration slope is **b≈0.88 at 24h to close**, **b≈0.72 at 7 days**. As a trading rule it earns only **gross +1.7¢ per contract, which is wiped out by a 1–2¢ half-spread** — and it clears the eligibility bar in just two slices (**sports@24h** and **crypto@7d**). A measured, cost-fragile edge, **not a money printer**.
- **Cross-venue — not a universal law.** A pooled interaction test of the sports@24h slope (Polymarket 0.834 vs Kalshi 0.962) gives a difference of **b3 = 0.128, 95% CI [−0.034, 0.305]** — the interval **includes 0**, so the venue difference is **not statistically significant**. The bias is significant on Polymarket alone and not on Kalshi alone, but the two venues are statistically indistinguishable; venue/population-specificity is *suggested, not established*.
- **Method honesty.** The trading rule was **pre-registered** (`reports/frozen_rule_v1.json`) before any forward data, and is **forward-tested live** by a standing daily job ([`scripts/forward_daily.ps1`](scripts/forward_daily.ps1)) that logs realizable spread-crossed paper fills and reports **realized-minus-predicted edge** — so the "historical edge ≠ live edge" claim is checked, not asserted. Full design in [`ARCHITECTURE.md` §14](ARCHITECTURE.md).

## Headline finding

A week before resolution, Polymarket sports markets are barely better than coin flips. They sit a hair below the 0.25 chance-baseline (Brier 0.236 across 1,475 markets), while political and geopolitical markets at the same horizon carry real predictive signal (Brier 0.106 and 0.140 respectively). The split is the load-bearing result — the platform is *not* uniformly calibrated, and the divergence is overwhelmingly explained by category, not by trading volume.

## Findings

The full writeup — methodology, calibration curves at each horizon, by-category tables, by-volume tables, comparison to Polymarket's own published numbers, and caveats — lives at [`reports/v1_calibration.md`](reports/v1_calibration.md).

## How to reproduce

```bash
git clone https://github.com/ian-menachery/calibration-tracker
cd calibration-tracker
python -m venv .venv
.venv/Scripts/activate           # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

python -m calibration.cli discover --since 2024-01-01      # ~30 s
python -m calibration.cli fetch-tags                       # ~15 min
python -m calibration.cli fetch-prices                     # ~30 min
python -m calibration.cli extract-snapshots                # ~5 s
python -m calibration.cli analyze                          # ~30 s
```

Outputs land in `data/markets.db` (SQLite) and `reports/`.

## Repo structure

The pipeline runs in five independently-runnable, idempotent stages:

1. **discover** (`polymarket/discovery.py`) — pulls resolved binary markets ≥$1M volume from Polymarket's Gamma API into the `markets` table.
2. **fetch-tags** (`polymarket/tags.py`) — pulls each market's category tags from Gamma's `/events/{id}` endpoint into `market_tags`.
3. **fetch-prices** (`polymarket/prices.py`) — pulls full price history per market from Polymarket's CLOB API into `raw_price_history` at split fidelity (hourly across 14 days plus minute across the last 24 hours).
4. **extract-snapshots** (`analysis/snapshots.py`) — pure pandas; locates the closest tick to (resolution − 1h / 24h / 7d) and the close, writing to `price_snapshots`.
5. **analyze** (`analysis/calibration.py` + `metrics.py` + `reporting/charts.py`) — buckets markets by predicted price, computes per-bucket realized rate with bootstrap CIs, computes Brier and log loss overall and per category, saves PNGs and CSVs to `reports/`.

Storage helpers live in `src/calibration/storage/`. CLI entry point at `src/calibration/cli.py` (one subcommand per stage). 84 unit tests in `tests/`.

## Future work and roadmap

[`ROADMAP.md`](ROADMAP.md) lists deferred future work (Phase 6 multi-outcome decomposition, v2 modeling, Kalshi cross-platform). The project is intentionally finished at v1.1 — see [`reports/v1_calibration.md`](reports/v1_calibration.md) for the full writeup.

## Stack

Python 3.11+, [httpx](https://www.python-httpx.org/), [pandas](https://pandas.pydata.org/), [numpy](https://numpy.org/), [matplotlib](https://matplotlib.org/), [pydantic](https://docs.pydantic.dev/), [pytest](https://docs.pytest.org/), [ruff](https://docs.astral.sh/ruff/), and stdlib `sqlite3`.

## License

MIT — see [`LICENSE`](LICENSE).
