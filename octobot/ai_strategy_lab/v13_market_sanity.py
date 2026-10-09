"""P0-03: versioned, provisional PAPER-ONLY market policy, independent of exposure.

Evidence: 5,700 observations, 2026-09-21..24; see P0_03 implementation report.
No P/L tuning, strategy inputs or model-controlled policy overrides.
"""
from dataclasses import asdict, dataclass
from decimal import Decimal
import datetime as dt

from octobot.ai_strategy_lab import v13_exposure as exposure
from octobot.ai_strategy_lab import v13_market as market


@dataclass(frozen=True)
class PaperPolicy:
    version: str = 'v13-market-sanity-paper-v1'
    provisional: bool = True
    paper_only: bool = True
    max_spread_ratio: str = '0.005'
    max_mark_mid_divergence: str = '0.01'
    max_age_seconds: int = 1800
    market_identity: str = 'kucoin_futures_usdt'


POLICY = PaperPolicy()


class Veto(exposure.Rejected):
    def __init__(self, code, detail, symbol=None):
        super().__init__(code)
        self.detail, self.symbol = detail, symbol

    def evidence(self):
        return dict(policy=asdict(POLICY), code=str(self), detail=self.detail, symbol=self.symbol)


def numeric(value, field, *, positive=False, nonnegative=False):
    if value is None:
        raise Veto('missing_market_metadata', field)
    try:
        return exposure.number(value, field, positive=positive, nonnegative=nonnegative)
    except exposure.Rejected as exc:
        raise Veto('invalid_market_metadata', field) from exc


def time(value):
    try:
        return market._time(value, 'market timestamp')
    except ValueError as exc:
        raise Veto('invalid_market_timestamp', str(exc)) from exc


def structure_and_time(symbol, quote, record, decision_time):
    """Required even for reductions; no stale, crossed, unknown or synthetic exit."""
    if not isinstance(quote, dict):
        raise Veto('invalid_book', 'quote must be an object', symbol)
    try:
        identity = market.normalize_symbol(quote.get('symbol'))
    except ValueError as exc:
        raise Veto('market_identity_mismatch', 'missing/invalid quote symbol', symbol) from exc
    if identity != symbol or quote.get('market_identity') != POLICY.market_identity:
        raise Veto('market_identity_mismatch', 'symbol or market differs', symbol)
    if quote.get('market_record_hash', record.get('record_hash')) != record.get('record_hash'):
        raise Veto('market_identity_mismatch', 'quote belongs to another observation', symbol)
    if not isinstance(decision_time, dt.datetime) or decision_time.tzinfo is None:
        raise Veto('invalid_market_timestamp', 'execution decision must be timezone-aware', symbol)
    start, available, event = time(record.get('observed_at_start')), time(record.get('observed_at_end')), time(quote.get('timestamp'))
    if start > available:
        raise Veto('invalid_market_timestamp', 'reversed observation interval', symbol)
    if event > available or available > decision_time:
        raise Veto('future_market_data', 'event <= available <= execution decision required', symbol)
    for observed in (start, available, event):
        if (decision_time - observed).total_seconds() > POLICY.max_age_seconds:
            raise Veto('stale_market_data', 'market evidence exceeds maximum age', symbol)
    for field in ('mark_timestamp', 'metadata_observed_at'):
        if quote.get(field) is not None:
            observed = time(quote[field])
            if observed > available:
                raise Veto('future_market_data', field, symbol)
            if (decision_time - observed).total_seconds() > POLICY.max_age_seconds:
                raise Veto('stale_market_data', field, symbol)
    try:
        bids, asks = market._book(quote.get('bids'), 'bids'), market._book(quote.get('asks'), 'asks')
        exposure.number(quote.get('mark_price'), 'mark', positive=True)
    except (ValueError, TypeError, KeyError) as exc:
        raise Veto('invalid_book', str(exc), symbol) from exc
    if bids[0]['price'] > asks[0]['price']:
        raise Veto('crossed_book', 'bid exceeds ask', symbol)
    for key, value in (('best_bid', bids[0]['price']), ('best_ask', asks[0]['price'])):
        if key in quote and quote[key] != value:
            raise Veto('invalid_book', 'book top disagrees with levels', symbol)
    return bids, asks


def preflight(symbol, quote, delta, protective):
    """All legs are checked before P0-02 runs portfolio exposure checks."""
    bids, asks = quote['bids'], quote['asks']  # Already structurally validated.
    bid, ask = Decimal(str(bids[0]['price'])), Decimal(str(asks[0]['price']))
    mid = (bid + ask) / 2
    spread = (ask - bid) / mid
    divergence = abs(Decimal(str(quote['mark_price'])) - mid) / mid
    if not protective:
        if spread > Decimal(POLICY.max_spread_ratio):
            raise Veto('spread_limit', f'spread_ratio={spread}', symbol)
        if divergence > Decimal(POLICY.max_mark_mid_divergence):
            raise Veto('mark_book_divergence', f'mark_mid_divergence={divergence}', symbol)
        for field in ('price_tick', 'quantity_step', 'step', 'contract_multiplier'):
            numeric(quote.get(field), field, positive=True)
        for field in ('min_quantity', 'min_notional'):
            numeric(quote.get(field), field, nonnegative=True)
        if quote['step'] != quote['quantity_step']:
            raise Veto('invalid_market_metadata', 'quantity step differs from declared precision', symbol)
        units = Decimal(str(quote['quantity_step'])) / Decimal(str(quote['contract_multiplier']))
        if units < 1 or units != units.to_integral_value():
            raise Veto('invalid_market_metadata', 'quantity precision inconsistent with multiplier', symbol)
    # Fee/available tick cannot be invented even for exits.
    if numeric(quote.get('fee_rate'), 'fee_rate', nonnegative=True) >= 1:
        raise Veto('invalid_market_metadata', 'fee_rate', symbol)
    if quote.get('price_tick') is not None:
        numeric(quote['price_tick'], 'price_tick', positive=True)
    if delta is None:
        # Partial target sizing requires a known step even for a reduction.
        # A full close skips sizing and uses the known held quantity instead.
        numeric(quote.get('step'), 'step', positive=True)
        return None
    levels = asks if delta > 0 else bids
    capacity = sum((Decimal(str(level['base_quantity'])) for level in levels), Decimal(0))
    if capacity < abs(Decimal(str(delta))):
        raise Veto('insufficient_depth', 'observed side cannot cover the full quantity', symbol)
    return dict(symbol=symbol, protective=protective, spread_ratio=float(spread),
                mark_mid_divergence=float(divergence), available_quantity=float(capacity))


def adapter_veto(error):
    """Translate legacy adapter failures; their explanatory detail is preserved."""
    detail = str(error)
    if ('future' in detail and 'futures' not in detail) or 'future book' in detail:
        code = 'future_market_data'
    elif 'stale' in detail:
        code = 'stale_market_data'
    elif 'crossed' in detail:
        code = 'crossed_book'
    elif any(word in detail for word in ('symbol', 'identity', 'missing market quote')):
        code = 'market_identity_mismatch'
    elif any(word in detail for word in ('timestamp', 'timezone', 'chronological', 'observation start', 'observation end')):
        code = 'invalid_market_timestamp'
    elif any(word in detail for word in ('funding', 'fee', 'multiplier', 'quantity step')):
        code = 'invalid_market_metadata'
    else:
        code = 'invalid_book'
    return Veto(code, detail)
