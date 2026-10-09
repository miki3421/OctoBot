"""Paper V1 policy boundaries on isolated SQLite state."""
import datetime as dt
import sqlite3

import pytest

from octobot.ai_strategy_lab import v13_btc_risk_policy as risk

NOW=dt.datetime(2026,9,25,12,tzinfo=dt.timezone.utc)
POLICY=dict(version=risk.VERSION,per_asset_exposure=.315,gross_exposure=.90,
    daily_loss=dict(limit_fraction=.02),drawdown=dict(limit_fraction=.05),
    order_frequency=dict(max_new_entries=4,window_seconds=86400),
    cooldown=dict(seconds=3600),missing_gates=[])


def state(*, unrealized=0, realized=0, fees=0, funding=0):
    return dict(initial_equity=10000,positions={'BTCUSDT':dict(quantity=1,entry_price=100,
        current_price=100+unrealized,realized_pnl=realized,fees=fees,funding=funding)})


@pytest.fixture
def db():
    with sqlite3.connect(':memory:') as connection:
        connection.execute('CREATE TABLE equity_history(bar TEXT PRIMARY KEY,equity REAL,pnl REAL)')
        risk.initialize(connection)
        yield connection


@pytest.mark.parametrize('loss,blocked',[(199.99,False),(200,True),(200.01,True)])
def test_daily_loss_boundary_includes_unrealized(db,loss,blocked):
    risk.check(POLICY,db,state(),NOW)
    if blocked:
        with pytest.raises(ValueError,match='daily_loss_limit'):
            risk.check(POLICY,db,state(unrealized=-loss),NOW)
    else:
        risk.check(POLICY,db,state(unrealized=-loss),NOW)


def test_fee_and_funding_breach_and_restart_day_rollover(db):
    risk.check(POLICY,db,state(),NOW)
    with pytest.raises(ValueError,match='daily_loss_limit'):
        risk.check(POLICY,db,state(fees=101,funding=-100),NOW)
    tomorrow=NOW+dt.timedelta(days=1,minutes=7)
    risk.check(POLICY,db,state(fees=50),tomorrow)
    assert db.execute('SELECT COUNT(*) FROM daily_equity_reference').fetchone()[0]==2
    assert db.execute('SELECT first_observed_at FROM daily_equity_reference WHERE utc_day=?',
                      (tomorrow.date().isoformat(),)).fetchone()[0]==tomorrow.isoformat()


def test_drawdown_peak_exact_and_above_with_reduction_exempt(db):
    risk.check(POLICY,db,state(unrealized=1000),NOW)
    later=NOW+dt.timedelta(days=1)
    with pytest.raises(ValueError,match='drawdown_limit'):
        risk.check(POLICY,db,state(unrealized=450),later)
    assert db.execute('SELECT equity FROM equity_peak').fetchone()[0]==11000


def test_frequency_and_cooldown_restart_boundaries(db):
    risk.check(POLICY,db,state(),NOW)
    for index in range(4):
        at=NOW+dt.timedelta(hours=index)
        risk.record_new_risk(db,'decision-'+str(index),at)
    with pytest.raises(ValueError,match='order_frequency_limit'):
        risk.check(POLICY,db,state(),NOW+dt.timedelta(hours=4))
    risk.check(POLICY,db,state(),NOW+dt.timedelta(hours=24,seconds=1))
    db.execute('DELETE FROM new_risk_fills')
    risk.record_new_risk(db,'decision-last',NOW+dt.timedelta(hours=24,seconds=1))
    with pytest.raises(ValueError,match='cooldown_active'):
        risk.check(POLICY,db,state(),NOW+dt.timedelta(hours=24,minutes=59))
    risk.check(POLICY,db,state(),NOW+dt.timedelta(hours=25,seconds=1))


def test_policy_missing_is_denied(db):
    altered=dict(POLICY,cooldown=None)
    with pytest.raises(ValueError,match='risk_policy_incomplete'):
        risk.check(altered,db,state(),NOW)


def test_missing_persisted_policy_tables_after_economic_activity_is_denied():
    with sqlite3.connect(':memory:') as db:
        db.execute('CREATE TABLE orders(id INTEGER)')
        db.execute('INSERT INTO orders VALUES (1)')
        with pytest.raises(ValueError,match='policy_state_missing'):
            risk.initialize(db)


def test_observed_xbtusdtm_contract_minima_still_unknown_denies_entry():
    # Values copied from the captured public /contracts/XBTUSDTM response;
    # the book here is synthetic, so this is a metadata veto, not fill proof.
    from octobot.ai_strategy_lab import v13_market_sanity
    quote=dict(mark_price=83920.01,fee_rate=.0006,price_tick=.1,
        contract_multiplier=.001,quantity_step=.001,step=.001,
        min_quantity=None,min_notional=None,
        bids=[dict(price=83920.,base_quantity=1.)],
        asks=[dict(price=83920.1,base_quantity=1.)])
    with pytest.raises(v13_market_sanity.Veto,match='missing_market_metadata'):
        v13_market_sanity.preflight('BTCUSDT',quote,.001,False)
