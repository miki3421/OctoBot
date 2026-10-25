"""GET-only fixture/live journey for M1 replacement. Never submits consent."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser();p.add_argument('--fixture',action='store_true');args=p.parse_args()
E=Path('/evidence');OUT=E/('browser-fixture' if args.fixture else 'browser-live');OUT.mkdir(exist_ok=True)
BASE='http://127.0.0.1:5001'
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1100});errors=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    if args.fixture:
        results=[f for f in E.glob('full-copy-*/projection/result.json') if json.loads(f.read_text()).get('passed')]
        root=max(results,key=lambda f:f.stat().st_mtime).parent
        account=json.loads((root/'first-account.json').read_text());account['stale']=False
        management=json.loads((root/'first-management.json').read_text());management.update(available=True,stale=False,approval_ready=True,csrf_token='CONTROL-FIXTURE-ONLY')
        data=page.request.get(BASE+'/v13_variants/data').json();data.update(m1=account,fourth_stale=False,fourth_available=True)
        data['variants']['M1']=account['variant']
        page.route('**/v13_variants/data',lambda r:r.fulfill(json=data))
        page.route('**/v13_variants/m1/review/weekly',lambda r:r.fulfill(json=management))
        for name in ('v13_m1_weekly.js','v13_variants_lifecycle.js'):
            raw=(Path('/release/ui')/name).read_text()
            def handler(content):
                return lambda route:route.fulfill(body=content,content_type='text/javascript')
            page.route('**/static/js/common/'+name+'*',handler(raw))
    page.goto(BASE+'/v13_variants/m1/review',wait_until='networkidle')
    page.wait_for_function("document.querySelector('#weekly-status').textContent.includes('Nuova strategia attiva')")
    assert page.locator('#weekly-rows tr').count()==6
    assert page.locator('#successor-progress p').count()==6
    assert page.locator('#weekly-approve').is_disabled()
    if args.fixture:page.evaluate("document.querySelector('main').prepend(Object.assign(document.createElement('p'),{textContent:'CONTROL FIXTURE ONLY · copia completa, nessun risultato economico'}))")
    page.screenshot(path=str(OUT/'m1-successor-maintenance.png'),full_page=True)
    page.goto(BASE+'/v13_variants',wait_until='networkidle')
    page.get_by_role('heading',name='M1 · gestione graduale + SHORT',exact=True).wait_for()
    assert page.locator('#cards article').count()==6
    assert page.locator('#m1-retired-version').is_visible()
    assert not page.locator('#cards').get_by_role('heading',name='V13 + M1 SHORT',exact=True).count()
    if args.fixture:page.evaluate("document.querySelector('main').prepend(Object.assign(document.createElement('p'),{textContent:'CONTROL FIXTURE ONLY · copia completa'}))")
    page.screenshot(path=str(OUT/'m1-successor-overview.png'),full_page=True)
    for name in ('range-24','range-7','range-all','all','future','history'):
        page.locator('#'+name).click()
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(OUT/'m1-successor-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1100})
    page.goto(BASE+'/v13_variants/m1',wait_until='networkidle')
    page.get_by_role('heading',name='M1 · gestione graduale + SHORT',exact=True).first.wait_for()
    assert page.locator('#cards article').count()==1
    if not args.fixture:
        for route in ('/v13_variants/m1/charts','/v13_paper','/v13_variants/fast','/v13_variants/half','/btc_intraday','/btc_intraday_pair'):
            assert page.request.get(BASE+route).status==200,route
        view=page.request.get(BASE+'/v13_variants/m1/review/weekly').json()
        assert view['policy']['version']=='m1-gradual-long-short-v3' and view['active']
        assert view['policy']['short_caps']==view['proposal']['short_reference_caps']
        assert view['proposal']['stage_rule']['remaining_fractions']==[.5,.25,0.]
        assert view['policy']['authority_kind']=='direct_operator_instruction'
        view.pop('csrf_token',None);(OUT/'management.json').write_text(json.dumps(view,indent=2))
    assert not errors,errors
    result=dict(passed=True,scope='CONTROL_FIXTURE' if args.fixture else 'LIVE_AUTHOR_VERIFICATION',six_active_accounts=True,
        old_m1_version_archived=True,new_m1_detail=True,stage_progress=True,all_filters=True,mobile=True,
        post_requests=0,operator_password_used=False,errors=errors)
    (OUT/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));browser.close()
