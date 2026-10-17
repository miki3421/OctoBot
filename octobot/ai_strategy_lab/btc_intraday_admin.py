"""Local authenticated root-only protective close, for the synthetic intraday account only."""
import argparse
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from btc_intraday_paper import ACCOUNT,SCOPE,atomic


def request(state,now_ns):
    if state['account']!=ACCOUNT or state['scope']!=SCOPE or state['q']>=0:
        raise ValueError('no_matching_short_position')
    return dict(schema=1,account=ACCOUNT,action='CLOSE_ONLY',position_id=ACCOUNT+':'+str(state['position_generation']),
                generation=state['position_generation'],maximum_quantity_btc=abs(state['q']),
                nonce=uuid.uuid4().hex,issued_ns=now_ns,expires_ns=now_ns+60_000_000_000,
                administrator=dict(uid=0,channel='AUTHENTICATED_LOCAL_ROOT_OWNED_FILE'))


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--account-db',required=True);p.add_argument('--control',required=True);args=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('local root authentication required')
    directory=Path(args.control)
    if directory.is_symlink() or directory.stat().st_uid!=0 or directory.stat().st_mode&0o022:
        raise SystemExit('root-owned control directory required')
    db=sqlite3.connect(Path(args.account_db).resolve().as_uri()+'?mode=ro',uri=True)
    try:state=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    finally:db.close()
    old=os.umask(0o027)
    try:atomic(directory/'close.json',request(state,time.time_ns()))
    finally:os.umask(old)
    print('Richiesta locale di chiusura protettiva registrata; il runner verifichera posizione, scadenza e book fresco.')
