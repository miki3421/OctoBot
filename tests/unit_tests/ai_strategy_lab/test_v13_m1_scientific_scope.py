"""Scientific receipts retain their full frozen universe after execution shrinks."""
import copy
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from octobot.ai_strategy_lab import v13_m1_managed as managed
from octobot.ai_strategy_lab import v13_m1_weekly as w


class ScientificScopeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
        self.symbols=json.loads(Path('docs/research-protocols/v13-prospective-risk-matched-v2.json').read_text())['universe']
        self.slot=dt.datetime(2026,10,26,0,15,tzinfo=dt.timezone.utc)
        self.runner=managed.Runner.__new__(managed.Runner);self.runner.signal_symbols=list(self.symbols)
        self.runner.universe=self.symbols[:6];self.runner.db=sqlite3.connect(':memory:');self.runner.db.row_factory=sqlite3.Row
        self.runner.db.execute('CREATE TABLE inputs(day TEXT PRIMARY KEY,payload TEXT)')
        source=self.root/'source';(source/'science').mkdir(parents=True);proposals=self.root/'proposals';proposals.mkdir()
        docs=self.root/'docs/contracts';docs.mkdir(parents=True)
        (docs/'v13-research-paper-v1.json').write_text(json.dumps(dict(scientific_lineage_ref='test-lineage')))
        self.runner.c=dict(derivation=dict(repo=str(self.root),source=str(source),proposals=str(proposals),
            uids=dict(producer=0,capture=0),contract_sha256='contract',account='original',epoch='original-epoch'))
        requests=[];day=self.slot.date()-dt.timedelta(days=1)
        for s in self.symbols:
            bars=[]
            for i in range(61):
                ms=int(dt.datetime.combine(day-dt.timedelta(days=60-i),dt.time(),dt.timezone.utc).timestamp()*1000)
                bars.append([ms,'1','1','1',str(100+i),'1',ms+86400000-1])
            raw=json.dumps(bars).encode()
            requests.append(dict(url='https://fapi.binance.com/fapi/v1/klines?symbol='+s+'&interval=1d',raw_hex=raw.hex(),raw_sha256=hashlib.sha256(raw).hexdigest(),received_at=self.slot.isoformat()))
        self.snapshot=dict(day=day.isoformat(),published_at=self.slot.isoformat(),requests=requests)
        self.proposal=dict(day=day.isoformat(),created_at=self.slot.isoformat(),scope=managed.base.source.SCOPE,
            lineage='test-lineage',contract_sha256='contract',account='original',epoch='original-epoch',targets={s:'0.1' for s in self.symbols})
        self.install()

    def install(self):
        self.snapshot['snapshot_id']=w.digest({k:v for k,v in self.snapshot.items() if k!='snapshot_id'})
        self.proposal['snapshot_id']=self.snapshot['snapshot_id'];self.proposal['proposal_id']=w.digest({k:v for k,v in self.proposal.items() if k!='proposal_id'})
        c=self.runner.c['derivation'];Path(c['source'],'science',self.snapshot['snapshot_id']+'.json').write_text(json.dumps(self.snapshot))
        Path(c['proposals'],'latest.json').write_text(json.dumps(self.proposal))

    def tearDown(self):self.runner.db.close();self.tmp.cleanup()

    def prepare(self):
        with patch.object(managed.base.source,'derive',return_value=self.proposal):return self.runner.prepare_input(self.slot)

    def test_eighteen_receipts_are_verified_while_six_execution_symbols_stay_six(self):
        before=list(self.runner.universe);v=self.prepare()
        self.assertEqual(set(v['prices']),set(self.symbols));self.assertTrue(all(len(x)==61 for x in v['prices'].values()))
        self.assertEqual(self.runner.universe,before)

    def test_new_execution_symbol_does_not_expand_original_scientific_scope(self):
        self.runner.universe.append('QNTUSDT');before=list(self.runner.universe)
        v=self.prepare();self.assertNotIn('QNTUSDT',v['prices']);self.assertEqual(self.runner.universe,before)

    def test_tampered_receipt_outside_execution_scope_still_rejected(self):
        self.snapshot['requests'][-1]['raw_sha256']='0'*64;self.install();before=list(self.runner.universe)
        with self.assertRaisesRegex(ValueError,'raw_hash'):self.prepare()
        self.assertEqual(self.runner.universe,before)

    def test_future_snapshot_still_rejected_without_mutating_execution_scope(self):
        self.snapshot['published_at']=(self.slot+dt.timedelta(seconds=1)).isoformat();self.install()
        with self.assertRaisesRegex(ValueError,'daily_cutoff'):self.prepare()
        self.assertEqual(len(self.runner.universe),6)

    def test_incomplete_cached_scientific_scope_is_not_silently_accepted(self):
        v=self.prepare();v['prices'].pop(self.symbols[-1])
        self.runner.db.execute('UPDATE inputs SET payload=?',(json.dumps(v),))
        with self.assertRaisesRegex(ValueError,'scientific_input_scope'):self.prepare()


if __name__=='__main__':unittest.main()
