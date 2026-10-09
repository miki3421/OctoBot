"""Read-only, orderless 14-day qualification evaluator. No network operations.

Card work-card-32019ba9-bcfa-49ad-b3e2-9e9e49f9f4f8. Shared capture validators
are replayed; this is an author check, not independent scientific assurance.
"""
import argparse
import gzip
import io
import math
from pathlib import Path
import sqlite3

if __package__:
    from . import v13_universe_qualification as capture
else:
    import v13_universe_qualification as capture


def percentile95(values):
    return sorted(values)[math.ceil(0.95*len(values))-1] if values else None


def longest_missing(slots):
    longest = run = 0
    for present in slots:
        run = 0 if present else run+1
        longest = max(longest, run)
    return longest*900


def summarize(universe, books, daily, funding, metadata_days, stopped=None):
    """All denominators fixed in advance; never drop a symbol or missing slot."""
    count = capture.DAYS*96
    common = [all(i in books[s] for s in universe) for i in range(count)]
    symbols = {}
    for symbol in universe:
        values = list(books[symbol].values())
        p95 = percentile95([v['spread_bps'] for v in values])
        depth = sum(v['bid_depth_usdt'] >= 3150 and v['ask_depth_usdt'] >= 3150 for v in values)
        coverage = len(values)/count
        depth_fraction = depth/len(values) if values else None
        daily_coverage = len(daily[symbol])/capture.DAYS
        funding_coverage = len(funding[symbol])/capture.DAYS
        passed = (coverage >= .95 and p95 is not None and p95 <= 20
                  and depth_fraction is not None and depth_fraction >= .95
                  and daily_coverage >= .95 and funding_coverage >= .95)
        symbols[symbol] = dict(book_coverage=coverage, valid_books=len(values), expected_books=count,
                               p95_spread_bps=p95, both_sides_depth_pass_fraction=depth_fraction,
                               daily_bar_coverage=daily_coverage,
                               funding_response_coverage=funding_coverage,
                               funding_settlement_coverage_certified=False, passed=passed)
    common_coverage = sum(common)/count
    gap = longest_missing(common)
    metadata_coverage = len(metadata_days)/capture.DAYS
    checks = dict(all_symbols=all(v['passed'] for v in symbols.values()),
                  common_book_coverage=common_coverage >= .95,
                  common_gap=gap <= 2*3600, metadata_coverage=metadata_coverage >= .95)
    status = 'QUALIFIED' if all(checks.values()) else 'NOT_QUALIFIED'
    if stopped not in (None, 'window_complete'):
        status = 'INCONCLUSIVE'
    return dict(status=status, checks=checks, symbols=symbols,
                common_book_coverage=common_coverage, maximum_common_gap_seconds=gap,
                metadata_day_coverage=metadata_coverage, collector_stop=stopped,
                percentile_method='nearest_rank_ceil_0.95_n', missing_slot_seconds=900,
                evaluation_scope='data_quality_only', orders_authorized=False,
                paper_orders_authorized=False, automatic_promotion=False,
                min_quantity=None, min_notional=None)


def raw_bytes(row):
    limit = 4*1024*1024 if row['kind'].endswith('metadata') else 64*1024
    if row['raw_gzip'] is None or len(row['raw_gzip']) > limit+2048:
        raise ValueError('invalid_receipt_size')
    with gzip.GzipFile(fileobj=io.BytesIO(row['raw_gzip'])) as archive:
        raw = archive.read(limit+1)
    if len(raw) > limit or capture.sha(raw) != row['raw_hash']:
        raise ValueError('receipt_hash_or_size')
    return raw


