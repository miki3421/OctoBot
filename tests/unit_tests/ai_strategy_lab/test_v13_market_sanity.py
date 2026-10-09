"""P0-03 market vetoes must precede all simulated fills."""
from unittest.mock import patch

from tests.unit_tests.ai_strategy_lab.test_v13_paper_v2 import START, quote, state, market, dt
from octobot.ai_strategy_lab import v13_paper_v2 as paper

AT = START + dt.timedelta(minutes=15)


def test_original_extreme_spread_cannot_create_risk():
    q = quote(AT)
    q['asks'][0]['price'] = 150.
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result, fills, _, _ = paper.process_market(state(), market(AT), {'BTCUSDT': q}, AT + dt.timedelta(seconds=2))
        execution.assert_not_called()
    assert not fills
    assert result['risk']['reason'] == 'spread_limit'

import copy
import json
import math
import sqlite3
import dataclasses
import pytest
from tests.unit_tests.ai_strategy_lab.test_v13_paper_v2 import runtime, decision, counts
from octobot.ai_strategy_lab import v13_market_sanity as sanity


def run(account=None, quotes=None, record=None, checked=None):
    return paper.process_market(account or state(), record or market(AT),
        quotes or {'BTCUSDT': quote(AT)}, checked or AT + dt.timedelta(seconds=2))


def assert_veto(code, *, account=None, q=None, quotes=None, record=None, checked=None):
    account = account or state()
    original = copy.deepcopy(account)
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        try:
            result, fills, _, _ = run(account, quotes or {'BTCUSDT': q or quote(AT)}, record, checked)
        except sanity.Veto as exc:
            assert str(exc) == code
            assert exc.evidence()['policy']['version'] == sanity.POLICY.version
        else:
            assert not fills
            assert result['risk']['reason'] == code
            assert result['risk']['market_veto']['code'] == code
            assert result['pending'] == account['pending']
        execution.assert_not_called()
    assert account == original


def position(account, quantity=10.):
    account['positions']['BTCUSDT'] = dict(paper.new_position(), quantity=quantity,
        entry_price=100., current_price=100., last_mark_at=START.isoformat())
    return account


def book(bid=99.9, ask=100.1, mark=100.):
    q = quote(AT, price=mark)
    q['bids'][0]['price'], q['asks'][0]['price'] = bid, ask
    return q


def test_tight_market_and_mark_inside_book():
    result, fills, _, _ = run()
    assert len(fills) == 1
    assert result['risk']['market_policy']['provisional'] is True
    assert result['risk']['market_checks'][0]['spread_ratio'] == pytest.approx(.002)
    assert result['risk']['market_checks'][0]['mark_mid_divergence'] == 0


def test_versioned_configuration_cannot_be_mutated():
    with pytest.raises(dataclasses.FrozenInstanceError):
        sanity.POLICY.max_spread_ratio = '1'
    assert sanity.POLICY.paper_only


def test_spread_exact_boundary_allowed():
    _, fills, _, _ = run(quotes={'BTCUSDT': book(99.75, 100.25)})
    assert len(fills) == 1


def test_spread_immediately_above_boundary_rejected():
    assert_veto('spread_limit', q=book(99.75, math.nextafter(100.25, math.inf)))


@pytest.mark.parametrize('mark,accepted', [(101., True), (math.nextafter(101., math.inf), False),
                                         (99., True), (math.nextafter(99., -math.inf), False)])
def test_divergence_exact_and_immediately_above_boundary(mark, accepted):
    q = book(mark=mark)
    if accepted:
        assert len(run(quotes={'BTCUSDT': q})[1]) == 1
    else:
        assert_veto('mark_book_divergence', q=q)


@pytest.mark.parametrize('side', ['bids', 'asks'])
@pytest.mark.parametrize('value', [0., -1., float('nan'), float('inf'), -float('inf'), True, None])
def test_invalid_top_price(side, value):
    q = quote(AT)
    q[side][0]['price'] = value
    assert_veto('invalid_book', q=q)


