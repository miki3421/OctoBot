"""Read-only localhost navigation acceptance; no downloads or account mutations."""
import argparse,json,re
from pathlib import Path
from playwright.sync_api import sync_playwright

p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--live',action='store_true');args=p.parse_args();args.evidence.mkdir(exist_ok=True)
root=args.source/'packages/tentacles/Services/Interfaces/web_interface';base='http://127.0.0.1:5001'
css=root/'static/css/lab_navigation.css';js=root/'static/js/common/lab_navigation.js';partial=(root/'templates/components/lab_sidebar.html').read_text()
reference=(root/'templates/v13_research_dashboard.html').read_text();style=re.search(r'<link rel="stylesheet" href="([^"]*lab_navigation.css[^\"]*)"',reference).group(1);script=re.search(r'<script defer src="([^"]*lab_navigation.js[^\"]*)"',reference).group(1)
paths=['/v13_paper','/v13_paper/charts','/v13_variants','/v13_variants/original','/v13_variants/fast','/v13_variants/half','/v13_variants/m1','/v13_variants/fast/charts','/v13_variants/half/charts','/btc_intraday','/v13_m1','/v13_candidates','/v13_comparison','/btc_research','/qwen_shadow']
expected=set(re.findall(r'class="lab-nav-link" data-lab-route href="([^"]+)"',partial));assert len(expected)==14
errors=[];blocked=[];pages=[];checks=[]
def data_ready(page,path):
 if path=='/v13_paper':page.wait_for_function("document.getElementById('equity').textContent.includes('USDT')",timeout=20000)
 elif path in ['/v13_variants','/btc_intraday']:page.wait_for_function("!document.getElementById('content').classList.contains('hidden')")
