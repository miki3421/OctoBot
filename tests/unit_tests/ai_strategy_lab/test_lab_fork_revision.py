"""Version-aware passive checks, no live journal or SMTP writes."""
import copy
import datetime as dt
import unittest
import test_lab_fork_monitor as fixture


class Tests(unittest.TestCase):
    def setUp(self):
        self.f=fixture.ForkMonitorTests(methodName='runTest');self.f.setUp()
        self.v=self.f.value
        self.v['receipt']['economic_t0']=(fixture.NOW-dt.timedelta(days=2)).isoformat()
        self.v['receipt']['first_decision_slot']=(fixture.NOW-dt.timedelta(days=1)).replace(hour=0,minute=15).isoformat()
        self.v['discrete_revision']=dict(schema=1,version='v13-paired-discrete-risk-v3',boundary=fixture.NOW.replace(hour=0,minute=15).isoformat(),
            account_ids=self.v['receipt']['account_ids'],history_preserved=True,no_real_orders=True,state='OBSERVING',
            legacy=dict(slots=1,evaluated=1,matched=0),current=dict(slots=1,evaluated=1,matched=1))
        self.v['slots'][0]['detail'].update(policy_revision='v13-paired-discrete-risk-v3',risk_matched=True,discrete_status='MATCHED')

    def tearDown(self):self.f.tearDown()
    def read(self):self.f.write();return self.f.read()

    def test_new_revision_exposes_distinct_denominators(self):
        result=self.read();self.assertEqual(result['issues'],[])
        self.assertEqual(result['discrete_revision']['legacy']['matched'],0)
        self.assertEqual(result['discrete_revision']['current']['matched'],1)

    def test_scheduled_boundary_keeps_prior_mismatch_visible(self):
        self.v['discrete_revision'].update(boundary=(fixture.NOW+dt.timedelta(days=1)).replace(hour=0,minute=15).isoformat(),state='SCHEDULED')
        self.v['slots'][0]['detail']=dict(risk_gap=.04,risk_matched=False)
        self.assertIn('FORK_RISK_MISMATCH',self.read()['issues'])

    def test_unqualified_zero_gap_and_unknown_gap_are_not_passes(self):
        detail=self.v['slots'][0]['detail'];detail.update(risk_matched=False,discrete_status='UNQUALIFIED_PARTIAL_EXECUTION')
        self.assertIn('FORK_RISK_MISMATCH',self.read()['issues'])
        detail.update(risk_gap=None,discrete_status='UNQUALIFIED_FUNDING');self.v['funding_debt']='missing'
        result=self.read();self.assertIn('FORK_RISK_MISMATCH',result['issues']);self.assertIn('FORK_FUNDING_INCOMPLETE',result['issues'])
        self.assertIsNone(result['risk_gap']);self.assertFalse(result['risk_qualified'])

    def test_legacy_execution_cannot_claim_new_revision(self):
        self.v['slots'][0]['detail'].pop('policy_revision')
        self.assertEqual(self.read()['issues'],['FORK_PROJECTION_UNAVAILABLE'])

    def test_invalid_identity_or_impossible_counts_never_report_healthy(self):
        old=copy.deepcopy(self.v['discrete_revision'])
        for mode in ('version','boundary','counts','history'):
            self.v['discrete_revision']=copy.deepcopy(old)
            if mode=='version':self.v['discrete_revision']['version']='foreign'
            if mode=='boundary':self.v['discrete_revision']['boundary']='2032-05-10T00:16:00+00:00'
            if mode=='counts':self.v['discrete_revision']['current']['matched']=2
            if mode=='history':self.v['discrete_revision']['history_preserved']=False
            with self.subTest(mode=mode):self.assertEqual(self.read()['issues'],['FORK_PROJECTION_UNAVAILABLE'])


if __name__=='__main__':unittest.main()
