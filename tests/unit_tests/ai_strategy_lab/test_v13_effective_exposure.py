"""P0-02: all rejected intents must stop before the simulated fill boundary."""
import copy
import json
import sqlite3
import math
from unittest.mock import patch

import pytest
from tests.unit_tests.ai_strategy_lab.test_v13_paper_v2 import START, quote, market, state, dt, runtime, decision, counts
from octobot.ai_strategy_lab import v13_paper_v2 as paper

AT = START + dt.timedelta(minutes=15)


def tick(account, quotes=None):
    if quotes is None:
        quotes = {s: quote(AT, symbol=s) for s in set(account['pending']['targets']) | set(account['positions'])}
    return paper.process_market(account, market(AT), quotes, AT)


def test_original_counterexample_rejected_before_any_fill():
    account = state(targets={'BTCUSDT': .315, 'ETHUSDT': .315, 'SOLUSDT': .27})
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result, fills, _, _ = tick(account)
        execution.assert_not_called()
    assert fills == []
    assert result['risk']['reason'] == 'projected_exposure_limit'
    assert result['pending'] == account['pending']


def test_asset_boundary_costs_rejected_before_any_fill():
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result, fills, _, _ = tick(state(targets={'BTCUSDT': .315}))
        execution.assert_not_called()
    assert not fills
    assert result['risk']['reason'] == 'projected_exposure_limit'


def clean_quote(*, symbol="BTCUSDT", price=100., step=1e-10):
    q = quote(AT, symbol=symbol, price=price, step=step, fee=0)
    q['bids'][0]['price'] = q['asks'][0]['price'] = price
    q['price_tick'] = 1e-10
    return q


@pytest.fixture
def no_slippage(monkeypatch):
    monkeypatch.setattr(paper.v13_market, 'ADVERSE_SLIPPAGE_RATE', 0.)


def held(account, symbol='BTCUSDT', quantity=10., price=100., **values):
    account['positions'][symbol] = dict(paper.new_position(), quantity=quantity,
        entry_price=price, current_price=price, **values)
    return account


def rejected(account, quotes=None, reason=None, raises=False):
    before = copy.deepcopy(account)
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        try:
            if raises:
                with pytest.raises((ValueError, KeyError, TypeError)):
                    tick(account, quotes)
                return
            result, fills, _, _ = tick(account, quotes)
            assert not fills
            assert result['risk']['reason']
            if reason:
                assert reason in (result['risk']['reason'] + ' ' + result['risk'].get('market_veto', {}).get('detail', ''))
            assert result['pending'] == account['pending']
            return result
        finally:
            execution.assert_not_called()
            assert account == before


@pytest.mark.parametrize('offset,accepted', [(0., True), (-1e-10, True), (1e-10, False)])
@pytest.mark.parametrize('gross', [False, True])
def test_effective_boundaries(no_slippage, offset, accepted, gross):
    weights = ({'BTCUSDT': .3, 'ETHUSDT': .3, 'SOLUSDT': .3 + offset}
               if gross else {'BTCUSDT': .315 + offset})
    account = state(targets=weights)
    quotes = {s: clean_quote(symbol=s) for s in weights}
    if not accepted:
        rejected(account, quotes, 'projected_exposure_limit')
    else:
        result, fills, _, _ = tick(account, quotes)
        assert len(fills) == len(weights)
        assert result['risk']['reason'] is None
        assert len(result['risk']['post_fills']) == len(fills)
        assert all(not v['breaches'] for v in result['risk']['post_fills'])


@pytest.mark.parametrize('cost', ['fees', 'spread', 'slippage', 'price_rounding'])
def test_each_cost_can_break_boundary(monkeypatch, cost):
    monkeypatch.setattr(paper.v13_market, 'ADVERSE_SLIPPAGE_RATE', .0002 if cost == 'slippage' else 0)
    q = clean_quote()
    if cost == 'fees': q['fee_rate'] = .001
    if cost == 'spread': q['asks'][0]['price'] = 100.1
    if cost == 'price_rounding':
        q['asks'][0]['price'] = 100.00001
        q['price_tick'] = .1
    rejected(state(targets={'BTCUSDT': .315}), {'BTCUSDT': q}, 'projected_exposure_limit')