with sync_playwright() as pw:
 browser=pw.chromium.launch(headless=True,args=['--no-sandbox'])
 ctx=browser.new_context(viewport={'width':1498,'height':1100})
 def gate(route):
  req=route.request
  if req.method!='GET' or not req.url.startswith(base+'/'):blocked.append(req.url);route.abort();return
  path=req.url[len(base):].split('?')[0]
  if not args.live and path in paths:
   # Real server renders existing Jinja. Apply the same bounded shell additions as the candidate templates.
   response=route.fetch();assert response.status==200
   text=response.text();assert '<body>' in text and text.count('<main')==1
   text=text.replace('</head>','<link rel="stylesheet" href="'+style+'"></head>',1).replace('<body>','<body class="lab-page">'+partial,1).replace('<main','<main id="lab-main-content" tabindex="-1"',1).replace('</body>','<script defer src="'+script+'"></script></body>',1)
   route.fulfill(response=response,body=text)
  elif not args.live and path=='/static/css/lab_navigation.css':route.fulfill(status=200,content_type='text/css',body=css.read_text())
  elif not args.live and path=='/static/js/common/lab_navigation.js':route.fulfill(status=200,content_type='application/javascript',body=js.read_text())
  else:route.continue_()
 ctx.route('**/*',gate)
 page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
 for path in paths:
  response=page.goto(base+path,wait_until='domcontentloaded');assert response.status==200
  page.wait_for_function("document.querySelectorAll('#lab-sidebar [aria-current=page]').length===1")
  links=page.locator('#lab-sidebar [data-lab-route]');assert set(links.evaluate_all('(links)=>links.map(a=>a.getAttribute("href"))'))==expected
  active=page.locator('#lab-sidebar [aria-current="page"]');assert active.get_attribute('href')==('/v13_paper' if path=='/v13_variants/original' else path)
  assert page.locator('#lab-sidebar').is_visible() and page.locator('#lab-menu-toggle').is_hidden()
  assert page.locator('#lab-sidebar').evaluate('s=>!s.inert')
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),path
  box=page.locator('main').bounding_box();assert box['x']>=238,path
  if path in ['/v13_paper','/v13_variants','/btc_intraday']:
   data_ready(page,path)
   page.wait_for_function("Array.from(document.querySelectorAll('canvas')).filter(c=>c.clientWidth>0).every(c=>Math.abs(c.width-c.clientWidth*devicePixelRatio)<3)")
   assert page.locator('canvas').count()>0
  pages.append({'path':path,'active':active.inner_text(),'status':response.status})
 checks.append('15 existing pages, 14 links, exact active route and original alias, desktop no overflow')
 for path in ['/v13_paper','/v13_variants','/btc_intraday']:
  page.goto(base+path,wait_until='domcontentloaded');page.wait_for_function("document.querySelector('#lab-sidebar [aria-current=page]')")
  data_ready(page,path);page.wait_for_timeout(100);page.screenshot(path=str(args.evidence/(path.strip('/')+'-desktop.png')),full_page=True)
 # All templates at the drawer breakpoint, independently of their individual responsive CSS.
 for path in paths:
  page.set_viewport_size({'width':390,'height':844});page.goto(base+path,wait_until='domcontentloaded');page.wait_for_function("document.querySelector('#lab-sidebar [aria-current=page]')")
  assert page.locator('#lab-menu-toggle').is_visible() and page.locator('#lab-sidebar').evaluate('s=>s.inert')
  assert page.locator('#lab-menu-toggle').get_attribute('aria-expanded')=='false'
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),path
 checks.append('all 15 pages at 390px: closed drawer inert, menu visible, no horizontal overflow')
 page.goto(base+'/v13_paper',wait_until='domcontentloaded');page.wait_for_function("document.querySelector('#lab-sidebar [aria-current=page]')")
 menu=page.locator('#lab-menu-toggle');menu.click()
 assert page.locator('#lab-menu-close').evaluate('e=>document.activeElement===e')
 assert menu.get_attribute('aria-expanded')=='true' and page.locator('main').evaluate('m=>m.inert')
 assert page.locator('#lab-sidebar').get_attribute('role')=='dialog'
 first=page.locator('#lab-sidebar a[href]').first;last=page.locator('#lab-sidebar a[href]').last
 last.focus();page.keyboard.press('Tab');assert first.evaluate('e=>document.activeElement===e')
 first.focus();page.keyboard.press('Shift+Tab');assert last.evaluate('e=>document.activeElement===e')
 page.keyboard.press('Escape');assert menu.evaluate('e=>document.activeElement===e') and not page.locator('main').evaluate('m=>m.inert')
 checks.append('mobile focus trap, Escape and focus restoration; background content inert only while open')
 menu.click();page.locator('#lab-nav-backdrop').click(position={'x':380,'y':800});assert menu.get_attribute('aria-expanded')=='false'
 menu.click();page.locator('#lab-menu-close').click();assert menu.get_attribute('aria-expanded')=='false'
 menu.click();page.locator('#lab-sidebar [href="/btc_intraday"][data-lab-route]').click();page.wait_for_url('**/btc_intraday');page.wait_for_function("document.querySelector('#lab-sidebar [aria-current=page]')")
 assert page.locator('#lab-current-page').inner_text()=='BTC intraday'
 assert page.locator('#lab-menu-toggle').get_attribute('aria-expanded')=='false'
 checks.append('close button, backdrop and actual navigation to intraday preserve usable drawer state')
 page.screenshot(path=str(args.evidence/'intraday-mobile-closed.png'),full_page=True)
 page.locator('#lab-menu-toggle').click();page.wait_for_function("document.getElementById('lab-sidebar').getBoundingClientRect().left===0");page.screenshot(path=str(args.evidence/'mobile-menu-open.png'),full_page=False)
 page.set_viewport_size({'width':1200,'height':900});page.wait_for_timeout(250)
 assert not page.locator('main').evaluate('m=>m.inert') and not page.locator('#lab-sidebar').evaluate('s=>s.inert')
 assert page.locator('#lab-menu-toggle').is_hidden() and page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
 page.set_viewport_size({'width':390,'height':844});assert page.locator('#lab-sidebar').evaluate('s=>s.inert')
 checks.append('desktop/mobile resize clears modal state and restores desktop navigation')
 for width in [1100,1280]:
  page.set_viewport_size({'width':width,'height':900});page.goto(base+'/v13_paper',wait_until='domcontentloaded');page.wait_for_timeout(200);assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'),width
 checks.append('content layouts fit desktop widths 1100 and 1280')
 browser.close()
result=dict(mode='live' if args.live else 'preview',pages=pages,checks=checks,page_errors=errors,blocked_requests=blocked,read_only=True)
(args.evidence/('live-navigation.json' if args.live else 'preview-navigation.json')).write_text(json.dumps(result,indent=2)+'\n');assert not errors and not blocked,result
print(json.dumps(result))
