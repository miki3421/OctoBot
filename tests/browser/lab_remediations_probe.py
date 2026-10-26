"""GET-only live delivery check for the 26 October maintenance package."""
import json
from pathlib import Path
from playwright.sync_api import sync_playwright

base = 'http://127.0.0.1:5001'
out = Path('/evidence/browser-remediations')
out.mkdir(exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(headless=True, args=['--no-sandbox'])
    page = browser.new_page(viewport={'width': 1436, 'height': 1314})
    errors, writes = [], []
    page.on('pageerror', lambda error: errors.append(str(error)))
    page.on('request', lambda request: writes.append(request.url) if request.method != 'GET' else None)
    page.goto(base + '/v13_variants', wait_until='networkidle')
    page.wait_for_function("document.querySelector('#cards').children.length === 6")
    data = page.request.get(base + '/v13_variants/data').json()
    assert data['m1']['health']['reason'] is None
    assert data['m1']['control']['baseline_error'] is None
    assert data['m1']['control']['baseline_day'] == '2026-10-25'
    assert any(slot['slot'].startswith('2026-10-26') and slot['status'] == 'DENIED'
               for slot in data['m1']['daily_slots'])
    latest = next(slot for slot in data['slots'] if slot['status'] == 'EXECUTED')
    assert latest['detail']['risk_matched'] is False
    assert 'Risultati non qualificati a parità di rischio' in page.locator('#status').inner_text()
    page.screenshot(path=str(out / 'comparison.png'), full_page=True)
    page.goto(base + '/v13_variants/m1/review', wait_until='networkidle')
    page.locator('#automatic-review').get_by_role('heading', name='Approvazione automatica ponderata · attiva').wait_for()
    assert page.locator('#weekly-approve').is_hidden()
    value = page.request.get(base + '/v13_variants/m1/review/weekly').json()
    assert value['automatic_review']['enabled']
    assert value['policy']['short_caps'] == value['proposal']['short_reference_caps']
    page.goto(base + '/v13_paper', wait_until='networkidle')
    page.wait_for_function("document.querySelector('#analysis-report-updated').textContent === 'Rapporto pubblicato'")
    report = page.request.get(base + '/v13_paper/analysis').json()['report']
    assert report['available'] and report['status'] == 'ready'
    page.locator('section[aria-labelledby="qwen-analysis-title"]').screenshot(path=str(out / 'qwen-report.png'))
    for route in ('/v13_variants/m1/charts', '/v13_variants/fast', '/v13_variants/half',
                  '/btc_intraday_pair', '/btc_intraday', '/qwen_shadow'):
        assert page.request.get(base + route).status == 200
    assert not errors, errors
    assert not writes, writes
    result = dict(passed=True, visible_accounts=6, m1_baseline_current=True,
                  denied_slot_preserved=True, automatic_review=True, short_budget_preserved=True,
                  unequal_risk_notice=True, qwen_report_ready=True, write_requests=0, errors=errors)
    (out / 'result.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))
    browser.close()