def test_existing_asset_must_still_fit_after_other_asset_costs():
    account = held(state(targets={'BTCUSDT': .315, 'ETHUSDT': .01}), quantity=31.5)
    rejected(account, reason='projected_exposure_limit')


def test_increase_accounts_for_existing_unrealized_and_realized_pnl():
    account = held(state(targets={'BTCUSDT': .315}), quantity=10., price=90., realized_pnl=-100.)
    rejected(account, reason='projected_exposure_limit')


@pytest.mark.parametrize('old,target', [(20., -.315), (-20., .315)])
def test_reversal_is_new_risk(old, target):
    rejected(held(state(targets={'BTCUSDT': target}), quantity=old), reason='projected_exposure_limit')


@pytest.mark.parametrize('old,target', [(10., -.1), (-10., .1)])
def test_compliant_reversal_reconciles(old, target):
    result, fills, _, _ = tick(held(state(targets={'BTCUSDT': target}), quantity=old))
    assert len(fills) == 1
    assert not result['risk']['current']['breaches']
    assert result['positions']['BTCUSDT']['quantity'] * old < 0
    assert result['positions']['BTCUSDT']['realized_pnl'] < 0


@pytest.mark.parametrize('target', [0., .1, .315])
def test_reduction_above_cap_allowed_even_if_still_over(target):
    account = held(state(targets={'BTCUSDT': target}), quantity=40.)
    result, fills, _, _ = tick(account)
    assert len(fills) == 1 and fills[0]['quantity'] < 0
    assert result['positions']['BTCUSDT']['quantity'] >= 0
    assert result['positions']['BTCUSDT']['quantity'] < 40
    assert result['pending'] is None
    if target == .315:
        assert result['risk']['current']['asset_ratios']['BTCUSDT'] > .315
        assert result['risk']['reason'] == 'risk_reduction_above_limit'
    else:
        assert not result['risk']['current']['breaches']


@pytest.mark.parametrize('cause', ['mark', 'realized', 'funding', 'fees'])
def test_passive_breach_persisted_and_new_risk_blocked(cause):
    account = held(state(targets={'BTCUSDT': .315, 'ETHUSDT': .01}), quantity=31.5,
                   last_mark_at=START.isoformat())
    q = quote(AT)
    if cause == 'mark': q = quote(AT, price=110.)
    if cause == 'realized': account['positions']['BTCUSDT']['realized_pnl'] = -1
    if cause == 'fees': account['positions']['BTCUSDT']['fees'] = 1
    if cause == 'funding':
        q['funding'] = [dict(timestamp_ms=int(AT.timestamp()*1000), rate=.001)]
    quotes = {'BTCUSDT': q, 'ETHUSDT': quote(AT, symbol='ETHUSDT')}
    result = rejected(account, quotes, 'current_exposure_limit')
    assert result['risk']['current']['breaches']
    account['pending'] = None
    result, fills, funding, _ = tick(account, quotes)
    assert not fills
    assert result['risk']['reason'] == 'passive_exposure_limit'
    assert paper.health_payload(result, AT)['status'] == 'blocked'
    if cause == 'funding': assert len(funding) == 1


@pytest.mark.parametrize('equity', [0., -1., float('nan'), float('inf'), -float('inf')])
def test_invalid_equity_never_executes(equity):
    account = state()
    account['initial_equity'] = equity
    rejected(account, raises=not math.isfinite(equity))


@pytest.mark.parametrize('equity', [0., -100.])
def test_known_positions_can_close_with_nonpositive_equity(equity):
    account = held(state(targets={}), quantity=10.)
    account['initial_equity'] = equity
    result, fills, _, _ = tick(account)
    assert len(fills) == 1
    assert result['positions']['BTCUSDT']['quantity'] == 0
    assert result['risk']['current']['gross'] == 0
    assert result['risk']['reason'] == 'risk_reduction_above_limit'
    assert paper.health_payload(result, AT)['equity'] < 0


@pytest.mark.parametrize('field', ['step', 'quantity_step', 'contract_multiplier', 'price_tick', 'min_quantity', 'min_notional', 'fee_rate'])
@pytest.mark.parametrize('value', [None, float('nan'), float('inf'), -1.])
def test_invalid_required_metadata_stops_before_execution(field, value):
    q = quote(AT)
    q[field] = value
    rejected(state(), {'BTCUSDT': q})


