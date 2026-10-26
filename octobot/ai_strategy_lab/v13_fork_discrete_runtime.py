"""Future-bound discrete risk revision on the existing research-only pair."""
import argparse
import copy
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import time

from . import v13_fork_runner as f
from . import v13_fork_view as view
from .v13_fork_discrete_core import TickMixin, apply_pair

VERSION='v13-paired-discrete-risk-v3'
SCOPE='RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK'


def root_file(path):
    path=Path(path)
    if path.is_symlink() or not path.is_file() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:
        raise ValueError('root_owned_release_file_required')
    return path


def grant(config):
    c=config['discrete_revision'];path=root_file(c['grant'])
    if f.sha(path)!=c['grant_sha256']:raise ValueError('revision_grant_hash')
    value=f.read(path)
    if (value['schema']!=1 or value['version']!=VERSION or value['scope']!=SCOPE
            or value['operator_action']!='AUTHORIZE_EXISTING_PAIR_DISCRETE_REVISION'
            or value['real_orders_authorized'] is not False
            or value['new_accounts'] is not False):
        raise ValueError('revision_operator_scope')
    boundary=f.p.timestamp(value['boundary'])
    if boundary.utcoffset()!=dt.timedelta() or boundary.time()!=dt.time(0,15):raise ValueError('revision_boundary')
    if f.p.timestamp(value['issued_at'])>=boundary:raise ValueError('revision_grant_calendar')
    for name,expected in value['code_pins'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or f.sha(Path(config['repo'])/name)!=expected:
            raise ValueError('revision_code_changed:'+name)
    return value


class Runner(TickMixin,f.Runner):
    execution_scope=SCOPE

    def __init__(self,config):
        self.authorization=grant(config)
        self.boundary=f.p.timestamp(self.authorization['boundary'])
        path=Path(config['db'])
        if not path.is_file() or path.is_symlink():raise ValueError('existing_pair_required_no_reset')
        connection=sqlite3.connect(path,timeout=1)
        connection.execute('PRAGMA query_only=ON')
        try:
            if connection.execute("SELECT 1 FROM meta WHERE key='offline_discrete_identity'").fetchone():
                raise ValueError('offline_work_ledger_cannot_be_promoted')
            row=connection.execute("SELECT payload FROM meta WHERE key='discrete_revision'").fetchone()
            saved=json.loads(row[0]) if row else None
        finally:connection.close()
        identity=dict(grant_sha256=config['discrete_revision']['grant_sha256'],version=VERSION,
                      boundary=self.boundary.isoformat(),module_sha256=f.sha(__file__))
        if saved and saved['identity']!=identity:raise ValueError('revision_continuation_changed')
        if not saved:
            if f.source.now()>=self.boundary:raise ValueError('revision_cannot_start_retroactively')
            if f.sha(path)!=self.authorization['stopped_ledger_sha256']:raise ValueError('revision_handoff_ledger_changed')
        super().__init__(config,initialize=False)
        try:
            if (self.identity!=self.authorization['legacy_identity']
                    or self.receipt['account_ids']!=self.authorization['account_ids']
                    or self.receipt['end_exclusive']!=self.authorization['end_exclusive']
                    or not f.p.timestamp(self.receipt['first_decision_slot'])<self.boundary<f.p.timestamp(self.receipt['end_exclusive'])):
                raise ValueError('revision_legacy_binding')
            if not saved:
                inherited=self.states()
                if f.p.digest(inherited)!=self.authorization['states_sha256']:raise ValueError('revision_full_state_changed')
                saved=dict(identity=identity,installed_at=f.source.now().isoformat(),
                           account_ids=self.receipt['account_ids'],inherited_states_sha256=f.p.digest(inherited),
                           legacy_receipt_sha256=f.p.digest(self.receipt),boundary=self.boundary.isoformat(),
                           legacy_slot_count=self.db.execute('SELECT COUNT(*) FROM slots').fetchone()[0],
                           legacy_fill_count=self.db.execute('SELECT COUNT(*) FROM fills').fetchone()[0])
                with self.db:self.put('discrete_revision',saved)
            self.epoch=saved
        except Exception:
            self.close();raise

    def first_decision_slot(self):
        return f.p.timestamp(self.receipt['first_decision_slot'])

    def prepare_input(self,slot):
        item=super().prepare_input(slot)
        expected={'day','targets','prices','proposal_id','snapshot_id'}
        if set(item)!=expected or item['day']!=(slot.date()-dt.timedelta(days=1)).isoformat():
            raise ValueError('revision_real_daily_input_required')
        f.p.require_hash(item['proposal_id']);f.p.require_hash(item['snapshot_id'])
        return item

    def apply_decision(self,*args):
        instant=args[5]
        if instant<self.boundary:return f.apply_pair(*args)
        states,filters,fills,outcome=apply_pair(*args,version=VERSION,scope=SCOPE)
        outcome.update(policy_revision=VERSION,version_boundary=self.boundary.isoformat())
        return states,filters,fills,outcome


def revision_summary(runner):
    legacy=[];current=[]
    for row in runner.db.execute('SELECT slot,status,payload FROM slots ORDER BY slot'):
        detail=json.loads(row['payload']);entry=dict(slot=row['slot'],status=row['status'],detail=detail)
        (legacy if f.p.timestamp(row['slot'])<runner.boundary else current).append(entry)
    def summarize(rows):
        evaluated=[r for r in rows if r['status'] in ('EXECUTED','OBSERVED_NO_FILL')]
        return dict(slots=len(rows),evaluated=len(evaluated),matched=sum(r['detail'].get('risk_matched') is True for r in evaluated),
                    latest_slot=rows[-1]['slot'] if rows else None)
    return dict(schema=1,version=VERSION,boundary=runner.boundary.isoformat(),installed_at=runner.epoch['installed_at'],
                account_ids=runner.receipt['account_ids'],legacy=summarize(legacy),current=summarize(current),
                state='SCHEDULED' if f.source.now()<runner.boundary else ('OBSERVING' if current else 'AWAITING_FIRST_SLOT'),
                no_real_orders=True,history_preserved=True)


def publish(runner):
    class Proxy:
        def __init__(self):self.c=dict(runner.c,output='/tmp/fork-legacy-projection.json')
        def __getattr__(self,name):return getattr(runner,name)
    proxy=Proxy();view.publish(proxy)
    value=f.read(proxy.c['output']);value['discrete_revision']=revision_summary(runner)
    f.source.atomic(runner.c['output'],value)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true')
    args=parser.parse_args();os.umask(0o027);path=root_file(args.config);config=f.read(path)
    if os.geteuid()!=config['runner_uid'] or config['runner_uid']!=30934:raise ValueError('revision_runner_uid')
    lock=open(str(config['db'])+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    runner=Runner(config)
    try:
        while True:
            try:
                if grant(config)!=runner.authorization:raise ValueError('revision_grant_changed')
                runner.tick()
            except Exception as error:
                with runner.db:runner.put('health',dict(status='BLOCKED',checked_at=f.source.now().isoformat(),reason=str(error)))
                print(f.dump(dict(status='BLOCKED',reason=str(error))),flush=True)
            publish(runner)
            if args.once:break
            time.sleep(20)
    finally:runner.close()


if __name__=='__main__':main()
