"""Autonomous, full-history M1 paper fork. Network and execution interfaces absent.

Cards work-card-af5139fb-d6e9-420b-bc80-706fcb5256e4 and
work-card-418e6bfc-83ca-4516-8b58-c6f4d9007aff. Existing experiment code is reused
without modification. Copied authorizations are archival evidence only.
"""
import argparse
import copy
import datetime as dt
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import sqlite3
import time
from decimal import Decimal, ROUND_DOWN

from octobot.ai_strategy_lab import v13_fork_runner as shared
from octobot.ai_strategy_lab import v13_fork_snapshot as snapshot
from octobot.ai_strategy_lab import v13_m1_future as causal

engine, paper, source, p, exposure = shared.engine, shared.paper, shared.source, shared.p, shared.exposure
UTC = dt.timezone.utc
VERSION = 'v13-m1-full-history-paper-v1'


def describe(db):
    factory=db.row_factory
    try:
        db.row_factory=None
        return snapshot.describe(db)
    finally:
        db.row_factory=factory


def prepare_clone(original, destination):
    """One online RO transaction; byte-identical sealed seed and working copy."""
    original, destination = Path(original), Path(destination)
    if original.is_symlink() or not original.is_file() or destination.exists():
        raise ValueError('new_isolated_clone_required')
    destination.mkdir(mode=0o750, parents=True)
    seed = destination / 'seed.sqlite'
    before = source.now()
    src = shared.ro(original)
    src.execute('BEGIN')
    dst = sqlite3.connect(seed)
    try:
        tables, state = describe(src)
        src.backup(dst, pages=256, sleep=.01)
        if dst.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
            raise ValueError('clone_integrity')
        if describe(dst) != (tables, state):
            raise ValueError('clone_logical_mismatch')
    finally:
        dst.close(); src.rollback(); src.close()
    snapshot.seal(seed)
    account = destination / 'account.sqlite'
    shutil.copyfile(seed, account); account.chmod(0o640)
    if shared.sha(seed) != shared.sha(account) or seed.stat().st_ino == account.stat().st_ino:
        raise ValueError('clone_bytes')
    # Reconstruct economic quantities from the entire filled prefix independently.
    db = shared.ro(seed)
    try:
        for symbol, position in state['positions'].items():
            actual = paper.new_position()
            for row in db.execute("SELECT quantity,price,fee FROM orders WHERE symbol=? AND status='filled' ORDER BY bar,id", (symbol,)):
                paper.apply_fill(actual, *row)
            funding = db.execute('SELECT COALESCE(SUM(amount),0) FROM funding_events WHERE symbol=?', (symbol,)).fetchone()[0]
            for key in ('quantity', 'entry_price', 'realized_pnl', 'fees'):
                if not math.isclose(actual[key], position[key], rel_tol=1e-10, abs_tol=1e-6):
                    raise ValueError('clone_accounting:' + symbol + ':' + key)
            if not math.isclose(funding, position['funding'], rel_tol=1e-10, abs_tol=1e-6):
                raise ValueError('clone_funding:' + symbol)
        metrics = paper.totals(state, require_positive=False)
        last = db.execute('SELECT equity FROM equity_history ORDER BY bar DESC LIMIT 1').fetchone()
        if not last or not math.isclose(last[0], metrics['equity'], abs_tol=1e-6):
            raise ValueError('clone_equity')
    finally:
        db.close()
    receipt = dict(version=VERSION, prepared_at=source.now().isoformat(), backup_started_at=before.isoformat(),
                   economic_t0=state['last_success_at'], seed_sha256=shared.sha(seed),
                   account_id='v13-m1-short-paper-v1-' + shared.sha(seed)[:12], tables=tables,
                   inherited_metrics=metrics, inherited_risk=state['risk_policy_state'],
                   inherited_positions=state['positions'], historical_claims_usable=False,
                   scope='RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK')
    path = destination / 'clone-receipt.json'
    path.write_text(shared.dump(receipt) + '\n'); snapshot.seal(path)
    return receipt


