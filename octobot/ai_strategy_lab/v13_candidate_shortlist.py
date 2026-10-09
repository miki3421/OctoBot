"""Frozen, descriptive shortlist. Card 06360869; no execution surface/network."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import statistics

if __package__:
    from . import v13_universe_view as view
else:  # Standalone offline tool/tests; no numerical package bootstrap.
    import v13_universe_view as view

VERSION = 'v13-shortlist-research-v1'
POLICY = {'minimum_age_days': 365, 'minimum_turnover_usdt': 5000000,
          'maximum_candidates': 12, 'minimum_dates': 2, 'maximum_dates': 3}
PROTOCOL = 'docs/V13_SHORTLIST_RESEARCH_V1.md'
REPORT = 'docs/data/v13-shortlist-research-v1.json'


def build(samples, cutoff, protocol_hash):
    """samples are verified view.project outputs, one per UTC date."""
    if not 2 <= len(samples) <= 3:
        raise ValueError('insufficient_sample_dates')
    samples = sorted(samples, key=lambda s: s['as_of'])
    dates = [view.timestamp(s['as_of']).date() for s in samples]
    if len(set(dates)) != len(dates) or any(view.timestamp(s['as_of']) > cutoff for s in samples):
        raise ValueError('invalid_sample_dates')
    universe_hash = samples[0]['universe_hash']
    if any(not s['available'] or s['universe_hash'] != universe_hash for s in samples):
        raise ValueError('inconsistent_universe')
    maps = [{r['symbol']: r for r in s['rows']} for s in samples]
    pool = [r for r in samples[-1]['rows'] if r['group'] == 'candidate']
    rows = []
    for current in pool:
        symbol = current['symbol']; observations = [m.get(symbol) for m in maps]
        reasons = []
        if any(r is None or r['group'] != 'candidate' for r in observations):
            reasons.append('Assente o fuori ambito in almeno una data campionata')
        ages = [r.get('age_days') if r else None for r in observations]
        activity = [r.get('turnover_24h') if r and r.get('turnover_currency') == 'USDT' else None for r in observations]
        if any(a is None for a in ages):
            reasons.append('Data di prima apertura non verificabile in tutti i campioni')
        elif min(ages) < POLICY['minimum_age_days']:
            reasons.append('Apertura dichiarata da meno di 365 giorni in almeno un campione')
        if any(a is None for a in activity):
            reasons.append('Turnover USDT non disponibile in tutti i campioni')
        elif min(activity) < POLICY['minimum_turnover_usdt']:
            reasons.append('Turnover 24h sotto 5 milioni USDT in almeno un campione')
        complete = all(a is not None for a in activity)
        rows.append({'symbol': symbol, 'eligible': not reasons, 'selected': False,
                     'reasons': reasons, 'median_turnover_usdt': statistics.median(activity) if complete else None,
                     'minimum_turnover_usdt': min(activity) if complete else None,
                     'minimum_age_days': min(ages) if all(a is not None for a in ages) else None,
                     'turnover_samples': activity, 'history_status': 'NOT_VERIFIED',
                     'depth_status': 'NOT_MEASURED', 'correlation_status': 'NOT_COMPUTED',
                     'min_quantity': None, 'min_notional': None})
    eligible = sorted((r for r in rows if r['eligible']), key=lambda r: (-r['median_turnover_usdt'], r['symbol']))
    for rank, row in enumerate(eligible, 1):
        row['activity_rank'] = rank
        row['selected'] = rank <= POLICY['maximum_candidates']
        row['reasons'] = (['Supera i filtri esplorativi in tutte le date; posizione '+str(rank)+' per attività mediana']
                          if row['selected'] else ['Supera i filtri, oltre il limite esplorativo di 12 simboli'])
    return {'version': VERSION, 'scope': 'OBSERVATION_ONLY', 'created_at': cutoff.isoformat(),
            'protocol_sha256': protocol_hash, 'policy': dict(POLICY), 'universe_hash': universe_hash,
            'samples': [{k: s[k] for k in ('as_of', 'capture_id', 'raw_sha256')} for s in samples],
            'counts': {'examined': len(rows), 'eligible': len(eligible),
                       'selected': min(len(eligible), POLICY['maximum_candidates'])},
            'rows': sorted(rows, key=lambda r: (not r['selected'], r.get('activity_rank', 9999), r['symbol'])),
            'orders_authorized': False, 'paper_orders_authorized': False,
            'limitations': ['Poche date osservate; turnover 24h potenzialmente sovrapposti',
                            'Apertura dichiarata non equivale a storico disponibile',
                            'Liquidità eseguibile e correlazioni non ancora verificate']}


def sample_archive(root, repo, cutoff):
    """Offline scan; reject corrupt records rather than selecting around them."""
    root, repo = Path(root), Path(repo)
    by_date = {}
    for path in sorted((root / 'market').glob('*.json.gz')):
        m = view._read(path, view.CAPTURE_UID)
        when = view.timestamp(m['observed_at_end'])
        if when > cutoff:
            continue
        if m['record_hash'] != view.digest({k: v for k, v in m.items() if k != 'record_hash'}):
            raise ValueError('archive_record_hash_mismatch')
        noon = dt.datetime.combine(when.date(), dt.time(12), dt.timezone.utc)
        key = (abs((when - noon).total_seconds()), when)
        if when.date() not in by_date or key < by_date[when.date()][0]:
            by_date[when.date()] = (key, m)
    contract_raw = (repo / 'docs/contracts/v13-original-portfolio-adapter-candidate-v1.json').read_bytes()
    if hashlib.sha256(contract_raw).hexdigest() != view.CONTRACT_HASH:
        raise ValueError('contract_changed')
    contract = view.decode(contract_raw); samples = []
    for day in sorted(by_date)[-POLICY['maximum_dates']:]:
        m = by_date[day][1]; cid = m['capture_ids'][0]
        if not isinstance(cid, str) or not view.re.fullmatch(r'[a-f0-9]{64}', cid):
            raise ValueError('invalid_capture_id')
        receipt = view._read(root / 'raw' / (cid + '.json.gz'), view.CAPTURE_UID)
        samples.append(view.project(m, receipt, contract, cutoff))
    return samples


def load_public(repo='/workspace'):
    repo = Path(repo)
    envelope = view.decode((repo / REPORT).read_bytes()); report = envelope['report']
    if envelope['report_sha256'] != view.digest(report):
        raise ValueError('shortlist_report_changed')
    if report['version'] != VERSION or report['scope'] != 'OBSERVATION_ONLY' or report['policy'] != POLICY:
        raise ValueError('wrong_shortlist_contract')
    if report['protocol_sha256'] != hashlib.sha256((repo / PROTOCOL).read_bytes()).hexdigest():
        raise ValueError('shortlist_protocol_changed')
    if report['orders_authorized'] is not False or report['paper_orders_authorized'] is not False:
        raise ValueError('unexpected_authority')
    return dict(available=True, report_sha256=envelope['report_sha256'], **report)


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Offline frozen shortlist; output must be new.')
    parser.add_argument('--source', required=True); parser.add_argument('--repo', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    cutoff = dt.datetime.now(dt.timezone.utc)
    samples = sample_archive(args.source, args.repo, cutoff)
    result = build(samples, cutoff, hashlib.sha256((Path(args.repo) / PROTOCOL).read_bytes()).hexdigest())
    with open(args.output, 'x') as stream:
        json.dump({'report': result, 'report_sha256': view.digest(result)}, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'counts': result['counts'], 'samples': result['samples'],
                      'selected': [r['symbol'] for r in result['rows'] if r['selected']]}))
