"""Synthetic-only browser approval against real Unix broker and private ledger.

This probe must never target the operational dashboard or a non-fixture proposal.
"""
import json,os,time
from pathlib import Path
from playwright.sync_api import sync_playwright
URL='http://127.0.0.1:5103'
OUT=Path('/evidence');OUT.mkdir(exist_ok=True)
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1440,'height':1100});errors=[];external=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda r:external.append(r.url) if not r.url.startswith(URL+'/') else None)
    page.goto(URL+'/v13_variants/m1/review');page.wait_for_selector('#weekly-approve:enabled')
    initial=page.request.get(URL+'/v13_variants/m1/review/weekly').json()
    assert initial['available'] and initial['approval_ready'] and not initial['stale']
    assert initial['proposal']['data_mode']=='CONTROL_FIXTURE_ONLY', 'REFUSE non-fixture proposal'
    assert initial['proposal_status']=='PROPOSED'
    pid=initial['proposal']['proposal_id'];token=initial['csrf_token']
    assert len(initial['proposal']['rows'])==29
    page.select_option('#weekly-filter','all');assert page.locator('#weekly-rows tr').count()==29
    page.screenshot(path=str(OUT/'weekly-desktop-before.png'),full_page=True)
    body=dict(proposal_id=pid,confirmation=pid,action='APPROVE',exclude_short=[],password='fixture-only-approval-password-20261023')
    response=page.request.post(URL+'/v13_variants/m1/review/decision',data=body)
    assert response.status==403,'Missing Origin/CSRF must fail'
    response=page.request.post(URL+'/v13_variants/m1/review/decision',data=body,headers={'Origin':'http://wrong.invalid','X-CSRFToken':token})
    assert response.status==403,'Cross origin must fail'
    page.click('#weekly-approve');page.fill('#weekly-password','wrong-password-for-fixture')
    page.click('#weekly-submit');assert 'Conferma' in page.locator('#weekly-decision-message').inner_text()
    page.check('#weekly-ack');page.click('#weekly-submit');page.wait_for_function("document.querySelector('#weekly-decision-message').textContent.includes('non registrata')")
    assert page.locator('#weekly-password').input_value()==''
    page.fill('#weekly-password',body['password']);page.click('#weekly-submit')
    page.wait_for_function("!document.querySelector('#weekly-dialog').open")
    assert 'Attesa conferma del runner' in page.locator('#weekly-result').inner_text()
    assert page.locator('#weekly-password').input_value()==''
    # Separate process must consume authority and commit actual reductions.
    result=None
    for _ in range(14):
        result=page.request.get(URL+'/v13_variants/m1/review/weekly').json()
        if result.get('last_execution',{}):break
        page.wait_for_timeout(5000)
    assert result.get('active') and result.get('policy',{}).get('revision')==1
    assert result.get('last_execution',{}).get('status') in ('REDUCTIONS_APPLIED_WAITING_DAILY','PARTIAL_REBALANCE'),result
    reduced=[s for s,p in result['positions'].items() if initial['positions'].get(s,{}).get('quantity',0)>0 and p['quantity']<initial['positions'][s]['quantity']]
    assert reduced, 'No actual reductions in private ledger'
    for s,p in result['positions'].items():
        if result['policy']['long_caps'][s]==0:assert p['quantity']<=0, (s,p['quantity'])
    token=result['csrf_token'];headers={'Origin':URL,'X-CSRFToken':token}
    replay=page.request.post(URL+'/v13_variants/m1/review/decision',data=body,headers=headers)
    assert replay.status==200 and replay.json()['ok']
    conflict=page.request.post(URL+'/v13_variants/m1/review/decision',data=dict(body,action='REJECT'),headers=headers)
    assert conflict.status==409
    page.reload();page.wait_for_selector('#weekly-body:not(.hidden)');assert page.locator('#weekly-approve').is_disabled()
    page.screenshot(path=str(OUT/'weekly-desktop-after.png'),full_page=True)
    page.set_viewport_size({'width':390,'height':844});page.screenshot(path=str(OUT/'weekly-mobile-after.png'),full_page=True)
    assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
    assert not errors,errors
    assert not external,external
    # Never save a password or CSRF token in evidence.
    for value in (initial,result):value.pop('csrf_token',None)
    (OUT/'browser-result.json').write_text(json.dumps(dict(scope='CONTROL_FIXTURE_ONLY_NOT_KUCOIN_ADMISSIBILITY',before=initial,after=result,reduced_symbols=reduced,errors=errors,external_requests=external),indent=2)+'\n')
    browser.close();print('PASS: real browser, CSRF, Unix writer, private ledger fills, replay/conflict, desktop/mobile')