@pytest.mark.parametrize('field', ['quantity_step', 'price_tick', 'min_quantity', 'min_notional', 'contract_multiplier'])
def test_missing_metadata_not_invented(field):
    q = quote(AT)
    del q[field]
    rejected(state(), {'BTCUSDT': q}, 'missing')


@pytest.mark.parametrize('field,value', [(f, v) for f in ('mark_price', 'fee_rate')
                         for v in (float('nan'), float('inf'), 0., -1.)
                         if not (f == 'fee_rate' and v == 0.)])
def test_invalid_pricing_is_not_executed(field, value):
    q = quote(AT)
    q[field] = value
    rejected(state(), {'BTCUSDT': q}, raises=(field == 'mark_price'))


@pytest.mark.parametrize('weight', [float('nan'), float('inf'), -float('inf')])
def test_nonfinite_targets_do_not_execute(weight):
    rejected(state(targets={'BTCUSDT': weight}))


@pytest.mark.parametrize('constraint,value', [('min_quantity', 11.), ('min_notional', 2000.), ('contract_multiplier', .03)])
def test_minima_and_multiplier_are_enforced_without_inflating_order(constraint, value):
    q = quote(AT)
    q[constraint] = value
    rejected(state(), {'BTCUSDT': q})


def test_existing_off_grid_quantity_rejects_new_risk():
    account = held(state(targets={'BTCUSDT': .1}), quantity=1.005)
    rejected(account, reason='quantity precision')


def test_quantity_rounding_never_adds_capacity(no_slippage):
    account = state(targets={'BTCUSDT': .3149999999999999})
    q = clean_quote(step=.01)
    result, fills, _, _ = tick(account, {'BTCUSDT': q})
    assert fills[0]['quantity'] == 31.49
    assert result['risk']['current']['asset_ratios']['BTCUSDT'] < .315


def test_missing_metadata_allows_observed_protective_close():
    account = held(state(targets={}), quantity=40.)
    q = quote(AT)
    for key in ('step', 'contract_multiplier', 'price_tick', 'min_quantity', 'min_notional'):
        del q[key]
    result, fills, _, _ = tick(account, {'BTCUSDT': q})
    assert len(fills) == 1 and fills[0]['quantity'] == -40.
    assert result['positions']['BTCUSDT']['quantity'] == 0


def test_missing_held_quote_blocks_new_risk():
    account = held(state(targets={'ETHUSDT': .1}), quantity=10.)
    rejected(account, {'ETHUSDT': quote(AT, symbol='ETHUSDT')}, 'missing portfolio quotes')


def test_mixed_reduction_and_bad_new_risk_is_atomic():
    account = held(state(targets={'BTCUSDT': .1, 'ETHUSDT': .315}), quantity=20.)
    rejected(account, reason='projected_exposure_limit')


def test_net_exposure_recomputed_each_fill(no_slippage):
    account = state(targets={'BTCUSDT': .3, 'ETHUSDT': -.3, 'SOLUSDT': .3})
    result, fills, _, _ = tick(account, {s: clean_quote(symbol=s) for s in account['pending']['targets']})
    assert len(fills) == 3
    assert result['risk']['current']['gross_ratio'] == pytest.approx(.9)
    assert result['risk']['current']['net_ratio'] == pytest.approx(.3)


def test_postfill_mismatch_aborts_whole_tick():
    account = state()
    original = copy.deepcopy(account)
    fill = paper.apply_fill
    def corrupted(position, quantity, price, fee):
        fill(position, quantity, price, fee)
        position['fees'] += 1
    with patch.object(paper, 'apply_fill', side_effect=corrupted):
        with pytest.raises(ValueError, match='post-fill projection mismatch'):
            tick(account)
    assert account == original


def test_tolerance_is_only_eight_binary64_ulps():
    from octobot.ai_strategy_lab import v13_exposure as risk
    import math
    assert risk.RATIO_ULPS == 8
    for limit in (paper.MAX_GROSS, paper.MAX_ASSET):
        assert not risk.above(limit + 8*math.ulp(limit), limit)
        assert risk.above(limit + 9*math.ulp(limit), limit)
        assert risk.above(limit + 1e-12, limit)


