"""Pure offline candidate primitives. No account, network, file or ledger I/O.

Cards 0188dd29 / da39b55e. This module is not a paper runner or an issuer.
Input receipt custody, persistence, funding reconciliation and live risk checks
remain the responsibility of a future qualified dual-arm runner.
"""
from decimal import Decimal, DecimalException, InvalidOperation, ROUND_DOWN, ROUND_CEILING, ROUND_FLOOR
import hashlib
import json

NS = 1_000_000_000
GRID = 300 * NS
VERSION = "btc-intraday-long-short-kernel-v1"
UNIVERSE = tuple("AAVE ADA ATOM AVAX BCH BTC DOGE DOT ETH HBAR LINK LTC NEAR SOL UNI XLM XRP ZEC".split())
UNIVERSE = tuple(s + "USDT" for s in UNIVERSE)


def number(value):
    if isinstance(value, bool):
        raise ValueError("INVALID_NUMBER")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError("INVALID_NUMBER") from None
    if not result.is_finite():
        raise ValueError("INVALID_NUMBER")
    return result


def timestamp(value):
    if type(value) is not int or value < 0:
        raise ValueError("INVALID_TIMESTAMP")
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     allow_nan=False).encode()).hexdigest()


def signal(rows, slot_ns, decision_ns, *, short_only=False):
    """All 289 rows must have been received AND durably available by their slot.

    Input: {slot_ns, quotes: {symbol: {price, exchange_ns, received_ns,
    available_ns}}}. Rows after the requested slot cannot alter its identity.
    A proposal is research-only even when its direction is LONG or SHORT.
    """
    result = dict(status="MISSING", research_only=True, issuable=False,
                  version=VERSION, slot_ns=slot_ns)
    try:
        timestamp(slot_ns)
        timestamp(decision_ns)
        if slot_ns % GRID or decision_ns < slot_ns:
            raise ValueError("INVALID_DECISION_CLOCK")
        if decision_ns > slot_ns + 30 * NS:
            return dict(result, status="MISSED_DEADLINE")
        begin = slot_ns - 288 * GRID
        selected = {}
        for row in rows:
            at = timestamp(row["slot_ns"])
            if not begin <= at <= slot_ns:
                continue
            if at in selected or at % GRID:
                raise ValueError("DUPLICATE_OR_OFF_GRID")
            quotes = row["quotes"]
            if set(quotes) != set(UNIVERSE):
                raise ValueError("UNIVERSE_INCOMPLETE")
            prices = {}
            for symbol in UNIVERSE:
                q = quotes[symbol]
                exchange, received, available = (timestamp(q[k]) for k in
                                                  ("exchange_ns", "received_ns", "available_ns"))
                if not exchange <= received <= available <= at or at - exchange > 120 * NS:
                    raise ValueError("INPUT_NOT_CAUSAL_OR_STALE")
                price = number(q["price"])
                if price <= 0:
                    raise ValueError("INVALID_PRICE")
                prices[symbol] = price
            selected[at] = prices
        expected = list(range(begin, slot_ns + GRID, GRID))
        if sorted(selected) != expected:
            raise ValueError("WINDOW_INCOMPLETE")
        current, hour = selected[slot_ns], selected[slot_ns - 12 * GRID]
        returns = {s: current[s] / hour[s] - 1 for s in UNIVERSE}
        negative = sum(r < 0 for r in returns.values())
        positive = sum(r > 0 for r in returns.values())
        status = "NO_SIGNAL"
        if returns["BTCUSDT"] <= Decimal("-.01") and negative >= 12:
            status = "SHORT"
        elif not short_only and returns["BTCUSDT"] >= Decimal(".01") and positive >= 12:
            status = "LONG"
        # Normalize equal numeric prices independently of receipt provenance.
        causal = [{"slot_ns": at, "prices": {s: str(selected[at][s].normalize())
                                                for s in UNIVERSE}} for at in expected]
        causal_hash = digest(causal)
        arm = "SHORT_CONTROL" if short_only else "LONG_SHORT"
        return dict(result, status=status, btc_return=str(returns["BTCUSDT"]),
                    negative=negative, positive=positive, causal_sha256=causal_hash,
                    decision_id=digest(dict(version=VERSION, arm=arm, slot_ns=slot_ns,
                                            causal_sha256=causal_hash)))
    except (KeyError, TypeError, ValueError, DecimalException) as error:
        # Bounded reason only, never arbitrary input or exception text.
        allowed = {"INVALID_NUMBER", "INVALID_TIMESTAMP", "INVALID_DECISION_CLOCK",
                   "DUPLICATE_OR_OFF_GRID", "UNIVERSE_INCOMPLETE",
                   "INPUT_NOT_CAUSAL_OR_STALE", "INVALID_PRICE", "WINDOW_INCOMPLETE"}
        return dict(result, reason=str(error) if str(error) in allowed else "INVALID_SCHEMA")


