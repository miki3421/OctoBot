"""GET-only current M1 metrics journey; injected failures are UI fixtures."""
import copy
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE=os.environ.get('LAB_REVIEW_BASE','http://127.0.0.1:5103')
OUT=Path(os.environ.get('LAB_REVIEW_EVIDENCE','/evidence/browser-preview'))
OUT.mkdir(exist_ok=True)
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1436,'height':1314})
    errors=[];writes=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:writes.append(request.url) if request.method not in ('GET','HEAD') else None)
    assert page.goto(BASE+'/v13_variants/m1/review',wait_until='networkidle').status==200
    page.locator('#review-content').wait_for(state='visible')
    payload=page.request.get(BASE+'/v13_variants/m1/review/data').json()
    assert payload['available'] and payload['review']['schema']==2
    data=payload['review'];symbols=data['m1']['symbols']
    assert page.locator('#review-window').input_value()=='since_version'
    assert page.locator('#review-symbols tr').count()==len(symbols)
    assert '23 ottobre' not in page.locator('#analysis-title').inner_text()
    assert '5 minuti' in page.locator('#review-status').inner_text() or payload['stale']
    def money(text):return float(text.replace('USDT','').replace('.','').replace(',','.').replace('\u2212','-').strip())
    for period in ('since_version','24h','48h','since_clone','legacy'):
        page.locator('#review-window').select_option(period)
        total=data['m1']['totals'][period]
        if total['available']:
            assert abs(money(page.locator('#m1-result').inner_text())-total['net'])<=.0051
        assert page.locator('#review-symbols tr').count()==len(symbols)
    page.locator('#review-window').select_option('since_version')
    page.get_by_role('button',name='Dettagli BTCUSDT',exact=True).click()
    assert page.locator('#review-symbol').input_value()=='BTCUSDT'
    assert page.locator('#review-detail tr').count()==13
    assert 'SHORT' in page.locator('#review-symbols').inner_text()
    assert 'Approvazione automatica ponderata' in page.locator('#automatic-review').inner_text()
    assert page.locator('#weekly-approve').is_hidden()
    archived=page.request.get(BASE+'/v13_variants/m1/review/data?archive=1').json()
    assert archived['snapshot'] and archived['report_id']=='3d7bdbfb0ba5d60ddca6ccf4457a04e27b61eea705b75ec17501e3a5af8fb2cd'
    page.locator('#analysis-title').scroll_into_view_if_needed()
    page.screenshot(path=str(OUT/'metrics-viewport.png'))
    page.screenshot(path=str(OUT/'desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(OUT/'mobile.png'),full_page=True)
    stale=copy.deepcopy(payload);stale.update(stale=True,refresh_failed=True)
    page.route('**/review/data',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(stale)))
    page.reload(wait_until='networkidle');assert 'aggiornamento fallito' in page.locator('#review-status').inner_text()
    page.unroute('**/review/data')
    missing=copy.deepcopy(payload);window=missing['review']['m1']['symbols']['BTCUSDT']['windows']['since_version']
    window.update(available=False,sides=None,net=None)
    missing['review']['m1']['totals']['since_version'].update(available=False,net=None,long_net=None,short_net=None,unavailable_symbols=['BTCUSDT'])
    page.route('**/review/data',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(missing)))
    page.reload(wait_until='networkidle');assert 'Totale non disponibile' in page.locator('#reconciliation-status').inner_text()
    assert '—' in page.locator('#m1-result').inner_text()
    page.unroute('**/review/data')
    page.route('**/review/data',lambda route:route.fulfill(status=200,content_type='application/json',body='{"available":false}'))
    page.reload(wait_until='networkidle');assert page.locator('#review-content').is_hidden()
    assert page.locator('#weekly-body').is_visible()
    assert not errors,errors
    assert not writes,writes
    result=dict(passed=True,symbols=len(symbols),five_windows=True,default_current_epoch=True,
                net_matches_api=True,side_detail=True,archive_retained=True,desktop_mobile=True,
                fixture_only=['refresh_failure','missing_boundary','unavailable_projection'],
                no_writes=True,javascript_errors=errors)
    (OUT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
    browser.close()
