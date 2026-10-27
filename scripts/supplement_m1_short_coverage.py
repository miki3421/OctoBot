"""Retain all base-qualified cases hidden by the predeclared stress intersection.

This is a coverage supplement after inspecting the main result, not a new
primary sample, strategy version, parameter search or qualification claim.
The original common-scenario aggregate is never modified.
"""
import argparse
import copy
import datetime as dt
import hashlib
import importlib.util
import json
from pathlib import Path

SPEC=importlib.util.spec_from_file_location('broader',Path(__file__).with_name('qualify_m1_short_broader.py'))
b=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(b)


def run(e):
    e=Path(e);contract=json.loads((e/'evaluation-contract.json').read_text())
    for name,h in {**contract['evaluation_code_sha256'],**contract['frozen_code_sha256']}.items():
        if b.sha(b.ROOT/name)!=h:raise ValueError('frozen_code_changed')
    result=json.loads((e/'results.json').read_text());inventory=json.loads((e/'inventory.json').read_text())
    plan=json.loads((e/'coverage-supplement-plan.json').read_text())
    if plan['primary_result_sha256']!=b.sha(e/'results.json'):
        raise ValueError('primary_result_changed')
    grid=json.loads((e/'grid.json').read_text());index=json.loads((e/'book_index.json').read_text())
    signals={b.iso(x['slot']):x for x in json.loads((e/'signals.json').read_text())}
    with b.sealed_db(inventory['source'],inventory['source_sha256']) as db:
        marks={s:[] for s in b.R.SIGNALS}
        for x in db.execute('SELECT bar,symbol,price FROM marks ORDER BY bar,symbol'):
            marks[x['symbol']].append((b.stamp(x['bar']),x['price']))
    environment=json.loads((e/'environment.json').read_text())
    books=b.Books(e,environment['archive_source'],index,b.stamp(inventory['last'])+300,marks)
    rows=copy.deepcopy(result['scenarios']['base']['episodes']);existing={x['signal_at'] for x in rows}
    base_failures={x['signal_at'] for x in result['rejected'] if x['scenario']=='base'}
    eligible=[x['signal_at'] for x in result['selected'] if x['signal_at'] not in existing|base_failures]
    if eligible!=plan['uniform_base_only_signal_times']:
        raise ValueError('supplement_selection_changed')
    scenario=next(x for x in contract['scenarios'] if x['name']=='base');cache={}
    for at in eligible:
        value=b.pair(json.loads((b.ROOT/'docs/research-protocols/m1-short-risk-exits-candidate-v1.json').read_text()),
                     signals[at],grid,books,marks,scenario,contract['capital_reference'],cache)
        for arm in ('corrected','six_hour'):value[arm].pop('path')
        rows.append(value)
    rows.sort(key=lambda x:x['signal_at'])
    output=dict(scope='POST_PRIMARY_COVERAGE_SUPPLEMENT_NO_NEW_PRIMARY_OR_RULES',
                created_at=dt.datetime.now(dt.timezone.utc).isoformat(),primary_result_unchanged=True,
                extra_base_only_times=eligible,summary=b.aggregate(rows),episodes=rows,
                interpretation='All base-qualified cases in the same selected cohort; unequal stress eligibility prevents direct cross-scenario total comparison.')
    (e/'coverage-supplement.json').write_text(json.dumps(output,indent=2)+'\n')
    print(json.dumps(output['summary'],indent=2))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--evidence',required=True,type=Path)
    run(p.parse_args().evidence)
