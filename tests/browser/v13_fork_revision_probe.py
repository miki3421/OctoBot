"""GET-only revision display, with browser-local preview data when requested."""
import argparse
import copy
import datetime as dt
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

parser=argparse.ArgumentParser();parser.add_argument('--evidence',type=Path,required=True)
parser.add_argument('--preview-js',type=Path);args=parser.parse_args();root=args.evidence
errors=[];results=[]
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100})
    page.on('pageerror',lambda error:errors.append(str(error)))
    original=page.request.get('http://localhost:5001/v13_variants/data').json()
    payload=copy.deepcopy(original)
    if args.preview_js:
        payload['discrete_revision']=dict(schema=1,version='v13-paired-discrete-risk-v3',boundary='2026-10-27T00:15:00+00:00',
            state='SCHEDULED',legacy=dict(slots=13,evaluated=13,matched=7),current=dict(slots=0,evaluated=0,matched=0))
        page.route('**/v13_variants/data',lambda route:route.fulfill(json=payload))
        page.route('**/v13_variants_lifecycle.js*',lambda route:route.fulfill(path=str(args.preview_js),content_type='application/javascript'))
    for version in ('','/fast','/half','/original','/m1'):
        page.goto('http://localhost:5001/v13_variants'+version,wait_until='networkidle')
        page.locator('#content').wait_for(state='visible')
        status=page.locator('#status').inner_text()
        if version in ('','/fast','/half'):
            assert 'correzione del rischio v3' in status,status
            assert '7/13' in status and '0/0' in status,status
        else:assert 'correzione del rischio v3' not in status
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        results.append(dict(page=version or '/comparison',status=status))
        if not version:
            for button in ('range-24','range-7','range-all'):page.locator('#'+button).click()
            page.screenshot(path=str(root/'revision-desktop.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.goto('http://localhost:5001/v13_variants',wait_until='networkidle')
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
    page.screenshot(path=str(root/'revision-mobile.png'),full_page=True)
    if args.preview_js:
        latest=next(s for s in payload['slots'] if s['status']=='EXECUTED')
        latest['status']='OBSERVED_NO_FILL';latest['detail'].update(risk_gap=None,risk_matched=False)
        page.reload(wait_until='networkidle');assert 'scarto non verificabile' in page.locator('#status').inner_text()
        latest['detail'].update(risk_gap=.01,risk_matched=True)
        page.reload(wait_until='networkidle');assert 'rischio effettivo non allineato' not in page.locator('#status').inner_text()
        payload['discrete_revision']={'schema':1,'version':'v13-paired-discrete-risk-v3'}
        page.reload(wait_until='networkidle');assert page.locator('#cards .card').count()>=6
    browser.close()
assert not errors,errors
(root/'browser-revision.json').write_text(json.dumps(dict(pages=results,javascript_errors=errors,read_only=True),indent=2))
print('Revision pages, ranges and mobile layout passed; no JavaScript errors')