def risk_gate(state, instant, kind, policy, control):
    """Persistent inherited loss/peak counters; dedicated exceptions require policy."""
    equity = paper.totals(state, require_positive=False)['equity']
    risk = state['risk_policy_state']; day = instant.date().isoformat()
    if risk['daily_day'] != day:
        risk.update(daily_day=day, daily_start=equity, daily_entries=0)
    risk['high_water'] = max(risk['high_water'], equity)
    if equity <= 0 or risk['daily_start'] is None:
        return 'risk_equity_missing'
    if equity <= risk['daily_start'] * .98:
        return 'daily_loss_2_percent'
    if equity <= risk['high_water'] * .90:
        return 'drawdown_10_percent'
    if policy == 'INHERIT_STRICT':
        return engine.risk_gate(state, instant, equity)
    if policy != 'M1_DEDICATED_APPROVED':
        return 'policy_choice_not_approved'
    if risk['daily_entries'] >= 3:
        return 'three_risk_batches_per_UTC_day'
    if kind == 'DAILY':
        if control.get('normal_day') == day:
            return 'one_normal_rebalance_per_UTC_day'
        last = control.get('last_normal_at')
        if last and (instant - p.timestamp(last)).total_seconds() < 79200:
            return 'normal_cooldown_22_hours'
    return None


def exact_plan(state,quotes,targets,allow):
    """Mirror quantities without a lossy quantity-weight-quantity round trip."""
    legs=[];notes=[]
    for s,target in sorted(targets.items()):
        q=quotes[s];old=state['positions'][s]['quantity'];delta=target-old
        if abs(delta)<1e-10:continue
        protective=old*target>=0 and abs(target)<abs(old)
        if not allow and not protective:
            notes.append(dict(symbol=s,reason='new_risk_suspended'));continue
        mid=(q['asks'][0]['price']+q['bids'][0]['price'])/2
        if not protective and ((q['asks'][0]['price']-q['bids'][0]['price'])/mid>float(shared.sanity.POLICY.max_spread_ratio) or abs(q['mark_price']-mid)/mid>float(shared.sanity.POLICY.max_mark_mid_divergence)):
            notes.append(dict(symbol=s,reason='spread_or_mark_divergence'));continue
        step=q['quantity_step'];capacity=math.fsum(v['base_quantity'] for v in q['asks' if delta>0 else 'bids'])
        if abs(delta)>capacity:
            amount=float((Decimal(str(capacity))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step)))
            delta=math.copysign(amount,delta);notes.append(dict(symbol=s,reason='partial_observed_depth'))
        if not delta:continue
        after=old+delta
        actual_protective=old*after>=0 and abs(after)<abs(old)
        if not actual_protective and abs(after/step-round(after/step))>1e-7:
            notes.append(dict(symbol=s,reason='quantity_not_aligned'));continue
        price=exposure.execution_price(q,delta,engine.market.fill_price)
        opening=abs(after) if old*after<0 else max(0.,abs(after)-abs(old))
        if not actual_protective and opening*price<1:
            notes.append(dict(symbol=s,reason='below_simulated_notional_1_USDT'));continue
        if not .0006<=q['fee_rate']<1:raise ValueError('fee_invalid')
        legs.append(dict(symbol=s,quantity=delta,price=price,fee=abs(delta*price)*q['fee_rate'],protective=actual_protective,
                         weight=target*q['mark_price']/paper.totals(state,require_positive=False)['equity']))
    return sorted(legs,key=lambda v:(not v['protective'],v['symbol'])),notes