@pytest.mark.parametrize('value', [0., -1., float('nan'), float('inf'), None])
def test_invalid_mark(value):
    q = quote(AT)
    q['mark_price'] = value
    assert_veto('invalid_book', q=q)


def test_crossed_book():
    assert_veto('crossed_book', q=book(101., 100.))


@pytest.mark.parametrize('side', ['bids', 'asks'])
@pytest.mark.parametrize('depth', [[], None, {}, [None], [{'price': 100}],
    [{'price': 100., 'base_quantity': 0}], [{'price': 100., 'base_quantity': float('inf')}],
    [{'price': 100., 'base_quantity': 1., 'quote_quantity': 999.}]])
def test_empty_or_malformed_depth(side, depth):
    q = quote(AT)
    q[side] = depth
    assert_veto('invalid_book', q=q)


def test_unordered_depth():
    q = quote(AT)
    q['asks'].append(dict(price=100., base_quantity=10.))
    assert_veto('invalid_book', q=q)


def test_book_top_inconsistency():
    q = quote(AT)
    q['best_bid'] = 99.
    assert_veto('invalid_book', q=q)


@pytest.mark.parametrize('field', ['timestamp', 'observed_at_start', 'observed_at_end'])
@pytest.mark.parametrize('value', [None, 'invalid', '2026-09-12T10:15:00'])
def test_invalid_causal_timestamp(field, value):
    q, r = quote(AT), market(AT)
    (q if field == 'timestamp' else r)[field] = value
    assert_veto('invalid_market_timestamp', q=q, record=r)


def test_future_event_after_available():
    q = quote(AT + dt.timedelta(seconds=1))
    assert_veto('future_market_data', q=q)


def test_available_after_decision_even_if_event_old():
    r = market(AT)
    r['observed_at_end'] = (AT + dt.timedelta(seconds=3)).isoformat()
    assert_veto('future_market_data', record=r)


def test_reversed_observation_interval():
    r = market(AT)
    r['observed_at_start'] = (AT + dt.timedelta(seconds=1)).isoformat()
    assert_veto('invalid_market_timestamp', record=r)


def test_stale_quote_and_exact_age_limit():
    assert_veto('stale_market_data', checked=AT+dt.timedelta(seconds=1800, microseconds=1))
    assert len(run(checked=AT+dt.timedelta(seconds=1800))[1]) == 1


def test_stale_event_with_fresh_available_time():
    q = quote(AT - dt.timedelta(seconds=1801))
    assert_veto('stale_market_data', q=q)


@pytest.mark.parametrize('field', ['mark_timestamp', 'metadata_observed_at'])
@pytest.mark.parametrize('offset,code', [(1, 'future_market_data'), (-1801, 'stale_market_data')])
def test_optional_component_timestamps_when_available(field, offset, code):
    q = quote(AT)
    q[field] = (AT + dt.timedelta(seconds=offset)).isoformat()
    assert_veto(code, q=q)


@pytest.mark.parametrize('field', ['price_tick', 'quantity_step', 'step', 'contract_multiplier', 'min_quantity', 'min_notional'])
def test_missing_metadata(field):
    q = quote(AT)
    del q[field]
    assert_veto('missing_market_metadata', q=q)


@pytest.mark.parametrize('field', ['price_tick', 'quantity_step', 'step', 'contract_multiplier', 'min_quantity', 'min_notional'])
@pytest.mark.parametrize('value', [-1., float('nan'), float('inf'), True])
def test_invalid_metadata(field, value):
    q = quote(AT)
    q[field] = value
    assert_veto('invalid_market_metadata', q=q)


@pytest.mark.parametrize('field,value', [('symbol', 'ETHUSDT'), ('symbol', None),
    ('market_identity', 'other_exchange'), ('market_record_hash', 'unrelated')])
