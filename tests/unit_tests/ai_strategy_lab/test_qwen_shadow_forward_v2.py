"""Author checks only, work-card-e9bee595-96b1-4f79-ad0a-4b28a1f9a4bc.
All captures, clocks and model responses are synthetic, not forward data.
"""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest import mock
ROOT=Path(__file__).resolve().parents[3]/'octobot/ai_strategy_lab'
def load(name):
    s=importlib.util.spec_from_file_location(name,ROOT/(name+'.py'));m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
c=load('qwen_shadow_custody_v2');p=c.p;e=load('qwen_shadow_evaluate_v2');v=load('qwen_shadow_view');pub=load('qwen_shadow_publish_v2')
class ForwardTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.archive=self.root/'archive';self.archive.mkdir();self.db=self.root/'shadow-forward.sqlite';self.outcomes=self.root/'outcomes.sqlite'
        self.slot='2032-05-10T00:10:00+00:00';self.t=p.utc(self.slot)
        self.props={'model_alias':'moe-private','model_path':'FIXTURE.gguf','model_ftype':'FIXTURE','build_info':'FIXTURE','chat_template':'FIXTURE'}
        model={'model_alias':'moe-private','model_artifact':'FIXTURE.gguf','model_ftype':'FIXTURE','build_info':'FIXTURE','model_sha256':'0'*64,'server_sha256':'0'*64,'template_sha256':hashlib.sha256(b'FIXTURE').hexdigest()}
        self.manifest=p.make_manifest(model,'0'*64,self.slot,'0'*64)
        self.end=int((self.t.replace(minute=0)-c.DAY).timestamp()*1000)
        self.bars=[[self.end-(120-i)*p.DAY_MS,str(10000+i*10)] for i in range(121)]
        self.raw=self.raw_bars(self.bars);self.calls=[]
    def raw_bars(self,bars):return json.dumps({'code':'200000','data':[[t,x,x,x,x,1,1] for t,x in bars]}).encode()
    def clock(self,seconds=120):return lambda:self.t+dt.timedelta(seconds=seconds)
    def reader(self,kind,body=None):
        self.calls.append(kind)
        if kind=='props':return self.props
        if kind=='slots':return [{'is_processing':False}]
        self.assertNotIn('baseline',body['messages'][1]['content'])
        return {'choices':[{'finish_reason':'stop','message':{'content':'{"decision":"LONG","reason_codes":["TREND_UP"]}'}}]}
    def collected(self):return c.collect(self.archive,self.slot,self.manifest,clock=self.clock(60),fetch=lambda url:self.raw)
    def test_live_version_distinct_v1_frozen(self):
        old=load('qwen_btc_shadow_v1');self.assertEqual(hashlib.sha256(Path(old.__file__).read_bytes()).hexdigest(),'cf578264a0e54177527cbe7f37936db78a626d03fadd74d663125b1cf49d61ce')
        with self.assertRaises(ValueError):old.check_manifest(self.manifest)
    def test_future_and_receipt_do_not_change_causal_identity(self):
        source=p.observation(self.bars,self.slot,self.slot,self.manifest)
        self.assertEqual(source,p.observation(self.bars+[[self.end+p.DAY_MS,'999999999']],self.slot,(self.t+dt.timedelta(minutes=2)).isoformat(),self.manifest))
    def test_capture_one_get_reserved_before_network(self):
        receipt=self.collected();self.assertEqual(c.capture(self.archive,self.slot,self.manifest)[0],receipt)
        with self.assertRaises(FileExistsError):c.collect(self.archive,self.slot,self.manifest,clock=self.clock(60),fetch=lambda u:self.fail('repeat GET'))
    def test_failed_capture_no_retry(self):
        with self.assertRaises(OSError):c.collect(self.archive,self.slot,self.manifest,clock=self.clock(60),fetch=mock.Mock(side_effect=OSError('fixture')))
        with self.assertRaises(FileExistsError):self.collected()
    def test_raw_tamper_denied(self):
        self.collected();raw=self.archive/'2032-05-10.raw.json';raw.write_bytes(raw.read_bytes()+b' ')
        with self.assertRaises(ValueError):c.capture(self.archive,self.slot,self.manifest)
        self.assertEqual(c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader)['status'],'SOURCE_MISSING_RECORDED');self.assertEqual(self.calls,[])
    def test_receipt_not_available_before_received(self):
        self.collected();c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(30),reader=self.reader);self.assertEqual(self.calls,[])
    def test_pair_replay_provenance_append_only(self):
        self.collected();result=c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader)
        self.assertEqual(result['decision'],'LONG');self.assertEqual(len(self.calls),3)
        self.assertEqual(c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader)['status'],'REPLAY_NO_INFERENCE');self.assertEqual(len(self.calls),3)
        self.assertEqual(len(c.sources(self.db,self.manifest)[1]),2)
        with sqlite3.connect(self.db) as db:
            for sql in ('DELETE FROM records','UPDATE attempts SET token="x"','DELETE FROM provenance'):
                with self.assertRaises(sqlite3.IntegrityError):db.execute(sql)
    def test_late_decide_no_generation(self):
        self.collected();result=c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(601),reader=self.reader)
        self.assertEqual(self.calls,[]);self.assertEqual(result['status'],'SOURCE_MISSING_RECORDED')
    def test_calendar_and_early_missing_rejected(self):
        for slot in ((self.t-c.DAY).isoformat(),(self.t+180*c.DAY).isoformat()):
            with self.assertRaises(ValueError):p.recover_slot(slot,self.manifest,self.db,self.clock(1000))
        with self.assertRaises(ValueError):p.run_input(self.bars,self.slot,self.slot,self.manifest,self.db,self.reader,self.clock(-1))
    def test_restart_closes_without_regeneration(self):
        source=p.observation(self.bars,self.slot,self.slot,self.manifest);con=p.connect(self.db,self.manifest)
        con.execute('INSERT INTO attempts VALUES(?,?,?,?)',(self.slot,p.canonical(source).decode(),'fixture',self.slot));p.add_record(con,source,'baseline',p.baseline(source),self.slot);con.commit();con.close()
        self.assertEqual(p.recover_slot(self.slot,self.manifest,self.db,self.clock(601))['status'],'RECOVERED_MISSING');self.assertEqual(self.calls,[])
    def test_busy_model_missing(self):
        self.collected()
        def reader(kind,body=None):return [{'is_processing':True}] if kind=='slots' else self.reader(kind,body)
        c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=reader)
        self.assertNotIn('completion',self.calls);self.assertEqual(p.inspect_journal(self.db)[1]['result']['reason_codes'],['MODEL_BUSY'])
    def test_storage_failure_before_inference(self):
        self.collected()
        with mock.patch.object(p,'connect',side_effect=sqlite3.OperationalError('fixture')):
            with self.assertRaises(sqlite3.OperationalError):c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader)
        self.assertEqual(self.calls,[])
    def test_outcome_maturity_and_next_capture_only(self):
        self.collected();c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader)
        with self.assertRaises(ValueError):c.mature(self.archive,self.db,self.outcomes,self.slot,self.manifest,clock=self.clock())
        tomorrow=self.t+c.DAY;bars=self.bars[1:]+[[self.end+p.DAY_MS,'11300']]
        c.collect(self.archive,tomorrow.isoformat(),self.manifest,clock=lambda:tomorrow+dt.timedelta(seconds=60),fetch=lambda u:self.raw_bars(bars))
        self.assertEqual(c.mature(self.archive,self.db,self.outcomes,self.slot,self.manifest,clock=lambda:tomorrow+dt.timedelta(minutes=12))['status'],'AVAILABLE')
        with sqlite3.connect(self.outcomes) as db:
            row=p.strict_json(db.execute('SELECT payload FROM outcomes').fetchone()[0]);self.assertEqual(row['origin_close'],'11200');self.assertEqual(row['next_close'],'11300')
            with self.assertRaises(sqlite3.IntegrityError):db.execute('DELETE FROM outcomes')
        self.assertEqual(c.mature(self.archive,self.db,self.outcomes,self.slot,self.manifest,clock=lambda:tomorrow+dt.timedelta(minutes=12))['status'],'OUTCOME_REPLAY_PRESERVED')
    def test_missing_outcome_cannot_be_replaced(self):
        self.collected();c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader);tomorrow=self.t+c.DAY
        self.assertEqual(c.mature(self.archive,self.db,self.outcomes,self.slot,self.manifest,clock=lambda:tomorrow+dt.timedelta(minutes=12))['status'],'MISSING')
        c.collect(self.archive,tomorrow.isoformat(),self.manifest,clock=lambda:tomorrow+dt.timedelta(seconds=60),fetch=lambda u:self.raw_bars(self.bars[1:]+[[self.end+p.DAY_MS,'11300']]))
        self.assertEqual(c.mature(self.archive,self.db,self.outcomes,self.slot,self.manifest,clock=lambda:tomorrow+dt.timedelta(minutes=13))['status'],'OUTCOME_REPLAY_PRESERVED')
    def test_seal_before_io(self):
        with self.assertRaisesRegex(ValueError,'PERFORMANCE_SEALED'):e.evaluate(self.manifest,'absent','absent','absent',clock=self.clock())
    def test_bootstrap_and_percentile_definition(self):
        lo,hi=e.bootstrap([.01]*180);self.assertAlmostEqual(lo,.01);self.assertAlmostEqual(hi,.01)
        with self.assertRaises(ValueError):e.bootstrap([None]*180)
        with self.assertRaises(ValueError):e.bootstrap([.1]*179)
        self.assertEqual(e.percentile([0,10],.25),2.5)
    def test_root_approval_missing_denies(self):
        with self.assertRaises(FileNotFoundError):c.approved('decide',self.manifest,path=self.root/'no-activation.json')
    def test_closed_public_schema(self):
        status=v.prepared(self.manifest,'0'*64,self.slot);self.assertEqual(status['phase'],'PREPARED');self.assertFalse(status['scheduler_active'])
        with self.assertRaises(ValueError):v.validate({**status,'hit_rate':.9},now=self.t)
        altered=json.loads(json.dumps(status));altered['calendar'][0]['qwen']['reason_codes']=['<script>']
        with self.assertRaises(ValueError):v.validate(altered,now=self.t)
        with self.assertRaises(ValueError):v.validate({**status,'performance_sealed':False},now=self.t)
    def test_projection_excludes_outcome_and_performance(self):
        self.collected();c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader)
        result=pub.build(self.manifest,'0'*64,self.db,self.outcomes,clock=self.clock(),scheduler_active=True);self.assertEqual(result['recorded_pairs'],1)
        for field in ('origin_close','next_close','score','paired_mean','hit_rate','causal_bars'):self.assertNotIn(field,json.dumps(result))
        self.assertEqual(v.validate(result,now=self.t+dt.timedelta(minutes=30))['issues'],['MONITOR_STALE'])
    def test_calendar_all_missing_is_insufficient_not_zero(self):
        review=p.utc(self.manifest['review_at'])
        for i in range(180):
            slot=(self.t+i*c.DAY).isoformat()
            p.record_missing(slot,self.manifest,self.db,'SLOT_DEADLINE_MISSED',lambda:review)
            c.mature(self.archive,self.db,self.outcomes,slot,self.manifest,clock=lambda:review)
        result=e.evaluate(self.manifest,self.db,self.outcomes,self.archive,clock=lambda:review)
        self.assertEqual(result['review_status'],'INSUFFICIENT');self.assertEqual(result['joint_valid_mature'],0)
        self.assertIsNone(result['paired_mean']);self.assertIsNone(result['paired_ci_95'])
        self.assertEqual(result['coverage_denominator'],180);self.assertIsNone(result['arms']['qwen']['directional_hit_rate'])
    def test_storage_failure_after_inference_recovers_missing(self):
        self.collected();add=p.add_record
        def fail_qwen(con,source,arm,*args,**kwargs):
            if arm=='qwen':raise sqlite3.OperationalError('fixture after inference')
            return add(con,source,arm,*args,**kwargs)
        with mock.patch.object(p,'add_record',side_effect=fail_qwen):
            with self.assertRaises(sqlite3.OperationalError):c.decide(self.archive,self.db,self.slot,self.manifest,clock=self.clock(),reader=self.reader)
        self.assertEqual(len(self.calls),3)
        p.recover_slot(self.slot,self.manifest,self.db,self.clock(601))
        self.assertEqual(len(self.calls),3);self.assertEqual(p.inspect_journal(self.db)[1]['result']['decision'],'MISSING')
    def test_full_calendar_score_evaluator_matches_constant_fixture(self):
        # This constructs fixture stores directly; no market fetch or model request.
        review=p.utc(self.manifest['review_at']);origins={}
        con=p.connect(self.db,self.manifest);out=c.outcome_connect(self.outcomes,self.manifest)
        previous='0'*64
        for i in range(181):
            slot=(self.t+i*c.DAY).isoformat();end=self.end+i*p.DAY_MS
            # Constant exponential slope keeps the baseline LONG. Qwen SHORT is deliberately worse.
            import math
            bars=[[end-(120-j)*p.DAY_MS,str(10000*math.exp((i+j-120)*.001))] for j in range(121)]
            started=(p.utc(slot)+dt.timedelta(seconds=60)).isoformat();raw=self.raw_bars(bars)
            receipt={'schema_version':2,'scope':p.SCOPE,'lineage':self.manifest['lineage'],'slot_utc':slot,'started_at':started,'received_at':started,'request_url':c.query_url(slot,started),'raw_sha256':hashlib.sha256(raw).hexdigest()}
            day=p.utc(slot).date().isoformat();c.new_file(self.archive/(day+'.raw.json'),raw);c.new_file(self.archive/(day+'.receipt.json'),p.canonical(receipt))
            if i<180:
                source=p.observation(bars,slot,started,self.manifest);origins[slot]=source
                con.execute('INSERT INTO attempts VALUES(?,?,?,?)',(slot,p.canonical(source).decode(),'fixture',started));con.execute('INSERT INTO provenance VALUES(?,?)',(slot,p.canonical(receipt).decode()))
                for arm,result in [('baseline',p.baseline(source)),('qwen',{'decision':'SHORT','reason_codes':['TREND_DOWN']})]:p.add_record(con,source,arm,result,started)
            if i:
                prior=(self.t+(i-1)*c.DAY).isoformat();source=origins[prior]
                value={'slot_utc':prior,'lineage':self.manifest['lineage'],'observation_id':source['observation_id'],'status':'AVAILABLE','origin_close':source['causal_bars'][-1][1],'next_close':bars[-1][1],'receipt':receipt,'recorded_at':started}
                digest=p.sha({'payload':value,'previous_hash':previous});out.execute('INSERT INTO outcomes VALUES(?,?,?,?)',(prior,p.canonical(value).decode(),previous,digest));previous=digest
        con.commit();con.close();out.commit();out.close()
        result=e.evaluate(self.manifest,self.db,self.outcomes,self.archive,clock=lambda:review)
        self.assertEqual(result['joint_valid_mature'],180);self.assertAlmostEqual(result['paired_mean'],-.002)
        self.assertAlmostEqual(result['paired_ci_95'][0],-.002);self.assertEqual(result['review_status'],'INSUFFICIENT')
        self.assertEqual(result['arms']['baseline']['directional_hit_rate'],1);self.assertEqual(result['arms']['qwen']['directional_hit_rate'],0)
        self.assertEqual(result['calendar_blocks'][2]['joint'],60)
        # Missing regime must stay insufficient even with full coverage.
        self.assertEqual(result['arms']['baseline']['SHORT'],0)
    def test_foreign_database_unmodified(self):
        with sqlite3.connect(self.db) as db:db.execute('CREATE TABLE ledger(x)')
        before=self.db.read_bytes()
        with self.assertRaises(ValueError):p.connect(self.db,self.manifest)
        self.assertEqual(before,self.db.read_bytes())
if __name__=='__main__':unittest.main()
