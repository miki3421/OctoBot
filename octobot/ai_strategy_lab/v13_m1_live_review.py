"""Read-only, reconciled M1 accounting publication; never a strategy input."""
from collections import defaultdict
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import time

SCOPE = 'M1_LIVE_SYMBOL_ATTRIBUTION_NO_ORDERS'
ACCOUNT = 'v13-m1-short-paper-v1-5e761f0cedac'
PROJECTION = Path('/v13-paper/m1-review-ui/current.json')
UTC = dt.timezone.utc


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                    ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def validate_account(account, r):
    """Reconcile the entire copied ledger before deriving any window."""
    fills = defaultdict(list)
    funding = defaultdict(list)
    for row in account['fills']:
        fills[row['symbol']].append(row)
    for row in account['funding']:
        funding[row['symbol']].append(row)
    if not (set(fills) | set(funding)) <= set(account['state']['positions']):
        raise ValueError('untracked_symbol_activity')
    for symbol, position in account['state']['positions'].items():
        result = r.replay(fills[symbol], float('inf'))
        for key, field in (('q', 'quantity'), ('entry', 'entry_price'), ('realized', 'realized_pnl'), ('fees', 'fees')):
            if not r.close(result[key], position[field]):
                raise ValueError('state_reconciliation:' + symbol)
        if not r.close(sum(r.number(x['amount']) for x in funding[symbol]), position['funding']):
            raise ValueError('funding_reconciliation:' + symbol)
    equity = account['state']['initial_equity'] + sum(r.pnl(p) for p in account['state']['positions'].values())
    if not account['equity_observation'] or not r.close(equity, account['equity_observation']['equity']):
        raise ValueError('equity_reconciliation')
    return fills, funding


def window(account, grouped, symbols, start, end, r, start_positions=None):
    fills, funding = grouped
    rows = {}
    baseline = terminal = 0.
    complete = True
    for symbol in symbols:
        marks = account['marks'].get(symbol, [])
        if symbol not in account['state']['positions']:
            # A new M1 admission outside the Original universe has no Original
            # position or trades. Absence is explicit, not a missing mark.
            if fills[symbol] or funding[symbol]:
                raise ValueError('untracked_symbol_activity')
        kwargs = {}
        anchor = (start_positions or {}).get(symbol)
        if anchor is not None:
            kwargs['start_mark'] = (r.timestamp(anchor['last_mark_at']), anchor['current_price'])
        try:
            value = r.attribution(fills[symbol], funding[symbol], marks, start, end, **kwargs)
            endpoints = []
            for t in (start, end):
                position = r.replay(fills[symbol], t)
                if t == start and anchor is not None:
                    mark = anchor['current_price']
                else:
                    mark = r.price_before(marks, t)[1] if position['q'] else 0.
                endpoints.append(position['realized'] - position['fees']
                                 + position['q'] * (mark - position['entry'])
                                 + sum(r.number(x['amount']) for x in funding[symbol]
                                       if x['timestamp_ms'] / 1000 <= t))
            if not r.close(value['net'], endpoints[1] - endpoints[0]):
                raise ValueError('window_reconciliation:' + symbol)
            value.update(available=True, reason=None)
            baseline += endpoints[0]
            terminal += endpoints[1]
        except ValueError as error:
            if str(error) != 'boundary_mark_missing':
                raise
            complete = False
            value = dict(available=False, reason='BOUNDARY_MARK_UNAVAILABLE',
                         start=r.iso(start), end=r.iso(end), days=(end-start)/86400,
                         net=None, sides=None)
        rows[symbol] = value
    totals = dict(available=complete, start=r.iso(start), end=r.iso(end),
                  days=(end-start)/86400, net=None, long_net=None, short_net=None,
                  fees=None, funding=None, reconciliation_error=None,
                  unavailable_symbols=[s for s, v in rows.items() if not v['available']])
    if complete:
        net = sum(v['net'] for v in rows.values())
        totals.update(net=net, long_net=sum(v['sides']['LONG']['net'] for v in rows.values()),
                      short_net=sum(v['sides']['SHORT']['net'] for v in rows.values()),
                      fees=sum(v['sides'][side]['fees'] for v in rows.values() for side in r.SIDES),
                      funding=sum(v['sides'][side]['funding'] for v in rows.values() for side in r.SIDES),
                      baseline_equity=account['state']['initial_equity']+baseline,
                      end_equity=account['state']['initial_equity']+terminal,
                      reconciliation_error=net-(terminal-baseline))
        if not r.close(net, terminal-baseline):
            raise ValueError('aggregate_reconciliation')
    return rows, totals


