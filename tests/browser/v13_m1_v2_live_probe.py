"""Real UI acceptance checks without any valid operator credential or consent."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:5001';OUT=Path('/evidence')
EXPECTED='1772f2efa446fa66888a35b803ffc234fa46e667a86ae9714ce0d49e5fffe6c0'
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:external.append(r.url) if not r.url.startswith(BASE+'/') else None)
    page.goto(BASE+'/v13_variants/m1/review',wait_until='networkidle');page.wait_for_selector('#weekly-approve:enabled')
    before=page.request.get(BASE+'/v13_variants/m1/review/weekly').json();p=before['proposal']
    assert p['proposal_id']==EXPECTED and p['version']=='m1-long-maintenance-v2'
    assert p['data_mode']=='PUBLIC_CAPTURE_RESEARCH_ONLY' and before['policy'] is None and not before['active']
    assert before['approval_ready'] and not before['stale'] and before['proposal_status']=='PROPOSED'
    assert abs(sum(p['short_caps'].values())-.25545833343071755)<1e-10
    assert p['short_caps']==p['short_reference_caps']
    assert page.locator('#weekly-rows tr').count()==2
    page.locator('section[aria-labelledby="weekly-title"]').screenshot(path=str(OUT/'v2-live-desktop.png'))
    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(OUT/'v2-live-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1100});page.click('#weekly-approve')
    assert page.locator('#weekly-short-options input').count()==0
    body=dict(proposal_id=EXPECTED,confirmation=EXPECTED,action='APPROVE',exclude_short=[],components=['LONG_MAINTENANCE'],password='invalid-live-v2-probe-never-operator-credential')
    assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=body).status==403
    assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=body,headers={'Origin':'https://untrusted.invalid','X-CSRFToken':before['csrf_token']}).status==403
    page.check('#weekly-ack');page.fill('#weekly-password',body['password']);page.click('#weekly-submit')
    page.wait_for_function("document.querySelector('#weekly-decision-message').textContent.includes('non registrata')")
    assert page.locator('#weekly-password').input_value()=='';page.click('#weekly-cancel')
    after=page.request.get(BASE+'/v13_variants/m1/review/weekly').json()
    assert after['proposal']['proposal_id']==EXPECTED and after['proposal_status']=='PROPOSED' and after['policy'] is None and not after['active']
    for route in ('/v13_variants','/v13_variants/m1','/v13_variants/m1/charts','/v13_paper','/btc_intraday','/btc_intraday_pair'):
        assert page.request.get(BASE+route).status==200,route
    assert not errors,errors;assert not external,external
    for value in (before,after):value.pop('csrf_token',None)
    (OUT/'live-v2-browser.json').write_text(json.dumps(dict(scope='LIVE_AUTHOR_VERIFICATION_NO_OPERATOR_ACCEPTANCE',before=before,after=after,invalid_password_denied=True,csrf_origin_denied=True,operator_credential_used=False,rebalance_approved=False,errors=errors,external=external),indent=2)+'\n')
    browser.close();print('PASS: live v2, separate SHORT capacity, password denial, mobile and six routes; no rebalance approval')
