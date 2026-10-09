"""Synthetic, non-forward monitor tests. Card work-card-2869a16f-5dae-4811-aeea-53a74e4449a2."""
import copy
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
def load(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
m=load('monitor_test','octobot/ai_strategy_lab/v13_btc_forward_monitor.py')
p=load('producer_monitor_test','octobot/ai_strategy_lab/v13_btc_research_v2.py')
T=dt.datetime(2026,10,1,0,10,tzinfo=m.UTC)
END=T+179*m.DAY

class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.db=self.root/'slots.sqlite';self.cfg=self.root/'approval.json'
        self.cfg.write_text(json.dumps({'status':'APPROVED_FORWARD_RESEARCH_ONLY','start_slot_utc':T.isoformat(),'end_slot_utc':END.isoformat(),'journal_path':str(self.db)}));self.cfg.chmod(0o440)
        self.system=lambda:({k:{'ActiveState':'active','UnitFileState':'enabled','NextElapseUSecRealtime':'','LastTriggerUSec':''} for k in m.ROLES},{k:{'ActiveState':'inactive','Result':'success','ExecMainStatus':'0','ExecMainExitTimestamp':''} for k in m.ROLES},True)
    def tearDown(self):self.tmp.cleanup()
    def read(self,now):return m.build(self.cfg,self.db,now,system=self.system)
    def missing(self):
        d,source=p.missing(T.isoformat(),(T+dt.timedelta(minutes=11)).isoformat(),'0'*64,'SOURCE_FAILURE')
        p.append_slot(self.db,d,source,(T+dt.timedelta(minutes=11)).isoformat())
        os.chown(self.db,30041,30041);self.db.chmod(0o640)
    def save(self,v):
        f=self.root/'status.json';m.publish(f,v);os.chown(f,30041,30041);return f
    def test_future_window_never_creates_journal_or_slots(self):
        v=self.read(T-m.DAY);self.assertEqual(v['phase'],'waiting');self.assertEqual(v['recorded'],0);self.assertEqual(v['expected'],0);self.assertEqual(len(v['calendar']),180);self.assertEqual({r['state'] for r in v['calendar']},{'PENDING'});self.assertFalse(self.db.exists());self.assertTrue(v['performance_sealed'])
    def test_expired_absent_journal_is_overdue_not_healthy(self):
        v=self.read(T+dt.timedelta(minutes=11));self.assertEqual(v['overdue'],1);self.assertEqual(v['phase'],'attention');self.assertEqual(v['calendar'][0]['state'],'UNRECORDED')
    def test_missing_and_readonly_no_outcome_payload(self):
        self.missing();before=self.db.read_bytes();v=self.read(T+dt.timedelta(minutes=12));self.assertEqual(v['counts']['MISSING'],1);self.assertEqual(v['calendar'][0]['reason'],'SOURCE_FAILURE');self.assertEqual(v['integrity'],'ok');self.assertEqual(self.db.read_bytes(),before);self.assertNotIn('causal_bars',json.dumps(v));self.assertNotIn('outcome_json',json.dumps(v))
    def test_reject_tamper_and_ownership(self):
        self.missing();self.db.chmod(0o666);self.assertEqual(self.read(T+m.DAY)['integrity'],'unavailable');self.db.chmod(0o640)
        with sqlite3.connect(self.db) as db:db.execute('DROP TRIGGER slots_no_update');db.execute("UPDATE slots SET record_hash=?",('bad',))
        v=self.read(T+m.DAY);self.assertIn('JOURNAL_UNAVAILABLE',v['issues']);self.assertEqual(v['phase'],'attention')
    def test_stale_snapshot_cannot_appear_current(self):
        v=self.read(T-m.DAY);f=self.save(v);out=m.public_view(f,now=T-m.DAY+dt.timedelta(minutes=4));self.assertEqual(out['phase'],'attention');self.assertIn('MONITOR_STALE',out['issues'])
    def test_future_or_extra_keys_snapshot_rejected(self):
        v=self.read(T-m.DAY);f=self.save(v)
        with self.assertRaisesRegex(ValueError,'snapshot_future'):m.public_view(f,now=T-2*m.DAY)
        for mutate in [lambda v:v.update({'returns':99}),lambda v:v['calendar'][0].update({'performance':99}),lambda v:v.update({'recorded':-1}),lambda v:v['counts'].update({'LONG':99})]:
            changed=copy.deepcopy(v);mutate(changed);f=self.save(changed)
            with self.assertRaisesRegex(ValueError,'snapshot_schema_invalid'):m.public_view(f,now=T-m.DAY)
    def test_unapproved_or_unsynchronized_is_not_healthy(self):
        self.cfg.chmod(0o640);c=json.loads(self.cfg.read_text());c['status']='NOT_APPROVED';self.cfg.write_text(json.dumps(c))
        with self.assertRaisesRegex(ValueError,'approval_missing'):self.read(T-m.DAY)
        c['status']='APPROVED_FORWARD_RESEARCH_ONLY';self.cfg.write_text(json.dumps(c));old=self.system;self.system=lambda:(*old()[:2],False);self.assertIn('CLOCK_UNSYNCHRONIZED',self.read(T-m.DAY)['issues'])
    def test_directional_and_no_proposal_counts_without_outcome_values(self):
        for i,slope in enumerate((1,-1,0)):
            slot=T+i*m.DAY;last=slot.replace(minute=0)-m.DAY
            rows=[[int((last-dt.timedelta(days=120-j)).timestamp()*1000),200+slope*j,200+slope*j,200+slope*j,200+slope*j,1,1] for j in range(121)]
            receipt=p.capture(self.root/'archive',json.dumps({'code':'200000','data':rows}).encode(),(slot+dt.timedelta(minutes=1)).isoformat(),request_url='SYNTHETIC_NON_FORWARD')
            decision,source=p.produce(self.root/'archive',receipt,slot.isoformat(),(slot+dt.timedelta(minutes=2)).isoformat(),'0'*64)
            p.append_slot(self.db,decision,source,(slot+dt.timedelta(minutes=2)).isoformat())
        with sqlite3.connect(self.db) as db:db.execute('INSERT INTO outcomes VALUES(?,?,?)',(T.isoformat(),'PRIVATE_OUTCOME_PAYLOAD_MUST_NOT_BE_READ','0'*64))
        os.chown(self.db,30041,30041);self.db.chmod(0o640)
        out=self.read(T+3*m.DAY);self.assertEqual(out['counts'],{'LONG':1,'SHORT':1,'NO_PROPOSAL':1,'MISSING':0});self.assertEqual(out['mature_outcomes'],1);self.assertNotIn('PRIVATE_OUTCOME',json.dumps(out));self.assertEqual(out['integrity'],'ok')
    def test_review_is_only_after_full_window(self):
        v=self.read(T+180*m.DAY);self.assertTrue(v['performance_sealed']);v=self.read(T+181*m.DAY);self.assertFalse(v['performance_sealed']);self.assertEqual(v['review_at'],(T+181*m.DAY).isoformat())
    def test_snapshot_symlink_rejected(self):
        f=self.save(self.read(T-m.DAY));link=self.root/'link';link.symlink_to(f)
        with self.assertRaises(OSError):m.public_view(link,now=T-m.DAY)

if __name__=='__main__':unittest.main()