def quantity(equity, price):
    equity, price = number(equity), number(price)
    if equity <= 0 or price <= 0:
        return Decimal(0)
    notional = min(Decimal(".1") * equity, Decimal(".0025") * equity / Decimal(".0128"),
                   Decimal(".01") * price)
    return (notional / price / Decimal(".001")).to_integral_value(rounding=ROUND_DOWN) * Decimal(".001")


def execution(book, signed_quantity, *, stress=False, partial=False):
    """Synthetic L5 pricing only; caller must establish freshness and custody.

    Same size mapping, costs and rounding as pinned reference execution().
    A result is a price estimate, never a durable fill or admission approval.
    """
    q = number(signed_quantity)
    if not q:
        return None
    levels = {}
    for side in ("bid", "ask"):
        levels[side] = [(number(book[f"{side}_price_{i}"]), number(book[f"{side}_size_{i}"]))
                        for i in range(1, 6)]
        if any(p <= 0 or size < 0 for p, size in levels[side]):
            raise ValueError("INVALID_BOOK")
    bids, asks = levels["bid"], levels["ask"]
    if bids[0][0] >= asks[0][0] or any(b[0] > a[0] for a, b in zip(bids, bids[1:])) or any(
            b[0] < a[0] for a, b in zip(asks, asks[1:])):
        raise ValueError("INVALID_BOOK")
    side = levels["ask" if q > 0 else "bid"]
    available = sum(size * Decimal(".001") for _, size in side)
    if abs(q) > available and not partial:
        return None
    amount = (min(abs(q), available) / Decimal(".001")).to_integral_value(rounding=ROUND_DOWN) * Decimal(".001")
    if not amount:
        return None
    remaining, notional = amount, Decimal(0)
    for price, size in side:
        used = min(remaining, size * Decimal(".001"))
        notional += used * price
        remaining -= used
    multiplier = 2 if stress else 1
    price = notional / amount * (1 + Decimal(".0001") * multiplier * (1 if q > 0 else -1))
    price = (price / Decimal(".1")).to_integral_value(
        rounding=ROUND_CEILING if q > 0 else ROUND_FLOOR) * Decimal(".1")
    if not partial and amount * price < 1:
        return None
    return (amount if q > 0 else -amount), price, amount * price * Decimal(".0006") * multiplier


def exit_trigger(signed_position, entry_price, bid, ask, elapsed_seconds):
    """Direction-specific price/time trigger only; no claim to execute an exit."""
    q, entry, bid, ask, elapsed = map(number, (signed_position, entry_price, bid, ask, elapsed_seconds))
    if not q:
        return None
    if entry <= 0 or bid <= 0 or bid >= ask or elapsed < 0:
        raise ValueError("INVALID_EXIT_INPUT")
    stop = bid <= entry * Decimal(".99") if q > 0 else ask >= entry * Decimal("1.01")
    take = bid >= entry * Decimal("1.02") if q > 0 else ask <= entry * Decimal(".98")
    return "STOP_LOSS" if stop else "TIME_EXIT" if elapsed >= 21600 else "TAKE_PROFIT" if take else None


def funding_cashflow(signed_position, preceding_mark, final_rate, *, stress=False):
    """Arithmetic only: None means pending; event evidence must be verified upstream."""
    if preceding_mark is None or final_rate is None:
        return None
    q, mark, rate = map(number, (signed_position, preceding_mark, final_rate))
    if mark <= 0:
        raise ValueError("INVALID_MARK")
    cash = -q * mark * rate
    return min(cash, Decimal(0)) * 2 if stress else cash


def paired_equity(control, candidate, start_ns, end_ns):
    """Require the full SAME five-minute grid: no interpolation or gap deletion.

    Series: {at_ns, equity, complete}. No holdout evaluation or scientific PASS.
    Missing valuations cause rejection, not artificial zero returns.
    """
    timestamp(start_ns)
    timestamp(end_ns)
    if start_ns % GRID or end_ns % GRID or start_ns >= end_ns:
        raise ValueError("INVALID_COMPARISON_WINDOW")
    expected = list(range(start_ns, end_ns + GRID, GRID))

    def read(series):
        values = {}
        for row in series:
            at = timestamp(row["at_ns"])
            if not start_ns <= at <= end_ns:
                continue
            if at in values or row["complete"] is not True:
                raise ValueError("INCOMPLETE_OR_DUPLICATE_EQUITY")
            value = number(row["equity"])
            if value <= 0:
                raise ValueError("INVALID_EQUITY")
            values[at] = value
        if sorted(values) != expected:
            raise ValueError("COMPARISON_COVERAGE_MISSING")
        return values

    left, right = read(control), read(candidate)
    if left[start_ns] != Decimal(10000) or right[start_ns] != Decimal(10000):
        raise ValueError("PAIRED_FLAT_SEED_REQUIRED")
    a, b = left[end_ns] - left[start_ns], right[end_ns] - right[start_ns]
    return dict(scope="OFFLINE_DESCRIPTIVE_NOT_SCIENTIFIC_VALIDATION", start_ns=start_ns,
                end_ns=end_ns, points=len(expected), control_net_usdt=str(a),
                candidate_net_usdt=str(b), difference_usdt=str(b - a))