def apply_weights(state, quotes, weights, instant, kind, policy, control, debt=None, force_reduce=False, exact_targets=None):
    """Atomic basket; every reversal consumes combined side depth exactly once."""
    result = copy.deepcopy(state)
    veto = risk_gate(result, instant, kind, policy, control) or debt
    allow = not veto and not force_reduce
    if kind == 'M1_ENTRY' and not allow:
        # A refused reversal must still allow a protective long close.
        weights = {s: (0. if result['positions'][s]['quantity'] > 0 else w) for s, w in weights.items()}
        if exact_targets is not None:
            exact_targets={s:(0. if result['positions'][s]['quantity']>0 else q) for s,q in exact_targets.items()}
    legs, notes = exact_plan(result,quotes,exact_targets,allow) if exact_targets is not None else engine.research_plan(result, quotes, weights, allow)
    if kind=='M1_ENTRY' and allow and notes:
        return apply_weights(state,quotes,weights,instant,kind,policy,control,'m1_market_veto',True,exact_targets)
    fills = []
    for leg in legs:
        s = leg['symbol']; old = copy.deepcopy(result['positions'][s])
        paper.apply_fill(result['positions'][s], leg['quantity'], leg['price'], leg['fee'])
        quantities, marks = exposure.quantities_and_marks(result)
        risk = exposure.snapshot(quantities, marks, paper.totals(result, require_positive=False)['equity'], .90, .315)
        protective = old['quantity'] * result['positions'][s]['quantity'] >= 0 and abs(result['positions'][s]['quantity']) < abs(old['quantity'])
        if risk['breaches'] and not protective:
            if force_reduce:
                raise ValueError('protective_plan_increased_risk')
            return apply_weights(state, quotes, weights, instant, kind, policy, control, 'exposure_cap', True,exact_targets)
        fills.append(dict(**leg, before=old['quantity'], after=result['positions'][s]['quantity'],
                          realized_delta=result['positions'][s]['realized_pnl'] - old['realized_pnl']))
    increased = any(not f['protective'] for f in fills)
    if increased:
        result['risk_policy_state']['daily_entries'] += 1
        result['risk_policy_state']['last_increase_at'] = instant.isoformat()
    result['order_count'] += len(fills)
    return result, fills, dict(entry_block=veto, notes=notes, increased=increased)