def calculate(m1, original, receipt, successor, now, r):
    if receipt['account_id'] != ACCOUNT or m1['state'].get('fork_account') != ACCOUNT:
        raise ValueError('account_identity')
    start = r.timestamp(receipt['economic_t0'])
    epoch = r.timestamp(successor['activated_at'])
    cutoffs = [r.timestamp(m1['state']['m1_last_market_at']), r.timestamp(original['state']['last_market_at'])]
    end = min(cutoffs)
    if not start < epoch < end <= now.timestamp():
        raise ValueError('time_boundary')
    symbols = sorted(set(m1['state']['positions']) | set(original['state']['positions']))
    periods = dict(since_version=(epoch, end), since_clone=(start, end),
                   legacy=(start, epoch), **{'24h': (max(start, end-86400), end),
                                            '48h': (max(start, end-172800), end)})
    report = dict(schema=2, scope=SCOPE, account_id=ACCOUNT, generated_at=now.isoformat(),
                  start=r.iso(start), end=r.iso(end), epoch_start=r.iso(epoch),
                  default_window='since_version', execution_authorized=False,
                  history_inherited_not_scored=True, risk_limits_unchanged=True,
                  scientific_validity='DESCRIPTIVE_NOT_STRATEGY_VALIDATION',
                  funding_basis='Recorded simulator estimates by settlement time; historical observation lag is not reconstructed.',
                  provenance=dict(seed_sha256=receipt['seed_sha256'], activation_id=successor['activation_id'],
                                  source_cutoffs=dict(m1=r.iso(cutoffs[0]), original=r.iso(cutoffs[1])),
                                  filled_order_counts=dict(m1=len(m1['fills']), original=len(original['fills']))),
                  common_cutoff=True, cutoff_skew_seconds=abs(cutoffs[0]-cutoffs[1]),
                  refresh_seconds=300, maximum_boundary_mark_age_seconds=r.MAX_AGE,
                  periods={k: dict(start=r.iso(a), end=r.iso(b), days=(b-a)/86400,
                                   complete_requested_window=k not in ('24h','48h') or end-start >= (86400 if k=='24h' else 172800),
                                   crosses_version_boundary=a<epoch<b) for k,(a,b) in periods.items()},
                  proposals=[])
    for name, account in (('m1', m1), ('original', original)):
        grouped = validate_account(account, r)
        result = dict(symbols={s: dict(windows={}) for s in symbols}, totals={})
        for label, (a, b) in periods.items():
            anchors = receipt['inherited_positions'] if a == start else None
            rows, totals = window(account, grouped, symbols, a, b, r, anchors)
            result['totals'][label] = totals
            for symbol in symbols:
                result['symbols'][symbol]['windows'][label] = rows[symbol]
        for symbol in symbols:
            position = r.replay(grouped[0][symbol], end)
            result['symbols'][symbol].update(current_quantity=position['q'], current_entry=position['entry'],
                                             in_universe=symbol in account['state']['positions'])
        report[name] = result
    for label, expected in (('since_clone', receipt['inherited_metrics']['equity']),
                            ('since_version', successor['boundary_metrics']['equity'])):
        total = report['m1']['totals'][label]
        if total['available'] and not r.close(total['baseline_equity'], expected):
            raise ValueError('economic_anchor_reconciliation:' + label)
    report['snapshot_id'] = digest(report)
    return report


