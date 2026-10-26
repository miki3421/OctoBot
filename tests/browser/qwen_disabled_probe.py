"""Read-only user journey for operator-disabled descriptive Qwen."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

out=Path('/evidence/qwen-disabled-browser');out.mkdir(exist_ok=True)
base='http://127.0.0.1:5001'
with sync_playwright() as pw:
    browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1436,'height':1314});errors=[];writes=[]
    page.on('pageerror',lambda error:errors.append(str(error)))
    page.on('request',lambda request:writes.append(request.url) if request.method!='GET' else None)
    page.goto(base+'/v13_paper',wait_until='networkidle')
    page.wait_for_function("document.querySelector('#analysis-report-updated').textContent==='Servizio disabilitato'")
    assert page.locator('#qwen-analysis-title').inner_text()=='Analisi Qwen · disabilitata'
    assert 'Prossimo orario previsto' not in page.locator('#analysis-report').inner_text()
    result=page.request.get(base+'/v13_paper/analysis').json()
    assert result['available'] and result['metrics']['symbols']
    assert result['report']['status']=='disabled' and not result['report']['available']
    assert result['report']['next_scheduled_at'] is None
    page.locator('section[aria-labelledby="qwen-analysis-title"]').screenshot(path=str(out/'disabled.png'))
    for route in ('/v13_variants','/v13_variants/m1/review','/v13_variants/m1/charts','/btc_intraday_pair'):
        assert page.request.get(base+route).status==200
    assert not errors,errors
    assert not writes,writes
    result=dict(passed=True,disabled_visible=True,no_next_schedule=True,
                quantitative_metrics_available=True,write_requests=0,errors=errors)
    (out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
    browser.close()
