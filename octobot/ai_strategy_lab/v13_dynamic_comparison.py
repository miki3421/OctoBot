"""Synthetic-only A/B/C accounting, not a market-data or execution adapter.

Cards ea6b980a / dba701d5. Full three-arm ticks commit atomically to a NEW
explicitly labelled fixture SQLite. No operational files, network or grants.
Depth fills and risk checks use labelled fixtures only; verified market adapters
and operational authorization remain prerequisites for research-paper activation.
"""
import copy
import datetime as dt
import json
import math
import sqlite3
from decimal import Decimal, ROUND_DOWN, ROUND_CEILING, ROUND_FLOOR

try:
    from . import v13_dynamic_universe as selector
except ImportError:
    import v13_dynamic_universe as selector

ARMS = ('A', 'B', 'C')
SCOPE = 'SYNTHETIC_ACCOUNTING_ONLY_V3'
ORIGINAL = tuple(s+'USDT' for s in
                 'AAVE ADA ATOM AVAX BCH BTC DOGE DOT ETH HBAR LINK LTC NEAR SOL UNI XLM XRP ZEC'.split())


def number(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('invalid_number')
    if positive and value <= 0:
        raise ValueError('positive_required')
    return float(value)


def adverse_price(price, signed_quantity, tick_size):
    number(price, True); number(tick_size, True); number(signed_quantity)
    if not signed_quantity: raise ValueError('zero_price_direction')
    tick = Decimal(str(tick_size))
    rounded = (Decimal(str(price))/tick).to_integral_value(
        rounding=ROUND_CEILING if signed_quantity>0 else ROUND_FLOOR)*tick
    return number(float(rounded), True)


def build_targets(decision, covariance):
    """Use a selector record and supplied causal annualized covariance.

    Caller must verify covariance provenance before any non-fixture use.
    A uses its own18x18 submatrix; B and C use the same29x29 covariance.
    """
    import numpy as np
    body = {k: v for k, v in decision.items() if k != 'decision_id'}
    if selector.digest(body) != decision['decision_id'] or decision['version'] != selector.VERSION:
        raise ValueError('invalid_decision')
    symbols = list(selector.UNIVERSE)
    cov = np.asarray(covariance, dtype=float)
    if cov.shape != (29, 29):
        raise ValueError('invalid_covariance_shape')
    result = {}
    for arm in ARMS:
        universe = list(ORIGINAL) if arm == 'A' else symbols
        indices = [symbols.index(s) for s in universe]
        signals = [decision['rows'][s]['signal'] for s in universe]
        selected = decision['selected'] if arm == 'C' else universe
        weights = selector.target_weights(signals, cov[np.ix_(indices, indices)], universe, selected)
        result[arm] = dict(zip(universe, map(float, weights)))
    return result


def initial_state():
    return dict(scope=SCOPE, last_at=None, last_rebalance=None, funding_ids=[], funding_records={}, position_history=[], selection=None,
                arms={a: dict(cash=10000., equity=10000., positions={}, fees=0.,
                              slippage=0., funding=0., turnover=0., risk=dict(day=None, day_equity=10000., high_water=10000., last_increase=None, loss_stopped=False, anchor_valid=True)) for a in ARMS})


def advance(state, tick):
    """Public fixture entry point; real packets must use their guarded consumer."""
    return _advance(state,tick,expected_scope=SCOPE,contract_scope='SYNTHETIC_ONLY')


def _advance(state, tick, *, expected_scope, contract_scope):
    """A common mark tick; optional targets execute after decision timestamp.

    Funding is explicit for the interval (not defaulted to zero). Each event
    has id, at, symbol, rate and mark. Positions stay constant until the tick's
    final rebalance, hence funding belongs to the pre-rebalance position.
    Persisted post-tick positions govern settlement, including delayed rates.
    Late cash adjustments are recognized now, without rewriting past equity.
    No position changes between ticks are supported. Missing intervals deny.
    """
    if state['scope'] != expected_scope or tick.get('scope') != expected_scope:
        raise ValueError('synthetic_label_required')
    at = selector.timestamp(tick['at'])
    if state['last_at'] is not None and at <= selector.timestamp(state['last_at']):
        raise ValueError('nonincreasing_tick')
    marks = tick['marks']
    if set(marks) != set(selector.UNIVERSE):
        raise ValueError('common_marks_required')
    marks = {s: number(p, True) for s, p in marks.items()}
    funding = tick['funding']
    cursor=state.get('funding_cursor',state['last_at'])
    complete=funding.get('coverage_complete') is True
    incomplete_close=(funding.get('coverage_complete') is False and tick.get('protective_only') is True
                      and tick.get('targets')=={arm:{} for arm in ARMS} and state['last_at'] is not None)
    if (not complete and not incomplete_close) or funding['from']!=cursor or funding['to']!=tick['at']:
        raise ValueError('funding_coverage_required')
    events = funding['events']
    delayed = tick.get('delayed_funding', [])
    new_events = []
    registered = dict(state['funding_records'])
    for event, is_delayed in [(e,False) for e in events]+[(e,True) for e in delayed]:
        if not isinstance(event['id'], str) or not event['id']:
            raise ValueError('funding_identity')
        when = selector.timestamp(event['at'])
        if state['last_at'] is None or when > at:
            raise ValueError('funding_outside_interval')
        if is_delayed:
            if when > selector.timestamp(state['last_at']):raise ValueError('not_delayed_funding')
        elif not selector.timestamp(cursor) < when <= at:
            raise ValueError('funding_outside_interval')
        if event['symbol'] not in marks:raise ValueError('funding_symbol')
        number(event['rate']); number(event['mark'], True)
        economic_id = selector.digest([event['symbol'],when.isoformat()])
        fingerprint = selector.digest(dict(symbol=event['symbol'],at=when.isoformat(),rate=event['rate'],mark=event['mark']))
        if economic_id in registered:
            if registered[economic_id] != fingerprint:raise ValueError('funding_conflict')
            continue
        registered[economic_id] = fingerprint
        history = state['position_history']
        if not history or when < selector.timestamp(history[0]['at']):
            raise ValueError('position_history_missing')
        # A fill at the exact settlement timestamp comes AFTER settlement.
        prior = [h for h in history if selector.timestamp(h['at']) < when]
        positions = prior[-1]['positions'] if prior else {a:{} for a in ARMS}
        new_events.append((event,positions,is_delayed))
    seen = set(registered)
    targets = tick.get('targets')
    protective = tick.get('protective_only', False)
    if not isinstance(protective, bool):
        raise ValueError('invalid_protective_flag')
    fee = max(.0006, number(tick['fee_rate']))
    if tick['fee_rate'] < 0:
        raise ValueError('negative_fee')
    fees = tick.get('fee_rates')
    if fees is not None:
        if set(fees)!=set(marks):raise ValueError('common_fees_required')
        fees={s:max(.0006,number(v)) for s,v in fees.items()}
        if any(v<0 for v in tick['fee_rates'].values()):raise ValueError('negative_fee')
    if targets is not None:
        if set(targets) != set(ARMS):
            raise ValueError('all_arms_required')
        decision_at = selector.timestamp(tick['decision_at'])
        if decision_at >= at or (state['last_at'] and decision_at < selector.timestamp(state['last_at'])):
            raise ValueError('noncausal_decision')
        if state['last_rebalance'] and not protective:
            elapsed = (decision_at-selector.timestamp(state['last_rebalance'])).total_seconds()
            if elapsed <= 0 or elapsed % (7*86400):
                raise ValueError('weekly_schedule_required')
        for a, weights in targets.items():
            permitted = set(ORIGINAL) if a == 'A' else set(selector.UNIVERSE)
            if not set(weights) <= permitted:
                raise ValueError('target_universe')
            values = [number(v) for v in weights.values()]
            if any(abs(v) > .315+1e-12 for v in values) or sum(map(abs,values)) > .90+1e-12:
                raise ValueError('target_limits')
            if a == 'C' and sum(v != 0 for v in values) > 18:
                raise ValueError('selection_limit')
    selection = tick.get('selection')
    if selection is not None:
        if protective:
            raise ValueError('protective_selection_conflict')
        if targets is None or selector.timestamp(selection['slot']) != selector.timestamp(tick['decision_at']):
            raise ValueError('selection_slot_mismatch')
        previous = state['selection']
        if selection.get('parent_id') != (previous['decision_id'] if previous else None):
            raise ValueError('selection_parent_mismatch')
        if previous and (selection['lineage'] != previous['lineage'] or selection['start'] != previous['start']):
            raise ValueError('selection_lineage_mismatch')
        if build_targets(selection, tick['covariance']) != targets:
            raise ValueError('selection_targets_mismatch')
    elif state['selection'] is not None and targets is not None and not protective:
        raise ValueError('selection_required')
    if targets is not None:
        if tick.get('contract_scope') != contract_scope:
            raise ValueError('synthetic_contract_required')
        if (set(tick['books']) != set(marks) or set(tick['quantity_steps']) != set(marks)
                or set(tick.get('price_ticks',{})) != set(marks)):
            raise ValueError('common_books_required')
        for symbol, book in tick['books'].items():
            when = selector.timestamp(book['at'])
            if not decision_at < when <= at or (at-when).total_seconds() > 60:
                raise ValueError('noncausal_or_stale_book')
            number(tick['quantity_steps'][symbol],True)
            number(tick['price_ticks'][symbol],True)
            for side in ('bids','asks'):
                if not book[side]:
                    raise ValueError('empty_book')
                for price, quantity in book[side]:
                    number(price,True); number(quantity,True)
                prices = [p for p,q in book[side]]
                if prices != sorted(prices,reverse=side=='bids') or len(set(prices)) != len(prices):
                    raise ValueError('unordered_book')
            if book['bids'][0][0] >= book['asks'][0][0]:
                raise ValueError('crossed_book')
    result = copy.deepcopy(state)
    trades = []
    for arm in ARMS:
        account = result['arms'][arm]
        for event,positions,is_delayed in new_events:
            amount = -positions[arm].get(event['symbol'],0.) * event['mark'] * event['rate']
            account['cash'] += amount
            account['funding'] += amount
        def equity_now():
            return account['cash'] + sum(q*marks[s] for s,q in account['positions'].items())
        equity = equity_now()
        if equity <= 0 or not math.isfinite(equity):
            raise ValueError('invalid_equity')
        risk = account['risk']
        day = at.date().isoformat()
        # Day boundary uses last observed equity, thus overnight losses count.
        # Missing an entire UTC day denies increases instead of inventing its anchor.
        gap = risk['day'] is not None and (at.date()-dt.date.fromisoformat(risk['day'])).days > 1
        if risk['day'] != day:
            risk.update(day=day,day_equity=account['equity'],loss_stopped=False,anchor_valid=not gap)
        risk['high_water'] = max(risk['high_water'],equity)
        risk['loss_stopped'] |= equity <= .98*risk['day_equity']
        denied = []
        if risk['loss_stopped']: denied.append('daily_loss')
        if equity <= .90*risk['high_water']: denied.append('drawdown')
        if not risk['anchor_valid']: denied.append('missing_daily_anchor')
        if risk['last_increase']:
            last = selector.timestamp(risk['last_increase'])
            if last.date()==at.date(): denied.append('daily_frequency')
            if (at-last).total_seconds()<22*3600: denied.append('cooldown')
        account['denials'] = denied
        if targets is not None:
            desired = {s: equity*w/marks[s] for s,w in targets[arm].items() if w}
            books = copy.deepcopy(tick['books']) # Each independent arm sees identical liquidity.
            reductions, increases = [], []
            for symbol in sorted(set(account['positions']) | set(desired)):
                old = account['positions'].get(symbol,0.)
                new = desired.get(symbol,0.)
                if old*new < 0:
                    reductions.append((symbol,-old)); increases.append((symbol,new))
                elif abs(new)<abs(old): reductions.append((symbol,new-old))
                elif new!=old: increases.append((symbol,new-old))
            increased = False
            for is_increase, batch in ((False,reductions),(True,increases)):
                for symbol, requested in batch:
                    if fees is not None:fee=fees[symbol]
                    if is_increase and (denied or protective):
                        continue
                    current = account['positions'].get(symbol,0.)
                    # Partial close must never be followed by an opposite new entry.
                    if is_increase and current*requested < 0:
                        continue
                    step = tick['quantity_steps'][symbol]
                    magnitude = abs(requested)
                    eq = equity_now()
                    if is_increase:
                        if eq <= .98*risk['day_equity'] or eq <= .90*risk['high_water']:
                            denied.append('post_cost_loss_limit'); continue
                        gross = sum(abs(q*marks[s]) for s,q in account['positions'].items())
                        # Headroom based on current account; exact post-fill checks below.
                        worst = (max(p for p,q in books[symbol]['asks'])*1.0002 if requested>0 else min(p for p,q in books[symbol]['bids'])*.9998)
                        worst = adverse_price(worst,requested,tick['price_ticks'][symbol])
                        expense = max(0.,math.copysign(1.,requested)*(worst-marks[symbol]))+worst*fee
                        magnitude = min(magnitude,max(0.,(.9*eq-gross)/(marks[symbol]+.9*expense)),
                                        max(0.,(.315*eq-abs(current*marks[symbol]))/(marks[symbol]+.315*expense)))
                    else:
                        magnitude = min(magnitude,abs(current))
                    quantity = float((Decimal(str(magnitude))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step)))
                    levels = books[symbol]['asks' if requested>0 else 'bids']
                    available = sum(q for p,q in levels)
                    quantity = min(quantity,float((Decimal(str(available))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step))))
                    if quantity <= 0 or (is_increase and quantity*marks[symbol]<1.):
                        continue
                    # Quote the available levels before mutating either book or account.
                    remaining=quantity; notional=0.
                    for price, depth in levels:
                        take=min(depth,remaining); notional+=take*price; remaining-=take
                        if remaining<=1e-12: break
                    signed=math.copysign(quantity,requested)
                    price=adverse_price(notional/quantity*(1+math.copysign(.0002,requested)),requested,tick['price_ticks'][symbol])
                    if is_increase and quantity*price<1.:
                        continue
                    cost=quantity*price*fee
                    after_eq=eq-signed*(price-marks[symbol])-cost
                    if is_increase:
                        after_gross=gross-abs(current*marks[symbol])+abs((current+signed)*marks[symbol])
                        if (after_gross>.9*after_eq+1e-9 or abs((current+signed)*marks[symbol])>.315*after_eq+1e-9
                                or after_eq<=.98*risk['day_equity'] or after_eq<=.9*risk['high_water']):
                            denied.append('post_fill_risk_limit'); continue
                    remaining=quantity
                    for level in levels:
                        take=min(level[1],remaining);level[1]-=take;remaining-=take
                        if remaining<=1e-12:break
                    account['cash']-=signed*price+cost
                    account['positions'][symbol]=current+signed
                    if abs(account['positions'][symbol])<1e-12: del account['positions'][symbol]
                    account['fees']+=cost
                    slip=quantity*abs(price-notional/quantity)
                    account['slippage']+=slip
                    account['turnover']+=quantity*marks[symbol]
                    trades.append(dict(arm=arm,symbol=symbol,quantity=signed,price=price,fee=cost,slippage=slip,
                                       requested=requested,partial=quantity<abs(requested)-1e-12,protective=not is_increase))
                    increased |= is_increase
            if increased: risk['last_increase']=tick['at']
        account['equity'] = equity_now()
        risk['high_water']=max(risk['high_water'],account['equity'])
        risk['loss_stopped'] |= account['equity']<=.98*risk['day_equity']
        if not math.isfinite(account['equity']) or account['equity']<=0:
            raise ValueError('invalid_post_trade_equity')
    if selection is not None: result['selection']=copy.deepcopy(selection)

    result['funding_records']=registered
    result['position_history'].append(dict(at=tick['at'],positions={a:copy.deepcopy(result['arms'][a]['positions']) for a in ARMS}))
    result['funding_adjustments']=[dict(id=e['id'],settlement_at=e['at'],recognized_at=tick['at'],delayed=late,amounts={a:-positions[a].get(e['symbol'],0.)*e['mark']*e['rate'] for a in ARMS}) for e,positions,late in new_events]
    result.update(last_at=tick['at'], funding_ids=sorted(seen),
                  funding_cursor=tick['at'] if complete else cursor, equity_complete=complete)
    for account in result['arms'].values():
        account['net_equity']=account['equity'] if complete else None
    if targets is not None and not protective:
        result['last_rebalance'] = tick['decision_at']
    return result, trades


