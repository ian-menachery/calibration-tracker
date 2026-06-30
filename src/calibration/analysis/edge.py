"""Branch A: turn the FLB recalibration map into a sized, costed trading rule.

q_hat is the recalibrated "fair" YES probability for a market priced at p; the signed
edge is q_hat - p. e>0 -> back the favorite (buy YES); e<0 -> fade the longshot (buy NO).
Sizing is fractional Kelly off the CONSERVATIVE bound of the fair probability (q_lo for a
YES, q_hi for a NO). Held to resolution, so the only cost is crossing half the spread on
entry plus venue fees.

No model in the scoring path: q_hat comes only from price-vs-outcome recalibration
(analysis/recalibration.py). Pure math. Per CLAUDE.md every function here has a
known-input test in tests/test_edge.py.
"""

from __future__ import annotations


def edge(p: float, q_hat: float) -> float:
    """Signed edge in YES space: recalibrated fair prob minus market price."""
    return float(q_hat) - float(p)


def side_for(p: float, q_hat: float) -> str | None:
    """'YES' if the fair prob exceeds the price (back favorite), 'NO' if below (fade
    longshot), None if exactly flat."""
    e = float(q_hat) - float(p)
    if e > 0:
        return "YES"
    if e < 0:
        return "NO"
    return None


def kelly_fraction(q: float, p: float, side: str) -> float:
    """Full Kelly for a $1-payoff binary contract, in YES space.

    YES: (q - p) / (1 - p);  NO: (p - q) / p. `q` is the fair YES probability — pass the
    conservative bound (q_lo for a YES bet, q_hi for a NO bet). Clipped at 0 (a negative
    Kelly means the edge is on the other side / gone).
    """
    q = float(q)
    p = float(p)
    if side == "YES":
        f = (q - p) / (1.0 - p) if p < 1.0 else 0.0
    elif side == "NO":
        f = (p - q) / p if p > 0.0 else 0.0
    else:
        return 0.0
    return max(f, 0.0)


def fractional_kelly(f: float, fraction: float = 0.25) -> float:
    """Scale a full-Kelly fraction down (quarter/half Kelly). Clipped at 0."""
    return max(float(f), 0.0) * float(fraction)


def net_edge(gross: float, half_spread: float, fee: float = 0.0) -> float:
    """Net per-share edge after entry cost. Gross is the |edge| magnitude on the chosen
    side; subtract half the bid/ask spread (entry) and venue fees. Held to resolution, so
    there is no exit cost. May be negative (edge eaten by costs)."""
    return float(gross) - float(half_spread) - float(fee)


def kalshi_fee(price: float, rate: float = 0.07) -> float:
    """Kalshi taker fee per share ~= rate * p * (1 - p); makers free. Polymarket has no
    such per-trade fee, so its fee term is 0."""
    return float(rate) * float(price) * (1.0 - float(price))


def vwap_fill(levels: list[tuple[float, float]], target_size: float) -> float | None:
    """Size-weighted average fill price walking an order-book side best-first.

    `levels` are (price, size) pairs already ordered best-first (asks ascending,
    bids descending). Returns the VWAP to fill `target_size`, or None if the book
    is too thin to fill it. This is the realizable entry price (you cross the book),
    the honest cost the mid price hides.
    """
    filled = 0.0
    notional = 0.0
    for price, size in levels:
        take = min(size, target_size - filled)
        if take <= 0:
            break
        notional += take * price
        filled += take
        if filled >= target_size:
            return notional / filled
    return None


def simulate_position(
    p: float, q_hat: float, outcome: float, half_spread: float = 0.0, fee: float = 0.0
) -> tuple[str, float, float] | None:
    """Realized P&L per $1-payoff contract for one market, held to resolution.

    Entry crosses half the spread (plus fee) on the chosen side. Returns
    (side, predicted_edge, realized_pnl), or None if the rule takes no position.
    YES pays `outcome`; NO pays `1 - outcome`.
    """
    side = side_for(p, q_hat)
    if side is None:
        return None
    if side == "YES":
        entry = float(p) + half_spread + fee
        realized = float(outcome) - entry
        pred_edge = float(q_hat) - float(p)
    else:
        entry = (1.0 - float(p)) + half_spread + fee
        realized = (1.0 - float(outcome)) - entry
        pred_edge = float(p) - float(q_hat)
    return side, pred_edge, realized


def passes_universe(
    volume: float | None,
    market_type: str = "binary",
    disputed: bool = False,
    min_volume: float = 1_000_000.0,
) -> bool:
    """The written-down training cohort the rule is allowed to act on: standalone binary,
    at least `min_volume` USD volume, non-disputed. The live rule must only be applied to
    markets drawn from this same filter, or the measured edge does not transfer."""
    if market_type != "binary" or disputed:
        return False
    return volume is not None and volume >= min_volume
