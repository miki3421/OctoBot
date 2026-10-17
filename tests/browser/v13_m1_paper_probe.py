"""Live fourth paper account and fixture-only failure rendering. No ledger writes."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright
BASE='http://127.0.0.1:5001';OUT=Path('/evidence');errors=[];external=[]
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,args=['--no-sandbox']);page=b.new_page(viewport=dict(width=1440,height=1100))
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('request',lambda r:external.append(r.url) if not r.url.startswith(BASE) else None)
 response=page.goto(BASE+'/v13_variants',wait_until='networkidle');assert response.status==200
 page.wait_for_function("document.querySelector('#cards').children.length===4")
 api=page.request.get(BASE+'/v13_variants/data');d=api.json()
 assert set(d['variants'])=={'ORIGINAL','FAST','HALF','M1'} and d['fourth_available'] and not d['fourth_stale'],d.get('m1',{}).get('health')
 assert 'no-store' in api.headers['cache-control'] and 'no-store' in response.headers['cache-control']
 assert page.locator('#comparison-rows tr').count()==4
 page.locator('#history').click();assert 'Storico' in page.locator('#chart-title').inner_text()
 page.locator('#future').click()
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
 page.screenshot(path=str(OUT/'four-accounts-desktop.png'),full_page=True)
 for arm in ('original','fast','half','m1'):
  r=page.goto(BASE+'/v13_variants/'+arm,wait_until='networkidle');assert r.status==200
  page.wait_for_function("document.querySelector('#positions').children.length>0")
  assert page.locator('#positions tr').count()==18
  if arm=='m1':
   assert page.locator('#inherited tr').count()==d['variants']['M1']['historical_order_count']
   assert 'tre aumenti' in page.locator('#risk').inner_text()
   assert page.locator('#m1-episodes-panel').is_visible()
   page.screenshot(path=str(OUT/'m1-account-desktop.png'),full_page=True)
 # Existing scientific observer and symbol charts must still render.
 for url in ('/v13_m1','/v13_variants/fast/charts','/v13_variants/half/charts','/v13_paper'):
  assert page.goto(BASE+url,wait_until='networkidle').status==200
 page.set_viewport_size(dict(width=390,height=844))
 for url in ('/v13_variants','/v13_variants/m1'):
  page.goto(BASE+url,wait_until='networkidle');page.wait_for_function("document.querySelector('#cards').children.length>0")
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth'),url
  page.screenshot(path=str(OUT/('m1-account-mobile.png' if url.endswith('m1') else 'four-accounts-mobile.png')),full_page=True)
 # Synthetic projection example: report a blocked M1 explicitly, without changing source data.
 fixture=json.loads(json.dumps(d));fixture['m1']['health']['status']='BLOCKED';fixture['m1']['health']['reason']='FIXTURE_STORAGE_FAILURE'
 page.route('**/v13_variants/data',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(fixture)))
 page.reload(wait_until='networkidle');assert 'FIXTURE_STORAGE_FAILURE' in page.locator('#status').inner_text()
 page.unroute('**/v13_variants/data');page.reload(wait_until='networkidle')
 b.close()
assert not errors,errors
assert not external,external
(OUT/'browser-results.json').write_text(json.dumps(dict(live_four_accounts=True,legacy_views_unchanged=True,desktop_mobile=True,fixture_only=['storage_failure_display'],javascript_errors=errors,external_requests=external,no_store=True),indent=2))
print('Four-account comparison, all detail views, old observer, charts and mobile passed.')
