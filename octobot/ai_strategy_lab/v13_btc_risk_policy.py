"""Versioned safety limits for the separate V13 BTC paper experiment."""
from __future__ import annotations

import datetime as dt
import math

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import v13_paper_v2 as paper

VERSION = 'risk-policy-v13-btc-paper-v1'
LIMITS = {'daily_loss': {'limit_fraction': .02},
          'drawdown': {'limit_fraction': .05},
          'order_frequency': {'max_new_entries': 4, 'window_seconds': 86400},
          'cooldown': {'seconds': 3600}}


def validate(policy):
    if (not isinstance(policy,dict) or policy.get('version') != VERSION
        or any(policy.get(key) != value for key,value in LIMITS.items())
        or policy.get('per_asset_exposure') != paper.MAX_ASSET
        or policy.get('gross_exposure') != paper.MAX_GROSS
        or policy.get('missing_gates') != []):
        raise auth.Denied('risk_policy_incomplete')
    return policy


def initialize(db):
    tables={row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'orders' in tables and db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]:
        if not {'daily_equity_reference','equity_peak','new_risk_fills'} <= tables:
            raise auth.Denied('policy_state_missing')
    db.executescript('''CREATE TABLE IF NOT EXISTS daily_equity_reference (
        utc_day TEXT PRIMARY KEY, equity REAL NOT NULL, first_observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS equity_peak (
        account TEXT PRIMARY KEY, equity REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS new_risk_fills (
        decision_hash TEXT PRIMARY KEY, recorded_at TEXT NOT NULL);
    ''')


def check(policy, db, marked_state, now):
    validate(policy)
    equity = paper.totals(marked_state, require_positive=False)['equity']
    if not math.isfinite(equity) or equity <= 0:
        raise auth.Denied('policy_equity_invalid')
    day = now.date().isoformat()
    row = db.execute('SELECT equity FROM daily_equity_reference WHERE utc_day=?',(day,)).fetchone()
    if row is None:
        first = db.execute('SELECT equity FROM equity_history WHERE substr(bar,1,10)=? ORDER BY bar LIMIT 1',(day,)).fetchone()
        reference = first[0] if first else equity
        if not isinstance(reference,(int,float)) or not math.isfinite(reference) or reference <= 0:
            raise auth.Denied('policy_daily_reference_invalid')
        db.execute('INSERT INTO daily_equity_reference VALUES (?,?,?)',(day,reference,now.isoformat()))
    else:
        reference = row[0]
    if not isinstance(reference,(int,float)) or not math.isfinite(reference) or reference <= 0:
        raise auth.Denied('policy_daily_reference_invalid')
    peak_row = db.execute('SELECT equity FROM equity_peak WHERE account=?',('v13-paper-v2',)).fetchone()
    if peak_row is None:
        if (db.execute('SELECT COUNT(*) FROM new_risk_fills').fetchone()[0]
            or ('orders' in {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                and db.execute('SELECT COUNT(*) FROM orders').fetchone()[0])):
            raise auth.Denied('policy_peak_missing')
        historic = db.execute('SELECT MAX(equity) FROM equity_history').fetchone()[0]
        peak = max(equity,historic) if historic is not None else equity
        db.execute('INSERT INTO equity_peak VALUES (?,?)',('v13-paper-v2',peak))
    else:
        peak = peak_row[0]
        if not isinstance(peak,(int,float)) or not math.isfinite(peak) or peak <= 0:
            raise auth.Denied('policy_peak_invalid')
        if equity > peak:
            peak = equity
            db.execute('UPDATE equity_peak SET equity=? WHERE account=?',(peak,'v13-paper-v2'))
    if equity <= reference * (1-LIMITS['daily_loss']['limit_fraction']):
        raise auth.Denied('daily_loss_limit')
    if equity <= peak * (1-LIMITS['drawdown']['limit_fraction']):
        raise auth.Denied('drawdown_limit')
    since = (now-dt.timedelta(seconds=LIMITS['order_frequency']['window_seconds'])).isoformat()
    count = db.execute('SELECT COUNT(*) FROM new_risk_fills WHERE recorded_at > ? AND recorded_at <= ?',
                       (since,now.isoformat())).fetchone()[0]
    if count >= LIMITS['order_frequency']['max_new_entries']:
        raise auth.Denied('order_frequency_limit')
    latest = db.execute('SELECT MAX(recorded_at) FROM new_risk_fills').fetchone()[0]
    if latest and now-auth.timestamp(latest) < dt.timedelta(seconds=LIMITS['cooldown']['seconds']):
        raise auth.Denied('cooldown_active')


def record_new_risk(db, decision_hash, now):
    db.execute('INSERT INTO new_risk_fills VALUES (?,?)',(decision_hash,now.isoformat()))
