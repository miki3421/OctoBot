"""M1 live and clearly labelled browser fixtures. No journal modifications."""
import copy
import datetime as dt
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = 'http://127.0.0.1:5001'
OUT = Path('/evidence')
errors = []; external = []
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror', lambda e:errors.append(str(e)))
    page.on('request', lambda r: external.append(r.url) if not r.url.startswith(BASE) else None)
    response = page.goto(BASE+'/v13_m1', wait_until='networkidle'); assert response.status == 200
    page.wait_for_function("!document.querySelector('#status').textContent.includes('Caricamento')")
    data = page.request.get(BASE+'/v13_m1/data'); assert data.status == 200
    assert 'no-store' in data.headers['cache-control'] and 'no-store' in response.headers['cache-control']
    live = data.json(); assert live['available'] and not live['stale'] and live['phase'] == 'waiting', live
    assert page.locator('#phase').inner_text() == 'In attesa'
    assert page.locator('#signals-count').inner_text() == '0'
    assert 'Nessuno slot ancora atteso' in page.locator('#coverage').inner_text()
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'m1-live-desktop.png'), full_page=True)
    page.goto(BASE+'/v13_variants', wait_until='networkidle')
    page.locator('a[href="/v13_m1"]').click(); page.wait_for_url(BASE+'/v13_m1')
    page.set_viewport_size({'width':390,'height':844}); page.reload(wait_until='networkidle')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'m1-live-mobile.png'), full_page=True)
    # Future-looking examples are UI fixtures only, never study observations.
    fixture = copy.deepcopy(live); fixture['phase'] = 'collecting'
    t = dt.datetime.fromisoformat(live['activation']['t0']); iso = lambda offset:(t+dt.timedelta(seconds=offset)).isoformat()
    fixture['generated_at'] = iso(24000); fixture['counts']['signals'] = 2
    fixture['counts']['slots']['SCHEDULED'] = 1; fixture['counts']['slots']['COOLDOWN'] = 1
    fixture['counts']['episodes']['CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY'] = 1
    fixture['coverage'] = dict(expected=80, recorded_due=80, valid=80, overdue=0, valid_fraction=1.)
    fixture['last_feature'] = dict(observed_at=iso(300), btc_return_1h=-.012, negative_symbols=14, universe_count=18)
    fixture['last_slot'] = dict(slot=iso(300), status='COOLDOWN', recorded_at=iso(310))
    fixture['signals'] = [dict(slot=iso(300), status='COOLDOWN', recorded_at=iso(310), btc_return_1h=-.012, negative_symbols=14, episode_id=None), dict(slot=iso(0), status='SCHEDULED', recorded_at=iso(10), btc_return_1h=-.02, negative_symbols=15, episode_id='a'*64)]
    fixture['slots'] = [fixture['last_slot']]
    fixture['episodes'] = [dict(id='a'*64, signal_at=iso(0), status='CAPTURE_COMPLETE_AWAITING_OFFLINE_REPLAY', entry_due=iso(300), exit_due=iso(21900), entry_captured_at=iso(320), exit_captured_at=iso(21920))]
    def response_fixture(route):route.fulfill(status=200, content_type='application/json', body=json.dumps(fixture))
    page.route('**/v13_m1/data', response_fixture)
    page.set_viewport_size({'width':1440,'height':1100}); page.reload(wait_until='networkidle')
    assert page.locator('#phase').inner_text() == 'In raccolta'
    assert page.locator('#signals tr').count() == 2 and page.locator('#episodes tr').count() == 1
    assert '14 / 18' in page.locator('#breadth').inner_text()
    assert 'valutazione a fine studio' in page.locator('#episodes').inner_text()
    page.screenshot(path=str(OUT/'FIXTURE-m1-signals-episodes.png'), full_page=True)
    fixture['issues'] = ['COLLECTOR_FAILURE']; fixture['stale'] = True
    page.reload(wait_until='networkidle'); assert 'scaduto' in page.locator('#status').inner_text()
    assert 'fallito' in page.locator('#issues').inner_text()
    fixture['available'] = False
    page.reload(wait_until='networkidle'); assert page.locator('#signals-count').inner_text() == '—'
    assert page.locator('#signals tr').count() == 0 and page.locator('#episodes tr').count() == 0
    assert 'non disponibile' in page.locator('#status').inner_text()
    page.unroute('**/v13_m1/data'); page.reload(wait_until='networkidle')
    page.route('**/v13_m1/data', lambda route:route.abort())
    page.reload(wait_until='networkidle'); assert 'Impossibile aggiornare' in page.locator('#status').inner_text()
    page.unroute('**/v13_m1/data')
    page.set_viewport_size({'width':390,'height':844})
    page.route('**/v13_m1/data', response_fixture); fixture['available'] = True; fixture['issues'] = []; fixture['stale'] = False
    page.reload(wait_until='networkidle'); assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'FIXTURE-m1-mobile-episodes.png'), full_page=True)
    browser.close()
assert not errors, errors
assert not external, external
(OUT/'browser-results.json').write_text(json.dumps(dict(live_phase=live['phase'], live_available=True, live_counts=live['counts'], desktop_mobile_pass=True, fixture_only_cases=['collecting','signals','episodes','stale','unavailable','network_failure'], javascript_errors=errors, external_requests=external, no_store=True), indent=2))
print('M1 live and fixture browser checks passed; no study writes.')