def test_rejection_persists_across_reopen_and_replay(runtime):
    current, database, health, run, advance = runtime
    current['records'] = [decision({'BTCUSDT': .315, 'ETHUSDT': .315, 'SOLUSDT': .27})]
    run()
    advance(AT, prices={s: 100. for s in ('BTCUSDT', 'ETHUSDT', 'SOLUSDT')})
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        first = run(AT + dt.timedelta(seconds=2))
        before = counts(database)
        repeated = run(AT + dt.timedelta(minutes=1))
        execution.assert_not_called()
    assert first['reason'] == repeated['reason'] == 'projected_exposure_limit'
    assert before == counts(database)
    assert first['risk'] == repeated['risk']
    assert first['risk']['rejected_projection']['breaches']
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        event, = db.execute('SELECT payload FROM risk_events').fetchone()
        assert json.loads(event) == first['risk']
        saved = json.loads(db.execute('SELECT payload FROM state').fetchone()[0])
        assert saved['pending'] and saved['order_count'] == 0
        assert db.execute('SELECT status FROM intents').fetchone()[0] == 'pending'
    assert json.loads(health.read_text())['risk'] == first['risk']


def test_passive_drift_survives_restart_and_close_recovers(runtime):
    current, database, _, run, advance = runtime
    current['records'] = [decision({'BTCUSDT': .30})]
    run()
    advance(AT)
    assert run(AT + dt.timedelta(seconds=2))['order_count'] == 1
    later = AT + dt.timedelta(minutes=15)
    advance(later, name='drift', prices={'BTCUSDT': 110.})
    drift = run(later + dt.timedelta(seconds=2))
    assert drift['reason'] == 'passive_exposure_limit'
    assert drift['order_count'] == 1
    assert run(later + dt.timedelta(seconds=3))['risk'] == drift['risk']
    current['records'].append(decision({}, name='close', available=later))
    run(later + dt.timedelta(seconds=4))
    close_at = later + dt.timedelta(minutes=15)
    advance(close_at, name='close-market', prices={'BTCUSDT': 110.})
    # Real archives need not suddenly acquire missing venue constraints to exit.
    for key in ('quantity_step', 'price_tick', 'min_quantity', 'min_notional'):
        del current['quotes']['BTCUSDT'][key]
    closed = run(close_at + dt.timedelta(seconds=2))
    assert closed['status'] == 'healthy'
    assert closed['order_count'] == 2 and closed['position_count'] == 0
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        risks = [json.loads(r[0]) for r in db.execute('SELECT payload FROM risk_events ORDER BY rowid')]
        assert [r['reason'] for r in risks] == [None, 'passive_exposure_limit', None]
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_archived_missing_constraints_block_new_risk_not_inferred():
    from tests.unit_tests.ai_strategy_lab.test_v13_market import record_at, NOW, signed
    record = record_at()
    future = record['symbols']['AAVE']['futures']
    future['normalized_asks'][0].update(price=100.1, quote_quantity=100.1)
    record = signed(record)
    quotes = paper.v13_market.market_quotes(record, {'AAVEUSDT'})
    account = state(targets={'AAVEUSDT': .01})
    account['pending']['noticed_at'] = (NOW - dt.timedelta(minutes=1)).isoformat()
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        result, fills, _, _ = paper.process_market(account, record, quotes, NOW)
        execution.assert_not_called()
    assert not fills and result['risk']['reason'] == 'missing_market_metadata'
    assert quotes['AAVEUSDT']['quantity_step'] is None
    assert quotes['AAVEUSDT']['price_tick'] is None


def test_explicit_archived_constraints_forwarded_without_multiplier_double_count():
    from tests.unit_tests.ai_strategy_lab.test_v13_market import record_at, NOW, signed
    record = record_at()
    future = record['symbols']['AAVE']['futures']
    future['normalized_asks'][0].update(price=100.1, quote_quantity=100.1)
    future.update(quantity_step=.02, price_tick=.1, min_quantity=.02, min_notional=1.)
    record = signed(record)
    quotes = paper.v13_market.market_quotes(record, {'AAVEUSDT'})
    assert quotes['AAVEUSDT']['step'] == .02
    account = state(targets={'AAVEUSDT': .01})
    account['pending']['noticed_at'] = (NOW - dt.timedelta(minutes=1)).isoformat()
    result, fills, _, _ = paper.process_market(account, record, quotes, NOW)
    assert len(fills) == 1
    assert fills[0]['quantity'] == .98
    assert result['risk']['current']['gross'] == pytest.approx(.98 * 100.5)


