"""Actual route/CSRF code and isolated approval authentication; all synthetic."""
import ast
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import tempfile
import types
import unittest
import flask
from octobot.ai_strategy_lab import v13_m1_approval_broker as broker
from octobot.ai_strategy_lab import v13_m1_management_web as web
from tests.unit_tests.ai_strategy_lab.test_v13_m1_weekly import fixed_proposal

ROOT=Path(__file__).resolve().parents[3]
HOME=ROOT/'packages/tentacles/Services/Interfaces/web_interface/controllers/home.py'


class RouteTests(unittest.TestCase):
    def setUp(self):
        parsed=ast.parse(HOME.read_text());register=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name=='register')
        funcs=[n for n in register.body if isinstance(n,ast.FunctionDef) and n.name in ('v13_m1_weekly_data','v13_m1_weekly_decision')]
        self.assertEqual(len(funcs),2)
        for f in funcs:self.assertTrue(any(ast.unparse(d)=='login.login_required_when_activated' for d in f.decorator_list))
        module=ast.Module(body=[ast.FunctionDef(name='register',args=register.args,body=funcs,decorator_list=[])],type_ignores=[]);ast.fix_missing_locations(module)
        self.accepted=True;self.profile='local_ai_trading';self.calls=[]
        def decide(value):
            if value.get('confirmation')!=value.get('proposal_id'):raise ValueError('ack')
            self.calls.append(value);return dict(decision_id='fixture-decision',action=value['action'])
        scope=dict(flask=flask,models=types.SimpleNamespace(accepted_terms=lambda:self.accepted,get_current_profile=lambda:types.SimpleNamespace(profile_id=self.profile)),login=types.SimpleNamespace(login_required_when_activated=lambda f:f),v13_m1_management_web=types.SimpleNamespace(public_view=lambda:dict(available=False,approval_ready=False),decide=decide))
        exec(compile(module,str(HOME),'exec'),scope)
        app=flask.Flask(__name__);app.secret_key='synthetic-csrf-test-only';scope['register'](app);self.client=app.test_client()
        self.body=dict(proposal_id='fixture-id',confirmation='fixture-id',action='APPROVE',exclude_short=[],password='fixture-only-password')

    def token(self):return self.client.get('/v13_variants/m1/review/weekly').json['csrf_token']

    def test_missing_csrf_or_cross_origin_cannot_reach_the_writer(self):
        token=self.token()
        for headers in ({},{'Origin':'http://localhost'},{'Origin':'http://evil.invalid','X-CSRFToken':token}):
            r=self.client.post('/v13_variants/m1/review/decision',json=self.body,headers=headers)
            self.assertEqual(r.status_code,403)
        self.assertEqual(self.calls,[])

    def test_same_origin_session_token_profile_and_explicit_ack(self):
        headers={'Origin':'http://localhost','X-CSRFToken':self.token()}
        r=self.client.post('/v13_variants/m1/review/decision',json=self.body,headers=headers)
        self.assertEqual(r.status_code,200);self.assertTrue(r.json['ok']);self.assertIn('no-store',r.headers['Cache-Control'])
        self.assertNotIn(self.body['password'],r.text)
        bad=dict(self.body,confirmation='different')
        self.assertEqual(self.client.post('/v13_variants/m1/review/decision',json=bad,headers=headers).status_code,409)
        self.assertEqual(len(self.calls),1)

    def test_terms_profile_and_read_only_routes(self):
        headers={'Origin':'http://localhost','X-CSRFToken':self.token()}
        for kind in ('profile','terms'):
            self.profile='other' if kind=='profile' else 'local_ai_trading';self.accepted=kind!='terms'
            self.assertEqual(self.client.get('/v13_variants/m1/review/weekly').status_code,403)
            self.assertEqual(self.client.post('/v13_variants/m1/review/decision',json=self.body,headers=headers).status_code,403)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.client.get('/v13_variants/m1/review/decision').status_code,405)
        self.assertEqual(self.client.post('/v13_variants/m1/review/weekly').status_code,405)

    def test_socket_client_rejects_shape_and_forged_authority_before_io(self):
        for value in ([],{},dict(self.body,approved=True),dict(self.body,confirmation='wrong')):
            with self.subTest(value=value),self.assertRaises(ValueError):web.decide(value)


class BrokerTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.password='synthetic-approval-password'
        self.proposal=fixed_proposal(at=dt.datetime.now(dt.timezone.utc))
        p=self.root/'projection.json';p.write_text(json.dumps(dict(account='fixture-m1',proposal=self.proposal)))
        salt=b'synthetic-verifier-salt';v=dict(algorithm='scrypt-v1',salt=salt.hex(),scrypt=hashlib.scrypt(self.password.encode(),salt=salt,n=16384,r=8,p=1,dklen=32).hex())
        f=self.root/'verifier.json';f.write_text(json.dumps(v));f.chmod(0o600)
        self.broker=broker.Broker(dict(database=str(self.root/'approvals.sqlite'),account='fixture-m1',projection=str(p),runner_uid=os.geteuid(),web_peer_uids=[os.geteuid()],approval_uid=os.geteuid(),verifier=str(f)))
        self.request=dict(operation='decision',proposal_id=self.proposal['proposal_id'],action='APPROVE',exclude_short=[],password=self.password)
    def tearDown(self):self.broker.store.close();self.tmp.cleanup()

    def test_peer_password_and_proposal_identity_are_all_required(self):
        with self.assertRaises(ValueError):self.broker.handle(self.request,99999)
        with self.assertRaises(ValueError):self.broker.handle(dict(self.request,password='wrong-password'),os.geteuid())
        with self.assertRaises(ValueError):self.broker.handle(dict(self.request,proposal_id='different'),os.geteuid())
        self.assertEqual(self.broker.store.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],0)
        d=self.broker.handle(self.request,os.geteuid());self.assertEqual(d['proposal_id'],self.proposal['proposal_id'])
        self.assertNotIn('password',d)

    def test_unconfigured_authentication_is_explicitly_unavailable(self):
        (self.root/'verifier.json').unlink()
        status=self.broker.handle(dict(operation='status'),os.geteuid())
        self.assertFalse(status['authentication_configured'])
        with self.assertRaises(OSError):self.broker.handle(self.request,os.geteuid())
        self.assertEqual(self.broker.store.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],0)

    def test_malformed_requests_do_not_crash_or_record_decisions(self):
        with self.assertRaises(ValueError):self.broker.handle([],os.geteuid())
        self.assertEqual(self.broker.store.db.execute('SELECT COUNT(*) FROM decisions').fetchone()[0],0)


if __name__=='__main__':unittest.main()
