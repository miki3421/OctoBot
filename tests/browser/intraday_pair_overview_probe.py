"""Read-only served overview and explicit browser-only response fault fixtures."""
import argparse
import copy
import json
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

p = argparse.ArgumentParser()
p.add_argument('--evidence', required=True, type=Path)
args = p.parse_args()
args.evidence.mkdir(exist_ok=True)
base = 'http://127.0.0.1:5001'
errors, blocked, checks = [], [], []
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
    ctx = browser.new_context(viewport={'width':1374, 'height':1100})
    def gate(route):
        if route.request.method != 'GET' or not route.request.url.startswith(base+'/'):
            blocked.append(route.request.url); route.abort()
        else:
            route.continue_()
    ctx.route('**/*', gate)
    page = ctx.new_page()
    page.on('pageerror', lambda e:errors.append(str(e)))
    page.add_init_script("""window.canvasColors=[];
        const stroke=CanvasRenderingContext2D.prototype.stroke;
        CanvasRenderingContext2D.prototype.stroke=function(...args){
            window.canvasColors.push(this.strokeStyle);return stroke.apply(this,args);
        };""")
    page.goto(base+'/v13_variants')
    page.wait_for_function("document.querySelectorAll('#cards .card').length===7")
    assert page.locator('#cards [data-account=PAIR_SHORT]').count() == 1
    assert page.locator('#cards [data-account=PAIR_BOTH]').count() == 1
    assert page.locator('#comparison-rows tr').count() == 7
    assert page.locator('#legend .swatch').count() == 7
    assert page.evaluate("window.canvasColors.includes('#f48fb1') && window.canvasColors.includes('#80cbc4')")
    assert page.locator('#equity').get_attribute('aria-label') == 'Equity reale dei conti in USDT virtuali'
    pair = ctx.request.get(base+'/btc_intraday_pair/data').json()
    for key, arm in [('PAIR_SHORT','control-primary'), ('PAIR_BOTH','candidate-primary')]:
        text = page.locator('#cards [data-account='+key+'] .amount').inner_text()
        expected = page.evaluate('(n)=>Number(n).toLocaleString("it-IT",{minimumFractionDigits:2,maximumFractionDigits:2})', pair['arms'][arm]['equity'])
        assert text == expected+' USDT'
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(args.evidence/'overview-seven-desktop.png'), full_page=True)
    checks.append('live: seven cards/table rows/legend items, both new actual USDT curves, exact equity and no desktop overflow')
    for button in ('range-24','range-7','range-all'):
        page.locator('#'+button).click()
        assert page.locator('#'+button).get_attribute('aria-pressed') == 'true'
        assert page.locator('#equity').get_attribute('aria-label') == 'Equity reale dei conti in USDT virtuali'
    checks.append('live: 24-hour, 7-day and full-history filters keep actual USDT units')
    page.locator('#cards [data-account=PAIR_BOTH] a').click()
    page.wait_for_url('**/btc_intraday_pair')
    page.wait_for_function("document.querySelectorAll('#accounts .card').length===2")
    checks.append('live: new account card opens the dedicated paired page')
    page.goto(base+'/v13_variants');page.wait_for_function("document.querySelectorAll('#cards .card').length===7")
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(args.evidence/'overview-seven-mobile.png'), full_page=True)
    checks.append('live: seven cards fit mobile without page overflow')
    page.set_viewport_size({'width':1374,'height':1100})
    # Deliberate fixture outcomes below are never written to any account.
    variants = ctx.request.get(base+'/v13_variants/data').json()
    old = ctx.request.get(base+'/btc_intraday/data').json()
    assert variants['available']
    t = int(time.time()//300)*300000-600000
    fixtures = {'/v13_variants/data':copy.deepcopy(variants), '/btc_intraday/data':copy.deepcopy(old),
                '/btc_intraday_pair/data':copy.deepcopy(pair)}
    d = fixtures['/v13_variants/data']
    d.update(stale=False, fourth_stale=False, funding_debt=None, valuation_gap=None)
    for i, k in enumerate(('ORIGINAL','FAST','HALF','M1')):
        d['variants'][k]['equity_curve'] = [[time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(t/1000)),10000.],
                                           [time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime((t+300000)/1000)),10000.+i+1]]
    o = fixtures['/btc_intraday/data']
    o.update(stale=False, accounting_complete=True)
    o['state']['activation_at'] = (t-300000)*10**6
    o['equity'] = [[t*10**6,10000.,10000.,1],[(t+300000)*10**6,10010.,10010.,1]]
    q = fixtures['/btc_intraday_pair/data']
    q.update(stale=False)
    assert q['t0_ns']/1e6 <= t
    for i, arm in enumerate(('control-primary','candidate-primary')):
        q['arms'][arm].update(complete=True,points=[dict(at_ns=t*10**6,equity=10000.,complete=True),
                            dict(at_ns=(t+300000)*10**6,equity=10020.+i,complete=True)])
    status = {'pair':200}
    def response(route):
        path = route.request.url[len(base):].split('?')[0]
        code = status['pair'] if path == '/btc_intraday_pair/data' else 200
        route.fulfill(status=code, content_type='application/json',body=json.dumps(fixtures[path]))
    for path in fixtures:
        page.route('**'+path, response)
    page.reload();page.wait_for_function("document.querySelectorAll('#cards .card').length===7")
    page.locator('#all').click()
    assert page.locator('#chart-title').inner_text() == 'Rendimento percentuale · tutte le strategie'
    assert 'In attesa' not in page.locator('#chart-title').inner_text()
    assert page.locator('#cards [data-account=PAIR_BOTH]').inner_text().find('+0,21%') >= 0
    box=page.locator('#equity').bounding_box();page.mouse.move(box['x']+box['width']*.8,box['y']+70)
    assert 'LONG + SHORT' in page.locator('#hover').inner_text()
    checks.append('synthetic browser responses: common window uses all seven accounts and hover labels support new accounts')
    for bad in ('missing','stale','funding','identity'):
        saved = copy.deepcopy(fixtures['/btc_intraday_pair/data'])
        status['pair'] = 503 if bad == 'missing' else 200
        if bad == 'stale': fixtures['/btc_intraday_pair/data']['stale'] = True
        if bad == 'funding': fixtures['/btc_intraday_pair/data']['arms']['candidate-primary']['complete'] = False
        if bad == 'identity': fixtures['/btc_intraday_pair/data']['arms']['candidate-primary']['account'] = 'wrong-account'
        page.reload();page.wait_for_function("document.querySelectorAll('#cards .card').length===7")
        assert page.locator('#cards [data-account=BTC] .amount').inner_text() != 'Dati non disponibili'
        if bad in ('missing','identity'):
            assert page.locator('#cards [data-account=PAIR_BOTH] .amount').inner_text() == 'Dati non disponibili'
        page.locator('#all').click()
        assert page.locator('#chart-title').inner_text() == 'In attesa della finestra comune a tutte le strategie'
        page.locator('#history').click()
        assert page.locator('#equity').get_attribute('aria-label') == 'Equity reale dei conti in USDT virtuali'
        fixtures['/btc_intraday_pair/data'] = saved
    status['pair'] = 200
    checks.append('synthetic faults: missing/stale/incomplete-funding/wrong-identity pair never creates a partial common benchmark or zeros')
    # Single-version screens must retain their four-account comparison semantics.
    for path in fixtures: page.unroute('**'+path)
    for variant in ('fast','half','m1'):
        page.goto(base+'/v13_variants/'+variant)
        page.wait_for_function("!document.getElementById('content').classList.contains('hidden')")
        assert page.locator('#cards .card').count() == 1
        assert page.locator('#cards [data-account=PAIR_BOTH]').count() == 0
    checks.append('live: FAST, HALF and M1 detail pages remain separate and usable')
    assert not errors, errors
    assert not blocked, blocked
    report=dict(checks=checks, errors=errors, blocked=blocked)
    (args.evidence/'overview-browser.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps(report,ensure_ascii=False));browser.close()
