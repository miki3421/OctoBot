"""Account-bound structural M1 successor of the existing Original paper ledger.

This entry point requires a separate, root-pinned deployment authority. The old
research producer/issuer and the shared mark stream retain their identities.
Only this process owns the existing executor lock and account database.
"""
import argparse
import copy
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path

from . import v13_research_paper as P
from . import v13_m1_short_risk as R
from . import v13_m1_short_structure as S
from . import v13_m1_future as causal

VERSION = 'original-m1-structural-successor-v2'
PROTOCOL_ID = 'f7216e9549725ba94c5d01bdc0c972f509981e2df15ebd5be3db07b90185f8d1'
ACCOUNT = 'v13-paper-v2'
ORIGINAL_TICK = P.tick
ORIGINAL_ISSUER = P.issuer
AUTHORITY = None


def digest(value):
    return R.digest(value)


def validate(protocol):
    if (protocol.get('protocol_id') != PROTOCOL_ID or
            digest({k: v for k, v in protocol.items() if k != 'protocol_id'}) != PROTOCOL_ID):
        raise ValueError('successor_protocol_identity')
    return protocol


def root_json(path, expected):
    path = Path(path)
    if path.is_symlink() or path.stat().st_uid != 0 or path.stat().st_mode & 0o022:
        raise ValueError('successor_root_custody')
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError('successor_authority_changed')
    return json.loads(raw)


def authority(path, expected, repo):
    value = root_json(path, expected)
    if (value['scope'] != 'MANUAL_ORIGINAL_STRUCTURAL_PAPER_CUTOVER' or
            value['account'] != ACCOUNT or value['protocol_id'] != PROTOCOL_ID or
            value['real_orders_authorized'] is not False or not value['operator_reference']):
        raise ValueError('successor_authority_scope')
    for name, sha in value['code_pins'].items():
        if hashlib.sha256((Path(repo)/name).read_bytes()).hexdigest() != sha:
            raise ValueError('successor_code_changed:'+name)
    return value


def load(db):
    row = db.execute("SELECT payload FROM structural_meta WHERE key='control'").fetchone()
    return json.loads(row[0]) if row else None


def save(db, control):
    db.execute("INSERT OR REPLACE INTO structural_meta VALUES('control',?)", (json.dumps(control),))


def initialize(db, auth, protocol, state):
    """Append a version boundary without rewriting a historical economic row."""
    validate(protocol)
    db.execute('CREATE TABLE IF NOT EXISTS structural_meta(key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS structural_signals(slot INTEGER PRIMARY KEY,payload TEXT NOT NULL)')
    existing = load(db)
    if existing:
        if existing['authority_id'] != auth['authority_id']:
            raise ValueError('successor_reactivation_conflict')
        return existing
    if (state.get('pending') or any(p['quantity'] < 0 for p in state['positions'].values()) or
            digest(state) != auth['boundary_state_hash'] or state['order_count'] != auth['boundary_orders']):
        raise ValueError('successor_stopped_boundary_changed')
    metrics = P.paper.totals(state, require_positive=False)
    control = dict(authority_id=auth['authority_id'], protocol_id=PROTOCOL_ID,
        boundary=dict(at=auth['activated_at'], metrics=metrics, order_count=state['order_count'],
            label=protocol['label'], predecessor='V13 originale', account=ACCOUNT),
        phase='NORMAL', pending=None, episode=None, episode_day=None, cooldown_until=None,
        first_signal_slot=math.ceil(P.p.timestamp(auth['activated_at']).timestamp()/300)*300,
        last_signal_slot=None, status='AWAITING_FIRST_FRESH_BOOK',
        initial_longs={s: p['quantity'] for s, p in state['positions'].items() if p['quantity'] > 0},
        stages={}, planned_stage=None, exit_due=None)
    with db:
        save(db, control)
        db.execute("INSERT INTO structural_meta VALUES('activation',?)", (json.dumps(auth),))
    return control


