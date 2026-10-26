"""Complete copied-ledger integration, deliberately without a service entrypoint.

Only explicitly labelled offline work copies are accepted. The existing running
Runner, protocol and receipt are never patched or promoted by this module.
"""
import copy
import datetime as dt
import json
from pathlib import Path
import sqlite3

from . import v13_fork_runner as f
from . import v13_discrete_risk_candidate as candidate

VERSION = 'fast-half-discrete-offline-integration-v1'
SCOPE = 'OFFLINE_INTEGRATION_ONLY'


def apply_pair(states, targets, prices, filters, record, instant, funding_debt):
    """Plan once economically; provisional simulations have no ledger effects."""
    ordinary, next_filters, _, baseline = f.apply_pair(
        states, targets, prices, filters, record, instant, funding_debt)
    _, _, covariance, _, _ = f.risk_targets(states, targets, prices, filters)
    quantities = {a:{s:p['quantity'] for s,p in ordinary[a]['positions'].items()} for a in f.ARMS}
    repair = candidate.repair(states, quantities, covariance, record, instant, funding_debt,
                              paired_entry_veto=bool(baseline.get('shared_entry_block')))
    if repair['status']=='INVALID_INPUT':
        raise ValueError('discrete_plan_invalid:'+repair['reason'])
    result = repair['states']
    fills = []
    for arm in f.ARMS:
        state = result[arm]
        for leg in (x for x in repair['fills'] if x['arm']==arm):
            symbol = leg['symbol']
            before = states[arm]['positions'][symbol]
            position = state['positions'][symbol]
            if before['quantity']==0 or before['quantity']*position['quantity']<0:
                position['generation'] = before.get('generation',0)+1
            position['position_id'] = f.p.digest(dict(account=state['fork_account'],symbol=symbol,
                                                      generation=position.get('generation',1)))
            fills.append(dict(leg,at=instant.isoformat(),market_hash=record['record_hash'],
                              position_id=position['position_id'],
                              realized_delta=position['realized_pnl']-before['realized_pnl'],
                              offline_plan_version=VERSION))
        arm_fills = [x for x in fills if x['arm']==arm]
        if any(not x['protective'] for x in arm_fills):
            state['risk_policy_state'].update(daily_entries=1,last_increase_at=instant.isoformat())
        state['order_count'] += len(arm_fills)
        state['last_discrete_plan_version'] = VERSION
    outcome = dict(baseline,version=VERSION,scope=SCOPE,
                   execution_authorized=False,orders_authorized=False,
                   realized_allocation_volatility=repair.get('volatility'),
                   risk_gap=repair['gap'],risk_matched=repair['qualified'],
                   blocks=repair['blocks'],funding_debt=repair['funding_debt'],
                   notes=repair['notes'],ordinary_risk_gap=baseline['risk_gap'],
                   discrete_status=repair['status'],quantity_adjustments=repair['adjustments'],
                   paired_entry_veto=repair['paired_entry_veto'],ordinary_notes=baseline['notes'])
    return result,next_filters,fills,outcome


