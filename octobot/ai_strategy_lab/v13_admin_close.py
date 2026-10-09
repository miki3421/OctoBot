"""Executor-owned local administrative reduction for isolated BTC paper account."""
from __future__ import annotations

import argparse
from contextlib import closing
import datetime as dt
from decimal import Decimal
import fcntl
import json
import math
import os
import pathlib
import socket
import sqlite3
import stat
import struct

from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab import v13_market, v13_market_sanity, v13_paper_v2 as paper

UTC = dt.timezone.utc
FIELDS = frozenset(('schema_version','command_id','account','symbol','position_id',
    'position_generation','issued_at','expires_at','maximum_quantity_to_reduce'))
MAX_VALIDITY = dt.timedelta(minutes=5)


def validate(command, now):
    if not isinstance(command,dict) or set(command) != FIELDS or command['schema_version'] != 1:
        raise ValueError('admin_command_schema_invalid')
    if not auth.identifier(command['command_id']) or not auth.identifier(command['position_id']):
        raise ValueError('admin_command_identity_invalid')
    if command['account'] != 'v13-paper-v2' or command['symbol'] != 'BTCUSDT':
        raise ValueError('admin_command_scope_invalid')
    if type(command['position_generation']) is not int or command['position_generation'] < 1:
        raise ValueError('admin_command_generation_invalid')
    issued, expires = auth.timestamp(command['issued_at']), auth.timestamp(command['expires_at'])
    if not issued <= now < expires or expires-issued > MAX_VALIDITY:
        raise ValueError('admin_command_expired_or_future')
    quantity = command['maximum_quantity_to_reduce']
    if type(quantity) not in (int,float) or not math.isfinite(quantity) or quantity <= 0:
        raise ValueError('admin_command_quantity_invalid')
    return command