def public_view(path=PROJECTION, now=None, expected_uid=0):
    try:
        fixed_now = now
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != expected_uid or info.st_mode & 0o022 or info.st_size > 4000000:
                raise ValueError('projection_custody')
            value = json.loads(os.read(fd, 4000001))
        finally:
            os.close(fd)
        if (value['scope'] != SCOPE or value['schema'] != 2 or value['account_id'] != ACCOUNT
                or value['execution_authorized'] is not False
                or value['snapshot_id'] != digest({k:v for k,v in value.items() if k != 'snapshot_id'})):
            raise ValueError('projection_identity')
        generated = dt.datetime.fromisoformat(value['generated_at'])
        end = dt.datetime.fromisoformat(value['end'])
        now = now or dt.datetime.now(UTC)
        if generated.tzinfo is None or end.tzinfo is None or not end <= generated <= now:
            raise ValueError('projection_time')
        for name in ('m1', 'original'):
            for label, total in value[name]['totals'].items():
                if total['available']:
                    rows = [s['windows'][label] for s in value[name]['symbols'].values()]
                    if (not all(v['available'] for v in rows)
                            or abs(sum(v['net'] for v in rows)-total['net']) > 1e-6
                            or abs(total['long_net']+total['short_net']-total['net']) > 1e-6
                            or abs(total['reconciliation_error']) > 1e-6):
                        raise ValueError('projection_reconciliation')
                    for row in rows:
                        sides = row['sides']
                        if abs(sum(s['net'] for s in sides.values())-row['net']) > 1e-6:
                            raise ValueError('side_reconciliation')
                        for side in sides.values():
                            expected = side['realized']+side['open_pnl_end']-side['open_pnl_start']-side['fees']+side['funding']
                            if abs(expected-side['net']) > 1e-6:
                                raise ValueError('side_accounting')
        stale = (now-generated).total_seconds()>900 or (now-end).total_seconds()>900
        refresh_failed = False
        status_path = Path(path).with_name('status.json')
        if status_path.exists():
            info = status_path.lstat()
            if status_path.is_symlink() or info.st_uid != expected_uid or info.st_mode & 0o022 or info.st_size>4096:
                raise ValueError('status_custody')
            status_value = json.loads(status_path.read_text())
            checked = dt.datetime.fromisoformat(status_value['checked_at'])
            if (status_value['scope'] != SCOPE or status_value.get('status') not in ('READY','ERROR')
                    or checked.tzinfo is None or checked>(fixed_now or dt.datetime.now(UTC))):
                raise ValueError('status_contract')
            refresh_failed = status_value.get('status') == 'ERROR' and checked>=generated
        return dict(available=True, version='m1-live-symbol-review-v2', snapshot=False,
                    stale=stale or refresh_failed, refresh_failed=refresh_failed,
                    report_id=value['snapshot_id'], maintenance_active=True, review=value)
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        return dict(available=False, version='m1-live-symbol-review-v2', maintenance_active=True,
                    message='Metriche M1 aggiornate non disponibili o non verificabili.')


def snapshot(source, target, seconds=4):
    """Only incremental read locks; no full scan or integrity check on live DB."""
    started = time.monotonic()
    connection = sqlite3.connect(Path(source).resolve().as_uri()+'?mode=ro', uri=True, timeout=.1)
    destination = sqlite3.connect(target)
    try:
        def progress(*args):
            if time.monotonic()-started > seconds:
                raise TimeoutError('snapshot_budget')
        connection.backup(destination, pages=128, sleep=.01, progress=progress)
    finally:
        destination.close()
        connection.close()
    Path(target).chmod(0o400)
    return time.monotonic()-started


def publish(config):
    from . import v13_m1_symbol_review as r
    started = time.monotonic()
    scratch = Path(config['scratch'])
    with tempfile.TemporaryDirectory(prefix='snapshot-', dir=scratch) as folder:
        paths = {name: Path(folder)/(name+'.sqlite') for name in ('m1','original')}
        durations = {name: snapshot(config[name], paths[name]) for name in paths}
        accounts = {name: r.load_snapshot(path) for name,path in paths.items()}
        with sqlite3.connect(paths['m1'].as_uri()+'?mode=ro', uri=True) as db:
            successor = json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='strategy_successor'").fetchone()[0])
            daily = [dict(slot=row[0], status=row[1]) for row in db.execute("SELECT slot,status FROM m1_slots WHERE kind='DAILY' ORDER BY slot DESC")]
        receipt = json.loads(Path(config['receipt']).read_text())
        value = calculate(accounts['m1'], accounts['original'], receipt, successor, dt.datetime.now(UTC), r)
        value.pop('snapshot_id')
        value['daily_non_executed'] = [row for row in daily if row['status'] not in ('FILLED','NO_FILL')]
        value['publication'] = dict(snapshot_seconds=durations, duration_seconds=time.monotonic()-started,
                                   source_mode='BOUNDED_COHERENT_OFFLINE_COPIES', ledger_writes=False)
        value['snapshot_id'] = digest(value)
    atomic(Path(config['output']), value)
    return value


def atomic(target, value):
    """Replace only a generated cache file; never an operational ledger."""
    if target.is_symlink():
        raise ValueError('output_symlink')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', prefix='.publish-', dir=target.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, allow_nan=False)
            stream.write('\n')
            stream.flush()
            os.fsync(stream.fileno())
        temporary.chmod(0o444)
        temporary.replace(target)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