def entry_gate(state, now, protocol):
    risk = state['risk_policy_state']
    equity = P.paper.totals(state, require_positive=False)['equity']
    day = now.date().isoformat()
    if risk['daily_day'] != day:
        risk.update(daily_day=day, daily_start=equity, daily_entries=0)
    risk['high_water'] = max(risk['high_water'], equity)
    if equity <= 0 or risk['daily_start'] is None:
        return 'RISK_EQUITY_UNKNOWN'
    if equity <= risk['daily_start']*.98:
        return 'DAILY_LOSS_2_PERCENT'
    if equity <= risk['high_water']*.90:
        return 'DRAWDOWN_10_PERCENT'
    if risk['daily_entries'] >= protocol['risk']['order_frequency']:
        return 'DAILY_RISK_INCREASE_LIMIT'
    if (risk.get('last_increase_at') and
            (now-P.p.timestamp(risk['last_increase_at'])).total_seconds() < protocol['risk']['cooldown']):
        return 'RISK_INCREASE_COOLDOWN'
    current = P.exposure.snapshot({s:p['quantity'] for s,p in state['positions'].items()},
        {s:p['current_price'] for s,p in state['positions'].items()}, equity, .90, .315)
    if current['breaches']:
        return 'CURRENT_EXPOSURE_LIMIT'
    return None


def intent(control, kind, due, *, targets=None, plan=None, reason=None, deadline=None, approval_id=None):
    value = dict(kind=kind, due=due, deadline=deadline, targets=targets, plan=plan, reason=reason, approval_id=approval_id)
    value['id'] = digest(dict(account=ACCOUNT, authority=control['authority_id'],
                             episode_day=control['episode_day'], **value))
    control['pending'] = value


def read_signal_approval(c, authority_id, slot, now, input_hash):
    path = Path(c['approvals'])/'approvals.sqlite'
    info = path.stat()
    if path.is_symlink() or info.st_uid != c['uids']['issuer'] or info.st_mode & 0o022:
        raise ValueError('structural_approval_custody')
    connection = P.db(path, True)
    try:
        row = connection.execute('SELECT payload FROM structural_issuer_slots WHERE protocol=? AND slot=?',
                                 (PROTOCOL_ID, slot)).fetchone()
    finally:
        connection.close()
    if row is None:
        raise ValueError('structural_approval_not_issued')
    value = json.loads(row[0])
    if (value['approval_id'] != digest({k:v for k,v in value.items() if k!='approval_id'}) or
            value['scope'] != 'ORIGINAL_STRUCTURAL_M1_SIGNAL_APPROVAL' or value['status'] != 'APPROVE' or
            value['account'] != ACCOUNT or value['protocol_id'] != PROTOCOL_ID or
            value['authority_id'] != authority_id or value['slot'] != slot or value['input_hash'] != input_hash or
            value['issuer_uid'] != c['uids']['issuer'] or value['real_orders_authorized'] is not False):
        raise ValueError('structural_approval_identity')
    issued = P.p.timestamp(value['issued_at']).timestamp()
    if not slot <= issued <= slot+120 or not issued <= now.timestamp() <= slot+420 or value['expires_at'] != slot+420:
        raise ValueError('structural_approval_expiry')
    return value


def structural_issuer(c):
    if os.geteuid() != c['uids']['issuer']:
        raise ValueError('structural_issuer_identity')
    a = authority(AUTHORITY['path'], AUTHORITY['sha256'], c['repo'])
    validate(a['protocol'])
    # Daily original derivations remain available for inherited LONG reductions.
    try:
        ORIGINAL_ISSUER(c)
    except (ValueError, OSError, KeyError):
        pass
    now = P.source.now();slot = int(now.timestamp())//300*300
    if slot < math.ceil(P.p.timestamp(a['activated_at']).timestamp()/300)*300:
        return
    db = P.db(Path(c['approvals'])/'approvals.sqlite')
    try:
        db.execute('CREATE TABLE IF NOT EXISTS structural_issuer_slots(protocol TEXT,slot INTEGER,payload TEXT NOT NULL,PRIMARY KEY(protocol,slot))')
        if db.execute('SELECT 1 FROM structural_issuer_slots WHERE protocol=? AND slot=?',(PROTOCOL_ID,slot)).fetchone():
            return
        model = None
        try:
            if now.timestamp()-slot <= 120:
                rows = causal.read_window(str(Path(c['ledger'])/'execution.sqlite'),slot,list(R.SIGNALS))
                model = R.model(rows,slot)
        except (ValueError, KeyError, TypeError, OSError):
            if now.timestamp()-slot <= 120:
                return
        status = ('APPROVE' if model['feature']['btc_60m']<=-.01 and model['feature']['negative_breadth']>=12/18
                  else 'NO_PROPOSAL') if model is not None else 'MISSING'
        value = dict(scope='ORIGINAL_STRUCTURAL_M1_SIGNAL_APPROVAL',status=status,account=ACCOUNT,
            protocol_id=PROTOCOL_ID,authority_id=a['authority_id'],slot=slot,
            input_hash=model['input_hash'] if model else None,issued_at=now.isoformat(),expires_at=slot+420,
            issuer_uid=os.geteuid(),real_orders_authorized=False)
        value['approval_id'] = digest(value)
        with db:
            db.execute('INSERT INTO structural_issuer_slots VALUES(?,?,?)',(PROTOCOL_ID,slot,json.dumps(value)))
    finally:
        db.close()