def test_market_or_symbol_mismatch(field, value):
    q = quote(AT)
    q[field] = value
    assert_veto('market_identity_mismatch', q=q)


def test_insufficient_depth_and_immediate_shortfall():
    for quantity in (1., math.nextafter(10., -math.inf)):
        q = quote(AT)
        q['asks'][0]['base_quantity'] = quantity
        assert_veto('insufficient_depth', q=q)


def test_exact_depth_and_multiple_levels_used_without_extrapolation():
    q = quote(AT)
    q['asks'] = [dict(price=100.1, base_quantity=4.), dict(price=100.2, base_quantity=6.)]
    _, fills, _, _ = run(quotes={'BTCUSDT': q})
    assert len(fills) == 1
    assert fills[0]['price'] == pytest.approx(100.16 * 1.0002)


def test_later_asset_veto_stops_all_fills_and_exposure_preflight():
    a = state(targets={'BTCUSDT': .1, 'ETHUSDT': .1})
    q = book(99.9, 150.)
    q['symbol'] = 'ETHUSDT'
    assert_veto('spread_limit', account=a, quotes={'BTCUSDT': quote(AT), 'ETHUSDT': q})


@pytest.mark.parametrize('quantity', [10., -10.])
@pytest.mark.parametrize('condition', ['wide', 'divergent', 'missing_constraints'])
def test_protective_close_uses_real_observed_book(quantity, condition):
    a = position(state(targets={}), quantity)
    q = book(99.9, 150.) if condition == 'wide' else book(mark=110. if condition == 'divergent' else 100.)
    if condition == 'missing_constraints':
        for field in ('step', 'quantity_step', 'contract_multiplier', 'price_tick', 'min_quantity', 'min_notional'):
            del q[field]
    _, fills, _, _ = run(a, {'BTCUSDT': q})
    assert len(fills) == 1 and fills[0]['quantity'] == -quantity
    expected = (q['bids'][0]['price']*.9998 if quantity > 0 else q['asks'][0]['price']*1.0002)
    assert fills[0]['price'] == pytest.approx(expected)


@pytest.mark.parametrize('condition,code', [('empty', 'invalid_book'), ('crossed', 'crossed_book'),
    ('depth', 'insufficient_depth'), ('stale', 'stale_market_data'), ('future', 'future_market_data'),
    ('symbol', 'market_identity_mismatch'), ('fee', 'missing_market_metadata')])
def test_protective_close_blocked_without_safe_execution(condition, code):
    a = position(state(targets={}))
    q = quote(AT)
    if condition == 'empty': q['bids'] = []
    if condition == 'crossed': q['bids'][0]['price'] = 101.
    if condition == 'depth': q['bids'][0]['base_quantity'] = 1.
    if condition == 'stale': q['timestamp'] = (AT-dt.timedelta(seconds=1801)).isoformat()
    if condition == 'future': q['timestamp'] = (AT+dt.timedelta(seconds=1)).isoformat()
    if condition == 'symbol': q['symbol'] = 'ETHUSDT'
    if condition == 'fee': del q['fee_rate']
    assert_veto(code, account=a, q=q)


def test_mixed_intent_cannot_use_protective_exemption_for_new_leg():
    a = position(state(targets={'ETHUSDT': .1}))
    q = book(99.9, 150.)
    q['symbol'] = 'ETHUSDT'
    assert_veto('spread_limit', account=a, quotes={'BTCUSDT': quote(AT), 'ETHUSDT': q})


def test_market_guard_precedes_exposure_projection():
    q = book(99.9, 150.)
    with patch.object(paper.v13_exposure, 'snapshot', wraps=paper.v13_exposure.snapshot) as exposures:
        assert_veto('spread_limit', q=q)
    # Only current exposure is calculated; no projected state passes the veto.
    assert exposures.call_count == 2