def evaluate(archive, plan, start, binding, now):
    """Caller supplies the frozen activation binding; do not derive trust from DB."""
    archive = Path(archive)
    if archive.is_symlink() or not archive.is_file():
        raise ValueError('archive_missing_or_symlink')
    if not math.isfinite(now) or now < start+capture.DAYS*capture.DAY:
        return dict(status='IN_PROGRESS', final_evaluation_available=False,
                    orders_authorized=False, paper_orders_authorized=False)
    collector = capture.Collector(archive.parent, plan, start, binding, None)
    with sqlite3.connect(archive.resolve().as_uri()+'?mode=ro', uri=True) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('PRAGMA trusted_schema=OFF')
        db.execute('BEGIN')
        state = collector.check(db)
        if state['last_clock'] > now:
            raise ValueError('future_archive_clock')
        # Authenticate every completed receipt, including invalid data, before use.
        for row in db.execute('SELECT * FROM jobs'):
            if row['state'] in ('valid','invalid'):
                raw_bytes(row)
                if (row['started'] is None or row['received'] is None
                        or not math.isfinite(row['started']) or not math.isfinite(row['received'])
                        or row['reserved'] != 0):
                    raise ValueError('invalid_receipt_times_or_reservation')
            elif row['state'] in ('pending','missing'):
                if row['reserved'] != 0 or any(row[k] is not None for k in
                        ('started','received','status','raw_hash','raw_gzip','metrics')):
                    raise ValueError('unattempted_state_has_receipt')
            elif row['state'] in ('claimed','uncertain'):
                if (row['started'] is None or not math.isfinite(row['started'])
                        or not row['slot'] <= row['started'] <= row['deadline']
                        or row['reserved'] <= 0 or row['raw_gzip'] is None
                        or len(row['raw_gzip']) != row['reserved']
                        or any(row[k] is not None for k in ('received','status','raw_hash','metrics'))):
                    raise ValueError('uncertain_reservation_mismatch')
            else:
                raise ValueError('unknown_job_state')
        attempts, bytes_used = db.execute('SELECT count(started),coalesce(sum(length(raw_gzip)),0) FROM jobs').fetchone()
        if attempts > capture.ATTEMPT_CAP or bytes_used > capture.RAW_CAP:
            raise ValueError('archive_over_budget')
        universe = plan['universe']
        books = {s:{} for s in universe}; daily = {s:set() for s in universe}; funding = {s:set() for s in universe}
        metadata_days = set(); contracts = {}; metadata_latest = {}
        # Validate catalogs first, then derive explicit identities once per day.
        for day in range(capture.DAYS):
            slot = start+day*capture.DAY
            rows = list(db.execute("SELECT * FROM jobs WHERE slot=? AND kind IN ('kucoin_metadata','binance_metadata') AND state='valid'",(slot,)))
            for row in rows:
                verify_valid_row(collector, row, None)
            if len(rows)==2:
                try:
                    contracts[day] = collector.contracts(db,slot)
                    metadata_latest[day] = max(row['received'] for row in rows)
                    metadata_days.add(day)
                except (ValueError, KeyError, TypeError):
                    pass  # Unusable identity denies that entire day, never selects replacements.
        for row in db.execute("SELECT * FROM jobs WHERE state='valid' AND kind IN ('books','daily','funding') ORDER BY slot,id"):
            day = int((row['slot']-start)//capture.DAY)
            if day not in contracts:
                raise ValueError('valid_sample_without_verified_identity')
            # Identity evidence must already have existed before the request.
            if row['started'] < metadata_latest[day]:
                raise ValueError('noncausal_metadata')
            metrics = verify_valid_row(collector,row,contracts[day][row['symbol']])
            if row['kind']=='books':
                books[row['symbol']][int((row['slot']-start)//900)] = metrics
            elif row['kind']=='daily':
                daily[row['symbol']].add(day)
            else:
                funding[row['symbol']].add(day)
        result = summarize(universe,books,daily,funding,metadata_days,state['stopped'])
        result.update(activation_binding=binding, proposal_sha256=capture.PROPOSAL_HASH,
                      plan_sha256=capture.PLAN_HASH, attempts=attempts,
                      compressed_bytes_and_reservations=bytes_used,
                      archive_receipts_replayed=True, final_evaluation_available=True)
        return result


def verify_valid_row(collector, row, contract):
    if (row['status'] != 200 or row['error'] is not None
            or not row['slot'] <= row['started'] <= row['received'] <= row['deadline']):
        raise ValueError('invalid_success_receipt')
    computed = collector.validate(row,raw_bytes(row),row['received'],contract)
    if capture.canonical(computed).decode() != row['metrics']:
        raise ValueError('derived_metrics_mismatch')
    return computed


def evaluate_bound(repo, archive, activation, now):
    """Reuse the CLI's root-owned activation checks for embedded callers."""
    repo, archive, activation = Path(repo), Path(archive), Path(activation)
    plan = capture.load_plan(repo)
    capture.safe_path(activation,0)
    config = capture.decode(activation.read_bytes())
    if (config.get('plan_sha256') != capture.PLAN_HASH
            or config.get('collector_sha256') != capture.sha(Path(capture.__file__).read_bytes())
            or config.get('periodic_downloads_authorized') is not True
            or config.get('service_activation_authorized') is not True
            or config.get('orders_authorized') is not False):
        raise ValueError('unapproved_activation_binding')
    start = capture.utc(config['start_utc'])
    if capture.utc(config['end_utc']) != start+capture.DAYS*capture.DAY:
        raise ValueError('activation_window')
    if archive.resolve() != (Path(config['storage_root'])/'qualification.sqlite').resolve():
        raise ValueError('archive_path_binding')
    return evaluate(archive,plan,start,capture.sha(capture.canonical(config)),now)


def main():
    import time
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repo', required=True, type=Path)
    parser.add_argument('--archive', required=True, type=Path)
    parser.add_argument('--activation', required=True, type=Path)
    args = parser.parse_args()
    try:
        result = evaluate_bound(args.repo,args.archive,args.activation,time.time())
    except (ValueError, sqlite3.Error, OSError, KeyError, TypeError, EOFError) as error:
        result = dict(status='INCONCLUSIVE',reason=type(error).__name__,orders_authorized=False,paper_orders_authorized=False)
        print(capture.canonical(result).decode())
        raise SystemExit(1)
    print(capture.canonical(result).decode())


if __name__ == '__main__':
    main()