def test_postfill_failure_rolls_back_sqlite(runtime):
    _, database, _, run, advance = runtime
    run()
    advance(AT)
    before = counts(database)
    original = paper.apply_fill
    def wrong_fee(position, quantity, price, fee):
        original(position, quantity, price, fee + 1.)
    with patch.object(paper, 'apply_fill', side_effect=wrong_fee):
        result = run(AT + dt.timedelta(seconds=2))
    assert result['reason'] == 'post-fill projection mismatch'
    assert counts(database) == before
    with sqlite3.connect(f'file:{database}?mode=ro', uri=True) as db:
        assert db.execute('SELECT COUNT(*) FROM risk_events').fetchone()[0] == 0
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def test_valid_small_increment_does_not_fail_quantity_grid(no_slippage):
    account = held(state(targets={'BTCUSDT': .10}), quantity=9.99)
    result, fills, _, _ = tick(account, {'BTCUSDT': clean_quote(step=.01)})
    assert len(fills) == 1
    assert fills[0]['quantity'] == pytest.approx(.01)
    assert result['positions']['BTCUSDT']['quantity'] == 10.


def test_adverse_short_mark_decreases_equity_and_blocks_new_risk():
    account = held(state(targets={'BTCUSDT': -.31, 'ETHUSDT': .01}), quantity=-31.)
    result = rejected(account, {'BTCUSDT': quote(AT, price=102.), 'ETHUSDT': quote(AT, symbol='ETHUSDT')}, 'current_exposure_limit')
    assert result['risk']['current']['equity'] == 9938.


def test_failed_second_leg_never_executes_first_leg():
    account = state(targets={'BTCUSDT': .1, 'ETHUSDT': .1})
    quotes = {s: quote(AT, symbol=s) for s in account['pending']['targets']}
    quotes['ETHUSDT']['asks'][0]['base_quantity'] = .01
    rejected(account, quotes, reason='insufficient_depth')


def test_invalid_existing_balance_never_executes():
    account = held(state(), fees=float('nan'))
    rejected(account, raises=True)


def test_rejected_new_risk_commits_funding_once(runtime):
    current, database, _, run, advance = runtime
    current['records'] = [decision({'BTCUSDT': .3})]
    run()
    advance(AT)
    run(AT + dt.timedelta(seconds=2))
    later = AT + dt.timedelta(minutes=15)
    current['records'].append(decision({'BTCUSDT': .315}, name='increase', available=later))
    run(later)
    settlement = dict(timestamp_ms=int((later+dt.timedelta(minutes=1)).timestamp()*1000), rate=.001)
    next_at = later + dt.timedelta(minutes=15)
    advance(next_at, name='rejected-funded', funding=[settlement])
    for key in ('step', 'quantity_step', 'contract_multiplier', 'min_quantity'):
        current['quotes']['BTCUSDT'][key] = 1e-8
    with patch.object(paper, 'apply_fill', wraps=paper.apply_fill) as execution:
        rejected_result = run(next_at + dt.timedelta(seconds=2))
        again = run(next_at + dt.timedelta(seconds=3))
        execution.assert_not_called()
    assert rejected_result['reason'] == 'projected_exposure_limit'
    assert rejected_result['funding'] == again['funding'] == -3.
    assert counts(database)['orders'] == 1
    assert counts(database)['funding_events'] == 1


@pytest.fixture(autouse=True)
def isolate_global_gate_for_pre_p004_regression(monkeypatch):
    """Keep this earlier-stage unit suite isolated; real global gates have their own suite."""
    import contextlib
    from octobot.ai_strategy_lab import paper_runtime_authorization
    monkeypatch.setattr(paper_runtime_authorization, 'entry_scope', lambda *a, **k: contextlib.nullcontext({"test_only": True}))