def test_replay_of_economic_veto_is_idempotent(runtime):
    current, database, _, tick, advance = runtime
    tick()
    advance(AT)
    current['quotes']['BTCUSDT']['asks'][0]['price'] = 150.
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        first = tick(AT + dt.timedelta(seconds=2))
        before = counts(database)
        replay = tick(AT + dt.timedelta(seconds=3))
        execution.assert_not_called()
    assert first['reason'] == replay['reason'] == 'spread_limit'
    assert counts(database) == before
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        events = [json.loads(r[0]) for r in db.execute('SELECT payload FROM risk_events')]
        assert len(events) == 1 and events[0]['reason'] == 'spread_limit'
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_structural_veto_is_persisted_without_invalid_marks(runtime):
    current, database, _, tick, advance = runtime
    tick()
    advance(AT)
    current['quotes']['BTCUSDT']['asks'] = []
    before = counts(database)
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result = tick(AT+dt.timedelta(seconds=2))
        execution.assert_not_called()
    assert result['reason'] == 'invalid_book'
    assert result['risk_event_persisted'] is True
    assert counts(database) == before
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        assert json.loads(db.execute('SELECT payload FROM risk_events').fetchone()[0])['reason'] == 'invalid_book'


@pytest.mark.parametrize('structural', [True, False])
def test_rejection_storage_failure_never_claims_persistence(runtime, structural):
    current, database, _, tick, advance = runtime
    tick()
    advance(AT)
    if structural: current['quotes']['BTCUSDT']['asks'] = []
    else: current['quotes']['BTCUSDT']['asks'][0]['price'] = 150.
    with sqlite3.connect(database) as db:
        db.execute("CREATE TRIGGER fail_risk BEFORE INSERT ON risk_events BEGIN SELECT RAISE(ABORT,'risk storage unavailable'); END")
    before = counts(database)
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result = tick(AT+dt.timedelta(seconds=2))
        execution.assert_not_called()
    assert result['status'] == 'blocked' and result['risk_event_persisted'] is False
    assert result['market_veto']['code'] == ('invalid_book' if structural else 'spread_limit')
    assert counts(database) == before
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        assert db.execute('SELECT COUNT(*) FROM risk_events').fetchone()[0] == 0


_REAL_MARKET_QUOTES = paper.v13_market.market_quotes


def real_record():
    from tests.unit_tests.ai_strategy_lab.test_v13_market import record_at, signed
    r = record_at(AT)
    f = r['symbols']['AAVE']['futures']
    f['mark_price'] = 100.
    f['normalized_bids'] = [dict(price=99.9, base_quantity=100.)]
    f['normalized_asks'] = [dict(price=100.1, base_quantity=100.)]
    f.update(quantity_step=.01, price_tick=.01, min_quantity=.01, min_notional=0.)
    return signed(r)


@pytest.mark.parametrize('condition,code', [('spread', 'spread_limit'), ('divergence', 'mark_book_divergence'),
    ('symbol', 'market_identity_mismatch'), ('venue', 'market_identity_mismatch'), ('endpoint', 'market_identity_mismatch'),
    ('crossed', 'crossed_book'), ('depth', 'insufficient_depth'), ('empty', 'invalid_book'),
    ('timestamp', 'future_market_data'), ('tick', 'missing_market_metadata')])
