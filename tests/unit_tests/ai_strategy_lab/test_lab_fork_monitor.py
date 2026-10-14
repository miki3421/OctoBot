"""Fault, timing and SMTP tests. Never send synthetic alerts to a real inbox."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[3]
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
monitor=module('monitor','scripts/lab_resource_monitor.py')
mail=module('mail','scripts/lab_mail_alerts.py')
NOW=dt.datetime(2032,5,10,1,tzinfo=dt.timezone.utc)

class ForkMonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'projection.json'
        self.config=dict(path=str(self.path),heartbeat_warn_after_seconds=180,valuation_warn_after_seconds=420)
        self.value=dict(available=True,schema=1,generated_at=NOW.isoformat(),health=dict(checked_at=NOW.isoformat(),status='OBSERVING'),
            receipt=dict(parent_snapshot_sha256='a'*64,scope='RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK',economic_t0=(NOW-dt.timedelta(days=1)).isoformat(),first_decision_slot=NOW.replace(hour=0,minute=15).isoformat(),end_exclusive=(NOW+dt.timedelta(days=90)).isoformat(),account_ids={}),
            baseline=dict(equity=10000.,pnl=0.),funding_debt=None,valuation_gap=None,incomplete_funding_observations=1,variants={},
            slots=[dict(slot=NOW.replace(hour=0,minute=15).isoformat(),status='EXECUTED',detail=dict(risk_gap=0.))])
        for arm in ['FAST','HALF']:
            account='v13-risk-matched-clone-v2-'+arm.lower()+'-'+'a'*12
            self.value['receipt']['account_ids'][arm]=account
            self.value['variants'][arm]=dict(account_id=account,observed_at=(NOW-dt.timedelta(seconds=299)).isoformat(),
                metrics=dict(equity=9995.,pnl=-5.,realized_pnl=10.,unrealized_pnl=-14.,fees=2.,funding=1.),positions=[dict(symbol='BTCUSDT',net=-5.)])
        self.write()
    def tearDown(self):self.tmp.cleanup()
    def write(self):
        self.path.write_text(json.dumps(self.value));os.chown(self.path,30934,-1);self.path.chmod(0o640)
    def read(self,now=NOW):return monitor.read_forks(self.config,now.timestamp())
    def sample(self,forks):return dict(boot_id='1',uptime_seconds=100,memory=dict(total_bytes=100,available_bytes=50,swap_total_bytes=0,swap_free_bytes=0),swap_pages={},disks={},collectors={},containers=[],forks=forks)
    def test_five_minute_cadence_and_recovered_history_are_quiet(self):
        r=self.read();self.assertEqual(r['status'],'healthy');self.assertEqual(r['issues'],[])
        self.assertEqual(r['historical_incomplete_funding_observations'],1)
        self.assertEqual(set(r['accounts']),{'FAST','HALF'})
        for arm in self.value['variants']:self.value['variants'][arm]['observed_at']=(NOW-dt.timedelta(seconds=420)).isoformat()
        self.write();self.assertFalse(self.read()['issues'])
    def test_stale_heartbeat_and_individual_stale_account(self):
        self.value['health']['checked_at']=(NOW-dt.timedelta(seconds=181)).isoformat();self.write()
        self.assertIn('FORK_PROJECTION_STALE',self.read()['issues'])
        self.value['health']['checked_at']=NOW.isoformat();self.value['variants']['FAST']['observed_at']=(NOW-dt.timedelta(seconds=421)).isoformat();self.write()
        self.assertEqual(self.read()['issues'],['FORK_VALUATION_STALE:FAST'])
    def test_blocked_runner_current_debt_and_mark_gap_alert(self):
        self.value['health']['status']='BLOCKED';self.value['funding_debt']='missing';self.value['valuation_gap']={'at':'unknown'};self.write()
        alerts=self.read()['issues'];self.assertIn('FORK_RUNNER_BLOCKED',alerts);self.assertIn('FORK_FUNDING_INCOMPLETE',alerts);self.assertIn('FORK_VALUATION_GAP',alerts)
    def test_accounting_inconsistency_nonfinite_or_symbol_duplicate(self):
        for kind in ['total','attribution','negative_fee','nan','duplicate']:
            old=copy.deepcopy(self.value);a=self.value['variants']['FAST']
            if kind=='total':a['metrics']['equity']+=10
            if kind=='attribution':a['positions'][0]['net']=0
            if kind=='negative_fee':a['metrics']['fees']=-1
            if kind=='nan':a['metrics']['pnl']=float('nan')
            if kind=='duplicate':a['positions']*=2
            self.write()
            self.assertIn('FORK_ACCOUNTING_INVALID:FAST',self.read()['issues'],kind)
            self.value=old
    def test_missing_malformed_or_wrong_identity_is_not_healthy(self):
        old=copy.deepcopy(self.value)
        for kind in ['scope','account','future','timezone','schema','missing_arm']:
            self.value=copy.deepcopy(old)
            if kind=='scope':self.value['receipt']['scope']='LIVE'
            if kind=='account':self.value['variants']['FAST']['account_id']=self.value['variants']['HALF']['account_id']
            if kind=='future':self.value['generated_at']=(NOW+dt.timedelta(seconds=1)).isoformat()
            if kind=='timezone':self.value['health']['checked_at']='2032-05-10T01:00:00'
            if kind=='schema':self.value['schema']=2
            if kind=='missing_arm':del self.value['variants']['HALF']
            self.write();self.assertEqual(self.read()['issues'],['FORK_PROJECTION_UNAVAILABLE'],kind)
        self.path.unlink();self.assertEqual(self.read()['issues'],['FORK_PROJECTION_UNAVAILABLE']);self.assertFalse(self.path.exists())
    def test_custody_and_symlink(self):
        self.path.chmod(0o666);self.assertEqual(self.read()['status'],'unavailable')
        self.path.chmod(0o640);target=self.path.with_suffix('.backup');self.path.rename(target);self.path.symlink_to(target)
        self.assertEqual(self.read()['status'],'unavailable')
    def test_daily_slot_deadline_no_early_alarm_and_missing_after_window(self):
        self.value['slots']=[];before=NOW.replace(hour=0,minute=16,second=59)
        self.value['generated_at']=before.isoformat();self.value['health']['checked_at']=before.isoformat()
        for arm in self.value['variants']:self.value['variants'][arm]['observed_at']=before.isoformat()
        self.write();self.assertFalse(self.read(before)['issues'])
        later=before+dt.timedelta(seconds=2);self.assertIn('FORK_DECISION_MISSING',self.read(later)['issues'])
    def test_missed_denied_no_fill_and_risk_mismatch(self):
        for status,expected in [('MISSED','FORK_DECISION_MISSED'),('DENIED','FORK_DECISION_DENIED'),('OBSERVED_NO_FILL',None)]:
            self.value['slots'][0]['status']=status;self.write();self.assertEqual(self.read()['issues'],[expected] if expected else [])
        self.value['slots'][0]['detail']['risk_gap']=.0201;self.write();self.assertIn('FORK_RISK_MISMATCH',self.read()['issues'])
        self.value['slots'][0]['detail']['risk_gap']=.02;self.write();self.assertFalse(self.read()['issues'])
    def test_end_of_experiment_does_not_alert_normal_valuation_stoppage(self):
        self.value['receipt']['end_exclusive']=(NOW-dt.timedelta(seconds=10)).isoformat();self.value['health']['status']='COMPLETED_AWAITING_REVIEW'
        for arm in self.value['variants']:self.value['variants'][arm]['observed_at']=(NOW-dt.timedelta(hours=1)).isoformat()
        self.write();self.assertEqual(self.read()['issues'],[])
    def test_monitor_to_notifier_alert_and_recovery_are_persistent(self):
        self.value['funding_debt']='missing';self.write();sample=monitor.assess(self.sample(self.read()));path=Path(self.tmp.name)/'status.json'
        sample.update(scope='PASSIVE_LAB_TELEMETRY_ONLY',observed_at=NOW.isoformat());path.write_text(json.dumps(sample))
        alerts=mail.read_alerts(path,NOW.timestamp());self.assertEqual(alerts,['FORK_FUNDING_INCOMPLETE'])
        with sqlite3.connect(':memory:') as db:
            sent=[];send=lambda *v:sent.append(v)
            self.assertEqual(mail.notify(db,alerts,10000,send),'PROBLEMA');self.assertEqual(mail.notify(db,alerts,10300,send),'DEDUPLICATO')
            self.assertEqual(mail.notify(db,alerts,96400,send),'PROMEMORIA');self.assertEqual(mail.notify(db,[],96700,send),'RECUPERO');self.assertEqual(mail.notify(db,[],97000,send),'DEDUPLICATO');self.assertEqual(len(sent),3)
    def test_new_alerts_render_through_mock_smtp_and_remain_deduplicated(self):
        keys=[k for k in mail.LABELS if k.startswith('FORK_')]
        config=dict(SMTP_HOST='smtp.example.test',SMTP_PORT='587',SMTP_USERNAME='sender@example.test',SMTP_PASSWORD='test',SMTP_FROM='sender@example.test',SMTP_TO='user@example.test')
        with patch.object(mail.smtplib,'SMTP') as factory:
            smtp=factory.return_value.__enter__.return_value;smtp.send_message.return_value={}
            mail.deliver(config,'PROBLEMA',keys,10000)
            message=smtp.send_message.call_args.args[0];self.assertIn('[Trading AI Lab]',message['Subject']);self.assertIn('FAST/HALF',message.get_content());self.assertIn('funding',message.get_content());self.assertNotIn('test',message.get_content());self.assertTrue(smtp.starttls.call_args.kwargs['context'].check_hostname)
    def test_existing_resource_alerts_and_raw_failure_rules_preserved(self):
        s=self.sample(self.read());s['memory']['available_bytes']=1;s['container_error']='timeout'
        r=monitor.assess(s);self.assertIn('MEMORY_AVAILABLE_BELOW_10_PERCENT',r['notification_alerts']);self.assertNotIn('CONTAINER_STATE_UNAVAILABLE',r['notification_alerts'])

if __name__=='__main__':unittest.main()
