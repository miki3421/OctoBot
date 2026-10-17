"""Local GET-only browser acceptance of the separate intraday research account."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def main():
    p=argparse.ArgumentParser();p.add_argument('--origin',choices=['http://127.0.0.1:5001','http://127.0.0.1:5003'],required=True);p.add_argument('--evidence',type=Path,required=True);p.add_argument('--label',choices=['preview','live'],required=True);args=p.parse_args()
    errors=[];blocked=[]
    args.evidence.mkdir(parents=False,exist_ok=True)
    with sync_playwright() as playwright:
        browser=playwright.chromium.launch(headless=True,args=['--no-sandbox'])
        context=browser.new_context(viewport={'width':1440,'height':1100})
        def gate(route):
            if route.request.method=='GET' and route.request.url.startswith(args.origin+'/'):route.continue_()
            else:blocked.append(route.request.url);route.abort()
        context.route('**/*',gate)
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
        response=page.goto(args.origin+'/btc_intraday',wait_until='domcontentloaded');assert response.status==200
        page.wait_for_function("!document.getElementById('content').classList.contains('hidden')")
        assert 'BTC intraday' in page.title()
        assert page.locator('#equity').inner_text().endswith('USDT')
        api=context.request.get(args.origin+'/btc_intraday/data');assert api.status==200
        assert 'no-store' in api.headers['cache-control']
        data=api.json();assert data['account']=='btc-intraday-m1-l5-paper-v1' and data['no_real_orders']
        assert data['scope']=='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY'
        assert data['real_min_quantity']=='UNKNOWN' and data['real_min_notional']=='UNKNOWN'
        assert data['frequency_limits'] is False
        assert page.locator('#chart').evaluate("e=>e.width>0&&e.height>0")
        page.screenshot(path=str(args.evidence/(args.label+'-desktop.png')),full_page=True)
        page.set_viewport_size({'width':390,'height':844});page.wait_for_timeout(300)
        assert page.evaluate('document.documentElement.scrollWidth<=innerWidth+1')
        page.screenshot(path=str(args.evidence/(args.label+'-mobile.png')),full_page=True)
        if args.label=='live':
            page.goto(args.origin+'/v13_variants',wait_until='domcontentloaded')
            assert page.locator('a[href="/btc_intraday"]').count()>=1
            page.locator('a[href="/btc_intraday"]').first.click()
            page.wait_for_url('**/btc_intraday')
        browser.close()
    result=dict(label=args.label,read_only=True,page_errors=errors,blocked_requests=blocked,
                account=data['account'],status=data['status'],equity=data['metrics']['equity'],
                fills=data['state']['fills'],warmup_rows=data['warmup_rows'],mobile_no_overflow=True)
    (args.evidence/(args.label+'-browser.json')).write_text(json.dumps(result,indent=2)+'\n')
    assert not errors and not blocked,result
    print(json.dumps(result))


if __name__=='__main__':main()
