"""Read-only continuity audit of public funding observations, not a grant."""
import zlib
import hashlib
import sqlite3
from pathlib import Path
try:
    from . import v13_funding_observer as observer
except ImportError:
    import v13_funding_observer as observer


def inspect(path,mapping,*,start,end,as_of):
    if type(start) is not int or type(end) is not int or start%300 or end%300 or not start<end<=as_of:
        raise ValueError('closed_observation_window_required')
    db=sqlite3.connect(Path(path).absolute().as_uri()+'?mode=ro',uri=True);db.row_factory=sqlite3.Row
    expected={(slot,symbol) for slot in range(start,end,300) for symbol in mapping}
    seen=set();invalid=[];windows={s:[] for s in mapping}
    try:
        db.execute('PRAGMA query_only=ON');db.execute('BEGIN')
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('archive_integrity')
        for r in db.execute('SELECT * FROM receipts WHERE slot>=? AND slot<? ORDER BY slot,symbol',(start,end)):
            key=(r['slot'],r['symbol'])
            if key not in expected or key in seen:raise ValueError('unexpected_receipt')
            try:
                remote=mapping[r['symbol']]
                if r['state']!='valid' or r['status']!=200 or not r['slot']<=r['started']<=r['received']<r['slot']+300 or r['received']>as_of:
                    raise ValueError('receipt_state_or_time')
                if r['url']!='https://api-futures.kucoin.com/api/v1/funding-rate/'+remote+'/current':raise ValueError('url_binding')
                if len(r['raw_gzip'])>observer.LIMIT+1024:raise ValueError('raw_size')
                decoder=zlib.decompressobj(16+zlib.MAX_WBITS);raw=decoder.decompress(r['raw_gzip'],observer.LIMIT+1)
                if len(raw)>observer.LIMIT or not decoder.eof or decoder.unused_data:raise ValueError('raw_size')
                if hashlib.sha256(raw).hexdigest()!=r['raw_sha256']:raise ValueError('raw_hash')
                v=observer.validate(raw,remote,r['started'],r['received'])
                seen.add(key);windows[r['symbol']].append(dict(received=r['received'],period_start=v['timePoint'],announced_funding_time=v['fundingTime'],granularity=v['granularity'],raw_sha256=r['raw_sha256']))
            except (ValueError,KeyError,TypeError,zlib.error):invalid.append(list(key))
        missing=sorted(expected-seen)
        return dict(status='OBSERVATIONS_COMPLETE' if not missing else 'OBSERVATION_GAPS',start=start,end=end,
                    expected=len(expected),verified=len(seen),missing=missing,invalid=invalid,windows=windows,
                    funding_coverage_certified=False,execution_ready=False)
    finally:db.close()
