"""Read-only, pinned research snapshot for the M1 review UI; no live DB scans.

Card work-card-7756c81b-3d80-48cd-836a-c9fa1dbe4e57.
"""
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

REPORT = Path(__file__).resolve().parents[2] / 'reports/V13_M1_SYMBOL_REVIEW_2026-10-23.json'
REPORT_SHA256 = '3d7bdbfb0ba5d60ddca6ccf4457a04e27b61eea705b75ec17501e3a5af8fb2cd'
VERSION = 'm1-symbol-review-ui-v1'


def live_view():
    from . import v13_m1_live_review
    return v13_m1_live_review.public_view()


def finite(value):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise ValueError('invalid_metric')
    return value


def public_view(path=REPORT, now=None):
    """The accepted hash identifies the whole review, not an execution approval."""
    try:
        payload = Path(path).read_bytes()
        if len(payload) > 1024*1024 or hashlib.sha256(payload).hexdigest() != REPORT_SHA256:
            raise ValueError('report_identity')
        data = json.loads(payload)
        if data['schema'] != 1 or data['scope'] != 'EXPLORATORY_ADVISORY_ONLY_NO_ORDERS':
            raise ValueError('review_scope')
        if data['execution_authorized'] is not False or not data['history_inherited_not_scored']:
            raise ValueError('review_authority')
        now = now or dt.datetime.now(dt.timezone.utc)
        end = dt.datetime.fromisoformat(data['end'])
        if end.tzinfo is None or now < end:
            raise ValueError('review_time')
        symbols = sorted(data['m1']['symbols'])
        if len(symbols) != 18 or symbols != sorted(data['original']['symbols']):
            raise ValueError('review_universe')
        for account in ('m1', 'original'):
            total = 0.
            for record in data[account]['symbols'].values():
                for window in ('since_clone', '48h', '24h'):
                    w = record['windows'][window]
                    side_net = 0.
                    for direction in ('LONG', 'SHORT'):
                        s = w['sides'][direction]
                        for key in ('realized','fees','funding','open_pnl_start','open_pnl_end','net'):
                            finite(s[key])
                        if not math.isclose(s['net'], s['realized']+s['open_pnl_end']-s['open_pnl_start']-s['fees']+s['funding'], abs_tol=1e-6):
                            raise ValueError('side_reconciliation')
                        side_net += s['net']
                    if not math.isclose(side_net, w['net'], abs_tol=1e-6):
                        raise ValueError('window_reconciliation')
                total += record['since_clone']
            if not math.isclose(total, data[account]['net_since_clone'], abs_tol=1e-6):
                raise ValueError('account_reconciliation')
        if any(p['applied'] is not False or p['execution_authorized'] is not False for p in data['proposals']):
            raise ValueError('proposal_authority')
        return dict(available=True, version=VERSION, report_id=REPORT_SHA256,
                    snapshot=True, stale=(now-end).total_seconds()>86400,
                    maintenance_active=False, review=data)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return dict(available=False, version=VERSION, maintenance_active=False,
                    message='Revisione M1 non verificabile. Metriche e proposte non disponibili.')