def new_signal(c, db, state, control, protocol, now, rows):
    slot = int(now.timestamp())//300*300
    if slot < control['first_signal_slot'] or control['last_signal_slot'] == slot:
        return
    previous_slot = control['last_signal_slot'];control['last_signal_slot'] = slot
    if now.timestamp()-slot > 120 or rows is None:
        control['status'] = 'MISSING_SIGNAL_WINDOW_OR_LATE_SLOT'
        return
    try:
        model = R.model(rows, slot)
    except (ValueError, KeyError, TypeError):
        control['status'] = 'MISSING_OR_INVALID_CAUSAL_WINDOW'
        return
    f = model['feature']
    signal = f['btc_60m'] <= -.01 and f['negative_breadth'] >= 12/18
    day = now.date().isoformat()
    if not signal:
        control['status'] = 'NO_M1_SIGNAL'
        return
    if control['phase'] != 'NORMAL' or control['pending']:
        return
    if (control['episode_day'] == day or
            control['cooldown_until'] is not None and now.timestamp() < control['cooldown_until']):
        control['status'] = 'M1_COOLDOWN_OR_DAILY_LIMIT'
        return
    try:
        approval = read_signal_approval(c, control['authority_id'], slot, now, model['input_hash'])
    except (ValueError, KeyError, OSError, P.sqlite3.Error):
        control['last_signal_slot'] = previous_slot
        control['status'] = 'WAITING_INDEPENDENT_M1_APPROVAL'
        return
    control['episode_day'] = day
    db.execute('INSERT OR IGNORE INTO structural_signals VALUES(?,?)',
               (slot, json.dumps(dict(rows=rows, model_hash=model['input_hash']))))
    control['signal_slot'] = slot
    control['phase'] = 'ENTRY_PENDING'
    intent(control, 'ENTRY', slot+300, deadline=slot+420, approval_id=approval['approval_id'])
    control['status'] = 'M1_ENTRY_WAITING_NEXT_BOOK'


def long_reduction(state, control, record, now, daily):
    targets = {}; updates = {}
    for symbol, initial in control['initial_longs'].items():
        q = state['positions'][symbol]['quantity']
        stage = control['stages'].get(symbol)
        if q <= 0:
            continue
        index = 0 if stage is None else stage['index']+1
        if index >= 3:
            continue
        if stage is not None:
            if (now.timestamp()-stage['at'] < 86400 or daily is None or
                    daily['day'] <= stage['day'] or P.p.decode_weight(daily['targets'][symbol]) > 0):
                continue
        fraction = (.5, .25, 0.)[index]
        ceiling = R.floor_quantity(initial*fraction, record['quotes'][symbol]['quantity_step'])
        if ceiling < q:
            targets[symbol] = ceiling
            updates[symbol] = dict(index=index, at=now.timestamp(),
                day=daily['day'] if daily else (now.date()-dt.timedelta(days=1)).isoformat())
    if targets:
        control['planned_stage'] = updates
        intent(control, 'LONG_REDUCE', now.timestamp(), targets=targets)


