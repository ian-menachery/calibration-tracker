# calibration-tracker

A reproducible analysis of how well-calibrated Polymarket binary-market prices are, broken down by category and time-to-resolution.

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