def test_real_adapter_to_journal_pipeline_veto(runtime, monkeypatch, condition, code):
    from tests.unit_tests.ai_strategy_lab.test_v13_market import signed
    current, database, _, tick, advance = runtime
    current['records'] = [decision({'AAVEUSDT': .1})]
    tick()
    record = real_record()
    f = record['symbols']['AAVE']['futures']
    if condition == 'spread': f['normalized_asks'][0]['price'] = 150.
    if condition == 'divergence': f['mark_price'] = 105.
    if condition == 'symbol': record['symbols']['AAVE']['futures_symbol'] = 'BTC/USDT:USDT'
    if condition == 'venue': record['market_identity'] = 'other_futures_usdt'
    if condition == 'endpoint': record['endpoints'] = {'futures_depth': 'https://other.example/orderbook'}
    if condition == 'crossed': f['normalized_bids'][0]['price'] = 101.
    if condition == 'depth': f['normalized_asks'][0]['base_quantity'] = .01
    if condition == 'empty': f['normalized_asks'] = []
    if condition == 'timestamp': f['book_timestamp_ms'] = int((AT+dt.timedelta(seconds=5)).timestamp()*1000)
    if condition == 'tick': del f['price_tick']
    current['market'] = signed(record)
    monkeypatch.setattr(paper.v13_market, 'market_quotes', _REAL_MARKET_QUOTES)
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result = tick(AT+dt.timedelta(seconds=2))
        execution.assert_not_called()
    assert result['reason'] == code
    assert result['order_count'] == 0
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        saved = json.loads(db.execute('SELECT payload FROM risk_events').fetchone()[0])
        assert saved['reason'] == code
        assert saved['market_veto']['policy']['version'] == sanity.POLICY.version


def test_structural_failure_does_not_advance_mark_then_recovers(runtime):
    current, database, _, tick, advance = runtime
    tick()
    advance(AT)
    current['quotes']['BTCUSDT']['bids'] = []
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        first = tick(AT+dt.timedelta(seconds=2))
        replay = tick(AT+dt.timedelta(seconds=2))
        execution.assert_not_called()
    assert first['reason'] == replay['reason'] == 'invalid_book'
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        assert db.execute('SELECT COUNT(*) FROM risk_events').fetchone()[0] == 1
        assert json.loads(db.execute('SELECT payload FROM state').fetchone()[0])['positions'] == {}
    later = AT + dt.timedelta(minutes=15)
    advance(later, name='recovered')
    recovered = tick(later+dt.timedelta(seconds=2))
    assert recovered['status'] == 'healthy' and recovered['order_count'] == 1


@pytest.mark.parametrize('direction', [1., -1.])
def test_partial_protective_reduction_under_abnormal_spread(direction):
    a = position(state(targets={'BTCUSDT': direction*.1}), 20.*direction)
    result, fills, _, _ = run(a, {'BTCUSDT': book(99.9, 150.)})
    assert len(fills) == 1
    assert result['positions']['BTCUSDT']['quantity'] == 10.*direction
    assert result['risk']['market_checks'][0]['protective'] is True


def test_sanity_exemption_does_not_allow_reversal():
    a = position(state(targets={'BTCUSDT': -.1}))
    assert_veto('spread_limit', account=a, q=book(99.9, 150.))


def test_replay_after_protective_reduction_has_no_second_fill(runtime):
    current, database, _, tick, advance = runtime
    tick()
    advance(AT)
    tick(AT+dt.timedelta(seconds=2))
    notice = AT+dt.timedelta(minutes=1)
    current['records'].append(decision({}, name='protective', available=notice))
    tick(notice)
    close_at = AT+dt.timedelta(minutes=15)
    advance(close_at, name='wide-close')
    current['quotes']['BTCUSDT']['asks'][0]['price'] = 150.
    closed = tick(close_at+dt.timedelta(seconds=2))
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        replay = tick(close_at+dt.timedelta(seconds=3))
        execution.assert_not_called()
    assert closed['order_count'] == replay['order_count'] == 2
    assert replay['position_count'] == 0


@pytest.fixture(autouse=True)
def isolate_global_gate_for_pre_p004_regression(monkeypatch):
    """Keep this earlier-stage unit suite isolated; real global gates have their own suite."""
    import contextlib
    from octobot.ai_strategy_lab import paper_runtime_authorization
    monkeypatch.setattr(paper_runtime_authorization, 'entry_scope', lambda *a, **k: contextlib.nullcontext({"test_only": True}))