def fill_plan(state, record, targets, *, protective_only, partial):
    """No invented liquidity; full atomic admission and partial protective exits."""
    legs = []
    for symbol, target in sorted(targets.items()):
        old = state['positions'][symbol]['quantity']; delta = target-old
        if abs(delta) < 1e-10:
            continue
        protective = old*target >= 0 and abs(target) < abs(old)
        if protective_only and not protective:
            raise ValueError('successor_reduction_only')
        q = record['quotes'][symbol]; side = 'asks' if delta > 0 else 'bids'
        capacity = math.fsum(v['base_quantity'] for v in q[side])
        if capacity < abs(delta):
            if not partial:
                raise ValueError('entry_depth_unavailable')
            amount = R.floor_quantity(capacity, q['quantity_step'])
            delta = math.copysign(min(abs(delta), amount), delta)
        if not delta:
            continue
        checked = dict(q)
        if q.get('metadata_scope') == 'REAL_PRECISION_WITH_SEPARATE_SIMULATED_MINIMUMS':
            checked.update(min_quantity=q['simulation_min_quantity'], min_notional=q['simulation_min_notional'])
        P.sanity.preflight(symbol, checked, delta, protective)
        price = P.exposure.execution_price(q, delta, P.market.fill_price)
        if not protective and abs(delta*price) < 1:
            raise ValueError('entry_below_simulated_notional')
        fee = abs(delta*price)*q['fee_rate']
        legs.append(dict(symbol=symbol, quantity=delta, price=price, fee=fee,
                         before=old, after=old+delta, protective=protective))
    return legs


def apply_fills(state, legs, account, epoch):
    result = copy.deepcopy(state)
    for leg in legs:
        p = result['positions'][leg['symbol']]
        P.paper.apply_fill(p, leg['quantity'], leg['price'], leg['fee'])
        if leg['before'] == 0 or leg['before']*p['quantity'] < 0:
            p['generation'] += 1
            p['position_id'] = digest(dict(account=account, epoch=epoch,
                symbol=leg['symbol'], generation=p['generation']))
    result['order_count'] += len(legs)
    equity = P.paper.totals(result, require_positive=False)['equity']
    if any(not v['protective'] for v in legs):
        exposure = P.exposure.snapshot({s:p['quantity'] for s,p in result['positions'].items()},
            {s:p['current_price'] for s,p in result['positions'].items()}, equity, .90, .315)
        if exposure['breaches']:
            raise ValueError('successor_projected_exposure')
    return result


