"""Local-only rendered UI smoke test; existing Playwright browser image."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
root=Path('/evidence');errors=[];results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
 page.on('pageerror',lambda e:errors.append(str(e)))
 for version in ['comparison','original','fast','half']:
  url='http://127.0.0.1:5001/v13_variants'+('' if version=='comparison' else '/'+version)
  response=page.goto(url,wait_until='networkidle');assert response.status==200
  page.locator('#content').wait_for(state='visible');assert 'Caricamento' not in page.locator('#status').inner_text()
  assert page.locator('#cards .card').count()==(3 if version=='comparison' else 1)
  if version!='comparison':
   assert page.locator('#positions tr').count()==18
   assert page.locator('#inherited tr').count()==164
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(root/(version+'-desktop.png')),full_page=True)
  page.locator('#history').click();assert 'Storico comune' in page.locator('#chart-title').inner_text()
  results.append({'version':version,'status':response.status,'title':page.title(),'heading':page.locator('h1').inner_text()})
 page.set_viewport_size({'width':390,'height':844})
 for version in ['comparison','fast']:
  page.goto('http://127.0.0.1:5001/v13_variants'+('' if version=='comparison' else '/'+version),wait_until='networkidle')
  page.locator('#content').wait_for(state='visible')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(root/(version+'-mobile.png')),full_page=True)
 page.goto('http://127.0.0.1:5001/v13_paper',wait_until='networkidle')
 assert page.locator('a[href="/v13_variants"]').count()==1
 response=page.request.get('http://127.0.0.1:5001/v13_variants/data');assert response.status==200
 assert 'no-store' in response.headers['cache-control']
 payload=response.json();assert payload['available'] and not payload['stale']
 assert page.request.get('http://127.0.0.1:5001/v13_variants/unknown').status==404
 browser.close()
assert not errors,errors
(root/'browser-results.json').write_text(json.dumps({'pages':results,'javascript_errors':errors,'mobile_overflow':False,'data_no_store':True},indent=2))
print(json.dumps(results))
