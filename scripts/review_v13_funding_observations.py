"""Read-only funding-window review; never creates an approved calendar.

Card work-card-ad198a58-f077-4c6a-871c-e734ec5d32e0.
Reports announcements and transitions, not settled rates or mark-price coverage.
"""
import argparse
import json
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'octobot/ai_strategy_lab'))
import v13_funding_continuity as continuity


def review(result):
    symbols = {}
    for symbol, samples in result['windows'].items():
        distinct = []
        changes = []
        for sample in samples:
            window = {k: sample[k] for k in ('period_start', 'announced_funding_time', 'granularity')}
            if not distinct or window != distinct[-1]['window']:
                if distinct:
                    previous = distinct[-1]['window']
                    changes.append(dict(observed_at=sample['received'], previous=previous, current=window,
                        contiguous_boundary=previous['announced_funding_time']==window['period_start'],
                        interval_changed=previous['granularity']!=window['granularity']))
                distinct.append(dict(window=window, first_received=sample['received'],
                                     raw_sha256=sample['raw_sha256']))
        # Only announcements seen strictly before their declared settlement.
        due = sorted({s['announced_funding_time'] for s in samples
                      if s['received']*1000 < s['announced_funding_time'] <= result['end']*1000})
        symbols[symbol] = dict(observations=len(samples), distinct_windows=distinct,
                               transitions=changes, announced_events_due=due,
                               settlement_reconciliation='PENDING_HISTORY_RECONCILIATION' if due else 'NO_SETTLEMENT_DUE_IN_OBSERVED_WINDOW')
    return dict(scope='FUNDING_OBSERVATION_REVIEW_NOT_CALENDAR',
                status=result['status'], start=result['start'], end=result['end'],
                expected=result['expected'], verified=result['verified'],
                missing=result['missing'], invalid=result['invalid'], symbols=symbols,
                funding_coverage_certified=False, execution_ready=False,
                remaining=['independent_settlement_history_reconciliation', 'prior_mark_coverage',
                           'reviewed_calendar_for_execution_interval'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive',required=True);p.add_argument('--mapping-config',required=True)
    p.add_argument('--start',required=True,type=int);p.add_argument('--end',required=True,type=int)
    p.add_argument('--output',required=True)
    p.add_argument('--history',help='Separately acquired public history receipt directory')
    a=p.parse_args()
    mapping=json.loads(Path(a.mapping_config).read_text())['mapping']
    result=review(continuity.inspect(a.archive,mapping,start=a.start,end=a.end,as_of=time.time()))
    if a.history:
        from v13_funding_history_review import reconcile
        result['history_reconciliation']=reconcile(result,a.history,mapping,as_of=time.time())
    with Path(a.output).open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps({k:result[k] for k in ('status','expected','verified','funding_coverage_certified')}))


if __name__=='__main__':main()