def process(c, db, state, control, record, now, protocol, parent, structure, *, rows, daily, funding_ok):
    """Plan and execution are separate persisted cycles with a fresh-book gate."""
    gate = entry_gate(state, now, protocol)
    pending = copy.deepcopy(control['pending'])
    legs = []; claim = None; increasing = False
    fresh = 0 <= (now-P.p.timestamp(record['observed_at_end'])).total_seconds() <= 120
    if pending and now.timestamp() >= pending['due']:
        expired = pending['kind'] == 'ENTRY' and now.timestamp() > pending['deadline']
        if expired:
            control.update(phase='NORMAL', pending=None, status='ENTRY_EXPIRED_NO_RETROACTIVE_FILL')
        elif fresh and P.p.timestamp(record['observed_at_start']).timestamp() > pending['due']+20:
            kind = pending['kind']; plan = None
            targets = pending['targets']
            if kind == 'ENTRY':
                try:
                    if gate or not funding_ok:
                        raise ValueError(gate or 'FUNDING_UNKNOWN')
                    raw = json.loads(db.execute('SELECT payload FROM structural_signals WHERE slot=?',
                                                (control['signal_slot'],)).fetchone()[0])
                    model = R.model(raw['rows'], control['signal_slot'])
                    if model['input_hash'] != raw['model_hash']:
                        raise ValueError('persisted_signal_changed')
                    approval = read_signal_approval(c,control['authority_id'],control['signal_slot'],now,model['input_hash'])
                    if approval['approval_id'] != pending['approval_id']:
                        raise ValueError('pending_issuer_approval_changed')
                    plan = R.size(parent, model, P.paper.totals(state, require_positive=False)['equity'],
                                  protocol['sizing']['short_caps'], record['quotes'])
                    targets = {s:plan['quantities'].get(s, 0.) for s in state['positions']}
                    legs = fill_plan(state, record, targets, protective_only=False, partial=False)
                    increasing = any(not v['protective'] for v in legs)
                except (ValueError, KeyError, TypeError, OSError, P.sqlite3.Error) as error:
                    control['status'] = 'ENTRY_VETO:'+str(error)
                    targets = {s:0. for s,p in state['positions'].items() if p['quantity'] > 0}
                    legs = fill_plan(state, record, targets, protective_only=True, partial=True)
                    kind = 'VETO_CLOSE_LONG'; plan = None
            else:
                legs = fill_plan(state, record, targets, protective_only=True, partial=True)
            result = apply_fills(state, legs, ACCOUNT, c['epoch'])
            claim = pending['id']
            if kind == 'ENTRY' and plan and increasing:
                control.update(phase='ACTIVE', pending=None, status='SHORT_ACTIVE',
                    exit_due=control['signal_slot']+300+21600,
                    episode=R.episode(plan, state['positions'], result['positions'], legs,
                        now.timestamp(), claim))
                control['episode']['issuer_approval_id'] = pending['approval_id']
                result['risk_policy_state'].update(daily_entries=result['risk_policy_state']['daily_entries']+1,
                                                   last_increase_at=now.isoformat())
            else:
                remaining = {s:q for s,q in targets.items()
                             if not math.isclose(result['positions'][s]['quantity'], q, abs_tol=1e-10)}
                if remaining:
                    intent(control, kind, now.timestamp(), targets=remaining, reason=pending['reason'])
                else:
                    control['pending'] = None
                    if kind == 'EXIT':
                        control.update(phase='NORMAL', cooldown_until=now.timestamp()+21600,
                                       status='SHORT_CLOSED', last_exit_reason=pending['reason'])
                    elif kind == 'LONG_REDUCE':
                        control['stages'].update(control['planned_stage'] or {})
                        control['planned_stage'] = None
                    else:
                        control['phase'] = 'NORMAL'
            return result, control, legs, claim, increasing
    if control['phase'] == 'ACTIVE' and not control['pending']:
        reason = None; saved = control['episode']
        changed = any(not math.isclose(state['positions'][s]['quantity'], v['quantity'], abs_tol=1e-10)
                      for s,v in saved['legs'].items())
        if changed:
            reason = 'ADMINISTRATIVE_POSITION_CHANGE'
        elif funding_ok and fresh:
            slot = int(now.timestamp())//300*300
            feature = None
            if rows is not None:
                try:
                    feature = S.features(structure, rows, slot)
                except (ValueError, KeyError, TypeError):
                    pass
            feature_slot = slot if slot >= saved['at'] else None
            try:
                saved, reason = S.watch(parent, structure, saved, state['positions'], record['quotes'],
                    at=now.timestamp(), market_id=record['record_hash'],
                    feature_slot=feature_slot, feature=feature if feature_slot is not None else None)
                control['episode'] = saved
            except (ValueError, KeyError, TypeError):
                control['status'] = 'WAITING_EXECUTABLE_SHORT_VALUATION'
        if reason is None and now.timestamp() >= control['exit_due']:
            reason = 'MAX_HOLD'
        if reason:
            control['phase'] = 'EXIT_PENDING'
            intent(control, 'EXIT', now.timestamp(),
                   targets={s:0. for s,p in state['positions'].items() if p['quantity'] < 0}, reason=reason)
            control['status'] = 'EXIT_INTENT:'+reason
    new_signal(c, db, state, control, protocol, now, rows)
    if control['phase'] == 'NORMAL' and not control['pending']:
        long_reduction(state, control, record, now, daily)
    return state, control, legs, claim, increasing


def publish(c, control, state, now, protocol):
    value = dict(scope='ORIGINAL_STRUCTURAL_SUCCESSOR_PROJECTION', schema=1, account=ACCOUNT,
        generated_at=now.isoformat(), version=VERSION, protocol_id=PROTOCOL_ID,
        boundary=control['boundary'], label='M1 strutturale · ex Originale',
        phase=control['phase'], status=control['status'], pending=control['pending'] is not None,
        last_exit_reason=control.get('last_exit_reason'), metrics=P.paper.totals(state, require_positive=False),
        stages=control['stages'], short_budget=sum(protocol['sizing']['short_caps'].values()),
        real_orders_authorized=False, scientific_validity='UNASSESSED')
    P.source.atomic(Path(c['ledger'])/'structural-successor.json', value)


def health(c, state, now, control):
    error = (control['status'] if control['status'].startswith('AUTHORIZATION_DENIED:')
             else state.get('entry_gate') if state.get('entry_gate') == 'FUNDING_UNKNOWN' else None)
    value = P.health(c, state, now, error=error)
    value.update(strategy_version=VERSION, strategy_protocol_id=PROTOCOL_ID,
                 strategy_boundary=control['boundary']['at'], real_orders_authorized=False)
    P.source.atomic(Path(c['ledger'])/'health-research.json', value)
    return value


