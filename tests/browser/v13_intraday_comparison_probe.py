"""GET-only browser checks of the five-account comparison; no account writes."""
import argparse,copy,json,re
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--live',action='store_true');args=p.parse_args()
base='http://127.0.0.1:5001';args.evidence.mkdir(exist_ok=True)
js=args.source/'packages/tentacles/Services/Interfaces/web_interface/static/js/common/v13_variants.js'
tpl=args.source/'packages/tentacles/Services/Interfaces/web_interface/templates/v13_variants.html'
errors=[];blocked=[];checks=[]
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
 def context(variant='comparison',v=None,i=None,fail=False,preview=True,now=None):
  ctx=browser.new_context(viewport={'width':1440,'height':1100})
  if now is not None:
   ctx.add_init_script('Date.now=()=>'+str(now)+';const interval=window.setInterval;window.setInterval=(fn,ms,...args)=>{if(ms===60000)window.__testRefresh=fn;return interval(fn,ms,...args);};')
  # Trace only drawing commands, to verify that incomplete points break the orange line.
  ctx.add_init_script("""window.paths=[];{const p=CanvasRenderingContext2D.prototype;for(const n of ['beginPath','moveTo','lineTo','stroke']){const f=p[n];p[n]=function(...a){if(n==='beginPath')this._p=[];if(n==='moveTo'||n==='lineTo')(this._p??=[]).push(n);if(n==='stroke')window.paths.push({color:this.strokeStyle,path:this._p});return f.apply(this,a);};}}""")
  def gate(route):
   req=route.request
   if req.method!='GET' or not req.url.startswith(base+'/'):blocked.append(req.url);route.abort();return
   path=req.url[len(base):].split('?')[0]
   if preview and path==('/v13_variants'+('' if variant=='comparison' else '/'+variant)):
    text=tpl.read_text().replace('{% include "components/lab_sidebar.html" %}',(args.source/'packages/tentacles/Services/Interfaces/web_interface/templates/components/lab_sidebar.html').read_text());text=re.sub(r'{% if variant in .*?{% endif %}', '',text,flags=re.S).replace('{{ variant }}',variant)
    route.fulfill(status=200,content_type='text/html',body=text)
   elif preview and path in ['/static/css/lab_navigation.css','/static/js/common/lab_navigation.js']:route.fulfill(status=200,content_type='text/css' if path.endswith('.css') else 'application/javascript',body=(args.source/'packages/tentacles/Services/Interfaces/web_interface'/path.lstrip('/')).read_text())
   elif preview and path=='/static/js/common/v13_variants.js':route.fulfill(status=200,content_type='text/javascript',body=js.read_text())
   elif v is not None and path=='/v13_variants/data':route.fulfill(status=200,content_type='application/json',body=json.dumps(v))
   elif (i is not None or fail) and path=='/btc_intraday/data':route.fulfill(status=503 if fail else 200,content_type='application/json',body=json.dumps(i or {'error':'unavailable'}))
   else:route.continue_()
  ctx.route('**/*',gate)
  page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
  page.goto(base+'/v13_variants'+('' if variant=='comparison' else '/'+variant),wait_until='domcontentloaded')
  page.wait_for_function("!document.getElementById('content').classList.contains('hidden')")
  page.wait_for_function("document.querySelectorAll('#cards .card').length>0")
  return ctx,page
 # Actual API shapes are used even for deterministic fixtures.
 request=browser.new_context().request
 v=request.get(base+'/v13_variants/data').json();i=request.get(base+'/btc_intraday/data').json()
 ctx,page=context(preview=not args.live)
 page.wait_for_function("document.querySelectorAll('#cards .card').length===5")
 assert page.locator('#comparison-rows tr').count()==5
 assert 'BTC intraday' in page.locator('#cards').inner_text()
 assert page.locator('#cards a[href="/btc_intraday"]').count()==1
 assert '10.000 USDT' in page.locator('[data-account="BTC"]').first.inner_text()
 assert 'Equity reale dei conti' in page.locator('#chart-title').inner_text()
 assert page.locator('#history').get_attribute('class')=='active'
 assert page.locator('#equity').get_attribute('aria-label')=='Equity reale dei conti in USDT virtuali'
 assert page.locator('#legend .swatch').count()==5
 for period in ['range-24','range-7','range-all']:
  page.locator('#'+period).click()
  assert page.locator('#'+period).get_attribute('aria-pressed')=='true'
  assert page.locator('#equity').get_attribute('aria-label')=='Equity reale dei conti in USDT virtuali'
 checks.append('live three period buttons retain actual USDT view')
 page.screenshot(path=str(args.evidence/('live-desktop.png' if args.live else 'preview-desktop.png')),full_page=True)
 page.locator('#history').click();assert 'Equity reale dei conti' in page.locator('#chart-title').inner_text()
 page.locator('#future').click();assert 'Rendimento percentuale · V13' in page.locator('#chart-title').inner_text()
 page.locator('#all').click()
 page.locator('#history').click()
 page.locator('#range-24').click()
 page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(250)
 assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 page.screenshot(path=str(args.evidence/('live-mobile.png' if args.live else 'preview-mobile.png')),full_page=True)
 checks.append('live API five cards, rows, links, chart modes, mobile');ctx.close()
 if not args.live:
  v=copy.deepcopy(v);i=copy.deepcopy(i)
  start=1792260000000 # 18:00 UTC
  for k,values in {'ORIGINAL':[100,105,110],'FAST':[200,190,180],'HALF':[50,50,50],'M1':[10,11,12]}.items():
   v['variants'][k]['equity_curve']=[[datetime.fromtimestamp((start+n*900000+10000)/1000,timezone.utc).isoformat(),value] for n,value in enumerate(values)]
   v['variants'][k]['metrics']['equity']=values[-1]
   v['variants'][k]['observed_at']=datetime.fromtimestamp((start+1800000+10000)/1000,timezone.utc).isoformat()
  v['stale']=False;v['fourth_stale']=False
  i['stale']=False;i['accounting_complete']=True;i['equity']=[[(start+n*900000+20000)*1000000,value,None,1] for n,value in enumerate([10000,10050,10100])]
  i['metrics']['equity']=10100;i['metrics']['pnl']=100
  ctx,page=context(v=v,i=i)
  canvas=page.locator('#equity');box=canvas.bounding_box();page.locator('#equity').hover(position={'x':box['width']-10,'y':50})
  hover=page.locator('#hover').inner_text()
  assert all(x in hover for x in ['110,00 USDT','180,00 USDT','50,00 USDT','12,00 USDT','10.100,00 USDT']),hover
  assert '%' not in hover
  checks.append('default raw equity tooltip preserves the five actual account values')
  page.locator('#all').click()
  box=page.locator('#equity').bounding_box();page.locator('#equity').hover(position={'x':box['width']-10,'y':50})
  assert '+10,00%' in page.locator('#hover').inner_text() and ' USDT' not in page.locator('#hover').inner_text()
  cells=page.locator('#comparison-rows tr td:nth-child(2)').all_inner_texts()
  assert cells==['+10,00%','-10,00%','0,00%','+20,00%','+1,00%'],cells
  assert 'non è un benchmark scientifico fissato' in page.locator('#chart-note').inner_text()
  checks.append('different seeds: exact returns 10%, -10%, 0%, 20%, 1% on common observations');ctx.close()
  incomplete=copy.deepcopy(i);incomplete['equity'][1][3]=0
  ctx,page=context(v=v,i=incomplete)
  page.locator('#all').click()
  orange=page.evaluate("window.paths.filter(p=>p.color==='#ffab80'&&p.path.length)")[-1]['path']
  assert orange==['moveTo','moveTo'],orange
  checks.append('incomplete intermediate point breaks intraday line');ctx.close()
  for name,payload,fail in [('unavailable',None,True),('stale',dict(i,stale=True),False),('accounting',dict(i,accounting_complete=False),False),('wrong_identity',dict(i,account='wrong'),False)]:
   ctx,page=context(v=v,i=payload,fail=fail)
   assert page.locator('#cards .card').count()==5
   page.locator('#all').click()
   assert 'In attesa della finestra comune' in page.locator('#chart-title').inner_text()
   assert page.locator('#comparison-rows tr').count()==5
   assert all(x=='In attesa' for x in page.locator('#comparison-rows tr td:nth-child(2)').all_inner_texts()[:4])
   if name=='accounting':assert 'Equity provvisoria' in page.locator('[data-account="BTC"]').first.inner_text()
   page.locator('#future').click();assert 'Rendimento percentuale · V13' in page.locator('#chart-title').inner_text()
   assert page.locator('#comparison-rows tr td:nth-child(2)').all_inner_texts()[-1]=='Non disponibile'
   checks.append(name+': no fake return, V13 fallback works');ctx.close()
  shifted=copy.deepcopy(i);shifted['equity']=[[p[0]+86400000000000,*p[1:]] for p in i['equity']]
  ctx,page=context(v=v,i=shifted)
  page.locator('#all').click()
  assert 'In attesa della finestra comune' in page.locator('#chart-title').inner_text()
  checks.append('non-overlapping histories never interpolated');ctx.close()
  shifted=copy.deepcopy(i);shifted['equity']=[[p[0]+300000000000,*p[1:]] for p in i['equity']]
  ctx,page=context(v=v,i=shifted)
  page.locator('#all').click()
  assert 'In attesa della finestra comune' in page.locator('#chart-title').inner_text()
  checks.append('different 5-minute buckets never matched');ctx.close()
  for name,patch in [('V13 funding debt',{'funding_debt':{'reason':'fixture_missing_rate'}}),('V13 valuation gap',{'valuation_gap':{'reason':'fixture_missing_mark'}}),('V13 stale',{'stale':True})]:
   ctx,page=context(v=dict(v,**patch),i=i)
   page.locator('#all').click()
   assert 'In attesa della finestra comune' in page.locator('#chart-title').inner_text()
   checks.append(name+': shared comparison withheld');ctx.close()
 if not args.live:
  fixed=int(datetime.now(timezone.utc).timestamp()*1000);hour=3600000;day=24*hour
  fv=copy.deepcopy(v);fi=copy.deepcopy(i);ages=[8*day,7*day+1,7*day,day+1,day,hour]
  iso=lambda at:datetime.fromtimestamp(at/1000,timezone.utc).isoformat()
  fv['common_history']=[]
  for k,variant in fv['variants'].items():
   variant['inherited_curve']=[];variant['equity_curve']=[[iso(fixed-age),10100+100*n] for n,age in enumerate(ages)]
   variant['metrics']['equity']=10600;variant['observed_at']=iso(fixed-hour)
  fi['equity']=[[(fixed-age)*1000000,10100+100*n,None,1] for n,age in enumerate(ages)]
  fi['metrics']['equity']=10600;fi['state']['activation_at']=(fixed-9*day)*1000000
  ctx,page=context(v=fv,i=fi,now=fixed)
  def count(color):return page.evaluate("color=>window.paths.filter(p=>p.color===color&&p.path.length).at(-1)?.path.length??0",color)
  before=page.locator('#cards').inner_text();table=page.locator('#comparison-rows').inner_text()
  assert count('#8abfff')==6
  for button,n,amount in [('range-24',2,'10.500,00 USDT'),('range-7',4,'10.300,00 USDT'),('range-all',6,'10.100,00 USDT')]:
   page.evaluate('window.paths=[]');page.locator('#'+button).click();assert count('#8abfff')==n
   page.locator('#equity').hover(position={'x':74,'y':50});assert amount in page.locator('#hover').inner_text()
   assert page.locator('#cards').inner_text()==before and page.locator('#comparison-rows').inner_text()==table
  checks.append('inclusive 24h/7-day cutoffs exclude earlier points and preserve exact raw values and card/table data')
  page.locator('#range-24').click();page.evaluate('window.__testRefresh()')
  assert page.locator('#range-24').get_attribute('aria-pressed')=='true' and count('#8abfff')==2
  checks.append('automatic data refresh preserves selected period and USDT mode');ctx.close()
  recent=copy.deepcopy(fi);recent['equity']=recent['equity'][-1:]
  ctx,page=context(v=fv,i=recent,now=fixed);page.locator('#range-24').click();assert count('#ffab80')==1
  checks.append('recent intraday account is never extended to fill the selected period');ctx.close()
  empty=copy.deepcopy(fv);empty_i=copy.deepcopy(fi)
  for variant in empty['variants'].values():variant['equity_curve']=variant['equity_curve'][:1];variant['observed_at']=iso(fixed-8*day)
  empty_i['equity']=empty_i['equity'][:1]
  ctx,page=context(v=empty,i=empty_i,now=fixed);page.evaluate('window.paths=[]');page.locator('#range-24').click()
  assert 'Nessuna osservazione disponibile' in page.locator('#chart-note').inner_text() and count('#8abfff')==0
  assert page.locator('#hover').inner_text()==''
  page.locator('#range-all').click();assert count('#8abfff')==1
  checks.append('empty period clears chart and tooltip without zero balances; all-history restores actual point');ctx.close()
 for variant in ['original','fast','half','m1']:
  ctx,page=context(variant=variant,preview=not args.live)
  assert page.locator('#cards .card').count()==1
  assert page.locator('#all').is_hidden()
  assert page.locator('#positions tr').count()>0
  page.locator('#history').click();assert 'Equity reale dei conti' in page.locator('#chart-title').inner_text()
  ctx.close()
 checks.append('all four V13 detail pages preserved; no intraday API required')
 browser.close()
result={'mode':'live' if args.live else 'preview','checks':checks,'page_errors':errors,'blocked_requests':blocked,'read_only':True}
(args.evidence/('live-results.json' if args.live else 'preview-results.json')).write_text(json.dumps(result,indent=2)+'\n')
assert not errors and not blocked,result
print(json.dumps(result))
