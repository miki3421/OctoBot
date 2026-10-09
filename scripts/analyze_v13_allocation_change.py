"""Offline decomposition of the original V13 allocation, not a signal issuer."""
import argparse
import datetime as dt
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from urllib.parse import parse_qs, urlsplit

import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from octobot.ai_strategy_lab import trend


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def decompose(approvals, source, old_day, new_day):
    root = Path(source)
    db = sqlite3.connect(Path(approvals).resolve().as_uri() + '?mode=ro&immutable=1', uri=True)
    values = {v['day']: v for (raw,) in db.execute('SELECT payload FROM approvals') for v in [json.loads(raw)]}
    db.close()
    symbols = sorted(values[old_day]['targets'])
    covariances = []
    signals = []
    for day in (old_day, new_day):
        approval = values[day]
        snap = json.loads((root / 'science' / (approval['snapshot_id'] + '.json')).read_text())
        if (hashlib.sha256(canonical({k: v for k, v in snap.items() if k != 'snapshot_id'})).hexdigest() != approval['snapshot_id']
                or snap['day'] != day or snap['published_at'] > approval['issued_at']):
            raise ValueError('snapshot_identity_or_time')
        series = {s: {} for s in symbols}
        for receipt in snap['requests']:
            if '/klines?' not in receipt['url']:
                continue
            path = root / 'raw' / (receipt['capture_id'] + '.json.gz')
            wrapped = json.loads(gzip.decompress(path.read_bytes()))
            raw = bytes.fromhex(wrapped['raw_hex'])
            if hashlib.sha256(raw).hexdigest() != receipt['raw_sha256']:
                raise ValueError('raw_hash')
            symbol = parse_qs(urlsplit(receipt['url']).query)['symbol'][0]
            for row in json.loads(raw):
                date = dt.datetime.fromtimestamp(row[0] / 1000, dt.timezone.utc).date()
                if date.isoformat() > day:
                    raise ValueError('future_bar')
                series[symbol][date] = float(row[4])
        last = dt.date.fromisoformat(day)
        dates = [last - dt.timedelta(days=n) for n in range(60, -1, -1)]
        closes = np.asarray([[series[s][d] for s in symbols] for d in dates])
        returns = closes[1:] / closes[:-1] - 1
        covariance = np.cov(returns, rowvar=False, ddof=1) * 365
        signal = np.sign([float(approval['targets'][s]) for s in symbols])
        config = next(c for c in trend.TREND_CONFIGS if c.name == 'risk_budgeted_bear_regime_v13')
        recomputed = trend._target_weights(signal, covariance, config)
        expected = np.asarray([float(approval['targets'][s]) for s in symbols])
        error = float(np.max(np.abs(expected - recomputed)))
        if error > 1e-10:
            raise ValueError('original_weight_parity_failed')
        covariances.append(covariance); signals.append(signal)
    scenarios = {}
    for name, signal, covariance in [('old', signals[0], covariances[0]),
        ('new_active_old_covariance', signals[1], covariances[0]),
        ('old_active_new_covariance', signals[0], covariances[1]),
        ('new', signals[1], covariances[1])]:
        weights = trend._target_weights(signal, covariance, config)
        scenarios[name] = dict(weights=dict(zip(symbols, map(float, weights))),
            gross=float(np.sum(np.abs(weights))), active=int(np.count_nonzero(signal)),
            btc=float(weights[symbols.index('BTCUSDT')]))
    old, active, covariance, new = (scenarios[k]['btc'] for k in
        ('old', 'new_active_old_covariance', 'old_active_new_covariance', 'new'))
    # Shapley two-factor attribution avoids assigning the interaction to one factor.
    active_effect = .5 * ((active - old) + (new - covariance))
    covariance_effect = .5 * ((covariance - old) + (new - active))
    return dict(scope='ALLOCATION_CAUSE_DIAGNOSTIC_ONLY', old_day=old_day, new_day=new_day,
        original_weights_reproduced=True, scenarios=scenarios,
        btc_weight_delta=new-old, active_set_effect=active_effect,
        covariance_effect=covariance_effect,
        active_set_fraction_of_drop=active_effect/(new-old) if new != old else None,
        covariance_fraction_of_drop=covariance_effect/(new-old) if new != old else None)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('approvals','source','old-day','new-day','output'):
        p.add_argument('--'+name, required=True)
    args = p.parse_args()
    result = decompose(args.approvals,args.source,args.old_day,args.new_day)
    with Path(args.output).open('x') as stream:
        json.dump(result,stream,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!='scenarios'}))


if __name__ == '__main__':
    main()