def execute(command, *, ledger_path, market_journal, lock_path, now=None, fault=None):
    now = now or dt.datetime.now(UTC)
    validate(command,now)
    lock_path = pathlib.Path(lock_path)
    lock_path.parent.mkdir(parents=True,exist_ok=True)
    with lock_path.open('a+') as lock:
      fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
      with closing(paper.init_db(pathlib.Path(ledger_path))) as db:
        db.execute('''CREATE TABLE IF NOT EXISTS admin_commands (
            command_id TEXT PRIMARY KEY, position_id TEXT NOT NULL,
            position_generation INTEGER NOT NULL, applied_at TEXT NOT NULL,
            market_hash TEXT NOT NULL, quantity REAL NOT NULL)''')
        db.execute('''CREATE TABLE IF NOT EXISTS admin_denials (
            id INTEGER PRIMARY KEY, command_id TEXT, checked_at TEXT NOT NULL,
            reason_code TEXT NOT NULL)''')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('execution_integrity_failure')
        db.execute('BEGIN IMMEDIATE')
        try:
            if db.execute('SELECT 1 FROM admin_commands WHERE command_id=?',(command['command_id'],)).fetchone():
                raise ValueError('admin_command_replay')
            row = db.execute('SELECT payload FROM state WHERE id=1').fetchone()
            if row is None:
                raise ValueError('position_missing')
            state = json.loads(row[0],object_pairs_hook=auth.unique_object)
            # An outstanding strategy target has no authority in this path.
            state['pending'] = None
            position = state.get('positions',{}).get('BTCUSDT')
            if (not isinstance(position,dict) or not position.get('quantity')
                or position.get('position_id') != command['position_id']
                or position.get('position_generation') != command['position_generation']):
                raise ValueError('position_identity_mismatch')
            old = float(position['quantity'])
            maximum = float(command['maximum_quantity_to_reduce'])
            if maximum > abs(old):
                raise ValueError('admin_close_exceeds_position')
            record = v13_market.load_latest_market(market_journal,now)
            if record.get('schema_version') != 2:
                raise ValueError('market_schema_v2_required')
            quote = v13_market.market_quotes(record,{'BTCUSDT'})['BTCUSDT']
            v13_market_sanity.structure_and_time('BTCUSDT',quote,record,now)
            marked, passive_fills, funding, marks = paper.process_market(state,record,{'BTCUSDT':quote},now)
            if passive_fills:
                raise ValueError('unexpected_strategy_fill')
            marked_position = marked['positions']['BTCUSDT']
            if marked_position['quantity'] != old:
                raise ValueError('position_changed_during_mark')
            delta = -math.copysign(maximum,old)
            if maximum < abs(old):
                step = Decimal(str(quote['step']))
                if step <= 0 or Decimal(str(maximum)) % step != 0:
                    raise ValueError('partial_reduction_step_invalid')
            new_quantity = old + delta
            if not (abs(new_quantity) < abs(old) and (new_quantity == 0 or math.copysign(1,new_quantity)==math.copysign(1,old))):
                raise ValueError('admin_close_not_reducing')
            v13_market_sanity.preflight('BTCUSDT',quote,delta,True)
            price = v13_market.fill_price(quote,delta)
            fee = abs(delta)*price*quote['fee_rate']
            realized_before = marked_position['realized_pnl']
            paper.apply_fill(marked_position,delta,price,fee)
            if not math.isclose(marked_position['quantity'],new_quantity,abs_tol=1e-10):
                raise ValueError('admin_close_post_fill_mismatch')
            marked['order_count'] += 1
            marked['last_market_hash'] = record['record_hash']
            marked['last_market_at'] = record['observed_at_end']
            marked['risk'] = {'action':'admin_protective_reduction','reason':None,
                'command_id':command['command_id'],'checked_at':now.isoformat()}
            metrics = paper.totals(marked,require_positive=False)
            if fault == 'before_claim':
                raise RuntimeError('before_claim')
            db.execute('INSERT INTO admin_commands VALUES (?,?,?,?,?,?)',
                (command['command_id'],command['position_id'],command['position_generation'],
                 now.isoformat(),record['record_hash'],delta))
            if fault == 'after_claim':
                raise RuntimeError('after_claim')
            db.execute('''INSERT INTO orders(bar,symbol,action,weight,notional,fee,status,quantity,
                price,recorded_at,decision_hash,market_hash,realized_pnl)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (quote['timestamp'],'BTCUSDT','BUY' if delta>0 else 'SELL',None,delta*price,fee,
                 'filled',delta,price,now.isoformat(),command['command_id'],record['record_hash'],
                 marked_position['realized_pnl']-realized_before))
            db.executemany('INSERT INTO funding_events VALUES (?,?,?,?,?,?)',funding)
            db.executemany('INSERT INTO marks VALUES (?,?,?)',marks)
            db.execute('INSERT INTO market_events VALUES (?,?,?,?)',
                (record['record_hash'],record['observed_at_end'],now.isoformat(),json.dumps(record,sort_keys=True)))
            db.execute('INSERT INTO risk_events VALUES (?,?)',
                (record['record_hash'],json.dumps(marked['risk'],sort_keys=True)))
            db.execute('INSERT INTO equity_history VALUES (?,?,?)',
                (record['observed_at_end'],metrics['equity'],metrics['pnl']))
            db.execute('INSERT OR REPLACE INTO state VALUES (1,?)',(json.dumps(marked,sort_keys=True),))
            db.commit()
            return {'accepted':True,'reason':'admin_protective_reduction','orders':1,
                    'position':marked_position['quantity'],'equity':metrics['equity']}
        except BaseException as exc:
            db.rollback()
            try:
                db.execute('INSERT INTO admin_denials(command_id,checked_at,reason_code) VALUES (?,?,?)',
                    (command['command_id'],now.isoformat(),str(exc)))
                db.commit()
            except (OSError,sqlite3.Error):
                db.rollback()
            raise


def serve(socket_path, *, allowed_uid, allowed_gid, ledger_path, market_journal, lock_path):
    """SO_PEERCRED is mandatory; socket and parent are executor-owned local storage."""
    if not hasattr(socket,'SO_PEERCRED'):
        raise RuntimeError('peer_credentials_unavailable')
    path=pathlib.Path(socket_path)
    parent=path.parent.stat()
    if parent.st_uid != os.geteuid() or parent.st_mode & 0o022:
        raise ValueError('admin_socket_directory_unsafe')
    if path.exists() or path.is_symlink():
        raise ValueError('admin_socket_already_exists')
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
        server.bind(str(path))
        os.chmod(path,0o660)
        server.listen(8)
        try:
            while True:
                connection,_=server.accept()
                with connection:
                    pid,uid,gid=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))
                    if (uid,gid)!=(allowed_uid,allowed_gid):
                        connection.sendall(b'{"accepted":false,"reason":"admin_peer_denied"}\n')
                        continue
                    connection.settimeout(5)
                    raw=b''
                    while len(raw)<=4096 and not raw.endswith(b'\n'):
                        chunk=connection.recv(min(4097-len(raw),1024))
                        if not chunk:
                            break
                        raw+=chunk
                    if len(raw)>4096 or not raw.endswith(b'\n'):
                        connection.sendall(b'{"accepted":false,"reason":"admin_command_size_invalid"}\n')
                        continue
                    try:
                        command=json.loads(raw,object_pairs_hook=auth.unique_object)
                        result=execute(command,ledger_path=ledger_path,market_journal=market_journal,lock_path=lock_path)
                    except (ValueError,OSError,sqlite3.Error) as exc:
                        result={'accepted':False,'reason':str(exc),'orders':0}
                    connection.sendall((json.dumps(result,sort_keys=True)+'\n').encode())
        finally:
            path.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('socket','ledger','market-journal','lock'):
        parser.add_argument('--'+name,required=True,type=pathlib.Path)
    parser.add_argument('--allowed-uid',required=True,type=int)
    parser.add_argument('--allowed-gid',required=True,type=int)
    args=parser.parse_args()
    serve(args.socket,allowed_uid=args.allowed_uid,allowed_gid=args.allowed_gid,
          ledger_path=args.ledger,market_journal=args.market_journal,lock_path=args.lock)


if __name__ == '__main__':
    main()