def persist(db, result, control, record, now, fund, legs, claim, increasing, funding_ok):
    with db:
        if increasing:
            db.execute('UPDATE research_claims SET kind=? WHERE id=?', ('structural-committed', claim))
        for leg in legs:
            pos = result['positions'][leg['symbol']]
            columns = dict(bar=now.isoformat(), symbol=leg['symbol'], action='BUY' if leg['quantity']>0 else 'SELL',
                weight=pos['quantity']*pos['current_price']/P.paper.totals(result)['equity'],
                notional=abs(leg['quantity']*leg['price']), fee=leg['fee'], status='filled',
                quantity=leg['quantity'], price=leg['price'], recorded_at=now.isoformat(),
                decision_hash=claim, market_hash=record['record_hash'], realized_pnl=pos['realized_pnl'])
            db.execute('INSERT INTO orders('+','.join(columns)+') VALUES('+','.join('?' for _ in columns)+')', tuple(columns.values()))
        result.update(last_market_at=record['observed_at_end'], last_market_hash=record['record_hash'],
            last_success_at=now.isoformat(), entry_gate=None if funding_ok else 'FUNDING_UNKNOWN',
            execution_reason=control['status'], source_ready=True, risk={}, simulation_notes=[],
            structural_successor=dict(version=VERSION, boundary=control['boundary'], protocol_id=PROTOCOL_ID))
        db.executemany('INSERT INTO funding_events VALUES(?,?,?,?,?,?)', fund)
        db.executemany('INSERT OR IGNORE INTO marks VALUES(?,?,?)', [(now.isoformat(),s,q['mark_price']) for s,q in record['quotes'].items()])
        metrics = P.paper.totals(result, require_positive=False)
        db.execute('INSERT INTO equity_history VALUES(?,?,?)', (now.isoformat(), metrics['equity'], metrics['pnl']))
        db.execute('UPDATE state SET payload=? WHERE id=1', (json.dumps(result),))
        save(db, control)
        event = dict(scope=P.source.SCOPE, version=VERSION, at=now.isoformat(), claim=claim,
                     market_hash=record['record_hash'], status=control['status'], fills=legs,
                     funding_known=funding_ok, notes=[], entry_gate=result.get('entry_gate'),
                     reason=control['status'], funding_method='ESTIMATED_PREVIOUS_OBSERVED_MARK')
        if increasing or legs or control['phase']=='EXIT_PENDING':
            event.update(episode=control.get('episode'), last_exit_reason=control.get('last_exit_reason'),
                         pending=control.get('pending'))
        db.execute('INSERT INTO research_events VALUES(?,?)', (digest(event), json.dumps(event)))


def funding_coverage(db, state, record):
    """Same strict prior-mark coverage used by the M1 parent, including late rates."""
    end = P.p.timestamp(record['observed_at_end']).timestamp()*1000
    for symbol, position in state['positions'].items():
        cursor = P.p.timestamp(position.get('funding_cursor') or position['last_mark_at']).timestamp()*1000
        for event in record['quotes'][symbol]['funding']:
            when = event['timestamp_ms']
            if when > end:
                raise ValueError('future_funding_observation')
            if not cursor < when <= end:
                continue
            instant = dt.datetime.fromtimestamp(when/1000, dt.timezone.utc).isoformat()
            quantity = math.fsum(v[0] for v in db.execute(
                "SELECT quantity FROM orders WHERE symbol=? AND status='filled' AND bar<?", (symbol, instant)))
            if quantity:
                mark = db.execute('SELECT bar FROM marks WHERE symbol=? AND bar<? ORDER BY bar DESC LIMIT 1',
                                  (symbol, instant)).fetchone()
                if mark is None or when/1000-P.p.timestamp(mark[0]).timestamp() > 1800:
                    raise ValueError('funding_previous_mark_coverage')


