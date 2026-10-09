"""Read-only review of matured history and causal book midpoint estimates.

work-card-507f0fdb-521e-48bc-a9bb-60d17ceeee9d. No calendar or grant is emitted.
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'octobot/ai_strategy_lab'))
import v13_dynamic_data as data
import v13_funding_history_review as history
from review_v13_funding_observations import review
import v13_funding_continuity as continuity


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', required=True)
    p.add_argument('--observations', required=True)
    p.add_argument('--mapping-config', required=True)
    p.add_argument('--activation', required=True)
    p.add_argument('--history', required=True)
    p.add_argument('--start', type=int, required=True)
    p.add_argument('--end', type=int, required=True)
    p.add_argument('--output', required=True)
    args = p.parse_args()
    now = time.time()
    mapping = json.loads(Path(args.mapping_config).read_text())['mapping']
    observations = review(continuity.inspect(args.observations, mapping,
        start=args.start, end=args.end, as_of=now))
    reconciled = history.reconcile(observations, args.history, mapping, as_of=now)
    repo = Path(__file__).resolve().parents[1]
    plan = data.capture.load_plan(repo)
    activation = data.capture.decode(Path(args.activation).read_bytes())
    start = data.capture.utc(activation['start_utc'])
    binding = data.capture.sha(data.capture.canonical(activation))
    books = []
    for day in range(args.start // 86400 * 86400, args.end // 86400 * 86400 + 1, 86400):
        books.extend(data.read_day(args.archive, plan, start, binding, day, now,
                                   kinds=('books',))['records'])
    root = Path(args.history)
    envelope = data.capture.decode((root / 'report.json').read_bytes())
    receipts = []
    expected = [(s, at) for s, v in observations['symbols'].items()
                for at in v['announced_events_due']]
    for receipt in envelope['report']['receipts']:
        # URL, identity, raw hash, response and window were checked by reconcile.
        raw = data.capture.decode((root / 'raw' / (receipt['receipt_id'] + '.raw')).read_bytes())
        if raw['data'] is None:
            continue
        from urllib.parse import parse_qs, urlsplit
        remote = parse_qs(urlsplit(receipt['url']).query)['symbol'][0]
        symbol = next(s for s, r in mapping.items() if r == remote)
        receipts.append(dict(scope='VERIFIED_QUALIFICATION_RECEIPT', kind='funding',
            symbol=symbol, received_at=receipt['received_at'],
            events=[dict(at=e['timepoint'], rate=float(e['fundingRate']))
                    for e in raw['data'] if e['timepoint'] > args.start * 1000]))
    estimate = data.estimate_funding(receipts, books,
        as_of=dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(), expected=expected)
    result = dict(scope='MATURE_FUNDING_AND_PRIOR_BOOK_REVIEW_ONLY',
        history=reconciled, estimate=estimate, books_verified=len(books),
        mark_definition='CAUSAL_PRIOR_BOOK_MIDPOINT_NOT_EXCHANGE_MARK',
        funding_coverage_certified=False, execution_ready=False)
    with Path(args.output).open('x') as stream:
        json.dump(result, stream, indent=2)
    print(json.dumps(dict(history=reconciled['status'], events=len(estimate['events']),
        resolved_marks=sum(e['mark'] is not None for e in estimate['events']),
        execution_ready=False)))


if __name__ == '__main__':
    main()
