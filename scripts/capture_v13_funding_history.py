"""One-shot authorized funding history acquisition; no credentials or accounts."""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'octobot/ai_strategy_lab'))
import v13_universe_qualification as capture


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--mapping-config',required=True);p.add_argument('--output',required=True)
    p.add_argument('--start',required=True,type=int);p.add_argument('--end',required=True,type=int)
    p.add_argument('--public-downloads-authorized',required=True,action='store_true')
    a=p.parse_args()
    if not 0<a.start<a.end<=time.time() or a.end-a.start>86400:raise ValueError('closed_window_at_most_one_day')
    mapping=json.loads(Path(a.mapping_config).read_text())['mapping']
    plan=capture.load_plan(Path(__file__).resolve().parents[1])
    if mapping!=plan['symbol_mapping_to_verify_at_collection']:raise ValueError('approved_mapping_required')
    root=Path(a.output);root.mkdir();(root/'raw').mkdir()
    report=dict(scope='PUBLIC_FUNDING_HISTORY_REVIEW',receipts=[])
    for symbol,remote in sorted(mapping.items()):
        url=capture.BASE['funding']+'?'+urlencode(dict(symbol=remote,**{'from':a.start*1000,'to':a.end*1000}))
        started=dt.datetime.now(dt.timezone.utc).isoformat()
        try:status,raw=capture.public_get(url,65536)
        except (OSError,ValueError):status,raw=0,b''
        r=dict(url=url,status=status,started_at=started,received_at=dt.datetime.now(dt.timezone.utc).isoformat(),raw_sha256=capture.sha(raw))
        r['receipt_id']=capture.sha(capture.canonical(r));report['receipts'].append(r)
        (root/'raw'/(r['receipt_id']+'.raw')).write_bytes(raw)
        (root/'report.json').write_text(json.dumps(dict(report=report,report_sha256=capture.sha(capture.canonical(report))),indent=2))
        if status!=200 or len(raw)>65536:raise SystemExit('Capture stopped; receipts preserved, no implicit retry')
    print(json.dumps(dict(receipts=len(report['receipts']),execution_ready=False)))


if __name__=='__main__':main()
