"""Versioned continuation of the existing M1 account with approved maintenance.

Single writer of the existing ledger. Separate collector and approval writer;
no network, credentials, operational grants or Original account mutations.
"""
import argparse
import copy
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import time
from . import v13_m1_paper as base
from . import v13_m1_weekly as weekly
from .v13_m1_approval_broker import safe_file


class Runner(base.Runner):
    def __init__(self,config):
        super().__init__(config)
        self.mc=config['management'];self.signal_symbols=list(self.protocol['universe'])
        if self.mc['scope'] not in {'M1_WEEKLY_MANAGEMENT_V1','M1_WEEKLY_MANAGEMENT_CONTROL_TEST_V1'}:raise ValueError('management_scope')
        for name,expected in self.mc['code_pins'].items():
            if base.shared.sha(Path(config['repo'])/name)!=expected:raise ValueError('management_code_changed')
        with self.db:
            self.db.executescript('CREATE TABLE IF NOT EXISTS m1_weekly_reviews(id TEXT PRIMARY KEY,week TEXT UNIQUE NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,decision_id TEXT); '
                                 'CREATE TABLE IF NOT EXISTS m1_management_consumed(id TEXT PRIMARY KEY,payload TEXT NOT NULL); '
                                 'CREATE TABLE IF NOT EXISTS m1_management_admissions(symbol TEXT PRIMARY KEY,at TEXT NOT NULL,proposal_id TEXT NOT NULL); '
                                 'CREATE TABLE IF NOT EXISTS m1_management_zero_funding(symbol TEXT,from_at TEXT,to_at TEXT,scope TEXT,PRIMARY KEY(symbol,to_at)); '
                                 'CREATE TABLE IF NOT EXISTS m1_management_events(id TEXT PRIMARY KEY,at TEXT NOT NULL,kind TEXT NOT NULL,proposal_id TEXT,payload TEXT NOT NULL);')
            self.db.execute('CREATE INDEX IF NOT EXISTS m1_marks_symbol_time ON marks(symbol,bar)')
            self.db.execute('CREATE TABLE IF NOT EXISTS m1_transition_reviews(id TEXT PRIMARY KEY,week TEXT NOT NULL,payload TEXT NOT NULL,status TEXT NOT NULL,decision_id TEXT)')
        self.management_code=weekly.digest(self.mc['code_pins'])
        if not self.meta('management_start:'+self.management_code):
            with self.db:
                self.event('MANAGEMENT_START',dict(code=self.management_code,scope=self.mc['scope']))
                self.put('management_start:'+self.management_code,True)
        state=json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        self.universe=sorted(state['positions'])
        self.extend_parent(state)

    def extend_parent(self,state):
        for symbol,pos in state['positions'].items():
            if symbol not in self.parent['positions']:
                self.parent['positions'][symbol]=dict(base.paper.new_position(),current_price=pos['current_price'])

    def signal_universe(self):return self.signal_symbols

    def event(self,kind,value,proposal_id=None):
        previous=self.db.execute('SELECT id FROM m1_management_events ORDER BY rowid DESC LIMIT 1').fetchone()
        at=base.source.now().isoformat()
        body=dict(account=self.account,at=at,kind=kind,proposal_id=proposal_id,previous_id=previous[0] if previous else None,
                  code=self.management_code,value=value)
        event_id=weekly.digest(body)
        self.db.execute('INSERT INTO m1_management_events VALUES(?,?,?,?,?)',(event_id,at,kind,proposal_id,base.shared.dump(body)))
        return event_id

    def intent(self,control,kind,weights,now,due,deadline=None):
        super().intent(control,kind,weights,now,due,deadline)
        policy=self.managed_policy()
        if policy:
            pending=control['pending'];pending['maintenance_revision']=policy['revision'];pending['maintenance_proposal']=policy['proposal_id']
            pending['id']=weekly.digest({k:v for k,v in pending.items() if k!='id'})

    def fill_metadata(self,control):
        policy=self.managed_policy()
        return dict(revision=policy['revision'],proposal_id=policy['proposal_id'],approval=policy['decision_id'],code=self.management_code) if policy else None

    def science(self):
        return base.source.owned_json(Path(self.mc['source'])/'science.json',self.mc['capture_uid'])

    def market_record(self,now):
        # A failed account transaction may have rolled back new admissions.
        # Rebuild in-memory scope from committed state before every read.
        committed=json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        full=base.source.owned_json(Path(self.mc['source'])/'market.json',self.mc['capture_uid'])
        weekly.verify(full,'record_hash');self.full_market=full
        if full.get('fixture') and self.mc['scope']!='M1_WEEKLY_MANAGEMENT_CONTROL_TEST_V1':raise ValueError('fixture_forbidden_in_managed_account')
        policy=self.managed_policy()
        held={s for s,v in committed['positions'].items() if v['quantity']}
        if not held<=set(full['quotes']):raise ValueError('held_symbol_book_missing')
        desired={s for s in committed['positions'] if policy and (policy['long_caps'].get(s,0)>0 or policy['short_caps'].get(s,0)>0)}
        self.universe=sorted(held|(desired&set(full['quotes']))) if policy else sorted(committed['positions'])
        return self.project_market(full,self.universe)

    def project_market(self,full,universe):
        record=dict(scope=full['scope'],observed_at_start=full['observed_at_start'],observed_at_end=full['observed_at_end'],
                    quotes={s:full['quotes'][s] for s in universe},capture_ids=full['capture_ids'],parent_market_hash=full['record_hash'])
        record['record_hash']=weekly.digest(record)
        base.shared.verified_market(record,universe,base.source.now())
        # Read-only chart consumers can recover the mark used by each fill.
        archive=Path(self.mc['projection']).parent/'market';archive.mkdir(exist_ok=True)
        target=archive/(record['record_hash']+'.json.gz')
        if not target.exists():base.source.atomic(target,record)
        return record

    def managed_policy(self):
        value=self.meta('management_policy')
        if value is None:return None
        row=self.review_row(value['proposal_id'])
        decision=next((d for d in self.approval_decisions() if d['decision_id']==value['decision_id']),None)
        if not row or not decision:raise ValueError('policy_authority_missing')
        expected=weekly.approved_policy(json.loads(row['payload']),decision,value['revision']-1,value['activated_at'])
        if any(value.get(k)!=v for k,v in expected.items() if k!='quantity_ceilings'):
            raise ValueError('approved_policy_changed')
        if not set(value['quantity_ceilings'])<=set(weekly.POOL) or any(weekly.num(v)<0 for v in value['quantity_ceilings'].values()):
            raise ValueError('quantity_ceiling_invalid')
        if 'initial_quantity_ceilings' in expected:
            initial=expected['initial_quantity_ceilings']
            if set(value['quantity_ceilings'])!=set(initial) or any(v>initial[s]+1e-10 for s,v in value['quantity_ceilings'].items()):
                raise ValueError('quantity_ceiling_increased')
        return value

    def review_table(self,proposal_id):
        return 'm1_transition_reviews' if self.db.execute('SELECT 1 FROM m1_transition_reviews WHERE id=?',(proposal_id,)).fetchone() else 'm1_weekly_reviews'

    def review_row(self,proposal_id):
        table=self.review_table(proposal_id)
        return self.db.execute('SELECT * FROM '+table+' WHERE id=?',(proposal_id,)).fetchone()

    def transition_proposal(self):
        from . import v13_m1_transition as transition
        path=safe_file(self.mc['transition_proposal'],0)
        if base.shared.sha(path)!=self.mc['transition_sha256']:raise ValueError('transition_file_changed')
        value=json.loads(path.read_text());transition.validate(value)
        if value['account']!=self.account:raise ValueError('transition_account')
        return value

    def baseline(self,control,now):
        policy=self.managed_policy()
        if not policy:return super().baseline(control,now)
        if now>weekly.when(policy['valid_until']):raise ValueError('weekly_review_expired_new_risk_suspended')
        if policy.get('cadence')=='ORIGINAL_PUBLISHED_BASELINE':
            base.Runner.baseline(self,control,now)
            control['managed_reference']=dict(policy['short_caps'])
            return
        science=self.science()
        selected=policy['selected']
        reference=weekly.weights(science,selected,now.isoformat())
        control.update(baseline_day=science['day'],baseline_targets={s:reference.get(s,0.) for s in self.universe},
                       managed_reference=dict(policy['short_caps']),proposal_id=policy['proposal_id'])

    def funding(self,state,record):
        # A retired, flat asset with no quote must not stop protective action
        # on the held basket. Its accounting stays in the same state/history.
        subset=copy.deepcopy(state)
        subset['positions']={s:v for s,v in subset['positions'].items() if s in record['quotes']}
        end=record['observed_at_end'];endms=int(weekly.when(end).timestamp()*1000)
        for s,pos in subset['positions'].items():
            if pos['quantity']!=0:continue
            cursor=pos['funding_cursor'];q=record['quotes'][s];points=q['funding'];interval=q['funding_interval_ms']
            fresh=(type(interval) is int and 0<interval<=86400000 and points and points[-1]['timestamp_ms']<=endms<points[-1]['timestamp_ms']+interval)
            traded=self.db.execute("SELECT 1 FROM orders WHERE symbol=? AND status='filled' AND bar>? LIMIT 1",(s,cursor)).fetchone()
            if fresh and not traded and (weekly.when(end)-weekly.when(cursor)).total_seconds()>interval/1000:
                self.db.execute('INSERT OR IGNORE INTO m1_management_zero_funding VALUES(?,?,?,?)',(s,cursor,end,'ZERO_QUANTITY_NO_FUNDING_OBLIGATION'))
                pos['funding_cursor']=end
        funded=super().funding(subset,record)
        result=copy.deepcopy(state);result['positions'].update(funded['positions'])
        return result

    def decode_targets(self,targets):
        policy=self.managed_policy()
        if policy:
            if not isinstance(targets,dict) or not set(targets)<=set(weekly.POOL):raise ValueError('managed_target_universe')
            if policy.get('cadence')=='ORIGINAL_PUBLISHED_BASELINE':
                return {s:base.p.decode_weight(targets[s]) if isinstance(targets.get(s),str) else weekly.num(targets.get(s,0.)) for s in self.universe}
            return {s:weekly.num(targets.get(s,0.)) for s in self.universe}
        return super().decode_targets(targets)

    def approval_decisions(self):
        path=safe_file(self.mc['approvals'],self.mc['approval_uid'])
        db=base.shared.ro(path)
        try:
            if [r[0] for r in db.execute('SELECT account FROM identity')]!=[self.account]:raise ValueError('approval_store_account')
            return [json.loads(r[0]) for r in db.execute('SELECT payload FROM decisions WHERE account=? ORDER BY rowid',(self.account,))]
        finally:db.close()

    def management_cycle(self,state,control,record,now,debt):
        policy=self.managed_policy();revision=policy['revision'] if policy else 0
        # Freeze one proposal per calendar week. No silent reselection after
        # looking at the week's subsequent prices or after a rejection.
        label=weekly.week(now.isoformat())
        if self.mc.get('transition_proposal'):
            proposal=self.transition_proposal()
            if not self.db.execute('SELECT 1 FROM m1_weekly_reviews WHERE id=?',(proposal['parent_proposal_id'],)).fetchone():
                raise ValueError('transition_parent_absent')
            self.db.execute('INSERT OR IGNORE INTO m1_transition_reviews VALUES(?,?,?,\'PROPOSED\',NULL)',(proposal['proposal_id'],proposal['week'],base.shared.dump(proposal)))
        elif not self.db.execute('SELECT 1 FROM m1_weekly_reviews WHERE week=?',(label,)).fetchone():
            try:
                proposal=weekly.proposal(self.science(),self.full_market,account=self.account,revision=revision,
                    previous=policy['selected'] if policy else self.signal_symbols,positions=state['positions'],
                    equity=base.paper.totals(state,require_positive=False)['equity'],at=now.isoformat(),
                    existing_short_caps=policy['short_caps'] if policy else None)
                self.db.execute('INSERT INTO m1_weekly_reviews VALUES(?,?,?,\'PROPOSED\',NULL)',(proposal['proposal_id'],label,base.shared.dump(proposal)))
                self.put('management_input_status',None)
            except (ValueError,KeyError,TypeError,OSError):
                self.put('management_input_status','WAITING_QUALIFIED_WEEKLY_INPUTS')
        for decision in self.approval_decisions():
            if self.db.execute('SELECT 1 FROM m1_management_consumed WHERE id=?',(decision['decision_id'],)).fetchone():continue
            row=self.review_row(decision['proposal_id']);table=self.review_table(decision['proposal_id'])
            if not row:raise ValueError('approval_unknown_proposal')
            if self.mc.get('transition_proposal') and table!='m1_transition_reviews':raise ValueError('legacy_approval_not_transition_authority')
            proposal=json.loads(row['payload']);weekly.verify(decision,'decision_id')
            if decision['action']=='REJECT':
                self.db.execute('UPDATE '+table+' SET status=\'REJECTED\',decision_id=? WHERE id=?',(decision['decision_id'],row['id']))
                self.db.execute('INSERT INTO m1_management_consumed VALUES(?,?)',(decision['decision_id'],base.shared.dump(decision)));continue
            if now>weekly.when(proposal['expires_at']):
                self.db.execute('UPDATE '+table+' SET status=\'EXPIRED\',decision_id=? WHERE id=?',(decision['decision_id'],row['id']))
                self.db.execute('INSERT INTO m1_management_consumed VALUES(?,?)',(decision['decision_id'],base.shared.dump(decision)));continue
            if control['phase']!='NORMAL' or control.get('pending'):
                self.db.execute('UPDATE '+table+' SET status=\'APPROVED_WAITING_NORMAL_PHASE\',decision_id=? WHERE id=?',(decision['decision_id'],row['id']));continue
            next_policy=weekly.approved_policy(proposal,decision,revision,now.isoformat())
            # Missing science/funding/book cannot authorize a new admission.
            if next_policy.get('cadence')=='ORIGINAL_PUBLISHED_BASELINE':
                base.Runner.baseline(self,control,now)
                reference=control['baseline_targets']
            else:reference=weekly.weights(self.science(),next_policy['selected'],now.isoformat())
            new={s for s in weekly.POOL if next_policy['long_caps'][s]>0 or next_policy['short_caps'][s]>0}-set(state['positions'])
            if debt or not new<=set(self.full_market['quotes']):
                self.db.execute('UPDATE '+table+' SET status=\'APPROVED_WAITING_INPUTS\',decision_id=? WHERE id=?',(decision['decision_id'],row['id']));continue
            if next_policy.get('initial_quantity_ceilings') is not None:
                for s,q in next_policy['quantity_ceilings'].items():
                    next_policy['quantity_ceilings'][s]=min(q,max(0.,state['positions'][s]['quantity']))
            for symbol in sorted(new):
                q=self.full_market['quotes'][symbol];at=self.full_market['observed_at_end']
                base.shared.sanity.structure_and_time(symbol,q,self.full_market,now)
                state['positions'][symbol]=dict(base.paper.new_position(),current_price=q['mark_price'],last_mark_at=q['mark_timestamp'],funding_cursor=at,generation=0)
                self.db.execute('INSERT INTO m1_management_admissions VALUES(?,?,?)',(symbol,at,proposal['proposal_id']))
                self.db.execute('INSERT OR IGNORE INTO marks VALUES(?,?,?)',(at,symbol,q['mark_price']))
            self.universe=sorted(set(self.universe)|new);self.extend_parent(state)
            record=self.project_market(self.full_market,self.universe)
            control.update(baseline_targets={s:reference.get(s,0.) for s in self.universe},managed_reference=dict(next_policy['short_caps']),baseline_error=None)
            policy=next_policy;revision=policy['revision'];self.put('management_policy',policy)
            self.event('POLICY_ACTIVATED',dict(policy=policy,decision=decision),policy['proposal_id'])
            self.db.execute('UPDATE '+table+' SET status=\'ACTIVE_REBALANCE_PENDING\',decision_id=? WHERE id=?',(decision['decision_id'],row['id']))
            self.db.execute('INSERT INTO m1_management_consumed VALUES(?,?)',(decision['decision_id'],base.shared.dump(decision)))
        if policy and control['phase']=='NORMAL' and not control.get('pending'):
            closing,_=weekly.targets(state,policy,control['baseline_targets'],record['quotes'],kind='MAINTENANCE_CLOSE')
            if any(abs(closing[s]-state['positions'][s]['quantity'])>record['quotes'][s]['quantity_step']/2 for s in self.universe):
                self.intent(control,'MAINTENANCE_CLOSE',{s:0. for s in self.universe},now,now)
        return state,record

    def pending_targets(self,state,control,record,kind,weights,target):
        policy=self.managed_policy()
        if not policy or kind in {'EXIT','PROTECTIVE_REMAINDER'}:return weights,target
        pending=control.get('pending')
        if pending and pending.get('maintenance_revision')!=policy['revision']:raise ValueError('intent_policy_revision_changed')
        quantity,updated=weekly.targets(state,policy,control['baseline_targets'],record['quotes'],kind=kind,
                                        short_reference=control.get('managed_reference'))
        if kind=='M1_ENTRY':
            for s,pos in state['positions'].items():
                if s not in quantity:continue
                if pos['quantity']<0:quantity[s]=pos['quantity']
        self.put('management_policy',updated)
        return self.weights_from_quantities(state,quantity),quantity

    def execute_pending(self,state,control,record,now,debt):
        pending=copy.deepcopy(control.get('pending'))
        result=super().execute_pending(state,control,record,now,debt)
        policy=self.managed_policy()
        if pending and not control.get('pending') and policy and pending['kind'] in {'DAILY','REENTRY','MAINTENANCE_CLOSE'}:
            action=control['last_action']
            if action.get('entry_block') and pending['kind']!='MAINTENANCE_CLOSE':status='APPROVED_WAITING_RISK'
            elif action.get('notes'):status='PARTIAL_REBALANCE'
            elif pending['kind']=='MAINTENANCE_CLOSE':status='REDUCTIONS_APPLIED_WAITING_DAILY'
            else:status='EXECUTED'
            if action.get('status')=='MISSED':status='APPROVED_WAITING_NEXT_SLOT'
            self.db.execute('UPDATE '+self.review_table(policy['proposal_id'])+' SET status=? WHERE id=?',(status,policy['proposal_id']))
            self.put('management_last_execution',dict(proposal_id=policy['proposal_id'],decision_id=policy['decision_id'],status=status,at=record['observed_at_end'],action=action))
            self.event('REBALANCE_RESULT',dict(status=status,action=action,intent=pending['id']),policy['proposal_id'])
        return result

    def entry_plan(self,state,control):
        if not self.managed_policy():return super().entry_plan(state,control)
        policy=self.managed_policy()
        quantity,_=weekly.targets(state,policy,control['baseline_targets'],self.full_market['quotes'],kind='M1_ENTRY',short_reference=control.get('managed_reference'))
        overlay=[]
        for s,pos in state['positions'].items():
            if s not in quantity:continue
            if pos['quantity']<0:quantity[s]=pos['quantity']
            elif quantity[s]<0 or pos['quantity']>0:overlay.append(s)
        return quantity,overlay

    def has_overlay_budget(self,state,control):
        if not self.managed_policy():return super().has_overlay_budget(state,control)
        return any(s in self.universe and w>0 and abs(control.get('managed_reference',{}).get(s,0.))>0 for s,w in self.managed_policy()['short_caps'].items())

    def publish_management(self):
        rows=[dict(r) for r in self.db.execute('SELECT id,week,status,decision_id,payload FROM m1_weekly_reviews ORDER BY week DESC LIMIT 20')]
        if self.mc.get('transition_proposal'):
            for row in rows:row['status']='ARCHIVED_V1_NOT_APPROVABLE'
            rows=[dict(r) for r in self.db.execute('SELECT id,week,status,decision_id,payload FROM m1_transition_reviews ORDER BY rowid DESC LIMIT 20')]+rows
        latest=rows[0] if rows else None;proposal=json.loads(latest['payload']) if latest else None
        for row in rows:row.pop('payload')
        policy=self.managed_policy();state=json.loads(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        value=dict(scope='M1_WEEKLY_MANAGEMENT_STATUS_V1',account=self.account,generated_at=base.source.now().isoformat(),
                   active=bool(policy),policy=policy,proposal=proposal,reviews=rows,
                   input_status=self.meta('management_input_status'),proposal_status=latest['status'] if latest else 'WAITING_INPUTS',
                   positions=state['positions'],last_action=self.meta('control').get('last_action'),orders_authorized=False)
        value['last_execution']=self.meta('management_last_execution')
        base.source.atomic(self.mc['projection'],value)
        self.publish_new_series()

    def publish_new_series(self):
        bucket=int(base.source.now().timestamp())//300
        if self.meta('management_series_bucket')==bucket:return
        folder=Path(self.mc['projection']).parent/'series';folder.mkdir(exist_ok=True)
        for row in self.db.execute('SELECT symbol,at FROM m1_management_admissions'):
            records=self.db.execute('SELECT bar,price FROM marks WHERE symbol=? AND bar>=? ORDER BY bar DESC LIMIT 20001',(row['symbol'],row['at'])).fetchall()
            data=dict(scope='M1_ADMITTED_SYMBOL_PRICES_V1',account=self.account,symbol=row['symbol'],admitted_at=row['at'],
                      truncated=len(records)>20000,points=[dict(bar=r['bar'],price=r['price']) for r in reversed(records[:20000])])
            data['record_id']=weekly.digest(data)
            base.source.atomic(folder/(row['symbol']+'.json.gz'),data)
        with self.db:self.put('management_series_bucket',bucket)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');args=parser.parse_args()
    config=json.loads(safe_file(args.config,0).read_text())
    if (os.geteuid()!=config['runner_uid'] or config['runner_uid']<=0
        or len({config['runner_uid'],config['management']['capture_uid'],config['management']['approval_uid']})!=3):raise ValueError('runner_identity')
    lock=open(config['db']+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    runner=Runner(config)
    from .v13_m1_paper_view import publish
    try:
        while True:
            try:runner.tick()
            except Exception:
                with runner.db:runner.put('health',dict(status='BLOCKED',checked_at=base.source.now().isoformat(),reason='managed_cycle_failed_no_new_risk'))
            publish(runner);runner.publish_management()
            if args.once:break
            time.sleep(20)
    finally:runner.close()


if __name__=='__main__':main()
