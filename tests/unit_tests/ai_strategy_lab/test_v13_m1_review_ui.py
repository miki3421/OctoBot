"""Author checks for the read-only M1 review and inactive target preview."""
import ast
import copy
import datetime as dt
from pathlib import Path
import tempfile
import types
import unittest
import flask
import v13_m1_review_view as view
import v13_m1_maintenance_preview as maintenance

ROOT = Path(__file__).resolve().parents[3]
WEB = ROOT/'packages/tentacles/Services/Interfaces/web_interface'


class ReviewTests(unittest.TestCase):
    def test_real_frozen_review_and_side_reconciliation(self):
        result=view.public_view(now=dt.datetime(2026,10,23,13,tzinfo=dt.timezone.utc))
        self.assertTrue(result['available']);self.assertFalse(result['stale'])
        r=result['review'];self.assertEqual(len(r['m1']['symbols']),18)
        self.assertAlmostEqual(r['m1']['net_since_clone'],43.308226692670274)
        self.assertFalse(result['maintenance_active'])
        self.assertTrue(all(not p['applied'] for p in r['proposals']))

    def test_age_is_not_live_account_freshness(self):
        result=view.public_view(now=dt.datetime(2026,10,25,tzinfo=dt.timezone.utc))
        self.assertTrue(result['available']);self.assertTrue(result['snapshot']);self.assertTrue(result['stale'])
        self.assertFalse(view.public_view(now=dt.datetime(2026,10,22,tzinfo=dt.timezone.utc))['available'])

    def test_tampered_missing_or_replaced_report_has_no_metrics(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'report.json'
            self.assertFalse(view.public_view(p)['available'])
            p.write_bytes(view.REPORT.read_bytes()+b' ')
            before=p.read_bytes();result=view.public_view(p)
            self.assertFalse(result['available']);self.assertNotIn('review',result)
            self.assertEqual(before,p.read_bytes())


class MaintenancePreviewTests(unittest.TestCase):
    def setUp(self):
        self.base={'AAVEUSDT':2.61,'LTCUSDT':8.2,'BTCUSDT':.01}
        self.current=dict(self.base)
        self.caps={'AAVEUSDT':1.30,'LTCUSDT':4.1}
        self.shorts={'AAVEUSDT':2.61,'LTCUSDT':8.2}

    def test_daily_growth_cannot_buy_back_removed_quantity(self):
        base=dict(self.base,AAVEUSDT=10,LTCUSDT=15)
        r=maintenance.preview(base,self.current,self.caps,self.shorts)
        self.assertEqual(r['targets']['AAVEUSDT'],1.3)
        self.assertEqual(r['targets']['LTCUSDT'],4.1)
        self.assertEqual(r['targets']['BTCUSDT'],.01)
        self.assertFalse(r['freed_risk_reallocated']);self.assertFalse(r['execution_authorized'])

    def test_lower_cap_stays_lower_even_if_the_next_signal_recovers(self):
        lower=maintenance.preview(dict(self.base,AAVEUSDT=.8),self.current,self.caps,self.shorts)
        rebound=maintenance.preview(self.base,self.current,lower['next_long_caps'],self.shorts)
        self.assertEqual(rebound['targets']['AAVEUSDT'],.8)
        self.assertEqual(rebound['short_budgets'],self.shorts)

    def test_short_budget_survives_long_reduction_and_reentry_stays_capped(self):
        reduced=dict(self.current,AAVEUSDT=1.3,LTCUSDT=4.1)
        r=maintenance.preview(self.base,reduced,self.caps,self.shorts,'M1_ENTRY')
        self.assertEqual(r['targets'],{k:-v for k,v in self.base.items()})
        returned=maintenance.preview(self.base,r['targets'],r['next_long_caps'],r['short_budgets'],'REENTRY')
        self.assertEqual(returned['targets']['AAVEUSDT'],1.3)
        self.assertEqual(returned['targets']['LTCUSDT'],4.1)
        self.assertTrue(returned['requires_existing_risk_checks'])

    def test_short_budget_cannot_override_deteriorated_causal_baseline(self):
        r=maintenance.preview(dict(self.base,AAVEUSDT=.5),self.current,self.caps,self.shorts,'M1_ENTRY')
        self.assertEqual(r['targets']['AAVEUSDT'],-.5)

    def test_empty_long_target_requires_review_to_reopen(self):
        r=maintenance.preview(dict(self.base,AAVEUSDT=0),self.current,self.caps,self.shorts)
        r=maintenance.preview(self.base,self.current,r['next_long_caps'],self.shorts)
        self.assertEqual(r['targets']['AAVEUSDT'],0)

    def test_inputs_preserved_invalid_values_and_new_symbols_denied(self):
        inputs=[self.base,self.current,self.caps,self.shorts];before=copy.deepcopy(inputs)
        maintenance.preview(*inputs);self.assertEqual(inputs,before)
        for changed in (dict(self.caps,UNKNOWNUSDT=1),dict(self.caps,AAVEUSDT=float('nan')),dict(self.caps,AAVEUSDT=-1)):
            with self.subTest(changed=changed),self.assertRaises(ValueError):maintenance.preview(self.base,self.current,changed,self.shorts)
        with self.assertRaises(ValueError):maintenance.preview(*inputs,phase='FORCE_ORDER')


class RouteTests(unittest.TestCase):
    def setUp(self):
        tree=ast.parse((WEB/'controllers/home.py').read_text())
        register=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='register')
        funcs=[n for n in register.body if isinstance(n,ast.FunctionDef) and n.name in ('v13_m1_review','v13_m1_review_data')]
        self.assertEqual(len(funcs),2)
        for f in funcs:self.assertTrue(any(ast.unparse(d)=='login.login_required_when_activated' for d in f.decorator_list))
        module=ast.Module(body=[ast.FunctionDef(name='register',args=register.args,body=funcs,decorator_list=[])],type_ignores=[]);ast.fix_missing_locations(module)
        self.accepted=True;self.profile='local_ai_trading'
        namespace=dict(flask=flask,models=types.SimpleNamespace(accepted_terms=lambda:self.accepted,get_current_profile=lambda:types.SimpleNamespace(profile_id=self.profile)),login=types.SimpleNamespace(login_required_when_activated=lambda f:f),v13_m1_review_view=view)
        exec(compile(module,str(WEB/'controllers/home.py'),'exec'),namespace)
        app=flask.Flask(__name__,template_folder=str(WEB/'templates'));app.add_url_rule('/terms','terms',lambda:'terms')
        namespace['register'](app);self.client=app.test_client()

    def test_page_data_no_store_and_no_order_surface(self):
        response=self.client.get('/v13_variants/m1/review');self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response.headers['Cache-Control']);self.assertIn('Non applicate',response.text)
        response=self.client.get('/v13_variants/m1/review/data');self.assertTrue(response.json['available'])
        self.assertIn('no-store',response.headers['Cache-Control'])
        for path in ('/v13_variants/m1/review','/v13_variants/m1/review/data'):
            for method in ('post','put','patch','delete'):
                self.assertEqual(getattr(self.client,method)(path).status_code,405)

    def test_profile_and_terms_gates_remain(self):
        self.profile='other';self.assertEqual(self.client.get('/v13_variants/m1/review').status_code,404)
        self.assertEqual(self.client.get('/v13_variants/m1/review/data').status_code,403)
        self.profile='local_ai_trading';self.accepted=False
        self.assertEqual(self.client.get('/v13_variants/m1/review').status_code,302)
        self.assertEqual(self.client.get('/v13_variants/m1/review/data').status_code,403)


if __name__=='__main__':unittest.main()
