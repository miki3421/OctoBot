import copy
import datetime as dt
import json
import os
from pathlib import Path
import tempfile
import unittest
from octobot.ai_strategy_lab import v13_original_structural_view as V

T=dt.datetime(2026,10,27,12,tzinfo=dt.timezone.utc)


class StructuralViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=Path(self.tmp.name)/'view.json'
        self.data=dict(variants=dict(ORIGINAL=dict(account_id='v13-paper-v2',metrics=dict(equity=9700.),label='Originale')))
        self.value=dict(scope='ORIGINAL_STRUCTURAL_SUCCESSOR_PROJECTION',schema=1,account='v13-paper-v2',
            generated_at=T.isoformat(),real_orders_authorized=False,label='M1 strutturale · ex Originale',
            boundary=dict(at=T.isoformat(),metrics=dict(equity=9720.),order_count=262))
        self.write()
    def tearDown(self):self.tmp.cleanup()
    def write(self):
        if self.path.exists():self.path.unlink()
        self.path.write_text(json.dumps(self.value));self.path.chmod(0o640);os.chown(self.path,30914,30910)
    def test_missing_projection_preserves_predecessor(self):
        self.assertEqual(V.merge(self.data,self.path.with_name('absent'),T),self.data)
    def test_valid_boundary_keeps_total_equity_and_exposes_new_epoch(self):
        before=copy.deepcopy(self.data);x=V.merge(self.data,self.path,T)
        self.assertEqual(self.data,before);self.assertEqual(x['variants']['ORIGINAL']['metrics']['equity'],9700.)
        self.assertEqual(x['variants']['ORIGINAL']['epoch_change'],-20.)
        self.assertEqual(x['variants']['ORIGINAL']['label'],self.value['label'])
    def test_stale_future_or_wrong_scope_is_flagged(self):
        for mutation in ['stale','future','scope']:
            self.value['generated_at']=(T+dt.timedelta(seconds=10) if mutation=='future' else T-dt.timedelta(seconds=181)).isoformat()
            if mutation=='scope':self.value['scope']='OTHER';self.value['generated_at']=T.isoformat()
            self.write();result=V.merge(self.data,self.path,T)
            self.assertTrue(result['original_successor_unverified']);self.assertEqual(result['variants']['ORIGINAL']['label'],'Originale')
    def test_wrong_account_or_owner_is_flagged(self):
        self.value['account']='OTHER';self.write();self.assertTrue(V.merge(self.data,self.path,T)['original_successor_unverified'])
        self.value['account']='v13-paper-v2';self.write();os.chown(self.path,0,0)
        self.assertTrue(V.merge(self.data,self.path,T)['original_successor_unverified'])
    def test_symlink_cannot_supply_authoritative_successor(self):
        link=self.path.with_name('link');link.symlink_to(self.path)
        self.assertTrue(V.merge(self.data,link,T)['original_successor_unverified'])


if __name__=='__main__':unittest.main()