def tick(c, db, admin=None):
    global AUTHORITY
    spec = AUTHORITY
    a = authority(spec['path'], spec['sha256'], c['repo'])
    protocol = validate(a['protocol']); parent = a['parent']; structure = a['structure']
    R.validate(parent); S.validate(structure)
    if c['account'] != ACCOUNT:
        raise ValueError('successor_account_changed')
    if admin is not None:
        return ORIGINAL_TICK(c, db, admin)
    now = P.source.now()
    state = json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    control = initialize(db, a, protocol, state)
    last = db.execute('SELECT MAX(bar) FROM equity_history').fetchone()[0]
    if last and now <= P.p.timestamp(last):
        raise ValueError('successor_clock_regression')
    record = P.source.owned_json(Path(c['source'])/'market.json', c['uids']['capture'])
    if record['record_hash'] != digest({k:v for k,v in record.items() if k!='record_hash'}) or record['scope'] != P.source.SCOPE:
        raise ValueError('successor_market_identity')
    if set(record['quotes']) != set(state['positions']) or set(R.SIGNALS) != set(record['quotes']):
        raise ValueError('successor_signal_universe_changed')
    for s,q in record['quotes'].items():
        P.sanity.structure_and_time(s, q, record, now)
    if record['record_hash'] == state.get('last_market_hash'):
        publish(c, control, state, now, protocol)
        return health(c, state, now, control)
    original = copy.deepcopy(state)
    funding_ok = True
    try:
        funding_coverage(db, state, record)
        fund = P.funding(db, state, record)
    except (ValueError, KeyError, TypeError):
        state = original; fund = []; funding_ok = False
    for s,q in record['quotes'].items():
        state['positions'][s].update(current_price=q['mark_price'], last_mark_at=q['mark_timestamp'])
    slot = int(now.timestamp())//300*300
    rows = None
    try:
        rows = causal.read_window(str(Path(c['ledger'])/'execution.sqlite'), slot, list(R.SIGNALS))
    except (ValueError, KeyError, TypeError, OSError):
        pass
    try:
        daily = P.read_approval(c)
    except (ValueError, KeyError, TypeError, OSError):
        daily = None
    # Roll back signal/controller writes too if the economic transaction fails.
    db.execute('BEGIN IMMEDIATE')
    try:
        result, control, legs, claim, increasing = process(c, db, state, control, record, now,
            protocol, parent, structure, rows=rows, daily=daily, funding_ok=funding_ok)
        identity = P.auth.Identity(**a['identity'])
        policy = dict(protocol['risk'], version='risk-policy-original-structural-v1', missing_gates=[])
        if increasing:
            # P0-01's account claim must be durable before the global lease;
            # economic rows and controller still commit atomically below.
            db.rollback()
        def decision_claim():
            # This research-paper successor has a new, explicitly delegated
            # deterministic decision authority; no old issuer approval is
            # repurposed. Recompute its complete causal signal and bounded
            # sizing before durably consuming the one-shot account claim.
            raw = json.loads(db.execute('SELECT payload FROM structural_signals WHERE slot=?',
                                        (control['signal_slot'],)).fetchone()[0])
            model = R.model(raw['rows'], control['signal_slot'])
            if (model['input_hash'] != raw['model_hash'] or model['feature']['btc_60m'] > -.01 or
                    model['feature']['negative_breadth'] < 12/18 or a['account'] != ACCOUNT):
                raise ValueError('successor_decision_not_authorized')
            approval = read_signal_approval(c,control['authority_id'],control['signal_slot'],now,model['input_hash'])
            if approval['approval_id'] != control['episode']['issuer_approval_id']:
                raise ValueError('successor_issuer_approval_changed')
            plan = R.size(parent, model, P.paper.totals(state, require_positive=False)['equity'],
                          protocol['sizing']['short_caps'], record['quotes'])
            if plan['plan_id'] != control['episode']['plan_id']:
                raise ValueError('successor_plan_claim_mismatch')
            return P.consume_once(db, claim)
        lease = P.auth.Registry(Path(c['control']), audit=Path(c['ledger'])/'authorization.sqlite').entry(
            identity, claim, policy, decision_claim) if increasing else P.nullcontext()
        with lease:
            persist(db, result, control, record, now, fund, legs, claim, increasing, funding_ok)
    except P.auth.Denied as error:
        db.rollback()
        control.update(phase='NORMAL', pending=None, episode=None, status='AUTHORIZATION_DENIED:'+str(error))
        result = state
        persist(db, result, control, record, now, fund, [], claim, False, funding_ok)
    except Exception:
        db.rollback()
        raise
    publish(c, control, result, now, protocol)
    return health(c, result, now, control)


def main():
    global AUTHORITY
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('--successor-authority', required=True)
    parser.add_argument('--successor-authority-sha256', required=True)
    args, rest = parser.parse_known_args()
    AUTHORITY = dict(path=args.successor_authority, sha256=args.successor_authority_sha256)
    P.tick = tick
    P.issuer = structural_issuer
    P.main(rest)


if __name__ == '__main__':
    main()