class OfflineRunner(f.Runner):
    """Retain legacy continuation identity and add a separate offline epoch."""
    def __init__(self, config):
        scope = config.get('offline',{})
        if scope.get('scope') != SCOPE:
            raise ValueError('offline_scope_required')
        work = Path(scope['work_dir']).resolve(strict=True)
        db = Path(config['db'])
        if (not db.is_file() or db.is_symlink() or not db.resolve().is_relative_to(work)
                or db.resolve() in (Path(config['seed']).resolve(),Path(config['original']).resolve())):
            raise ValueError('offline_work_copy_required')
        self.boundary = f.p.timestamp(scope['boundary'])
        if self.boundary.time() != dt.time(0,15):
            raise ValueError('offline_daily_boundary')
        expected = scope['source_ledger_sha256']
        f.p.require_hash(expected)
        self.offline_identity = dict(version=VERSION,scope=SCOPE,module_sha256=f.sha(__file__),
                                     candidate_sha256=f.sha(candidate.__file__),base_sha256=f.sha(f.__file__),
                                     boundary=self.boundary.isoformat(),source_ledger_sha256=expected)
        # A hot DELETE journal requires SQLite's physical rollback before even
        # a SELECT can succeed. Only the validated offline work copy is opened
        # read/write; semantic queries remain read-only. Never unlink journals.
        connection = sqlite3.connect(db,timeout=1)
        connection.execute('PRAGMA query_only=ON')
        try:
            row = connection.execute("SELECT payload FROM meta WHERE key='offline_discrete_identity'").fetchone()
            saved = json.loads(row[0]) if row else None
            latest = connection.execute('SELECT MAX(at) FROM observations').fetchone()[0]
        finally:
            connection.close()
        if saved is not None and saved != self.offline_identity:
            raise ValueError('offline_continuation_identity_changed')
        if saved is None and (f.sha(db)!=expected or (latest and self.boundary<=f.p.timestamp(latest))):
            raise ValueError('offline_source_or_boundary_changed')
        super().__init__(config,initialize=False)
        if saved is None:
            with self.db:
                self.put('offline_discrete_identity',self.offline_identity)
                self.put('offline_discrete_boundary',dict(at=self.boundary.isoformat(),
                    inherited_states_sha256=f.p.digest(self.states()),legacy_receipt_sha256=f.p.digest(self.receipt),
                    execution_authorized=False,scope=SCOPE))

    def tick(self, now=None):
        """Same slot transaction semantics as the pinned legacy runner.

        This separate implementation is intentional: the active module has no
        adapter hook and must not be changed or monkeypatched for this test.
        """
        now = now or f.source.now()
        first = max(self.boundary,f.p.timestamp(self.receipt['first_decision_slot']))
        slot = now.replace(hour=0,minute=15,second=0,microsecond=0)
        if now>=f.p.timestamp(self.receipt['end_exclusive']):
            with self.db:
                self.put('health',dict(status='COMPLETED_AWAITING_REVIEW',checked_at=now.isoformat(),reason='fixed_horizon_reached'))
            return
        pending = first
        with self.db:
            while pending+dt.timedelta(seconds=120)<now:
                self.db.execute('INSERT OR IGNORE INTO slots VALUES(?,?,?)',
                    (pending.isoformat(),'MISSED',f.dump(dict(reason='outside_execution_window',scope=SCOPE))))
                pending += dt.timedelta(days=1)
        due = slot>=first and slot<=now<=slot+dt.timedelta(seconds=120) and not self.db.execute(
            'SELECT 1 FROM slots WHERE slot=?',(slot.isoformat(),)).fetchone()
        record = self.book_for_slot(slot,now) if due else None
        action = due and record is not None
        if record is None:
            record = f.read(Path(self.c['derivation']['source'])/'market.json')
        f.verified_market(record,self.universe,now)
        self.recover_passive_grid(record)
        at = f.p.timestamp(record['observed_at_end'])
        last = self.db.execute('SELECT MAX(at) FROM observations').fetchone()[0]
        if last and at<f.p.timestamp(last):
            raise ValueError('clock_or_capture_regression')
        if not action and last and int(at.timestamp())//300==int(f.p.timestamp(last).timestamp())//300:
            with self.db:
                self.put('health',dict(status='OBSERVING',checked_at=now.isoformat(),reason=self.meta('funding_debt')))
            return
        states = self.states()
        debt = None
        funding_rows = []
        try:
            states,funding_rows = self.fund(states,record)
        except (ValueError,KeyError,TypeError) as error:
            debt = str(error)
        for state in states.values():
            for s,q in record['quotes'].items():
                state['positions'][s].update(current_price=q['mark_price'],last_mark_at=q['mark_timestamp'])
            f.engine.risk_gate(state,at,f.paper.totals(state,require_positive=False)['equity'])
        filters = self.meta('filters')
        fills = []
        outcome = status = None
        if action:
            try:
                item = self.prepare_input(slot)
                states,filters,fills,outcome = apply_pair(states,item['targets'],item['prices'],filters,
                                                         record,at,debt or self.meta('valuation_gap'))
                outcome.update(proposal_id=item['proposal_id'],snapshot_id=item['snapshot_id'],market_hash=record['record_hash'])
                status = 'EXECUTED' if fills else 'OBSERVED_NO_FILL'
            except (ValueError,KeyError,TypeError) as error:
                status = 'DENIED'
                outcome = dict(reason=str(error),scope=SCOPE)
            if f.source.now()>slot+dt.timedelta(seconds=120):
                raise ValueError('execution_deadline_expired')
        original = json.loads(self.original.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        observation = dict(states={},funding_debt=debt,original_at=original.get('last_success_at'),scope=SCOPE)
        for arm,state in dict(states,ORIGINAL=original).items():
            observation['states'][arm] = f.paper.totals(state,require_positive=False)
        with self.db:
            if action:
                self.db.execute('INSERT INTO slots VALUES(?,?,?)',(slot.isoformat(),status,f.dump(outcome)))
            for arm,state in states.items():
                self.db.execute('UPDATE states SET payload=? WHERE arm=?',(f.dump(state),arm))
            for fill in fills:
                self.db.execute('INSERT INTO fills VALUES(?,?,?,?,?,?)',
                    (f.p.digest(dict(fill,slot=slot.isoformat())),fill['arm'],fill['at'],fill['symbol'],fill['quantity'],f.dump(fill)))
            for row in funding_rows:
                self.db.execute('INSERT INTO funding VALUES(?,?,?,?,?)',
                    (row['arm'],row['symbol'],row['at'],row['amount'],f.dump(row)))
            self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)',
                (at.isoformat(),record['record_hash'],f.dump(observation)))
            self.put('filters',filters)
            self.put('funding_debt',debt)
            self.put('health',dict(status='OBSERVING',checked_at=now.isoformat(),reason=debt))