class FixtureStore:
    """Explicit fixture path only. Reopen requires our marker/schema.

    Errors propagate; caller must not publish a successful result after failure.
    FULL sync plus a single transaction for all arms; no retry/recovery fallback.
    """
    def __init__(self, path, *, create=False):
        from pathlib import Path
        p = Path(path).absolute()
        if create:
            # Exclusive creation refuses overwriting any pre-existing file.
            with p.open('xb'):
                pass
        elif not p.is_file():
            raise ValueError('fixture_store_missing')
        self.db = sqlite3.connect(p.as_uri()+'?mode=rw', uri=True, isolation_level=None)
        try:
            self.db.execute('PRAGMA synchronous=FULL')
            if create:
                self.db.executescript('BEGIN; CREATE TABLE marker(scope TEXT NOT NULL); '
                                     'CREATE TABLE ticks(id TEXT PRIMARY KEY, input_hash TEXT NOT NULL, '
                                     'state TEXT NOT NULL, trades TEXT NOT NULL); COMMIT;')
                self.db.execute('INSERT INTO marker VALUES (?)',(SCOPE,))
            if self.db.execute('SELECT scope FROM marker').fetchall() != [(SCOPE,)]:
                raise ValueError('not_fixture_store')
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def commit(self, tick, *, prepare=None):
        hashed = selector.digest(tick)
        self.db.execute('BEGIN IMMEDIATE')
        try:
            prior = self.db.execute('SELECT input_hash,state,trades FROM ticks WHERE id=?',(tick['id'],)).fetchone()
            if prior:
                if prior[0] != hashed:
                    raise ValueError('tick_conflict')
                result = json.loads(prior[1]),json.loads(prior[2])
            else:
                latest = self.db.execute('SELECT state FROM ticks ORDER BY rowid DESC LIMIT 1').fetchone()
                state = json.loads(latest[0]) if latest else initial_state()
                prepared = prepare(state,tick) if prepare is not None else tick
                result = advance(state,prepared)
                self.db.execute('INSERT INTO ticks VALUES (?,?,?,?)',
                                (tick['id'],hashed,json.dumps(result[0],allow_nan=False),json.dumps(result[1],allow_nan=False)))
            self.db.execute('COMMIT')
            return result
        except BaseException:
            if self.db.in_transaction:
                self.db.execute('ROLLBACK')
            raise
