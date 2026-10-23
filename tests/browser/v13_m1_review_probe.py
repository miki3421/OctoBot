"""Read-only preview/live UI E2E; response failures injected in browser only.

Card work-card-9fbd0d4b-97f1-4e64-b762-e7611ec6c28e.
"""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE=os.environ.get('LAB_REVIEW_BASE','http://127.0.0.1:5102')
OUT=Path(os.environ.get('LAB_REVIEW_EVIDENCE','/evidence'))
errors=[];external=[];mutations=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:external.append(r.url) if not r.url.startswith(BASE) else None)
    page.on('request',lambda r:mutations.append(r.method) if r.method not in ('GET','HEAD') else None)
    response=page.goto(BASE+'/v13_variants/m1/review',wait_until='networkidle')
    assert response.status==200 and 'no-store' in response.headers['cache-control']
    page.locator('#review-content').wait_for(state='visible')
    assert page.locator('#review-symbols tr').count()==18
    assert page.locator('#review-proposals article').count()==2
    assert 'Non applicate' in page.locator('#proposals-title').locator('..').inner_text()
    assert page.locator('.lab-nav-link[aria-current="page"]').inner_text()=='M1 · metriche e proposte'
    assert '+43,31' in page.locator('#m1-result').inner_text()
    assert '435,64' in page.locator('#proposal-total').inner_text()
    assert 'fotografia' in page.locator('#review-period').inner_text()
    api=page.request.get(BASE+'/v13_variants/m1/review/data')
    assert api.status==200 and api.json()['available'] and not api.json()['maintenance_active']
    assert 'no-store' in api.headers['cache-control']
    js=page.locator('script[src*="v13_m1_review.js"]').get_attribute('src')
    asset=page.request.get(BASE+js);assert asset.status==200 and 'javascript' in asset.headers['content-type']
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'m1-review-desktop.png'),full_page=True)
    for window in ('48h','24h','since_clone'):
        page.locator('#review-window').select_option(window)
        assert page.locator('#review-symbols tr').count()==18
    page.get_by_role('button',name='Dettagli DOTUSDT',exact=True).click()
    assert page.locator('#review-symbol').input_value()=='DOTUSDT'
    assert '+2,44' in page.locator('#review-detail tr').first.inner_text()
    assert '-4,16' in page.locator('#review-detail tr').first.inner_text()
    assert page.locator('#review-detail tr').count()==13
    assert 'Preparazione' in page.locator('#integration-title').locator('..').inner_text()
    for method in ('post','put','patch','delete'):
        assert getattr(page.request,method)(BASE+'/v13_variants/m1/review/data').status==405
    page.goto(BASE+'/v13_variants',wait_until='networkidle')
    assert page.locator('nav[aria-label="Versioni V13"] a[href="/v13_variants/m1/review"]').count()==1
    page.locator('nav[aria-label="Versioni V13"] a[href="/v13_variants/m1/review"]').click()
    page.locator('#review-content').wait_for(state='visible')
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.locator('#lab-menu-toggle').click()
    assert page.locator('#lab-menu-toggle').get_attribute('aria-expanded')=='true'
    page.keyboard.press('Escape')
    assert page.locator('#lab-menu-toggle').get_attribute('aria-expanded')=='false'
    page.screenshot(path=str(OUT/'m1-review-mobile.png'),full_page=True)
    fixture=api.json();fixture['stale']=True
    page.route('**/v13_variants/m1/review/data',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(fixture)))
    page.reload(wait_until='networkidle');assert 'oltre 24 ore' in page.locator('#review-status').inner_text()
    page.unroute('**/v13_variants/m1/review/data')
    page.route('**/v13_variants/m1/review/data',lambda route:route.fulfill(status=200,content_type='application/json',body='{"available":false}'))
    page.reload(wait_until='networkidle');assert page.locator('#review-content').is_hidden()
    assert 'non verificabile' in page.locator('#review-status').inner_text()
    browser.close()
assert not errors,errors
assert not external,external
assert not mutations,mutations
result=dict(symbols=18,proposals=2,three_windows=True,side_detail=True,snapshot_label=True,
            original_reference=True,desktop_mobile=True,no_store=True,sidebar_and_comparison_links=True,
            mutation_methods_denied=True,fixture_only=['stale_notice','unavailable_report_hidden'],
            browser_mutations=mutations,javascript_errors=errors,external_requests=external,
            scope='READ_ONLY_UI_AUTHOR_CHECKS')
(OUT/'browser-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
