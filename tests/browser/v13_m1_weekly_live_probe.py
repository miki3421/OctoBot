"""Published weekly M1 journey: read-only plus explicitly invalid credentials.

Never read the operator credential, approve or reject a real proposal.
Card work-card-8f398480-1842-4f8e-88d1-947756d0916c.
"""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:5001';OUT=Path('/evidence')
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox']);page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda r:external.append(r.url) if not r.url.startswith(BASE+'/') else None)
    response=page.goto(BASE+'/v13_variants/m1/review',wait_until='networkidle');assert response.status==200
    page.wait_for_selector('#weekly-approve:enabled');page.wait_for_selector('#review-content:not(.hidden)')
    value=page.request.get(BASE+'/v13_variants/m1/review/weekly').json();assert value['available'] and value['approval_ready'] and not value['stale']
    assert value['proposal']['data_mode']=='PUBLIC_CAPTURE_RESEARCH_ONLY'
    assert value['proposal_status']=='PROPOSED' and not value['active']
    assert len(value['proposal']['rows'])==29
    page.select_option('#weekly-filter','all');assert page.locator('#weekly-rows tr').count()==29
    pid=value['proposal']['proposal_id'];token=value['csrf_token'];body=dict(proposal_id=pid,confirmation=pid,action='APPROVE',exclude_short=[],password='invalid-live-probe-password-never-use')
    assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=body).status==403
    assert page.request.post(BASE+'/v13_variants/m1/review/decision',data=body,headers={'Origin':'https://untrusted.invalid','X-CSRFToken':token}).status==403
    page.select_option('#weekly-filter','changes');page.click('#weekly-approve');page.check('#weekly-ack');page.fill('#weekly-password',body['password']);page.click('#weekly-submit')
    page.wait_for_function("document.querySelector('#weekly-decision-message').textContent.includes('non registrata')");assert page.locator('#weekly-password').input_value()==''
    page.click('#weekly-cancel');page.locator('section[aria-labelledby="weekly-title"]').screenshot(path=str(OUT/'weekly-live-desktop.png'))
    page.set_viewport_size({'width':390,'height':844});assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    page.screenshot(path=str(OUT/'weekly-live-mobile.png'),full_page=True)
    after=page.request.get(BASE+'/v13_variants/m1/review/weekly').json();assert after['proposal_status']=='PROPOSED' and not after['active'] and after['policy'] is None
    assert not errors,errors;assert not external,external
    for route in ['/v13_variants','/v13_variants/m1','/v13_variants/m1/charts','/v13_paper','/btc_intraday','/btc_intraday_pair']:
        response=page.request.get(BASE+route);assert response.status==200,(route,response.status)
    value.pop('csrf_token',None);after.pop('csrf_token',None)
    (OUT/'live-browser-result.json').write_text(json.dumps(dict(scope='OPERATIONAL_UI_AUTHOR_CHECK_NOT_INDEPENDENT_ACCEPTANCE',before=value,after=after,invalid_password_denied=True,missing_csrf_denied=True,cross_origin_denied=True,operator_credential_used=False,specific_proposal_approved=False,errors=errors,external_requests=external),indent=2)+'\n')
    browser.close();print('PASS: live weekly UI, 29 candidates, actual protected writer denial, no proposal approved, mobile and six regressions')
