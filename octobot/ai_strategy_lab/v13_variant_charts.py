"""Read-only symbol chart adapter for the FAST/HALF/M1 full-history branches.

Card work-card-6567dd57-1312-4f35-9b44-dd27730d8e2c.
Consumes the atomic comparison projection and the existing public-price ledger.
No branch, strategy, authorization or database writes.
"""
from collections import defaultdict
from contextlib import closing
import datetime as dt
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3

from octobot.ai_strategy_lab import v13_symbol_charts as charts
from octobot.ai_strategy_lab import v13_m1_paper_view

VARIANTS = {'fast': 'FAST', 'half': 'HALF', 'm1': 'M1'}
HASH = re.compile(r'^[0-9a-f]{64}$')
SIGNATURE = ('bar', 'symbol', 'action', 'quantity', 'price', 'fee', 'status')
MAX_JSON = 32 * 1024 * 1024


def read_json(path):
    path = Path(path)
    if path.is_symlink():
        raise ValueError('symlink_input')
    with path.open('rb') as stream:
        raw = stream.read(MAX_JSON + 1)
    if len(raw) > MAX_JSON:
        raise ValueError('input_too_large')
    if path.suffix == '.gz':
        import io
        with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
            raw = stream.read(MAX_JSON + 1)
        if len(raw) > MAX_JSON:
            raise ValueError('input_too_large')
    return json.loads(raw)


def canonical_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def projection(root, variant, now):
    if variant not in VARIANTS:
        raise ValueError('unknown_variant')
    if variant == 'm1':
        value = v13_m1_paper_view.public(root / 'm1-paper-ui/account.json', now)
        receipt, account = value['receipt'], value['variant']
        seed = receipt['seed_sha256']
        expected = 'v13-m1-short-paper-v1-' + seed[:12]
        if (value.get('available') is not True
                or receipt['scope'] != 'RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK'
                or not HASH.fullmatch(seed)
                or receipt['account_id'] != expected or account['account_id'] != expected
                or account['fork_at'] != receipt['economic_t0']):
            raise ValueError('variant_account_identity')
        fork, as_of = map(charts.timestamp, (receipt['economic_t0'], account['observed_at']))
        generated, checked = map(charts.timestamp, (value['generated_at'], value['health']['checked_at']))
        if not fork <= as_of <= generated <= now or not fork <= checked <= generated:
            raise ValueError('projection_time')
        stale = (value['stale'] or (now - checked).total_seconds() > 180
                 or (now - as_of).total_seconds() > 300)
        return value, account, fork, as_of, stale
    path = root / 'forks-ui/comparison.json'
    if path.stat().st_uid != 30934 or path.stat().st_mode & 0o022:
        raise ValueError('projection_custody')
    value = read_json(path)
    receipt = value['receipt']
    parent = receipt['parent_snapshot_sha256']
    if (value.get('available') is not True or value.get('schema') != 1
            or receipt['scope'] != 'RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK'
            or not HASH.fullmatch(parent)):
        raise ValueError('projection_scope')
    for arm in ('FAST', 'HALF'):
        expected = 'v13-risk-matched-clone-v2-' + arm.lower() + '-' + parent[:12]
        if receipt['account_ids'][arm] != expected or value['variants'][arm]['account_id'] != expected:
            raise ValueError('variant_account_identity')
    account = value['variants'][VARIANTS[variant]]
    fork, as_of = map(charts.timestamp, (receipt['economic_t0'], account['observed_at']))
    generated, checked = map(charts.timestamp, (value['generated_at'], value['health']['checked_at']))
    if not fork <= as_of <= generated <= now or checked > now:
        raise ValueError('projection_time')
    stale = ((now - generated).total_seconds() > 180
             or (now - checked).total_seconds() > 180
             or (now - as_of).total_seconds() > 420)
    return value, account, fork, as_of, stale


def reference_mark(root, fill, symbol, cache, variant=None):
    key = fill['market_hash']
    if not isinstance(key, str) or not HASH.fullmatch(key):
        raise ValueError('invalid_market_hash')
    if key not in cache:
        base = root / 'research/source/market' / (key + '.json')
        if not base.exists():
            base = base.with_suffix('.json.gz')
        if not base.exists() and variant=='m1':
            base=root/'m1-paper-ui/market'/(key+'.json.gz')
        if not base.exists():
            cache[key] = None
        else:
            record = read_json(base)
            if (record['record_hash'] != key
                    or canonical_hash({k: v for k, v in record.items() if k != 'record_hash'}) != key
                    or record['scope'] != 'RESEARCH_SIMULATION_ONLY'):
                raise ValueError('market_archive_tampered')
            cache[key] = {'observed_at_end': record['observed_at_end'],
                          'marks': {s: q['mark_price'] for s, q in record['quotes'].items()}}
    record = cache[key]
    if record is None:
        return None
    if record['observed_at_end'] != fill['at']:
        raise ValueError('fill_market_time_mismatch')
    return charts.number(record['marks'][symbol])


