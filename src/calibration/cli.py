"""calibration command-line entry point. One subcommand per pipeline stage."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from calibration.analysis.calibration import (
    bucket_5pct,
    bucket_decile,
    compute_metrics,
    load_calibration_frame,
)
from calibration.analysis.calibration import categorize_slug
from calibration.analysis.edge import (
    fractional_kelly,
    kelly_fraction,
    side_for,
    simulate_position,
    vwap_fill,
)
from calibration.analysis.recalibration import (
    apply_recalibration,
    predict_band,
    recalibrated_brier,
    recalibration_by_group,
    recalibration_with_ci,
)
from calibration.analysis.snapshots import extract_snapshots
from calibration.kalshi.candles import fetch_market_candles
from calibration.kalshi.client import KalshiClient
from calibration.kalshi.discovery import KALSHI_SERIES, fetch_settled_markets
from calibration.polymarket.client import GammaClient
from calibration.polymarket.discovery import (
    discover_markets,
    fetch_markets_by_ids,
    fetch_open_markets,
)
from calibration.polymarket.prices import CLOBClient, fetch_market_history, fetch_order_book
from calibration.polymarket.tags import fetch_event_tags
from calibration.reporting.charts import plot_calibration_curve
from calibration.storage.repository import (
    ForwardSignal,
    get_market,
    get_ticks_for_market,
    init_db,
    insert_market_tags,
    insert_price_ticks,
    insert_signals,
    mark_signal_resolved,
    markets_missing_created_at,
    markets_missing_history,
    markets_missing_tags,
    markets_with_history,
    min_tick_per_market,
    open_signals,
    set_market_created_at,
    upsert_markets,
    upsert_snapshots,
)

SNAPSHOT_TYPES = ("close", "1h", "24h", "7d")


def cmd_discover(args: argparse.Namespace) -> int:
    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc)
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Discovering markets since {since.date()} (volume floor=${args.volume_floor:.0f}) ...")
    with GammaClient() as client:
        markets, stats = discover_markets(client, since=since, volume_floor=args.volume_floor)
    print(f"Fetched {stats.fetched} markets; {stats.kept} kept after filtering ({stats.skipped} skipped).")

    conn = init_db(db_path)
    try:
        upsert_markets(conn, markets)
    finally:
        conn.close()
    print(f"Wrote {stats.kept} markets to {db_path}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    out_dir = Path(args.out)
    figures_dir = out_dir / "figures"
    out_dir.mkdir(parents=True, exist_ok=True)
    figures_dir.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)

    all_buckets: list[pd.DataFrame] = []
    all_metrics: list[pd.DataFrame] = []
    conn = init_db(db_path)
    try:
        for snap in SNAPSHOT_TYPES:
            df = load_calibration_frame(conn, snap)
            if df.empty:
                print(f"[{snap}] no rows; skipping")
                continue
            df["volume_quartile"] = pd.qcut(
                df["volume"], q=4, labels=["q1", "q2", "q3", "q4"], duplicates="drop"
            )
            for label, edges_fn in [("decile", bucket_decile), ("pct5", bucket_5pct)]:
                for weighting, weight_col in [("market", None), ("volume", "volume")]:
                    buckets = edges_fn(df, n_iter=args.bootstrap, rng=rng, weight_col=weight_col)
                    buckets["snapshot_type"] = snap
                    buckets["bucketing"] = label
                    buckets["weighting"] = weighting
                    all_buckets.append(buckets)

            metrics_overall = compute_metrics(df)
            metrics_cat = compute_metrics(df, group_col="category")
            metrics_vol = compute_metrics(df, group_col="volume_quartile")
            for m in (metrics_overall, metrics_cat, metrics_vol):
                m["snapshot_type"] = snap
                all_metrics.append(m)

            decile_market = bucket_decile(df, n_iter=args.bootstrap, rng=rng, weight_col=None)
            chart_path = figures_dir / f"calibration_{snap}.png"
            plot_calibration_curve(
                decile_market,
                title=f"Calibration: T-{snap} (market-weighted, decile)",
                save_to=chart_path,
            )
            br = compute_metrics(df).loc[0]
            print(f"[{snap}] n={int(br['n_markets']):>5,}  "
                  f"brier={br['brier_score']:.4f}  log_loss={br['log_loss']:.4f}  "
                  f"-> {chart_path}")
    finally:
        conn.close()

    if all_buckets:
        pd.concat(all_buckets, ignore_index=True).to_csv(out_dir / "calibration_buckets.csv", index=False)
    if all_metrics:
        pd.concat(all_metrics, ignore_index=True).to_csv(out_dir / "calibration_metrics.csv", index=False)
    print(f"Wrote bucket-level + metrics CSVs to {out_dir}/")
    return 0


HEADLINE_HORIZONS = ("close", "24h")  # full 4,532 coverage; 7d is restricted secondary


def _era(end_date: pd.Series) -> pd.Series:
    """Half-year era label (e.g. '2025-H1') from an ISO end_date string column."""
    dt = pd.to_datetime(end_date, utc=True, format="ISO8601")
    half = np.where(dt.dt.month <= 6, "H1", "H2")
    return dt.dt.year.astype(str) + "-" + half


def cmd_flb(args: argparse.Namespace) -> int:
    """Favorite-longshot bias: fit logit(q)=a+b*logit(p) per horizon and slice."""
    db_path = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    n_iter = args.bootstrap

    def _rng() -> np.random.Generator:
        # Fresh generator per fit-set so adding/reordering slices can't shift
        # another slice's CIs; reproducible given --seed.
        return np.random.default_rng(args.seed)

    rows: list[pd.DataFrame] = []
    frames: dict[str, pd.DataFrame] = {}
    conn = init_db(db_path)
    try:
        for snap in SNAPSHOT_TYPES:
            df = load_calibration_frame(conn, snap)
            if df.empty:
                print(f"[{snap}] no rows; skipping")
                continue
            frames[snap] = df

            def _tagged(kind: str, frame: pd.DataFrame, group_col: str | None) -> pd.DataFrame:
                out = recalibration_by_group(frame, group_col=group_col, n_iter=n_iter, rng=_rng())
                out.insert(0, "snapshot_type", snap)
                out.insert(1, "slice_kind", kind)
                return out

            rows.append(_tagged("overall", df, None))

            df = df.copy()
            df["volume_quartile"] = pd.qcut(
                df["volume"], q=4, labels=["q1", "q2", "q3", "q4"], duplicates="drop"
            )
            rows.append(_tagged("volume", df, "volume_quartile"))

            df["era"] = _era(df["end_date"])
            rows.append(_tagged("era", df, "era"))

            rows.append(_tagged("category", df, "category"))

            # Time-to-resolution: market lifespan = end_date - created_at (Gamma backfill).
            created = pd.to_datetime(df["created_at"], utc=True, format="ISO8601", errors="coerce")
            enddt = pd.to_datetime(df["end_date"], utc=True, format="ISO8601")
            lifespan_days = (enddt - created).dt.total_seconds() / 86400.0
            df["ttr_bucket"] = pd.cut(
                lifespan_days, bins=[0, 2, 7, 30, float("inf")],
                labels=["<2d", "2-7d", "7-30d", ">30d"], right=False,
            )  # markets with no created_at -> NaN bucket, dropped by groupby(observed=True)
            rows.append(_tagged("ttr", df, "ttr_bucket"))

            # Temporal split: fit on older markets, validate on newer (mirrors deployment).
            # end_date is stored as a uniform ISO-8601 UTC string, so lexicographic
            # order is chronological: take the median by position rather than a
            # numeric quantile (which can't subtract strings).
            if args.cutoff is not None:
                cutoff = args.cutoff
            else:
                ordered = df["end_date"].sort_values().to_numpy()
                cutoff = ordered[len(ordered) // 2]
            train = df[df["end_date"] < cutoff]
            test = df[df["end_date"] >= cutoff]
            temporal: list[dict] = []
            if len(train) >= 2 and len(test) >= 2:
                ins = recalibration_with_ci(train["predicted"].to_numpy(), train["outcome"].to_numpy(),
                                            n_iter=n_iter, rng=_rng())
                oos = recalibration_with_ci(test["predicted"].to_numpy(), test["outcome"].to_numpy(),
                                            n_iter=n_iter, rng=_rng())
                a_tr, b_tr = ins["a"], ins["b"]
                temporal.append({"subgroup": "insample", **ins})
                temporal.append({"subgroup": "oos_refit", **oos})
                # Honest OOS edge: apply the train-fit map to the held-out future.
                tp, ty = test["predicted"].to_numpy(), test["outcome"].to_numpy()
                temporal.append({
                    "subgroup": "oos_trainmap", "n": int(len(ty)), "a": a_tr, "b": b_tr,
                    "a_ci_lo": float("nan"), "a_ci_hi": float("nan"),
                    "b_ci_lo": float("nan"), "b_ci_hi": float("nan"),
                    "brier_market": float(np.mean((tp - ty) ** 2)),
                    "brier_recal": recalibrated_brier(tp, ty, a_tr, b_tr),
                })
                tdf = pd.DataFrame(temporal)
                tdf.insert(0, "snapshot_type", snap)
                tdf.insert(1, "slice_kind", "temporal")
                rows.append(tdf)

            # Tail power: how many markets live where the rule wants to act.
            tail_lo = int((df["predicted"] < 0.05).sum())
            tail_hi = int((df["predicted"] > 0.95).sum())
            print(f"[{snap}] n={len(df):>5,}  tails: p<0.05 -> {tail_lo}, p>0.95 -> {tail_hi}")

        # Intersection cohort: hold the population constant across horizons.
        common = ("close", "24h", "7d")
        if all(h in frames for h in common):
            shared = set(frames[common[0]]["market_id"])
            for h in common[1:]:
                shared &= set(frames[h]["market_id"])
            for h in common:
                sub = frames[h][frames[h]["market_id"].isin(shared)]
                isec = recalibration_by_group(sub, group_col=None, n_iter=n_iter, rng=_rng())
                isec["subgroup"] = f"{h}@intersection"
                isec.insert(0, "snapshot_type", h)
                isec.insert(1, "slice_kind", "intersection")
                rows.append(isec)
            print(f"[intersection] {len(shared):,} markets present at all of {common}")
    finally:
        conn.close()

    if not rows:
        print("No data; nothing written.")
        return 0
    result = pd.concat(rows, ignore_index=True)
    out_csv = out_dir / "flb_recalibration.csv"
    result.to_csv(out_csv, index=False)

    # Headline: overall b at the full-coverage horizons.
    print("\n=== FLB headline (b < 1 = favorite-longshot bias) ===")
    overall = result[(result["slice_kind"] == "overall") & (result["snapshot_type"].isin(HEADLINE_HORIZONS))]
    for _, r in overall.iterrows():
        # A near-zero market Brier means prices are already saturated at ~0/1
        # (e.g. T-close on resolved markets): the fit degenerates and b is
        # meaningless. Flag it rather than report a spurious headline.
        note = "  (SATURATED: prices ~= outcome; FLB undefined)" if r["brier_market"] < 0.01 else ""
        print(f"  T-{r['snapshot_type']:<5} b={r['b']:.3f} "
              f"[{r['b_ci_lo']:.3f}, {r['b_ci_hi']:.3f}]  a={r['a']:.3f}  n={int(r['n']):,}  "
              f"brier_market={r['brier_market']:.4f} brier_recal={r['brier_recal']:.4f}{note}")
    print(f"\nWrote {len(result)} rows to {out_csv}")
    return 0


RULE_HORIZONS = ("24h", "7d")  # 24h primary (both tails populated), 7d secondary


def _eligible_categories(fit: pd.DataFrame, min_n: int) -> dict[str, tuple[float, float]]:
    """From a per-category recalibration_by_group result, keep categories with a real FLB:
    b CI strictly below 1 and enough markets. Returns {category: (a, b)}."""
    out: dict[str, tuple[float, float]] = {}
    for _, r in fit.iterrows():
        if r["n"] >= min_n and r["b_ci_hi"] < 1.0:
            out[r["subgroup"]] = (float(r["a"]), float(r["b"]))
    return out


def cmd_backtest_rule(args: argparse.Namespace) -> int:
    """Validate the sized rule out-of-sample: fit the per-category map on older markets,
    apply to newer ones, and report realized P&L across a half-spread sweep."""
    db_path = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    spreads = [float(s) for s in args.spreads.split(",")]
    rows: list[dict] = []
    conn = init_db(db_path)
    try:
        for horizon in RULE_HORIZONS:
            df = load_calibration_frame(conn, horizon)
            df = df[df["volume"] >= args.min_volume]  # universe filter (binary/non-disputed already)
            if len(df) < 2 * args.min_n:
                print(f"[{horizon}] too few markets after universe filter; skipping")
                continue
            ordered = df["end_date"].sort_values().to_numpy()
            cutoff = ordered[len(ordered) // 2]
            train = df[df["end_date"] < cutoff]
            test = df[df["end_date"] >= cutoff]
            fit = recalibration_by_group(train, "category", n_iter=args.bootstrap,
                                         rng=np.random.default_rng(args.seed))
            eligible = _eligible_categories(fit, args.min_n)
            print(f"[{horizon}] eligible categories (train, b CI<1): {sorted(eligible)}")

            positions: list[dict] = []
            for _, m in test.iterrows():
                ab = eligible.get(m["category"])
                if ab is None:
                    continue
                q_hat = float(apply_recalibration(m["predicted"], ab[0], ab[1]))
                for hs in spreads:
                    res = simulate_position(m["predicted"], q_hat, m["outcome"], half_spread=hs)
                    if res is None:
                        continue
                    side, pred_edge, pnl = res
                    positions.append({"category": m["category"], "half_spread": hs,
                                      "side": side, "pred_edge": pred_edge, "pnl": pnl})
            if not positions:
                print(f"[{horizon}] no positions taken")
                continue
            pos = pd.DataFrame(positions)
            for hs in spreads:
                sub = pos[pos["half_spread"] == hs]
                rows.append({"horizon": horizon, "scope": "overall", "half_spread": hs,
                             "n_positions": len(sub), "mean_pred_edge": sub["pred_edge"].mean(),
                             "mean_realized_pnl": sub["pnl"].mean(), "total_realized_pnl": sub["pnl"].sum(),
                             "win_rate": (sub["pnl"] > 0).mean()})
            hs0 = pos[pos["half_spread"] == spreads[0]]
            print(f"[{horizon}] at half_spread={spreads[0]:.3f}: {len(hs0)} positions, "
                  f"mean realized P&L={hs0['pnl'].mean():+.4f}/contract, "
                  f"mean predicted edge={hs0['pred_edge'].mean():+.4f}")
    finally:
        conn.close()
    if not rows:
        print("No backtest rows; nothing written.")
        return 0
    pd.DataFrame(rows).to_csv(out_dir / "flb_rule_backtest.csv", index=False)
    print(f"Wrote rule backtest to {out_dir / 'flb_rule_backtest.csv'}")
    return 0


def cmd_freeze_rule(args: argparse.Namespace) -> int:
    """Freeze the pre-registration rule: per-category (a,b) fit on ALL resolved markets
    plus a precomputed q-band, so the forward test can size without refitting."""
    db_path = Path(args.db)
    out_path = Path(args.out)
    grid = [round(x, 2) for x in np.arange(0.01, 1.0, 0.01)]
    frozen = {
        "version": 1,
        "entry_horizon": "24h",
        "secondary_horizon": "7d",
        "kelly_fraction": args.kelly_fraction,
        "universe": {"market_type": "binary", "min_volume": args.min_volume, "non_disputed": True},
        "seed": args.seed,
        "min_n": args.min_n,
        "horizons": {},
    }
    conn = init_db(db_path)
    try:
        for horizon in RULE_HORIZONS:
            df = load_calibration_frame(conn, horizon)
            df = df[df["volume"] >= args.min_volume]
            fit = recalibration_by_group(df, "category", n_iter=args.bootstrap,
                                         rng=np.random.default_rng(args.seed))
            eligible = _eligible_categories(fit, args.min_n)
            cats: dict[str, dict] = {}
            for _, r in fit.iterrows():
                cat = r["subgroup"]
                entry = {"a": float(r["a"]), "b": float(r["b"]),
                         "b_ci_lo": float(r["b_ci_lo"]), "b_ci_hi": float(r["b_ci_hi"]),
                         "n": int(r["n"]), "eligible": cat in eligible}
                if cat in eligible:
                    g = df[df["category"] == cat]
                    band = predict_band(g["predicted"].to_numpy(), g["outcome"].to_numpy(),
                                        grid, n_iter=args.bootstrap, rng=np.random.default_rng(args.seed))
                    entry["grid"] = grid
                    entry["q_lo"] = [float(x) for x in band["q_lo"]]
                    entry["q_hat"] = [float(x) for x in band["q_hat"]]
                    entry["q_hi"] = [float(x) for x in band["q_hi"]]
                cats[cat] = entry
            frozen["horizons"][horizon] = {"fit_on": "all_resolved", "categories": cats}
    finally:
        conn.close()
    out_path.write_text(json.dumps(frozen, indent=2))
    elig = {h: sorted(c for c, v in frozen["horizons"][h]["categories"].items() if v["eligible"])
            for h in frozen["horizons"]}
    print(f"Froze rule to {out_path}. Eligible categories: {elig}")
    return 0


def _interp(grid: list[float], arr: list[float], x: float) -> float:
    return float(np.interp(x, np.asarray(grid), np.asarray(arr)))


def cmd_forward_scan(args: argparse.Namespace) -> int:
    """Apply the FROZEN rule to live open markets near their entry horizon and log
    realizable paper fills. No fitting on forward data."""
    rule = json.loads(Path(args.rule).read_text())
    horizons = rule["horizons"]
    kelly_frac = rule["kelly_fraction"]
    min_volume = rule["universe"]["min_volume"]
    size = args.size
    now = datetime.now(timezone.utc)
    windows = {"24h": (24.0, args.window_hours), "7d": (168.0, args.window_hours_7d)}

    conn = init_db(Path(args.db))
    scanned = 0
    skipped_book = 0
    logged = {h: 0 for h in horizons}
    try:
        with GammaClient() as g:
            candidates = list(fetch_open_markets(g, volume_floor=min_volume))
        print(f"Scanning {len(candidates)} open candidates at {now.isoformat()} ...")
        with CLOBClient() as c:
            for m in candidates:
                scanned += 1
                hours = (m.scheduled_end - now).total_seconds() / 3600.0
                for horizon, (target_h, win) in windows.items():
                    if horizon not in horizons or not (target_h - win <= hours <= target_h + win):
                        continue
                    cat = categorize_slug(m.slug)
                    centry = horizons[horizon]["categories"].get(cat)
                    if not centry or not centry.get("eligible"):
                        continue
                    book = fetch_order_book(c, m.clob_token_ids[0])
                    if book is None:
                        skipped_book += 1
                        continue
                    mid = (book["best_bid"] + book["best_ask"]) / 2.0
                    half_spread = (book["best_ask"] - book["best_bid"]) / 2.0
                    grid = centry["grid"]
                    q_hat = _interp(grid, centry["q_hat"], mid)
                    side = side_for(mid, q_hat)
                    if side is None:
                        continue
                    if side == "YES":
                        q_used = _interp(grid, centry["q_lo"], mid)
                        entry = vwap_fill(book["asks"], size)
                        if entry is None:
                            skipped_book += 1
                            continue
                        edge_gross, edge_net = q_hat - mid, q_used - entry
                    else:
                        q_used = _interp(grid, centry["q_hi"], mid)
                        bid_vwap = vwap_fill(book["bids"], size)
                        if bid_vwap is None:
                            skipped_book += 1
                            continue
                        entry = 1.0 - bid_vwap
                        edge_gross, edge_net = mid - q_hat, (1.0 - q_used) - entry
                    if edge_net <= 0:
                        continue  # edge eaten by the spread -> rule takes no position
                    stake = fractional_kelly(kelly_fraction(q_used, mid, side), kelly_frac)
                    if stake <= 0:
                        continue
                    insert_signals(conn, [ForwardSignal(
                        market_id=m.condition_id, venue="polymarket", horizon=horizon,
                        observed_at=now, category=cat, market_price=mid, side=side, q_hat=q_hat,
                        q_used=q_used, edge_gross=edge_gross, half_spread=half_spread, fee=0.0,
                        edge_net=edge_net, stake_fraction=stake, entry_price=entry,
                        end_date=m.scheduled_end,
                    )])
                    logged[horizon] += 1
    finally:
        conn.close()
    print(f"Scanned {scanned}; logged {logged} (skipped {skipped_book} thin/one-sided books). "
          f"Re-scans are idempotent (entry locked per market+horizon).")
    return 0


def cmd_forward_settle(args: argparse.Namespace) -> int:
    """Settle open forward signals whose markets have resolved: record outcome, realized
    P&L (held to resolution), and realized-minus-predicted edge. Disputed -> void."""
    now = datetime.now(timezone.utc)
    conn = init_db(Path(args.db))
    resolved = voided = still_open = 0
    pnls: list[float] = []
    gaps: list[float] = []
    try:
        sigs = open_signals(conn)
        print(f"Checking {len(sigs)} open signals ...")
        with GammaClient() as g:
            for s in sigs:
                rows = list(fetch_markets_by_ids(g, [s.market_id]))  # closed=true: empty until resolved
                if not rows or not rows[0].closed:
                    still_open += 1
                    continue
                m = rows[0]
                disputed = "disput" in (m.uma_resolution_status or "").lower()
                clean = m.outcome_prices and sorted(m.outcome_prices) == ["0", "1"]
                if not clean or disputed:
                    mark_signal_resolved(conn, s.market_id, s.horizon, "void", None, None, None, now)
                    voided += 1
                    continue
                rv = 1.0 if m.outcome_prices[0] == "1" else 0.0
                payoff = rv if s.side == "YES" else (1.0 - rv)
                pnl = payoff - s.entry_price
                gap = pnl - s.edge_net  # realized minus predicted (the efficiency tax)
                mark_signal_resolved(conn, s.market_id, s.horizon, "resolved", rv, pnl, gap, now)
                resolved += 1
                pnls.append(pnl)
                gaps.append(gap)
    finally:
        conn.close()
    msg = f"Resolved {resolved}, void {voided}, still open {still_open}."
    if pnls:
        msg += (f" Realized P&L/contract: mean {np.mean(pnls):+.4f}, total {np.sum(pnls):+.3f}; "
                f"mean realized-minus-predicted {np.mean(gaps):+.4f}.")
    print(msg)
    return 0


def cmd_fetch_tags(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    conn = init_db(db_path)
    try:
        pairs = markets_missing_tags(conn)
        if args.limit is not None:
            pairs = pairs[: args.limit]

        print(f"Fetching tags for {len(pairs)} markets ...")
        fetched = 0
        skipped = 0
        with GammaClient() as client:
            for i, (mid, evt_id) in enumerate(pairs, 1):
                tags = fetch_event_tags(client, evt_id)
                if not tags:
                    skipped += 1
                else:
                    insert_market_tags(conn, [(mid, t) for t in tags])
                    fetched += 1
                if i % 50 == 0:
                    print(f"  [{i}/{len(pairs)}] {fetched} fetched, {skipped} skipped")
        print(f"Done. Fetched tags for {fetched} markets, skipped {skipped} (HTTP error or no tags).")
    finally:
        conn.close()
    return 0


def cmd_backfill_created(args: argparse.Namespace) -> int:
    """Backfill markets.created_at from Gamma for rows discovered before the column existed."""
    db_path = Path(args.db)
    conn = init_db(db_path)
    try:
        ids = markets_missing_created_at(conn)
        if args.limit is not None:
            ids = ids[: args.limit]
        print(f"Backfilling created_at for {len(ids)} markets ...")
        pairs: list[tuple[str, datetime]] = []
        seen = 0
        with GammaClient() as client:
            for m in fetch_markets_by_ids(client, ids):
                seen += 1
                if m.created_at is not None:
                    pairs.append((m.condition_id, m.created_at))
                if seen % 500 == 0:
                    print(f"  [{seen}/{len(ids)}] {len(pairs)} with createdAt")
        filled = set_market_created_at(conn, pairs)
        print(f"Done. Filled {filled}; {len(ids) - filled} unresolved (no createdAt or not returned).")
    finally:
        conn.close()
    return 0


def cmd_tick_coverage(args: argparse.Namespace) -> int:
    """Flag markets whose first price tick is < 7d before resolution (no real T-7d snapshot)."""
    db_path = Path(args.db)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    conn = init_db(db_path)
    try:
        rows = []
        for mid, min_ts in min_tick_per_market(conn):
            market = get_market(conn, mid)
            if market is None or min_ts is None:
                continue
            first_tick = datetime.fromisoformat(min_ts)
            days_history = (market.end_date - first_tick).total_seconds() / 86400.0
            rows.append({
                "market_id": mid,
                "slug": market.slug,
                "end_date": market.end_date.isoformat(),
                "first_tick": first_tick.isoformat(),
                "days_of_history": round(days_history, 3),
                "has_7d_history": days_history >= 7.0,
            })
    finally:
        conn.close()
    df = pd.DataFrame(rows)
    out_csv = out_dir / "flb_tick_coverage.csv"
    df.to_csv(out_csv, index=False)
    if not df.empty:
        n_no7d = int((~df["has_7d_history"]).sum())
        print(f"{len(df)} markets with price history; {n_no7d} have < 7d of history "
              f"(no real T-7d snapshot). Wrote {out_csv}")
    else:
        print(f"No price history found. Wrote empty {out_csv}")
    return 0


def cmd_kalshi_discover(args: argparse.Namespace) -> int:
    """Discover settled binary Kalshi markets (per series) into the markets table (venue='kalshi')."""
    conn = init_db(Path(args.db))
    try:
        print(f"Discovering Kalshi settled binaries across {len(KALSHI_SERIES)} series "
              f"(<= {args.max_per_series}/series) ...")
        total = 0
        by_cat: dict[str, int] = {}
        with KalshiClient() as client:
            # Upsert per series (one DB connection, batched) so a long run is resumable.
            for series_ticker, category in KALSHI_SERIES.items():
                batch = list(fetch_settled_markets(client, {series_ticker: category},
                                                   max_per_series=args.max_per_series))
                if batch:
                    upsert_markets(conn, batch)
                    total += len(batch)
                    by_cat[category] = by_cat.get(category, 0) + len(batch)
                print(f"  {series_ticker}: {len(batch)}")
        print(f"Upserted {total} Kalshi markets. By category: {by_cat}")
    finally:
        conn.close()
    return 0


def cmd_kalshi_fetch_candles(args: argparse.Namespace) -> int:
    """Fetch candlesticks for Kalshi markets lacking price history (mirrors fetch-prices)."""
    conn = init_db(Path(args.db))
    try:
        ids = [mid for mid in markets_missing_history(conn)
               if (m := get_market(conn, mid)) is not None and m.venue == "kalshi"]
        if args.limit is not None:
            ids = ids[: args.limit]
        print(f"Fetching candles for {len(ids)} Kalshi markets ...")
        fetched = skipped = 0
        with KalshiClient() as client:
            for i, mid in enumerate(ids, 1):
                market = get_market(conn, mid)
                ticks = fetch_market_candles(client, market) if market else None
                if ticks is None:
                    skipped += 1
                    continue
                insert_price_ticks(conn, ticks)
                fetched += 1
                if i % 50 == 0:
                    print(f"  [{i}/{len(ids)}] {fetched} fetched, {skipped} skipped")
        print(f"Done. Fetched {fetched}, skipped {skipped} (no candles / HTTP error).")
    finally:
        conn.close()
    return 0


def cmd_extract_snapshots(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    conn = init_db(db_path)
    try:
        market_ids = markets_with_history(conn)
        print(f"Extracting snapshots for {len(market_ids)} markets ...")
        total = 0
        for mid in market_ids:
            market = get_market(conn, mid)
            if market is None:
                continue
            ticks = get_ticks_for_market(conn, mid)
            snaps = extract_snapshots(market, ticks)
            if snaps:
                upsert_snapshots(conn, snaps)
                total += len(snaps)
        print(f"Wrote {total} snapshots to {db_path}.")
    finally:
        conn.close()
    return 0


def cmd_fetch_prices(args: argparse.Namespace) -> int:
    db_path = Path(args.db)
    conn = init_db(db_path)
    try:
        if args.all:
            market_ids = [r[0] for r in conn.execute("SELECT market_id FROM markets").fetchall()]
        else:
            market_ids = markets_missing_history(conn)
        if args.limit is not None:
            market_ids = market_ids[: args.limit]

        print(f"Fetching prices for {len(market_ids)} markets ...")
        fetched = 0
        skipped = 0
        with CLOBClient() as client:
            for i, mid in enumerate(market_ids, 1):
                market = get_market(conn, mid)
                if market is None:
                    skipped += 1
                    continue
                ticks = fetch_market_history(client, market)
                if ticks is None:
                    print(f"  [{i}/{len(market_ids)}] skip {market.slug[:60]}: error or no data")
                    skipped += 1
                    continue
                insert_price_ticks(conn, ticks)
                fetched += 1
                if i % 50 == 0:
                    print(f"  [{i}/{len(market_ids)}] {fetched} fetched, {skipped} skipped")
        print(f"Done. Fetched {fetched} markets, skipped {skipped}.")
    finally:
        conn.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="calibration")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_discover = sub.add_parser("discover", help="Stage 1: fetch resolved binary markets from Gamma")
    p_discover.add_argument("--since", required=True, help="ISO date, e.g. 2024-01-01")
    p_discover.add_argument("--volume-floor", type=float, default=1_000_000.0)
    p_discover.add_argument("--db", default="data/markets.db")
    p_discover.set_defaults(func=cmd_discover)

    p_fetch = sub.add_parser("fetch-prices", help="Stage 2: fetch CLOB price history per market")
    p_fetch.add_argument("--db", default="data/markets.db")
    p_fetch.add_argument("--limit", type=int, default=None, help="cap markets per run")
    p_fetch.add_argument("--all", action="store_true", help="re-fetch even markets that already have ticks")
    p_fetch.set_defaults(func=cmd_fetch_prices)

    p_tags = sub.add_parser("fetch-tags", help="v1.1: fetch category tags per market via Gamma /events/{id}")
    p_tags.add_argument("--db", default="data/markets.db")
    p_tags.add_argument("--limit", type=int, default=None, help="cap markets per run")
    p_tags.set_defaults(func=cmd_fetch_tags)

    p_snap = sub.add_parser("extract-snapshots", help="Stage 3: extract calibration snapshots into price_snapshots")
    p_snap.add_argument("--db", default="data/markets.db")
    p_snap.set_defaults(func=cmd_extract_snapshots)

    p_kd = sub.add_parser("kalshi-discover", help="phase 5: discover settled binary Kalshi markets by series")
    p_kd.add_argument("--db", default="data/markets.db")
    p_kd.add_argument("--max-per-series", type=int, default=500, help="cap settled markets per series")
    p_kd.set_defaults(func=cmd_kalshi_discover)

    p_kc = sub.add_parser("kalshi-fetch-candles", help="phase 5: fetch candlesticks for Kalshi markets")
    p_kc.add_argument("--db", default="data/markets.db")
    p_kc.add_argument("--limit", type=int, default=None, help="cap markets per run")
    p_kc.set_defaults(func=cmd_kalshi_fetch_candles)

    p_bc = sub.add_parser("backfill-created", help="v2: backfill markets.created_at from Gamma")
    p_bc.add_argument("--db", default="data/markets.db")
    p_bc.add_argument("--limit", type=int, default=None, help="cap markets per run")
    p_bc.set_defaults(func=cmd_backfill_created)

    p_tc = sub.add_parser("tick-coverage", help="v2: flag markets with < 7d of price history before resolution")
    p_tc.add_argument("--db", default="data/markets.db")
    p_tc.add_argument("--out", default="reports", help="output directory for flb_tick_coverage.csv")
    p_tc.set_defaults(func=cmd_tick_coverage)

    p_an = sub.add_parser("analyze", help="Stage 4: bucket markets, compute Brier/log loss, save calibration charts")
    p_an.add_argument("--db", default="data/markets.db")
    p_an.add_argument("--out", default="reports", help="output directory for CSVs and figures/")
    p_an.add_argument("--bootstrap", type=int, default=1000, help="bootstrap iterations for per-bucket CIs")
    p_an.add_argument("--seed", type=int, default=42, help="rng seed for reproducible bootstrap CIs")
    p_an.set_defaults(func=cmd_analyze)

    p_flb = sub.add_parser("flb", help="favorite-longshot bias: fit logit(q)=a+b*logit(p) per horizon/slice")
    p_flb.add_argument("--db", default="data/markets.db")
    p_flb.add_argument("--out", default="reports", help="output directory for flb_recalibration.csv")
    p_flb.add_argument("--bootstrap", type=int, default=1000, help="bootstrap iterations for a/b CIs")
    p_flb.add_argument("--seed", type=int, default=42, help="rng seed for reproducible bootstrap CIs")
    p_flb.add_argument("--cutoff", default=None,
                       help="ISO end_date splitting train/test for the temporal slice (default: median)")
    p_flb.set_defaults(func=cmd_flb)

    p_bt = sub.add_parser("backtest-rule", help="phase 3: OOS backtest of the sized rule over a spread sweep")
    p_bt.add_argument("--db", default="data/markets.db")
    p_bt.add_argument("--out", default="reports")
    p_bt.add_argument("--min-volume", type=float, default=1_000_000.0)
    p_bt.add_argument("--min-n", type=int, default=100, help="min markets for a category to be eligible")
    p_bt.add_argument("--spreads", default="0,0.01,0.02,0.03", help="comma-separated half-spreads to sweep")
    p_bt.add_argument("--bootstrap", type=int, default=1000)
    p_bt.add_argument("--seed", type=int, default=42)
    p_bt.set_defaults(func=cmd_backtest_rule)

    p_fr = sub.add_parser("freeze-rule", help="phase 3: write the pre-registration frozen_rule_v1.json")
    p_fr.add_argument("--db", default="data/markets.db")
    p_fr.add_argument("--out", default="reports/frozen_rule_v1.json")
    p_fr.add_argument("--min-volume", type=float, default=1_000_000.0)
    p_fr.add_argument("--min-n", type=int, default=100)
    p_fr.add_argument("--kelly-fraction", type=float, default=0.25)
    p_fr.add_argument("--bootstrap", type=int, default=1000)
    p_fr.add_argument("--seed", type=int, default=42)
    p_fr.set_defaults(func=cmd_freeze_rule)

    p_fs = sub.add_parser("forward-scan", help="phase 4: log realizable paper fills for open markets vs the frozen rule")
    p_fs.add_argument("--db", default="data/markets.db")
    p_fs.add_argument("--rule", default="reports/frozen_rule_v1.json")
    p_fs.add_argument("--size", type=float, default=1000.0, help="target paper fill size (shares) for VWAP")
    p_fs.add_argument("--window-hours", type=float, default=12.0, help="+/- window around T-24h to enter")
    p_fs.add_argument("--window-hours-7d", type=float, default=24.0, help="+/- window around T-7d to enter")
    p_fs.set_defaults(func=cmd_forward_scan)

    p_se = sub.add_parser("forward-settle", help="phase 4: settle resolved forward signals (P&L, dispute->void)")
    p_se.add_argument("--db", default="data/markets.db")
    p_se.set_defaults(func=cmd_forward_settle)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
