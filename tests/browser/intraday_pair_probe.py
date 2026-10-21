"""Read-only localhost acceptance, plus explicit browser-response fixtures."""
import argparse
import copy
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

p = argparse.ArgumentParser()
p.add_argument('--source', type=Path, required=True)
p.add_argument('--evidence', type=Path, required=True)
p.add_argument('--candidate-fixture', type=Path)
args = p.parse_args()
root = args.source/'packages/tentacles/Services/Interfaces/web_interface'
base = 'http://127.0.0.1:5001'
errors, blocked = [], []
args.evidence.mkdir(exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
    ctx = browser.new_context(viewport={'width':1498, 'height':1100})
    def gate(route):
        req = route.request
        if req.method != 'GET' or not req.url.startswith(base+'/'):
            blocked.append(req.url); route.abort(); return
        path = req.url[len(base):].split('?')[0]
        if args.candidate_fixture and path == '/btc_intraday_pair':
            html = (root/'templates/btc_intraday_pair.html').read_text().replace(
                '{% include "components/lab_sidebar.html" %}',
                (root/'templates/components/lab_sidebar.html').read_text())
            route.fulfill(status=200, content_type='text/html', body=html)
        elif args.candidate_fixture and path == '/btc_intraday_pair/data':
            route.fulfill(status=200, content_type='application/json', body=args.candidate_fixture.read_text())
        elif args.candidate_fixture and path == '/static/js/common/btc_intraday_pair.js':
            route.fulfill(status=200, content_type='application/javascript',
                          body=(root/'static/js/common/btc_intraday_pair.js').read_text())
        else:
            route.continue_()
    ctx.route('**/*', gate)
    page = ctx.new_page(); page.on('pageerror', lambda e: errors.append(str(e)))
    response = page.goto(base+'/btc_intraday_pair'); assert response.status == 200
    page.wait_for_function("!document.getElementById('content').classList.contains('hidden')")
    assert page.locator('#accounts .card').count() == 2
    assert page.locator('#lab-sidebar [aria-current=page]').get_attribute('href') == '/btc_intraday_pair'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(args.evidence/'pair-desktop.png'), full_page=True)
    if args.candidate_fixture:
        value = json.loads(args.candidate_fixture.read_text())
    else:
        api = ctx.request.get(base+'/btc_intraday_pair/data'); assert api.status == 200
        assert 'no-store' in api.headers['cache-control']; value = api.json()
        assert value['active_account'] and value['no_real_orders']
    # A browser-only fixture confirms side/effect labels and error presentation.
    fixture = copy.deepcopy(value)
    fixture['arms']['candidate-primary']['trades'] = [dict(at_ns=fixture['checked_at_ns'],
        quantity=.001, price=100000, fee=.06, realized=0, kind='ENTRY', before=0, after=.001)]
    page.route('**/btc_intraday_pair/data', lambda r:r.fulfill(status=200,
               content_type='application/json', body=json.dumps(fixture)))
    page.reload(); page.wait_for_function("document.getElementById('trades').textContent.includes('apertura LONG')")
    assert 'BUY' in page.locator('#trades').inner_text()
    fixture['stale'] = True
    page.reload(); page.wait_for_function("document.getElementById('pair-status').textContent.includes('non aggiornati')")
    fixture['phase'] = 'BLOCKED'
    page.reload(); page.wait_for_function("document.getElementById('content').classList.contains('hidden')")
    assert 'sospeso' in page.locator('#pair-status').inner_text()
    page.unroute('**/btc_intraday_pair/data'); page.reload()
    page.wait_for_function("!document.getElementById('content').classList.contains('hidden')")
    page.set_viewport_size({'width':390, 'height':844})
    page.wait_for_timeout(250)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(args.evidence/'pair-mobile.png'), full_page=True)
    page.locator('#lab-menu-toggle').click()
    page.get_by_role('link',name='BTC intraday · SHORT / LONG + SHORT',exact=True).click()
    page.wait_for_url('**/btc_intraday_pair')
    assert not errors, errors
    assert not blocked, blocked
    report=dict(mode='synthetic_browser_fixture' if args.candidate_fixture else 'served_live_ui',
                phase=value['phase'], desktop_mobile='PASS', side_effect_and_failure_fixtures='PASS',
                errors=errors, blocked=blocked)
    (args.evidence/'browser.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report)); browser.close()