def load(variant, symbol=None, period='all', root='/v13-paper', now=None, overview=False):
    """Return branch-specific fills against shared, causally bounded public marks."""
    if period not in ('all', '1', '7'):
        raise ValueError('unknown_chart_period')
    now = now or dt.datetime.now(dt.timezone.utc)
    root = Path(root)
    value, account, fork, as_of, stale = projection(root, variant, now)
    positions = {v['symbol']: {'quantity': v['quantity'], 'entry_price': v['entry']}
                 for v in account['positions']}
    if len(positions) != len(account['positions']) or not positions:
        raise ValueError('invalid_positions')
    symbol = symbol or ('BTCUSDT' if 'BTCUSDT' in positions else sorted(positions)[0])
    if not isinstance(symbol, str) or not charts.SYMBOL.fullmatch(symbol) or symbol not in positions:
        raise ValueError('unknown_symbol')
    path = root / 'research/execution/execution.sqlite'
    if path.is_symlink() or not path.is_file():
        raise FileNotFoundError('missing_price_ledger')
    by_symbol = defaultdict(list)
    source_checks = {}
    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        original = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        inherited = [dict(r) for r in db.execute(
            "SELECT o.id,o.bar,o.recorded_at,o.symbol,o.action,o.quantity,o.price,o.fee,o.status,"
            "m.price AS reference_mark FROM orders o LEFT JOIN marks m "
            "ON m.symbol=o.symbol AND m.bar=o.bar WHERE o.status='filled' AND o.bar<=? "
            "ORDER BY o.bar,o.id", (fork.isoformat(),))]
        # Check the immutable economic prefix against the branch writer's projection.
        expected = value['inherited_fills']
        if (len(inherited) != account['historical_order_count'] or len(inherited) != len(expected)
                or any(tuple(r[k] for k in SIGNATURE) != tuple(e[k] for k in SIGNATURE)
                       for r, e in zip(inherited, expected))):
            raise ValueError('inherited_history_mismatch')
        for row in inherited:
            row['origin'] = 'inherited'
            by_symbol[row['symbol']].append(row)
        highest = max([r['id'] for r in inherited] or [0])
        archive_cache = {}
        seen = set()
        for index, fill in enumerate(account['fills'], highest + 1):
            arm = fill.get('arm', 'M1' if variant == 'm1' else None)
            if arm != VARIANTS[variant] or fill['symbol'] not in positions:
                raise ValueError('fill_wrong_arm')
            instant = charts.timestamp(fill['at'])
            key = (fill['at'], fill['symbol'])
            if not fork < instant <= as_of or key in seen:
                raise ValueError('fill_time_or_replay')
            seen.add(key)
            quantity = charts.number(fill['quantity'])
            row = dict(id=index, bar=fill['at'], recorded_at=fill['at'], symbol=fill['symbol'],
                       action='BUY' if quantity > 0 else 'SELL', quantity=quantity,
                       price=fill['price'], fee=fill['fee'], origin='post_fork',
                       reference_mark=reference_mark(root, fill, fill['symbol'], archive_cache, variant))
            by_symbol[fill['symbol']].append(row)
            source_checks[index] = fill
        if len(seen) != account['post_fork_order_count']:
            raise ValueError('post_fork_count_mismatch')
        state = dict(mode=original['mode'], research_epoch=account['account_id'],
                     activation_at=original['activation_at'], last_success_at=as_of.isoformat(),
                     positions=positions)
        start = charts.timestamp(state['activation_at'])
        cutoff = start if period == 'all' else max(start, as_of - dt.timedelta(days=int(period)))
        selected = sorted(positions) if overview else [symbol]
        marks = defaultdict(list)
        series_truncated={}
        # Bound each series before materializing it; avoid sorting the entire
        # multi-symbol archive into a temporary window-function table.
        query = 'SELECT symbol,bar,price FROM marks WHERE symbol=? AND bar>=? AND bar<=? ORDER BY bar DESC LIMIT ?'
        for sym in selected:
            args = (sym, cutoff.isoformat(), as_of.isoformat(), charts.MAX_POINTS + 1)
            for row in db.execute(query, args):
                marks[sym].append(dict(row))
            # Newly admitted M1 symbols have no fabricated Original history.
            # Read only their independently published observations after admission.
            series=root/'m1-paper-ui/series'/(sym+'.json.gz')
            if variant=='m1' and not marks[sym] and series.exists():
                data=read_json(series)
                if (data.get('scope')!='M1_ADMITTED_SYMBOL_PRICES_V1' or data.get('account')!=account['account_id']
                    or data.get('symbol')!=sym or data.get('record_id')!=canonical_hash({k:v for k,v in data.items() if k!='record_id'})):
                    raise ValueError('m1_admitted_prices_changed')
                marks[sym]=[dict(symbol=sym,bar=r['bar'],price=r['price']) for r in data['points'] if cutoff<=charts.timestamp(r['bar'])<=as_of]
                series_truncated[sym]=data['truncated']
        result = []
        for sym in selected:
            prices = sorted(marks[sym], key=lambda x: x['bar'])
            fills = sorted(by_symbol[sym], key=lambda x: x['id'])
            chart = charts.project(state, fills, prices[-charts.MAX_POINTS:], sym, now,
                                   len(prices) > charts.MAX_POINTS or series_truncated.get(sym,False))
            for event, row in zip(chart['fills'], fills):
                event['origin'] = row['origin']
                source = source_checks.get(row['id'])
                if source:
                    for field, calculated in [('before', event['before']), ('after', event['after']),
                                               ('realized_delta', event['realized_pnl'])]:
                        if not math.isclose(charts.number(source[field]), calculated,
                                            rel_tol=1e-9, abs_tol=1e-6):
                            raise ValueError('branch_fill_accounting_mismatch')
            chart.update(stale=stale, variant=variant, account_id=account['account_id'],
                         account_label=account['label'], fork_at=fork.isoformat())
            if overview:
                chart['total_fills'] = len(chart['fills'])
                chart['fills'] = [f for f in chart['fills'] if charts.timestamp(f['time']) >= cutoff]
                chart['observed_points'] = len(chart['points'])
                chart['points'] = charts.compact_points(chart['points'])
            result.append(chart)
    if not overview:
        return result[0]
    return dict(available=True, variant=variant, account_id=account['account_id'],
                account_label=account['label'], fork_at=fork.isoformat(), as_of=as_of.isoformat(),
                from_time=cutoff.isoformat(), period=period, stale=stale,
                symbols=sorted(positions), charts=result)
