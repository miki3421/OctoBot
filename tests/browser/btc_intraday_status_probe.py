"""GET-only status regression checks; fixture data never reaches a runner."""
import argparse,copy,json
from pathlib import Path
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--live',action='store_true');args=p.parse_args()
base='http://127.0.0.1:5001';args.evidence.mkdir(exist_ok=True)
js=args.source/'packages/tentacles/Services/Interfaces/web_interface/static/js/common/btc_intraday.js'
tpl=args.source/'packages/tentacles/Services/Interfaces/web_interface/templates/btc_intraday.html'
errors=[];blocked=[];checks=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
 def open_page(value=None):
  ctx=browser.new_context(viewport={'width':1440,'height':1100})
  def gate(route):
   req=route.request
   if req.method!='GET' or not req.url.startswith(base+'/'):blocked.append(req.url);route.abort();return
   path=req.url[len(base):].split('?')[0]
   if not args.live and path=='/btc_intraday':route.fulfill(status=200,content_type='text/html',body=tpl.read_text().replace('{% include "components/lab_sidebar.html" %}',(args.source/'packages/tentacles/Services/Interfaces/web_interface/templates/components/lab_sidebar.html').read_text()))
   elif not args.live and path in ['/static/css/lab_navigation.css','/static/js/common/lab_navigation.js']:route.fulfill(status=200,content_type='text/css' if path.endswith('.css') else 'application/javascript',body=(args.source/'packages/tentacles/Services/Interfaces/web_interface'/path.lstrip('/')).read_text())
   elif not args.live and path=='/static/js/common/btc_intraday.js':route.fulfill(status=200,content_type='text/javascript',body=js.read_text())
   elif value is not None and path=='/btc_intraday/data':route.fulfill(status=200,content_type='application/json',body=json.dumps(value))
   else:route.continue_()
  ctx.route('**/*',gate);page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  response=page.goto(base+'/btc_intraday',wait_until='domcontentloaded');assert response.status==200
  page.wait_for_function("!document.getElementById('content').classList.contains('hidden')")
  return ctx,page
 ctx,page=open_page()
 assert page.locator('#reason-note').inner_text().startswith('Ultimo slot registrato:')
 assert 'Motivo memorizzato dal motore:' in page.locator('#engine-note').text_content()
 assert page.locator('#equity').inner_text().endswith('USDT')
 assert page.locator('#chart').evaluate('c=>c.width>0')
 snapshot={'reason':page.locator('#reason').inner_text(),'note':page.locator('#reason-note').inner_text(),'engine':page.locator('#engine-note').text_content()}
 page.screenshot(path=str(args.evidence/('live-status-desktop.png' if args.live else 'preview-status-desktop.png')),full_page=True)
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(200);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 page.screenshot(path=str(args.evidence/('live-status-mobile.png' if args.live else 'preview-status-mobile.png')),full_page=True)
 payload=ctx.request.get(base+'/btc_intraday/data').json();assert payload['no_real_orders'] and payload['real_min_quantity']=='UNKNOWN' and payload['real_min_notional']=='UNKNOWN';ctx.close()
 checks.append('live-shaped data, diagnostic provenance, paper-only scope, desktop/mobile')
 if not args.live:
  value=copy.deepcopy(payload);value.update(stale=False,status='ACTIVE_PAPER',warmup_rows=289,book_age_seconds=.69)
  value['metrics'].update(equity=10000,pnl=0)
  value['state'].update(reason='PRICE_MISSING',pending=None,q=0,drawdown_halt=False,integrity_halt=False);value['state']['daily']['halt']=False
  latest=copy.deepcopy(value['slots'][0]);latest['slot_ns']=value['checked_at_ns']-60_000_000_000;latest['status']='NO_SIGNAL';value['slots']=[latest]
  cases=[('retained reason with accepted recent book',{}, {},'Ultimo slot: Nessun segnale M1'),
         ('old accepted book',{'book_age_seconds':2.1},{},'Ultimo book accettato non aggiornato'),
         ('unknown book age',{'book_age_seconds':None},{},'Ultimo book accettato non verificabile'),
         ('stale projection',{'stale':True},{},'Dati non aggiornati'),
         ('risk halt',{'status':'ACTIVE_RISK_HALTED'},{},'Nuovi ingressi sospesi dal rischio'),
         ('daily halt despite retained reason',{}, {'daily':dict(value['state']['daily'],halt=True)},'Nuovi ingressi sospesi dal rischio'),
         ('entry pending',{}, {'pending':{'kind':'ENTRY'}},'Ingresso programmato'),
         ('protective close pending',{}, {'pending':{'kind':'EXIT'}},'Chiusura protettiva in corso'),
         ('open short',{}, {'q':-.001},'SHORT aperto'),
         ('warmup',{'warmup_rows':100},{},'Raccolta iniziale'),
         ('storage blocked',{'status':'BLOCKED_STORAGE','error':'fixture storage fault'},{},'Conto fermo: fixture storage fault'),
         ('funding pending remains visible',{}, {'reason':'FUNDING_PENDING'},'Funding in attesa'),
         ('no slot',{'slots':[]},{},'In attesa della prima valutazione'),
         ('old slot',{'slots':[dict(latest,slot_ns=value['checked_at_ns']-600_000_000_000)]},{},'Ultima valutazione non recente'),
         ('L5 denial remains visible',{'slots':[dict(latest,status='L5_WINDOW_INCOMPLETE')]},{},'Ultimo slot: Finestra book incompleta')]
  for name,top,state,expected in cases:
   v=copy.deepcopy(value);v.update(top);v['state'].update(state);ctx,page=open_page(v)
   assert page.locator('#reason').inner_text()==expected,(name,page.locator('#reason').inner_text())
   assert expected in page.locator('#status').inner_text()
   assert page.locator('#equity').inner_text()=='10.000,00 USDT'
   if name=='retained reason with accepted recent book':assert 'PRICE_MISSING' in page.locator('#engine-note').text_content()
   checks.append(name);ctx.close()
 browser.close()
result=dict(mode='live' if args.live else 'preview',checks=checks,page_errors=errors,blocked_requests=blocked,snapshot=snapshot,read_only=True)
(args.evidence/('live-status-results.json' if args.live else 'preview-status-results.json')).write_text(json.dumps(result,indent=2)+'\n')
assert not errors and not blocked,result
print(json.dumps(result))
