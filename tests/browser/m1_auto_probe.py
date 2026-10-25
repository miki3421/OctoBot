"""Read-only desktop/mobile automatic-review journey; no approval POSTs."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

parser=argparse.ArgumentParser();parser.add_argument('--fixture',action='store_true');args=parser.parse_args()
E=Path('/evidence');out=E/('browser-fixture' if args.fixture else 'browser-live');out.mkdir(exist_ok=True)
base='http://127.0.0.1:5001'
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1436,'height':1314});errors=[];posts=[]
    page.on('pageerror',lambda e:errors.append(str(e)))
    page.on('request',lambda r:posts.append(r.url) if r.method!='GET' else None)
    if args.fixture:
        roots=[p.parent for p in E.glob('full-copy-*/projection/result.json') if json.loads(p.read_text()).get('passed')]
        folder=max(roots,key=lambda p:p.stat().st_mtime)
        value=json.loads((folder/'management.json').read_text());value.update(available=True,stale=False,approval_ready=True,csrf_token='CONTROL-FIXTURE-ONLY')
        page.route('**/v13_variants/m1/review/weekly',lambda r:r.fulfill(json=value))
        page.route('**/static/js/common/v13_m1_weekly.js*',lambda r:r.fulfill(body=Path('/release/ui/v13_m1_weekly.js').read_text(),content_type='text/javascript'))
    page.goto(base+'/v13_variants/m1/review',wait_until='networkidle')
    page.locator('#automatic-review').get_by_role('heading',name='Approvazione automatica ponderata · attiva').wait_for()
    assert page.locator('#weekly-approve').is_hidden() and page.locator('#weekly-reject').is_hidden()
    assert 2<=page.locator('#automatic-review table tr').count()<=12
    assert page.locator('#automatic-review').inner_text().find('80/100')>=0
    assert page.locator('#successor-progress p').count()==6
    if args.fixture:page.evaluate("document.querySelector('main').prepend(Object.assign(document.createElement('p'),{textContent:'CONTROL FIXTURE ONLY · verifica del flusso, nessun risultato economico'}))")
    page.screenshot(path=str(out/'m1-auto-desktop.png'),full_page=True)
    page.locator('#automatic-review').screenshot(path=str(out/'m1-auto-panel.png'))
    page.set_viewport_size({'width':390,'height':844})
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(out/'m1-auto-mobile.png'),full_page=True)
    if not args.fixture:
        value=page.request.get(base+'/v13_variants/m1/review/weekly').json();value.pop('csrf_token',None)
        assert value['automatic_review']['enabled'] and value['policy']['authority_kind']=='delegated_automatic_review'
        assert value['policy']['short_caps']==value['proposal']['short_reference_caps']
        (out/'management.json').write_text(json.dumps(value,indent=2))
        for route in ('/v13_variants','/v13_variants/m1','/v13_variants/m1/charts','/v13_paper','/btc_intraday_pair'):
            assert page.request.get(base+route).status==200
    assert not errors,errors
    assert not posts,posts
    result=dict(passed=True,fixture=args.fixture,desktop=True,mobile=True,scoring_visible=True,manual_buttons_hidden=True,post_requests=0,errors=errors)
    (out/'result.json').write_text(json.dumps(result,indent=2));print(json.dumps(result));browser.close()
