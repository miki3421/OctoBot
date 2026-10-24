"""Only target the offline fixture namespace. Never approve a live proposal."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:5103';OUT=Path('/evidence')
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];external=[]
    page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:external.append(r.url) if not r.url.startswith(BASE+'/') else None)
    page.goto(BASE+'/v13_variants/m1/review',wait_until='networkidle');page.wait_for_selector('#weekly-approve:enabled')
    before=page.request.get(BASE+'/v13_variants/m1/review/weekly').json();p=before['proposal']
    assert p['data_mode']=='CONTROL_FIXTURE_ONLY' and p['version']=='m1-long-maintenance-v2','REFUSE live or legacy proposal'
    assert not before['active'];assert page.locator('#weekly-rows tr').count()==2
    assert 'SHORT' in page.locator('#weekly-risk-summary').inner_text()
    page.locator('section[aria-labelledby="weekly-title"]').screenshot(path=str(OUT/'m1-v2-desktop.png'))
    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1');page.screenshot(path=str(OUT/'m1-v2-mobile.png'),full_page=True)
    page.set_viewport_size({'width':1440,'height':1100});page.click('#weekly-approve');assert page.locator('#weekly-short-options input').count()==0
    assert 'solo le riduzioni LONG' in page.locator('#weekly-dialog-title').inner_text()
    body=dict(proposal_id=p['proposal_id'],confirmation=p['proposal_id'],action='APPROVE',exclude_short=[],components=['LONG_MAINTENANCE'],password='fixture-only-v2-approval-password-20261024')
    assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=body).status==403
    headers={'Origin':BASE,'X-CSRFToken':before['csrf_token']}
    assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=dict(body,components=['ADMISSIONS']),headers=headers).status==409
    page.fill('#weekly-password','wrong-fixture-password');page.check('#weekly-ack');page.click('#weekly-submit');page.wait_for_function("document.querySelector('#weekly-decision-message').textContent.includes('non registrata')");assert page.locator('#weekly-password').input_value()==''
    page.fill('#weekly-password',body['password']);page.click('#weekly-submit');page.wait_for_function("!document.querySelector('#weekly-dialog').open")
    page.wait_for_function("document.querySelector('#weekly-execution').textContent.includes('Riduzioni applicate')",timeout=30000)
    after=page.request.get(BASE+'/v13_variants/m1/review/weekly').json();assert after['active'];assert after['policy']['short_caps']==p['short_reference_caps']
    assert after['positions']['AAVEUSDT']['quantity']<=1.30 and after['positions']['DOTUSDT']['quantity']<=146
    for symbol,pos in before['positions'].items():
        if symbol not in p['affected']:assert after['positions'][symbol]['quantity']==pos['quantity']
    headers['X-CSRFToken']=after['csrf_token'];assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=body,headers=headers).status==200
    assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=dict(body,action='REJECT'),headers=headers).status==409
    assert not errors,errors;assert not external,external
    for value in (before,after):value.pop('csrf_token',None)
    (OUT/'browser-v2-result.json').write_text(json.dumps(dict(scope='CONTROL_FIXTURE_ONLY_PRIVATE_COPY',before=before,after=after,errors=errors,external=external,operator_credential_used=False),indent=2)+'\n')
    browser.close();print('PASS: v2 browser, password and component binding, private runner reductions, SHORT preserved, mobile and replay')
