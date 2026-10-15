"""Exercise actual M1 route bodies without starting OctoBot or a collector."""
import ast
from pathlib import Path
import types
import unittest
import flask

ROOT = Path(__file__).resolve().parents[3]
HOME = ROOT / 'packages/tentacles/Services/Interfaces/web_interface/controllers/home.py'


class RouteTests(unittest.TestCase):
    def setUp(self):
        parsed = ast.parse(HOME.read_text())
        register = next(n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name == 'register')
        functions = [n for n in register.body if isinstance(n, ast.FunctionDef) and n.name in {'v13_m1_dashboard', 'v13_m1_data'}]
        self.assertEqual(len(functions), 2)
        for f in functions:
            self.assertTrue(any(ast.unparse(d) == 'login.login_required_when_activated' for d in f.decorator_list))
        isolated = ast.Module(body=[ast.FunctionDef(name='register', args=register.args, body=functions, decorator_list=[])], type_ignores=[])
        ast.fix_missing_locations(isolated)
        self.accepted = True; self.profile = 'local_ai_trading'; self.calls = 0
        def view():
            self.calls += 1
            return dict(available=False, phase='unavailable', counts=None)
        scope = dict(flask=flask, models=types.SimpleNamespace(accepted_terms=lambda:self.accepted,
                     get_current_profile=lambda:types.SimpleNamespace(profile_id=self.profile)),
                     login=types.SimpleNamespace(login_required_when_activated=lambda f:f),
                     v13_m1_monitor=types.SimpleNamespace(public_view=view))
        exec(compile(isolated, str(HOME), 'exec'), scope)
        self.app = flask.Flask('m1-route-test', template_folder=str(HOME.parents[1]/'templates'))
        self.app.add_url_rule('/terms', 'terms', lambda:'terms')
        blueprint = flask.Blueprint('test', __name__); scope['register'](blueprint); self.app.register_blueprint(blueprint)
        self.client = self.app.test_client()

    def test_page_and_projection_no_store(self):
        page = self.client.get('/v13_m1'); self.assertEqual(page.status_code, 200)
        self.assertIn('no-store', page.headers['Cache-Control']); self.assertIn('M1', page.text)
        data = self.client.get('/v13_m1/data'); self.assertEqual(data.status_code, 200)
        self.assertIsNone(data.json['counts']); self.assertIn('no-store', data.headers['Cache-Control'])

    def test_profile_and_terms_gate_both_routes(self):
        self.profile = 'other'; self.assertEqual(self.client.get('/v13_m1').status_code, 404)
        self.assertEqual(self.client.get('/v13_m1/data').status_code, 403)
        self.profile = 'local_ai_trading'; self.accepted = False
        self.assertEqual(self.client.get('/v13_m1').status_code, 302)
        self.assertEqual(self.client.get('/v13_m1/data').status_code, 403); self.assertEqual(self.calls, 0)

    def test_no_mutation_methods(self):
        for route in ('/v13_m1', '/v13_m1/data'):
            for method in ('post', 'put', 'delete'):
                self.assertEqual(getattr(self.client, method)(route).status_code, 405)
        self.assertEqual(self.calls, 0)


if __name__ == '__main__': unittest.main()
