"""Bounded scheduled read checks, using in-memory publication fixtures."""
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('first_slot',Path(__file__).resolve().parents[3]/'scripts/check_fork_discrete_first_slot.py')
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
T=dt.datetime(2032,5,10,0,25,tzinfo=dt.timezone.utc)


class Tests(unittest.TestCase):
    def setUp(self):
        self.g=dict(version='v13-paired-discrete-risk-v3',boundary=T.replace(minute=15).isoformat(),account_ids=dict(FAST='f',HALF='h'))
        self.v=dict(generated_at=T.isoformat(),discrete_revision=dict(self.g,history_preserved=True,legacy=dict(evaluated=13,matched=7),current=dict(evaluated=1,matched=1)),
                    slots=[dict(slot=self.g['boundary'],status='EXECUTED',detail=dict(policy_revision=self.g['version'],risk_gap=.01,risk_matched=True))],
                    funding_debt=None,valuation_gap=None,health=dict(status='OBSERVING'))

    def check(self,at=T):
        raw=json.dumps(self.g).encode();config=dict(grant='g',grant_sha256=hashlib.sha256(raw).hexdigest(),projection='p')
        with patch.object(c,'read',side_effect=lambda path,*args:raw if path=='g' else json.dumps(self.v).encode()):return c.assess(config,at)

    def test_before_slot_waits_without_claiming_success(self):
        at=T.replace(minute=10);self.v['generated_at']=at.isoformat()
        self.assertEqual(self.check(at)['status'],'WAITING_FOR_NATURAL_SLOT')

    def test_fill_and_legitimate_no_fill_can_qualify(self):
        for status in ('EXECUTED','OBSERVED_NO_FILL'):
            self.v['slots'][0]['status']=status
            self.assertEqual(self.check()['status'],'QUALIFIED_NATURAL_SLOT')

    def test_missing_denied_or_legacy_slot_requires_review(self):
        self.v['slots'][0]['status']='DENIED';self.assertEqual(self.check()['status'],'REVIEW_REQUIRED')
        self.v['slots'][0]['status']='EXECUTED';self.v['slots'][0]['detail']['policy_revision']='legacy'
        self.assertEqual(self.check()['status'],'REVIEW_REQUIRED')
        self.v['slots']=[];self.assertEqual(self.check()['status'],'REVIEW_REQUIRED')

    def test_unknown_or_unqualified_risk_never_passes(self):
        for gap,matched in ((None,False),(0.,False),(.02001,True),(float('nan'),True),(True,True)):
            self.v['slots'][0]['detail'].update(risk_gap=gap,risk_matched=matched)
            self.assertEqual(self.check()['status'],'REVIEW_REQUIRED')

    def test_stale_foreign_and_incomplete_publications_require_review(self):
        self.v['generated_at']=(T-dt.timedelta(minutes=10)).isoformat();self.assertEqual(self.check()['status'],'REVIEW_REQUIRED')
        self.v['generated_at']=T.isoformat();self.v['discrete_revision']['account_ids']={};self.assertEqual(self.check()['status'],'REVIEW_REQUIRED')
        self.v['discrete_revision']['account_ids']=self.g['account_ids'];self.v['funding_debt']='missing';self.assertEqual(self.check()['status'],'REVIEW_REQUIRED')


if __name__=='__main__':unittest.main()