class Runner:
    def __init__(self, config, initialize=False):
        self.c = config; self.protocol = shared.read(config['protocol'])
        self.universe = self.protocol['universe']; self.policy = self.protocol['risk_policy']['mode']
        if self.policy not in {'INHERIT_STRICT', 'M1_DEDICATED_APPROVED'}:
            raise ValueError('policy_not_selected')
        expected_policy=dict(daily_loss=.02,drawdown=.10,max_asset=.315,max_gross=.90,max_risk_batches_per_UTC_day=3,max_M1_episodes_per_UTC_day=1,normal_cooldown_seconds=79200,normal_risk_rebalances_per_day=1)
        if self.policy=='M1_DEDICATED_APPROVED' and any(self.protocol['risk_policy'].get(k)!=v for k,v in expected_policy.items()):
            raise ValueError('unsupported_policy_parameters')
        if self.protocol['permissions'] != dict(real_orders=False, operational_grants=False, modify_existing=False, issuer_executor_link=False):
            raise ValueError('research_scope')
        for name, expected in self.protocol['source_code_pins'].items():
            if shared.sha(Path(config['repo']) / name) != expected:
                raise ValueError('source_code_pin:' + name)
        self.seed = shared.ro(config['seed']); self.original = shared.ro(config['original'])
        self.parent = json.loads(self.seed.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        self.receipt = shared.read(config['receipt']); self.account = self.receipt['account_id']
        if shared.sha(config['seed']) != self.receipt['seed_sha256']:
            raise ValueError('seed_changed')
        self.t0 = p.timestamp(self.receipt['economic_t0'])
        path = Path(config['db'])
        if path.is_symlink() or not path.is_file():
            raise ValueError('continuation_missing_no_reset')
        self.db = sqlite3.connect(path.resolve().as_uri() + '?mode=rw', uri=True, timeout=10)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA synchronous=FULL')
        existing = self.db.execute("SELECT 1 FROM sqlite_master WHERE name='m1_meta'").fetchone()
        if bool(existing) == bool(initialize):
            raise ValueError('initialization_or_reset_refused')
        identity = dict(seed=self.receipt['seed_sha256'], protocol=shared.sha(config['protocol']), runner=shared.sha(__file__))
        if initialize:
            if describe(self.db)[0] != self.receipt['tables']:
                raise ValueError('working_clone_changed_before_initialization')
            self.db.executescript('''
            CREATE TABLE m1_meta(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
            CREATE TABLE m1_slots(kind TEXT,slot TEXT,status TEXT,payload TEXT,PRIMARY KEY(kind,slot));
            CREATE TABLE m1_episodes(id TEXT PRIMARY KEY,signal_at TEXT,entry_due TEXT,exit_due TEXT,status TEXT,payload TEXT);
            CREATE TABLE m1_fills(id TEXT PRIMARY KEY,at TEXT,symbol TEXT,quantity REAL,payload TEXT);
            CREATE TABLE m1_observations(at TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE inputs(day TEXT PRIMARY KEY,payload TEXT NOT NULL);
            ''')
            now = source.now(); first = dt.datetime.fromtimestamp((int(now.timestamp()) // 300 + 1) * 300, UTC)
            risk = self.parent['risk_policy_state']
            with self.db:
                self.put('identity', identity); self.put('activation', dict(recorded_at=now.isoformat(), first_signal_slot=first.isoformat()))
                self.put('control', dict(phase='NORMAL', pending=None, cooldown_until=None, episode_day=None,
                                        normal_day=risk['daily_day'] if risk['daily_entries'] else None,
                                        last_normal_at=risk['last_increase_at'], baseline_targets=None, last_seen=now.isoformat()))
        elif self.meta('identity') != identity:
            raise ValueError('continuation_identity_changed')
        self.activation = self.meta('activation')

    def meta(self, key):
        row = self.db.execute('SELECT payload FROM m1_meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, key, value):
        self.db.execute('INSERT OR REPLACE INTO m1_meta VALUES(?,?)', (key, shared.dump(value)))

    def prepare_input(self, slot):
        return shared.Runner.prepare_input(self, slot)

    def baseline(self, control, now):
        day = (now.date() - dt.timedelta(days=1)).isoformat()
        if control.get('baseline_day') != day:
            item = self.prepare_input(now)
            control.update(baseline_day=day, baseline_targets=item['targets'], proposal_id=item['proposal_id'])

    def funding(self, state, record):
        """Verified settlements use actual fork orders and a prior observed mark."""
        candidate = copy.deepcopy(state)
        end = p.timestamp(record['observed_at_end']); endms = int(end.timestamp()*1000)
        for s, pos in candidate['positions'].items():
            q = record['quotes'][s]; cursor = p.timestamp(pos['funding_cursor']); ms = int(cursor.timestamp()*1000)
            points, interval = q['funding'], q['funding_interval_ms']
            if type(interval) is not int or not 0 < interval <= 86400000 or not points or points[-1]['timestamp_ms'] + interval <= endms:
                raise ValueError('funding_coverage:' + s)
            events = [e for e in points if ms < e['timestamp_ms'] <= endms]
            if (events and events[0]['timestamp_ms'] - ms > interval) or any(b['timestamp_ms']-a['timestamp_ms'] > interval for a,b in zip(events,events[1:])):
                raise ValueError('funding_gap:' + s)
            for event in events:
                when = event['timestamp_ms']
                if self.db.execute('SELECT 1 FROM funding_events WHERE symbol=? AND timestamp_ms=?', (s,when)).fetchone():
                    continue
                at = dt.datetime.fromtimestamp(when/1000, UTC).isoformat()
                quantity = math.fsum(r[0] for r in self.db.execute("SELECT quantity FROM orders WHERE status='filled' AND symbol=? AND bar<?", (s,at)))
                mark = self.db.execute('SELECT bar,price FROM marks WHERE symbol=? AND bar<? ORDER BY bar DESC LIMIT 1', (s,at)).fetchone()
                if quantity and (not mark or (p.timestamp(at)-p.timestamp(mark['bar'])).total_seconds() > 1800):
                    raise ValueError('funding_previous_mark:' + s)
                reference = mark['price'] if mark else None
                rate = exposure.number(event['rate'], 'funding rate'); amount = -quantity*reference*rate if quantity else 0.
                pos['funding'] += amount
                self.db.execute('INSERT INTO funding_events VALUES(?,?,?,?,?,?)', (s,when,rate,quantity,reference,amount))
            pos['funding_cursor'] = end.isoformat()
        return candidate

    def intent(self, control, kind, weights, now, due, deadline=None):
        decision = dict(account=self.account, kind=kind, weights=weights, created_at=now.isoformat(),
                        due=due.isoformat(), deadline=deadline.isoformat() if deadline else None)
        decision['id'] = p.digest(decision); control['pending'] = decision

    def weights_from_quantities(self, state, quantities):
        equity = paper.totals(state, require_positive=False)['equity']
        if equity <= 0:
            raise ValueError('non_positive_equity')
        return {s: quantities[s] * state['positions'][s]['current_price'] / equity for s in self.universe}

    def execute_pending(self, state, control, record, now, debt):
        pending = control.get('pending')
        if not pending:
            return state
        kind = pending['kind']; at = p.timestamp(record['observed_at_end'])
        if pending['deadline'] and now > p.timestamp(pending['deadline']):
            if kind == 'M1_ENTRY':
                self.db.execute("UPDATE m1_episodes SET status='ENTRY_MISSED' WHERE id=?", (control['episode'],))
                control['phase'] = 'NORMAL'
            elif kind == 'DAILY':
                self.db.execute("UPDATE m1_slots SET status='MISSED',payload=? WHERE kind='DAILY' AND slot=?", (shared.dump(dict(reason='execution_window_expired')),pending['due']))
            control['pending'] = None
            control['last_action'] = dict(kind=kind, status='MISSED', reason='execution_window_expired')
            return state
        if now < p.timestamp(pending['due']) or p.timestamp(record['observed_at_start']) <= p.timestamp(pending['created_at']):
            return state
        if at < p.timestamp(pending['due']) or control.get('last_action_market') == record['record_hash']:
            return state
        if kind in {'M1_ENTRY', 'EXIT', 'PROTECTIVE_REMAINDER'}:
            target = control['entry_quantities'] if kind == 'M1_ENTRY' else {s:(0. if s in control['overlay_symbols'] and (kind=='EXIT' or state['positions'][s]['quantity']>0) else state['positions'][s]['quantity']) for s in self.universe}
            weights = self.weights_from_quantities(state, target)
        else:
            weights = pending['weights'];target=None
        updated, fills, outcome = apply_weights(state, record['quotes'], weights, at, kind, self.policy, control, debt, kind in {'EXIT','PROTECTIVE_REMAINDER'},target)
        if pending['deadline'] and source.now() > p.timestamp(pending['deadline']):
            raise ValueError('execution_deadline_expired')
        shared.verified_market(record,self.universe,source.now())
        for fill in fills:
            s = fill['symbol']; pos = updated['positions'][s]
            generation = state['positions'][s].get('generation', 0) + int(fill['before']==0 or fill['before']*fill['after']<0)
            pos['generation'] = generation; pos['position_id'] = p.digest(dict(account=self.account, symbol=s, generation=generation))
            payload = dict(**fill, kind=kind, at=at.isoformat(), decision_id=pending['id'], market_hash=record['record_hash'], position_id=pos['position_id'])
            fid = p.digest(payload)
            self.db.execute('INSERT INTO m1_fills VALUES(?,?,?,?,?)', (fid,at.isoformat(),s,fill['quantity'],shared.dump(payload)))
            self.db.execute("INSERT INTO orders(bar,symbol,action,weight,notional,fee,status,quantity,price,recorded_at,decision_hash,market_hash,realized_pnl) VALUES(?,?,?,?,?,?,'filled',?,?,?,?,?,?)",
                            (at.isoformat(),s,'BUY' if fill['quantity']>0 else 'SELL',fill['weight'],abs(fill['quantity']*fill['price']),fill['fee'],fill['quantity'],fill['price'],now.isoformat(),pending['id'],record['record_hash'],fill['realized_delta']))
        if outcome['increased'] and kind == 'DAILY':
            control.update(normal_day=at.date().isoformat(), last_normal_at=at.isoformat())
        control['pending'] = None; control['last_action_market'] = record['record_hash']
        control['last_action'] = dict(kind=kind, status='FILLED' if fills else 'NO_FILL', at=at.isoformat(), **outcome)
        if kind == 'DAILY':
            self.db.execute("UPDATE m1_slots SET status=?,payload=? WHERE kind='DAILY' AND slot=?", (control['last_action']['status'],shared.dump(control['last_action']),pending['due']))
        if kind == 'M1_ENTRY':
            control['phase'] = 'ACTIVE'
            evidence=json.loads(self.db.execute('SELECT payload FROM m1_episodes WHERE id=?',(control['episode'],)).fetchone()[0])
            evidence['entry_outcome']=dict(control['last_action'],mode='SHORT' if any(updated['positions'][s]['quantity']<0 for s in control['overlay_symbols']) else 'CASH_ONLY')
            self.db.execute('UPDATE m1_episodes SET status=?,payload=? WHERE id=?', ('ACTIVE',shared.dump(evidence),control['episode']))
        elif kind == 'EXIT':
            if all(abs(updated['positions'][s]['quantity'])<1e-10 for s in control['overlay_symbols']):
                control['phase'] = 'REENTRY_PENDING'; control['cooldown_until'] = (at+dt.timedelta(hours=6)).isoformat()
                self.db.execute("UPDATE m1_episodes SET status='CLOSED_AWAITING_REENTRY' WHERE id=?", (control['episode'],))
        elif kind == 'REENTRY':
            if not outcome['notes'] or outcome['increased']:
                control['phase'] = 'NORMAL'
                self.db.execute("UPDATE m1_episodes SET status='COMPLETED' WHERE id=?", (control['episode'],))
        return updated

    def tick(self, now=None):
        now = now or source.now(); control = self.meta('control')
        if now < p.timestamp(control['last_seen']):
            raise ValueError('clock_regression')
        record = source.owned_json(Path(self.c['derivation']['source'])/'market.json', 30911)
        shared.verified_market(record, self.universe, now)
        at = p.timestamp(record['observed_at_end'])
        if at <= self.t0:
            with self.db:self.put('health',dict(status='WAITING_FOR_NEW_BOOK',checked_at=now.isoformat(),reason=None))
            return
        state = json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        if state.get('m1_last_market_at') and at < p.timestamp(state['m1_last_market_at']):
            raise ValueError('market_regression')
        if state.get('m1_last_market_at')==at.isoformat() and state.get('m1_market_hash')!=record['record_hash']:
            raise ValueError('conflicting_book_at_same_timestamp')
        first = p.timestamp(self.activation['first_signal_slot'])
        grid = dt.datetime.fromtimestamp(int(now.timestamp())//300*300, UTC)
        daily = now.replace(hour=0,minute=15,second=0,microsecond=0)
        # Scientific input reads happen before the account transaction, without writes upstream.
        slot_new = grid >= first and not self.db.execute("SELECT 1 FROM m1_slots WHERE kind='M1' AND slot=?", (grid.isoformat(),)).fetchone()
        rows = causal.read_window(self.c['original'], int(grid.timestamp()), self.universe) if slot_new and now<=grid+dt.timedelta(seconds=120) else None
        feature = None
        if rows and len(rows)==289 and all(set(r['prices'])==set(self.universe) and set(r['source_times'])==set(self.universe) and all(0<=r['time']-v<=120 for v in r['source_times'].values()) for r in rows):
            feature = causal.detector.features(rows,288)
        # Derivation is independently verified; cache is research input only.
        try:
            self.baseline(control, now); control['baseline_error'] = None
        except (ValueError,KeyError,TypeError,OSError) as error:
            control['baseline_error'] = str(error)
        now = max(now, source.now())
        with self.db:
            for s,q in record['quotes'].items():
                state['positions'][s].update(current_price=q['mark_price'], last_mark_at=q['mark_timestamp'])
                self.db.execute('INSERT OR IGNORE INTO marks VALUES(?,?,?)',(at.isoformat(),s,q['mark_price']))
            # Savepoint makes a partially failed funding basket reversible.
            self.db.execute('SAVEPOINT funding_batch')
            try:
                state = self.funding(state,record); self.db.execute('RELEASE funding_batch'); debt = None
            except (ValueError,KeyError,TypeError) as error:
                self.db.execute('ROLLBACK TO funding_batch'); self.db.execute('RELEASE funding_batch'); debt = str(error)
            risk_gate(state, at, 'STATUS', self.policy, control)
            state = self.execute_pending(state,control,record,now,debt or control['baseline_error'])
            previous = self.db.execute("SELECT MAX(slot) FROM m1_slots WHERE kind='M1'").fetchone()[0]
            missed = p.timestamp(previous)+dt.timedelta(minutes=5) if previous else first
            while missed < grid:
                self.db.execute("INSERT INTO m1_slots VALUES('M1',?,'MISSED',?)", (missed.isoformat(),shared.dump(dict(reason='observer_not_present'))))
                missed += dt.timedelta(minutes=5)
            if slot_new:
                status = 'MISSED' if now>grid+dt.timedelta(seconds=120) else 'NO_SIGNAL' if feature else 'INSUFFICIENT_INPUT'
                trigger = now<=grid+dt.timedelta(seconds=120) and feature and causal.detector.signal(feature,'momentum_breadth')
                if trigger:
                    cooldown = control['cooldown_until'] and now < p.timestamp(control['cooldown_until'])
                    if control['phase']!='NORMAL' or cooldown:
                        status = 'COOLDOWN'
                    elif self.policy=='M1_DEDICATED_APPROVED' and control['episode_day']==grid.date().isoformat():
                        status = 'DAILY_EPISODE_LIMIT'
                    elif not any(pos['quantity']>1e-10 for pos in state['positions'].values()):
                        status = 'NO_LONG'
                    else:
                        status = 'SCHEDULED'
                        due = grid+dt.timedelta(minutes=5); end = due+dt.timedelta(hours=6)
                        eid = p.digest(dict(account=self.account,slot=grid.isoformat(),input_hash=causal.digest(rows)))
                        control.update(phase='PENDING_ENTRY',episode=eid,episode_day=grid.date().isoformat(),
                                       entry_quantities={s:(-pos['quantity'] if pos['quantity']>0 else pos['quantity']) for s,pos in state['positions'].items()},
                                       overlay_symbols=[s for s,pos in state['positions'].items() if pos['quantity']>0], exit_due=end.isoformat(),cooldown_until=(end+dt.timedelta(hours=6)).isoformat())
                        self.intent(control,'M1_ENTRY',None,now,due,due+dt.timedelta(seconds=120))
                        self.db.execute('INSERT INTO m1_episodes VALUES(?,?,?,?,?,?)', (eid,grid.isoformat(),due.isoformat(),end.isoformat(),'PENDING_ENTRY',shared.dump(dict(feature=feature,input_hash=causal.digest(rows),consumed_rows=rows))))
                self.db.execute("INSERT INTO m1_slots VALUES('M1',?,?,?)",(grid.isoformat(),status,shared.dump(dict(feature=feature,recorded_at=now.isoformat()))))
            if daily>=first and daily<=now and not self.db.execute("SELECT 1 FROM m1_slots WHERE kind='DAILY' AND slot=?",(daily.isoformat(),)).fetchone():
                status = 'MISSED' if now>daily+dt.timedelta(seconds=120) else 'OVERLAY_HOLD' if control['phase']!='NORMAL' else 'PENDING'
                if status=='PENDING' and not control['baseline_error']:
                    self.intent(control,'DAILY',control['baseline_targets'],now,daily,daily+dt.timedelta(seconds=120))
                elif status=='PENDING':
                    status='DENIED'
                self.db.execute("INSERT INTO m1_slots VALUES('DAILY',?,?,?)",(daily.isoformat(),status,shared.dump(dict(reason=control['baseline_error']))))
            if control['phase'] in {'ACTIVE','EXIT_PENDING'} and now>=p.timestamp(control['exit_due']) and not control['pending']:
                control['phase']='EXIT_PENDING'; self.intent(control,'EXIT',None,now,now)
            elif control['phase']=='ACTIVE' and any(state['positions'][s]['quantity']>1e-10 for s in control['overlay_symbols']) and not control['pending']:
                self.intent(control,'PROTECTIVE_REMAINDER',None,now,now)
            if control['phase']=='REENTRY_PENDING' and not control['pending']:
                veto = risk_gate(state,at,'REENTRY',self.policy,control) or debt or control['baseline_error']
                control['reentry_block'] = veto
                if not veto:
                    self.intent(control,'REENTRY',control['baseline_targets'],now,now)
            state = self.execute_pending(state,control,record,now,debt or control['baseline_error'])
            state.update(m1_last_market_at=at.isoformat(),m1_market_hash=record['record_hash'],fork_account=self.account)
            metrics = paper.totals(state,require_positive=False)
            self.db.execute('UPDATE state SET payload=? WHERE id=1',(shared.dump(state),))
            self.db.execute('INSERT OR REPLACE INTO equity_history VALUES(?,?,?)',(at.isoformat(),metrics['equity'],metrics['pnl']))
            self.db.execute('INSERT OR REPLACE INTO m1_observations VALUES(?,?)',(at.isoformat(),shared.dump(dict(metrics=metrics,market_hash=record['record_hash'],funding_debt=debt))))
            control['last_seen']=now.isoformat(); self.put('control',control)
            self.put('health',dict(status='OBSERVING',checked_at=now.isoformat(),reason=debt or control['baseline_error']))

    def close(self):
        self.db.close(); self.seed.close(); self.original.close()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--config',required=True); parser.add_argument('--initialize',action='store_true'); parser.add_argument('--once',action='store_true');args=parser.parse_args()
    path=Path(args.config)
    if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:
        raise ValueError('root_config_required')
    c=shared.read(path)
    if os.geteuid()!=c['runner_uid']:
        raise ValueError('runner_uid')
    lock=open(c['db']+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    runner=Runner(c,initialize=args.initialize)
    from octobot.ai_strategy_lab.v13_m1_paper_view import publish
    try:
        while True:
            try:runner.tick()
            except Exception as error:
                with runner.db:runner.put('health',dict(status='BLOCKED',checked_at=source.now().isoformat(),reason=str(error)))
                print(shared.dump(dict(status='BLOCKED',reason=str(error))),flush=True)
            publish(runner)
            if args.once:break
            time.sleep(20)
    finally:runner.close()


if __name__=='__main__':main()
