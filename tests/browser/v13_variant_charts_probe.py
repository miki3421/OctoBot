"""Rendered FAST/HALF charts; synthetic UI events never enter a journal."""
import copy
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path('/evidence');BASE='http://127.0.0.1:5001';errors=[];results=[]
with sync_playwright() as p:
 browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
 page=browser.new_page(viewport={'width':1440,'height':1100})
 page.on('pageerror',lambda e:errors.append(str(e)))
 for variant in ['fast','half']:
  response=page.goto(BASE+'/v13_variants/'+variant+'/charts',wait_until='networkidle');assert response.status==200
  page.locator('#overview-content').wait_for(state='visible')
  assert page.locator('#overview-grid canvas').count()==18
  assert variant.upper() in page.locator('h1').inner_text()
  assert page.evaluate('isVariant===true')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(ROOT/(variant+'-charts-overview-desktop.png')),full_page=True)
  page.get_by_role('button',name='Apri dettaglio BTCUSDT',exact=True).click()
  page.locator('#content').wait_for(state='visible')
  current=page.evaluate('data');assert current['variant']==variant
  assert all(f['origin'] in ['inherited','post_fork'] for f in current['fills'])
  inherited=next(f for f in current['fills'] if f['origin']=='inherited' and f['action']=='SELL')
  page.get_by_role('button',name='Dettagli fill '+str(inherited['id'])+' '+inherited['label'],exact=True).click()
  assert 'Ereditata dalla V13' in page.locator('#detail').inner_text()
  assert 'Realizzato meno la commissione' in page.locator('#detail').inner_text()
  assert 'Apertura short' not in page.locator('#detail strong').inner_text()
  page.screenshot(path=str(ROOT/(variant+'-btc-detail-desktop.png')),full_page=True)
  page.locator('#origin-filter').select_option('post_fork')
  assert page.evaluate('visibleFills.every(f=>f.origin==="post_fork")')
  page.locator('#origin-filter').select_option('inherited')
  assert page.evaluate('visibleFills.every(f=>f.origin==="inherited")')
  assert page.locator('#fills tr').count()==sum(f['origin']=='inherited' for f in current['fills'])
  page.set_viewport_size({'width':390,'height':844})
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(ROOT/(variant+'-btc-detail-mobile.png')),full_page=True)
  page.locator('#view-all').click();page.locator('#overview-content').wait_for(state='visible')
  assert page.locator('#overview-grid canvas').count()==18
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  page.screenshot(path=str(ROOT/(variant+'-charts-overview-mobile.png')),full_page=True)
  page.set_viewport_size({'width':1440,'height':1100})
  result=page.request.get(BASE+'/v13_variants/'+variant+'/charts/data?symbol=BTCUSDT')
  assert result.status==200 and result.json()['available']
  assert 'no-store' in result.headers['cache-control']
  results.append(dict(variant=variant,symbols=18,inherited_sell_detail=True,origin_filter=True,mobile_no_overflow=True))
 # Test a future SELL loss and its solid marker using browser-only synthetic data.
 fixture=page.request.get(BASE+'/v13_variants/fast/charts/data?symbol=BTCUSDT').json()
 old=fixture['fills'][-1];before=fixture['quantity'];assert before>0
 price=100.;qty=-before/2;fee=.06;entry=fixture['fills'][0]['price']
 realized=abs(qty)*(price-entry);mark=price+1;impact=qty*(mark-price)-fee
 event=dict(id=999999,time=fixture['as_of'],quote_time=fixture['as_of'],time_basis='execution',action='SELL',quantity=qty,price=price,
  kind='reduce',label='Riduzione long',before=before,after=before+qty,closed_quantity=abs(qty),opened_quantity=0,
  realized_pnl=realized,fee=fee,realized_less_fill_fee=realized-fee,unrealized_change=impact-realized+fee,equity_impact=impact,
  reference_mark=mark,entry_after=entry,origin='post_fork')
 fixture['fills'].append(event);fixture['quantity']=before+qty
 page.route('**/v13_variants/fast/charts/data?*',lambda route:route.fulfill(status=200,content_type='application/json',body=json.dumps(fixture)))
 page.goto(BASE+'/v13_variants/fast/charts?symbol=BTCUSDT',wait_until='networkidle');page.locator('#content').wait_for(state='visible')
 page.locator('#origin-filter').select_option('post_fork');assert page.locator('#fills tr').count()==1
 assert page.evaluate('sellOutcome(data.fills.at(-1)).icon')=='−'
 marker=page.evaluate('hits.find(h=>h.outcome==="−"&&h.f.id===999999)');assert marker
 box=page.locator('#chart').bounding_box();page.mouse.click(box['x']+marker['x'],box['y']+marker['y'])
 assert 'Dopo la biforcazione' in page.locator('#detail').inner_text()
 assert '999999' in page.locator('#detail').inner_text()
 page.screenshot(path=str(ROOT/'synthetic-postfork-loss-marker.png'),full_page=True)
 page.unroute('**/v13_variants/fast/charts/data?*')
 page.goto(BASE+'/v13_paper/charts?symbol=BTCUSDT',wait_until='networkidle');page.locator('#content').wait_for(state='visible')
 assert not page.evaluate('isVariant');assert page.locator('#origin-filter').count()==0
 assert page.request.get(BASE+'/v13_variants/unknown/charts').status==404
 for variant in ['fast','half']:
  page.goto(BASE+'/v13_variants/'+variant,wait_until='networkidle')
  assert page.locator('a[href="/v13_variants/'+variant+'/charts"]').count()==1
 browser.close()
assert not errors,errors
(ROOT/'browser-results.json').write_text(json.dumps(dict(pages=results,javascript_errors=errors,synthetic_postfork_sell_loss_marker=True,synthetic_scope='UI_ONLY_NO_JOURNAL_WRITE',original_charts_regression=True),indent=2))
print(json.dumps(results))
