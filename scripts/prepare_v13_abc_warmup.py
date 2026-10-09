"""Explicit one-shot public warm-up acquisition. Never backdates receipts.

Card work-card-2bbccd2a-2d67-4f98-b07b-fa5d30863aab.
An existing output directory is refused; no qualification archive is opened.
"""
import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'octobot/ai_strategy_lab'))
import v13_universe_qualification as capture


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True)
    parser.add_argument('--public-downloads-authorized', action='store_true', required=True)
    args = parser.parse_args()
    repo = Path(__file__).resolve().parents[1]
    plan = capture.load_plan(repo)
    root = Path(args.output).absolute()
    root.mkdir(mode=0o755)
    (root / 'raw').mkdir()
    end = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
    start = end - dt.timedelta(days=121)
    report = dict(scope='PRE_FORWARD_WARMUP_ACQUIRED_NOW', orders_authorized=False,
                  forward_backfill=False, receipts=[], from_utc=start.isoformat(),
                  to_exclusive_utc=end.isoformat(), plan_sha256=capture.PLAN_HASH)
    failed = False
    for symbol in sorted(plan['universe']):
        url = capture.BASE['daily'] + '?' + urlencode(dict(symbol=symbol, interval='1d',
            startTime=int(start.timestamp()*1000), endTime=int(end.timestamp()*1000)-1, limit=121))
        started = dt.datetime.now(dt.timezone.utc).isoformat()
        try:
            status, raw = capture.public_get(url, 65536)
        except (OSError, ValueError):
            status, raw = 0, b''
        received = dt.datetime.now(dt.timezone.utc).isoformat()
        receipt = dict(url=url, started_at=started, received_at=received,
                       status=status, raw_sha256=capture.sha(raw))
        receipt['receipt_id'] = capture.sha(capture.canonical(receipt))
        (root / 'raw' / (receipt['receipt_id']+'.raw')).write_bytes(raw)
        report['receipts'].append(receipt)
        (root / 'report.json').write_text(json.dumps(dict(report=report,
            report_sha256=capture.sha(capture.canonical(report))), indent=2))
        if status != 200 or len(raw)>65536:
            failed = True
        if status in (418, 429):
            break
    if failed or len(report['receipts']) != 29:
        raise SystemExit('Acquisition incomplete; preserved receipts, no retry or readiness claim')
    print(json.dumps(dict(receipts=len(report['receipts']), report_sha256=capture.sha(capture.canonical(report)))))


if __name__ == '__main__':
    main()
