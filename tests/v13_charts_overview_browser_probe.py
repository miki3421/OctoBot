"""Read-only UI acceptance for all V13 symbol charts; localhost GETs only."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin',choices=['http://127.0.0.1:5001','http://127.0.0.1:5003'],required=True)
    parser.add_argument('--evidence',type=Path,required=True)
    parser.add_argument('--label',choices=['preview','live'],required=True)
    args=parser.parse_args();errors=[];blocked=[];checks=[]
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1100})
        def route(r):
            if r.request.method=='GET' and r.request.url.startswith(args.origin+'/'):r.continue_()
            else:blocked.append(r.request.url);r.abort()
        context.route('**/*',route);page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        response=page.goto(args.origin+'/v13_paper/charts',wait_until='networkidle');assert response.status==200
        page.wait_for_function("document.querySelectorAll('.overview-card').length===18")
        assert page.locator('#symbol-control').is_hidden()
        assert page.locator('.overview-card canvas').count()==18
        painted=page.locator('.overview-card canvas').evaluate_all("els=>els.every(e=>e.width>0&&Array.from(e.getContext('2d').getImageData(0,0,e.width,e.height).data).some((v,i)=>i%4===3&&v>0))")
        assert painted
        data=context.request.get(args.origin+'/v13_paper/charts/overview').json()
        assert len(data['charts'])==18 and len(set(data['symbols']))==18
        assert all(len(c['points'])<=800 for c in data['charts'])
        outcomes=page.evaluate("""() => [
          {action:'SELL',closed_quantity:1,realized_less_fill_fee:9.9,fee:.1,equity_impact:-.2},
          {action:'SELL',closed_quantity:1,realized_less_fill_fee:-2.1,fee:.1},
          {action:'SELL',closed_quantity:0,realized_less_fill_fee:-.1,fee:.1},
          {action:'SELL',closed_quantity:1,realized_less_fill_fee:null,fee:null},
          {action:'SELL',closed_quantity:1,realized_less_fill_fee:0,fee:.1}
        ].map(sellOutcome)""")
        assert [o['icon'] for o in outcomes]==['+','−','·','?','=']
        badges=page.evaluate("""() => [...overviewCards.values()].flatMap(card=>card.hits.filter(h=>h.outcome).map(h=>({symbol:card.item.symbol,icon:h.outcome})))""")
        assert badges and any(b['icon']=='+' for b in badges) and any(b['icon']=='−' for b in badges)
        checks.append(dict(sell_outcomes=[o['icon'] for o in outcomes],overview_badges=len(badges),profit_separate_from_equity_cost=True))
        page.screenshot(path=str(args.evidence/(args.label+'-desktop.png')))
        page.get_by_role('button',name='Apri dettaglio BTCUSDT',exact=True).click()
        page.wait_for_function("!document.getElementById('content').hidden && document.getElementById('chart-title').textContent.startsWith('BTCUSDT')")
        assert page.locator('#symbol').input_value()=='BTCUSDT'
        badge=page.evaluate("() => hits.find(h=>h.outcome==='+')")
        assert badge
        box=page.locator('#chart').bounding_box()
        page.mouse.click(box['x']+badge['x'],box['y']+badge['y'])
        assert 'Profitto realizzato meno la commissione' in page.locator('#readout').inner_text()
        assert page.locator('#detail').is_visible()
        page.screenshot(path=str(args.evidence/(args.label+'-sell-detail.png')))

        page.locator('#fills button').first.click();assert page.locator('#detail').is_visible()
        assert 'Impatto immediato' in page.locator('#detail').inner_text()
        page.get_by_role('button',name='Tutti i simboli',exact=True).click()
        page.wait_for_function("!document.getElementById('overview-content').hidden")
        page.get_by_role('button',name='24 ore',exact=True).click()
        page.wait_for_timeout(1500)
        assert page.locator('#overview-content').is_visible()
        daily=context.request.get(args.origin+'/v13_paper/charts/overview?range=1').json();assert daily['period']=='1'
        checks.append(dict(desktop_charts=18,all_painted=True,total_fills=sum(len(c['fills']) for c in data['charts']),daily_fills=sum(len(c['fills']) for c in daily['charts']),detail_accounting_visible=True))
        page.get_by_role('button',name='Tutto lo storico',exact=True).click();page.wait_for_timeout(1500)
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        boxes=page.locator('.overview-card').evaluate_all('els=>els.slice(0,2).map(e=>({x:e.getBoundingClientRect().x,y:e.getBoundingClientRect().y}))')
        assert boxes[0]['x']==boxes[1]['x'] and boxes[1]['y']>boxes[0]['y']
        page.screenshot(path=str(args.evidence/(args.label+'-mobile.png')))
        checks.append(dict(mobile_single_column=True,no_horizontal_overflow=True))
        page.goto(args.origin+'/v13_paper/charts?symbol=AAVEUSDT',wait_until='networkidle')
        page.wait_for_function("!document.getElementById('content').hidden && document.getElementById('chart-title').textContent.startsWith('AAVEUSDT')")
        checks.append(dict(direct_symbol_link=True))
        browser.close()
    result=dict(checks=checks,page_errors=errors,blocked_requests=blocked,read_only=True)
    (args.evidence/(args.label+'-browser.json')).write_text(json.dumps(result,indent=2))
    assert not errors and not blocked,result
    print(json.dumps(result))


if __name__=='__main__':main()
