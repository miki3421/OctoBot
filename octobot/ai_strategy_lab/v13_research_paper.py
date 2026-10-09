"""Isolated original V13 research-paper roles; never an exchange order client.

Work card: work-card-77c03de2-8219-4ee0-8d56-a8651e760613.
Approvals and execution have separate writers/files; historical V2 is retained.
"""
from __future__ import annotations
import argparse
from contextlib import nullcontext
import copy
from decimal import Decimal, ROUND_DOWN, ROUND_UP, ROUND_FLOOR
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import socket
import sqlite3
import struct
import time

from octobot.ai_strategy_lab import v13_research_source as source
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from octobot.ai_strategy_lab import v13_market as market
from octobot.ai_strategy_lab import v13_market_sanity as sanity
from octobot.ai_strategy_lab import v13_exposure as exposure
from octobot.ai_strategy_lab import paper_authorization as auth


def db(path, readonly=False):
    path=Path(path)
    if path.is_symlink():raise p.Rejected('database_symlink')
    connection=sqlite3.connect(path.as_uri()+'?mode=ro' if readonly else str(path),uri=readonly,timeout=10)
    if not readonly:
        connection.execute('PRAGMA synchronous=FULL')
        connection.execute('PRAGMA journal_mode=DELETE')
    return connection


def producer(c):
    snap=source.owned_json(Path(c['source'])/'science.json',c['uids']['capture'])
    target=Path(c['proposals'])/'latest.json'
    if target.exists() and source.owned_json(target,c['uids']['producer'])['snapshot_id']==snap['snapshot_id']:return
    derivation=source.derive(c,snap,with_identity=True)
    proposal=dict(scope=source.SCOPE,account=c['account'],epoch=c['epoch'],lineage=c['contract']['scientific_lineage_ref'],
        contract_sha256=c['contract_sha256'],snapshot_id=snap['snapshot_id'],day=snap['day'],**derivation,
        created_at=source.now().isoformat(),scientific_validity='UNASSESSED')
    proposal['proposal_id']=p.digest(proposal)
    source.atomic(Path(c['proposals'])/(proposal['proposal_id']+'.json'),proposal)
    source.atomic(target,proposal)


def issuer(c):
    proposal=source.owned_json(Path(c['proposals'])/'latest.json',c['uids']['producer'])
    if set(proposal)!={'scope','account','epoch','lineage','contract_sha256','snapshot_id','day','targets','created_at','scientific_validity','proposal_id','causal_input_hash','decision_id'} or proposal['scientific_validity']!='UNASSESSED':raise p.Rejected('proposal_schema')
    if proposal['proposal_id']!=p.digest({k:v for k,v in proposal.items() if k!='proposal_id'}):raise p.Rejected('proposal_tampered')
    if (proposal['scope']!=source.SCOPE or proposal['account']!=c['account'] or proposal['epoch']!=c['epoch'] or
        proposal['lineage']!=c['contract']['scientific_lineage_ref'] or proposal['contract_sha256']!=c['contract_sha256']):
        raise p.Rejected('proposal_identity_mismatch')
    connection=db(Path(c['approvals'])/'approvals.sqlite')
    try:
        connection.execute('CREATE TABLE IF NOT EXISTS approvals(id TEXT PRIMARY KEY, proposal_id TEXT UNIQUE, decision_id TEXT UNIQUE, payload TEXT NOT NULL)')
        if connection.execute('SELECT 1 FROM approvals WHERE decision_id=?',(proposal['decision_id'],)).fetchone():return
        snap=source.owned_json(Path(c['source'])/'science'/(p.require_hash(proposal['snapshot_id'])+'.json'),c['uids']['capture'])
        if proposal['day']!=snap['day'] or not p.timestamp(snap['published_at'])<=p.timestamp(proposal['created_at'])<=source.now():
            raise p.Rejected('proposal_causality')
        verified=source.derive(c,snap,with_identity=True)
        if any(proposal[k]!=verified[k] for k in verified):raise p.Rejected('proposal_not_original_derivation')
        created=source.now(); from datetime import timedelta
        expires=min(created+timedelta(hours=36),p.timestamp(snap['published_at'])+timedelta(hours=36))
        approval=dict(proposal,issued_at=created.isoformat(),expires_at=expires.isoformat(),issuer_uid=os.geteuid(),
            authorization='OPERATOR_APPROVED_RESEARCH_SIMULATION_ONLY',kucoin_admissibility=False)
        approval['approval_id']=p.digest(approval)
        with connection:connection.execute('INSERT INTO approvals VALUES(?,?,?,?)',(approval['approval_id'],proposal['proposal_id'],proposal['decision_id'],p.canonical_bytes(approval).decode()))
    finally:connection.close()


def read_approval(c):
    file=Path(c['approvals'])/'approvals.sqlite'
    if file.is_symlink() or file.stat().st_uid!=c['uids']['issuer'] or file.stat().st_mode&0o022:raise p.Rejected('approval_owner')
    connection=db(file,True)
    try:row=connection.execute('SELECT payload FROM approvals ORDER BY rowid DESC LIMIT 1').fetchone()
    finally:connection.close()
    if not row:raise p.Rejected('issuer_has_no_approval')
    a=p.read_json(row[0]); now=source.now()
    if a['approval_id']!=p.digest({k:v for k,v in a.items() if k!='approval_id'}):raise p.Rejected('approval_tampered')
    if (a['scope']!=source.SCOPE or a['account']!=c['account'] or a['epoch']!=c['epoch'] or
        a['scientific_validity']!='UNASSESSED' or a['authorization']!='OPERATOR_APPROVED_RESEARCH_SIMULATION_ONLY' or a['contract_sha256']!=c['contract_sha256'] or a['issuer_uid']!=c['uids']['issuer'] or a['kucoin_admissibility'] is not False or
        a['lineage']!=c['contract']['scientific_lineage_ref']):raise p.Rejected('approval_identity')
    if not p.timestamp(a['created_at'])<=p.timestamp(a['issued_at'])<=now<p.timestamp(a['expires_at']):raise p.Rejected('approval_stale_or_future')
    return a


def migrate(c):
    path=Path(c['ledger'])/'execution.sqlite'
    if not path.exists():
        old=Path(c['legacy_snapshot'])
        if hashlib.sha256(old.read_bytes()).hexdigest()!=c['legacy_sha256']:raise p.Rejected('legacy_snapshot_changed')
        wal=Path(str(old)+'-wal')
        if wal.exists() and wal.stat().st_size:raise p.Rejected('legacy_snapshot_has_wal')
        # Immutable is permitted ONLY for this root-pinned, sealed backup.
        src=sqlite3.connect(old.as_uri()+'?mode=ro&immutable=1',uri=True)
        import tempfile
        handle,name=tempfile.mkstemp(prefix='.migration-',suffix='.sqlite',dir=path.parent)
        os.close(handle);temporary=Path(name);dst=db(temporary)
        try:
            if src.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise p.Rejected('legacy_integrity')
            src.backup(dst)
            if dst.execute('PRAGMA integrity_check').fetchone()!=('ok',):raise p.Rejected('migration_integrity')
            if dst.execute('SELECT COUNT(*) FROM state').fetchone()!=(1,):raise p.Rejected('migration_state_missing')
            dst.close();dst=None
            fd=os.open(temporary,os.O_RDONLY)
            try:os.fsync(fd)
            finally:os.close(fd)
            os.chmod(temporary,0o640);os.replace(temporary,path)
            fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
            try:os.fsync(fd)
            finally:os.close(fd)
        finally:
            src.close()
            if dst is not None:dst.close()
            # A failed temporary remains evidence; never use it as a ledger.
    connection=db(path)
    connection.executescript('''
      CREATE TABLE IF NOT EXISTS research_migration(epoch TEXT PRIMARY KEY, legacy_sha256 TEXT NOT NULL, contract_sha256 TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS research_claims(id TEXT PRIMARY KEY, kind TEXT NOT NULL, consumed_at TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS research_events(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    ''')
    row=connection.execute('SELECT epoch,legacy_sha256,contract_sha256 FROM research_migration').fetchall()
    expected=(c['epoch'],c['legacy_sha256'],c['contract_sha256'])
    if row and row!=[expected]:raise p.Rejected('execution_epoch_or_contract_changed')
    if not row:
        state=json.loads(connection.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        if state['mode']!=paper.MODE or list(connection.execute('SELECT mode FROM account_version'))!=[(paper.MODE,)]:raise p.Rejected('account_mode_changed')
        state['pending']=None
        state['research_epoch']=c['epoch'];state['risk_policy_state']={'high_water':max([paper.totals(state)['equity']]+[r[0] for r in connection.execute('SELECT equity FROM equity_history')]),'daily_day':None,'daily_start':None,'daily_entries':0,'last_increase_at':None}
        for symbol,position in state['positions'].items():
            position['generation']=1;position['position_id']=p.digest(dict(account=c['account'],epoch=c['epoch'],symbol=symbol,generation=1))
            position['funding_cursor']=position['last_mark_at']
        with connection:
            connection.execute('INSERT INTO research_migration VALUES (?,?,?)',expected)
            connection.execute('UPDATE state SET payload=? WHERE id=1',(p.canonical_bytes(state).decode(),))
    return connection


def consume_once(connection,decision):
    try:
        with connection:
            connection.execute('INSERT INTO research_claims VALUES(?,?,?)',(decision,'issuer-reserved',source.now().isoformat()))
        return True
    except sqlite3.IntegrityError:
        return False


def risk_gate(state, instant, equity):
    risk=state['risk_policy_state']; day=instant.date().isoformat()
    if risk['daily_day']!=day:
        risk.update(daily_day=day,daily_start=equity,daily_entries=0)
    risk['high_water']=max(risk['high_water'],equity)
    if equity<=0 or risk['daily_start'] is None: return 'risk_equity_missing'
    if equity<=risk['daily_start']*(1-.02):return 'daily_loss_2_percent'
    if equity<=risk['high_water']*(1-.10):return 'drawdown_10_percent'
    if risk['daily_entries']>=1:return 'one_risk_rebalance_per_UTC_day'
    if risk['last_increase_at'] and (instant-p.timestamp(risk['last_increase_at'])).total_seconds()<79200:return 'cooldown_22_hours'
    return None


def funding(connection,state,record):
    rows=[]
    end=p.timestamp(record['observed_at_end'])
    for symbol,position in state['positions'].items():
        quote=record['quotes'][symbol]
        cursor=p.timestamp(position.get('funding_cursor') or position['last_mark_at'])
        points=quote['funding']; interval=quote['funding_interval_ms']
        if type(interval)!=int or not 0<interval<=86400000 or not points:raise p.Rejected('funding_coverage_missing')
        selected=[v for v in points if int(cursor.timestamp()*1000)<v['timestamp_ms']<=int(end.timestamp()*1000)]
        if points[-1]['timestamp_ms']+interval<=int(end.timestamp()*1000):raise p.Rejected('funding_latest_settlement_missing')
        if selected and selected[0]['timestamp_ms']-int(cursor.timestamp()*1000)>interval:raise p.Rejected('funding_gap_start')
        if any(b['timestamp_ms']-a['timestamp_ms']>interval for a,b in zip(selected,selected[1:])):raise p.Rejected('funding_gap_middle')
        for event in selected:
            when=event['timestamp_ms'];rate=exposure.number(event['rate'],'funding rate')
            if connection.execute('SELECT 1 FROM funding_events WHERE symbol=? AND timestamp_ms=?',(symbol,when)).fetchone():continue
            instant=source.dt.datetime.fromtimestamp(when/1000,source.UTC).isoformat()
            quantity=math.fsum(r[0] for r in connection.execute('SELECT quantity FROM orders WHERE symbol=? AND status=\'filled\' AND bar<?',(symbol,instant)))
            if quantity==0:continue
            mark=connection.execute('SELECT price FROM marks WHERE symbol=? AND bar<? ORDER BY bar DESC LIMIT 1',(symbol,instant)).fetchone()
            if not mark:raise p.Rejected('funding_previous_observed_mark_missing')
            amount=-quantity*float(mark[0])*rate
            if not math.isfinite(amount):raise p.Rejected('funding_nonfinite')
            position['funding']+=amount
            rows.append((symbol,when,rate,quantity,mark[0],amount))
        position['funding_cursor']=end.isoformat()
    return rows


def research_plan(state,quotes,targets,allow_entries):
    equity=paper.totals(state,require_positive=False)['equity']; legs=[];notes=[]
    if equity<=0:
        return [],[dict(symbol=symbol,reason='non_positive_equity') for symbol in sorted(targets)]
    for symbol,weight in sorted(targets.items()):
        weight=exposure.number(weight,'target weight'); q=quotes[symbol]
        old=state['positions'].get(symbol,paper.new_position())['quantity']
        step=exposure.number(q['quantity_step'],'simulation step',positive=True)
        target=float((Decimal(str(equity))*Decimal(str(weight))/Decimal(str(q['mark_price']))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step)))
        delta=target-old
        if abs(delta)<=8*max(math.ulp(old),math.ulp(target),math.ulp(1.0)):continue
        protective=old*target>=0 and abs(target)<abs(old)
        if not allow_entries and not protective:
            notes.append(dict(symbol=symbol,reason='new_risk_suspended'));continue
        bids,asks=q['bids'],q['asks'];mid=(bids[0]['price']+asks[0]['price'])/2
        if not protective and ((asks[0]['price']-bids[0]['price'])/mid>float(sanity.POLICY.max_spread_ratio) or abs(q['mark_price']-mid)/mid>float(sanity.POLICY.max_mark_mid_divergence)):
            notes.append(dict(symbol=symbol,reason='spread_or_mark_divergence'));continue
        capacity=math.fsum(l['base_quantity'] for l in (asks if delta>0 else bids))
        if abs(delta)>capacity:
            limited=float((Decimal(str(capacity))/Decimal(str(step))).to_integral_value(rounding=ROUND_DOWN)*Decimal(str(step)))
            delta=math.copysign(limited,delta);notes.append(dict(symbol=symbol,reason='partial_observed_depth',requested=target-old,available=capacity))
        if abs(delta)<step*(1-1e-12) and not (protective and target==0):
            notes.append(dict(symbol=symbol,reason='below_simulated_quantity_minimum'));continue
        if delta==0:continue
        price=exposure.execution_price(q,delta,market.fill_price)
        if abs(delta*price)<1 and not protective:
            notes.append(dict(symbol=symbol,reason='below_simulated_notional_1_USDT'));continue
        fee=abs(delta*price)*exposure.number(q['fee_rate'],'fee',nonnegative=True)
        if q['fee_rate']>=1:raise p.Rejected('fee_invalid')
        legs.append(dict(symbol=symbol,quantity=delta,price=price,fee=fee,protective=protective,weight=weight))
    legs.sort(key=lambda v:(not v['protective'],v['symbol']))
    return legs,notes


def tick(c,connection,admin=None):
    instant=source.now()
    last=connection.execute('SELECT MAX(bar) FROM equity_history').fetchone()[0]
    if last and instant<=p.timestamp(last):raise p.Rejected('executor_clock_regression')
    state=json.loads(connection.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
    record=source.owned_json(Path(c['source'])/'market.json',c['uids']['capture'])
    if record['record_hash']!=p.digest({k:v for k,v in record.items() if k!='record_hash'}) or record['scope']!=source.SCOPE:raise p.Rejected('market_tampered')
    for symbol,q in record['quotes'].items():sanity.structure_and_time(symbol,q,record,instant)
    if admin is None and state.get('last_market_hash')==record['record_hash']:
        return health(c,state,instant)
    original=copy.deepcopy(state);funding_error=None
    try:funding_rows=funding(connection,state,record)
    except (ValueError,KeyError,TypeError) as e:
        state=original;funding_rows=[];funding_error=str(e)
    for symbol,q in record['quotes'].items():
        position=state['positions'].setdefault(symbol,paper.new_position())
        if 'generation' not in position:
            position.update(generation=0,position_id=p.digest(dict(account=c['account'],epoch=c['epoch'],symbol=symbol,generation=0)),funding_cursor=record['observed_at_end'])
        position['current_price']=exposure.number(q['mark_price'],'mark',positive=True)
        position['last_mark_at']=q['mark_timestamp']
    equity=paper.totals(state,require_positive=False)['equity']; entry_reason=risk_gate(state,instant,equity) or funding_error
    a=None;reason=None;legs=[];notes=[]
    if admin is None:
        try:
            a=read_approval(c)
            if connection.execute('SELECT 1 FROM research_claims WHERE id=?',(a['decision_id'],)).fetchone():reason='decision_already_consumed'
            elif p.timestamp(record['observed_at_start'])<=p.timestamp(a['issued_at']):reason='awaiting_book_after_approval'
            else:
                targets={s:p.decode_weight(w) for s,w in a['targets'].items()}
                if set(targets)!=set(record['quotes']):raise p.Rejected('intent_universe')
                if any(abs(w)>.315 for w in targets.values()) or math.fsum(map(abs,targets.values()))>.90:raise p.Rejected('intent_exposure')
                legs,notes=research_plan(state,record['quotes'],targets,entry_reason is None)
        except (ValueError,OSError,sqlite3.Error,KeyError) as e:reason=str(e)
        claim=a['decision_id'] if a else None
    else:
        claim=admin['nonce']
        if not auth.identifier(claim):raise p.Rejected('admin_nonce_invalid')
        if type(admin['generation']) is not int:raise p.Rejected('admin_generation_type')
        issued=p.timestamp(admin['issued_at']); expires=p.timestamp(admin['expires_at'])
        if admin['account']!=c['account'] or not issued<=instant<expires or not 0<(expires-issued).total_seconds()<=300:raise p.Rejected('admin_identity_or_expiry')
        if connection.execute('SELECT 1 FROM research_claims WHERE id=?',(claim,)).fetchone():raise p.Rejected('admin_replay')
        symbol=admin['symbol']; pos=state['positions'][symbol]
        if admin['position_id']!=pos['position_id'] or admin['generation']!=pos['generation']:raise p.Rejected('admin_position_generation')
        quantity=exposure.number(admin['quantity'],'admin reduction',positive=True)
        if quantity>abs(pos['quantity']) or pos['quantity']==0:raise p.Rejected('admin_increase_or_reverse')
        delta=-math.copysign(quantity,pos['quantity']);q=record['quotes'][symbol]
        sanity.preflight(symbol,q,delta,True)
        price=exposure.execution_price(q,delta,market.fill_price)
        legs=[dict(symbol=symbol,quantity=delta,price=price,fee=abs(delta*price)*q['fee_rate'],protective=True,weight=0)]
    increasing=any(not leg['protective'] for leg in legs)
    if increasing:
        snap=exposure.snapshot({s:v['quantity'] for s,v in state['positions'].items()},{s:v['current_price'] for s,v in state['positions'].items()},equity,.90,.315)
        if snap['breaches']:raise p.Rejected('current_exposure_limit')
    result=copy.deepcopy(state);fills=[]
    for leg in legs:
        symbol=leg['symbol'];pos=result['positions'][symbol];old=pos['quantity']
        paper.apply_fill(pos,leg['quantity'],leg['price'],leg['fee'])
        if old==0 or old*pos['quantity']<0:
            pos['generation']+=1;pos['position_id']=p.digest(dict(account=c['account'],epoch=c['epoch'],symbol=symbol,generation=pos['generation']))
        if increasing:
            eq=paper.totals(result)['equity']; snap=exposure.snapshot({s:v['quantity'] for s,v in result['positions'].items()},{s:v['current_price'] for s,v in result['positions'].items()},eq,.90,.315)
            if snap['breaches']:raise p.Rejected('projected_exposure_limit')
        fills.append(dict(bar=instant.isoformat(),symbol=symbol,action='BUY' if leg['quantity']>0 else 'SELL',weight=leg['weight'],notional=abs(leg['quantity']*leg['price']),fee=leg['fee'],status='filled',quantity=leg['quantity'],price=leg['price'],recorded_at=instant.isoformat(),decision_hash=claim,market_hash=record['record_hash'],realized_pnl=pos['realized_pnl']))
    policy=dict(c['contract']['risk_policy']['controls'],version=c['contract']['risk_policy']['version'],missing_gates=[])
    identity=auth.Identity(**c['identity'])
    registry=auth.Registry(Path(c['control']),audit=Path(c['ledger'])/'authorization.sqlite')
    lease=registry.entry(identity,claim,policy=policy,decision_claim=lambda:consume_once(connection,claim)) if increasing else nullcontext()
    try:
        with lease:
            with connection:
                if fills:
                    if increasing:
                        connection.execute('UPDATE research_claims SET kind=? WHERE id=?',('issuer-committed',claim))
                    else:
                        connection.execute('INSERT INTO research_claims VALUES(?,?,?)',(claim,'admin' if admin else 'issuer-reduction',instant.isoformat()))
                    for fill in fills:
                        fields=list(fill);connection.execute('INSERT INTO orders('+','.join(fields)+') VALUES('+','.join('?' for _ in fields)+')',tuple(fill.values()))
                    result['order_count']+=len(fills)
                    if increasing:result['risk_policy_state'].update(daily_entries=1,last_increase_at=instant.isoformat())
                    if a:result.update(last_source_hash=a['proposal_id'],last_bar=a['day'])
                result.update(last_market_at=record['observed_at_end'],last_market_hash=record['record_hash'],last_success_at=instant.isoformat(),entry_gate=entry_reason,execution_reason=reason,simulation_notes=notes,risk={},source_ready=(a is not None) if admin is None else state.get('source_ready',False))
                connection.executemany('INSERT INTO funding_events VALUES(?,?,?,?,?,?)',funding_rows)
                connection.executemany('INSERT OR IGNORE INTO marks VALUES(?,?,?)',[(instant.isoformat(),s,q['mark_price']) for s,q in record['quotes'].items()])
                metrics=paper.totals(result,require_positive=False)
                connection.execute('INSERT INTO equity_history VALUES(?,?,?)',(instant.isoformat(),metrics['equity'],metrics['pnl']))
                connection.execute('UPDATE state SET payload=? WHERE id=1',(p.canonical_bytes(result).decode(),))
                event=dict(scope=source.SCOPE,market_hash=record['record_hash'],claim=claim,fills=fills,notes=notes,entry_gate=entry_reason,reason=reason,funding_method='ESTIMATED_PREVIOUS_OBSERVED_MARK')
                connection.execute('INSERT INTO research_events VALUES(?,?)',(p.digest(event|{'at':instant.isoformat()}),p.canonical_bytes(event).decode()))
    except auth.Denied as error:
        # Persist the mark without any denied fills; the authorization audit is already durable.
        with connection:
            state.update(last_market_at=record['observed_at_end'],last_success_at=instant.isoformat(),entry_gate=str(error),execution_reason=str(error),simulation_notes=notes,risk={},source_ready=(a is not None) if admin is None else state.get('source_ready',False))
            connection.executemany('INSERT INTO funding_events VALUES(?,?,?,?,?,?)',funding_rows)
            connection.execute('UPDATE state SET payload=? WHERE id=1',(p.canonical_bytes(state).decode(),))
        result=state
    return health(c,result,instant)


def health(c,state,instant,error=None):
    h=paper.health_payload(state,instant,error=error)
    h.update(execution_scope=source.SCOPE,paper_orders_authorized=True,simulation_contract='v13-research-paper-v1',
             execution_model='SIMULAZIONE: profondità pubblica VWAP + 2bps; minimi simulati',funding_quality='ESTIMATED',
             min_quantity='UNKNOWN',min_notional='UNKNOWN',simulated_min_quantity='1 incremento simulato',simulated_min_notional_usdt=1,
             exchange_faithful_readiness='BLOCKED',scientific_validity='UNASSESSED',source_status='healthy' if not error and state.get('source_ready') else 'blocked',
             last_success_at=state.get('last_success_at'),source_last_success_at=state.get('last_success_at'),entry_gate=state.get('entry_gate'),execution_reason=state.get('execution_reason'),
             simulation_notes=state.get('simulation_notes',[]),research_epoch=c['epoch'])
    source.atomic(Path(c['ledger'])/'health-research.json',h)
    return h


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('role',choices=['capture','producer','issuer','executor']);parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');parser.add_argument('--poll',type=float,default=20)
    args=parser.parse_args(argv);os.umask(0o027);c=source.config(args.config,args.role)
    root=Path(c[{'capture':'source','producer':'proposals','issuer':'approvals','executor':'ledger'}[args.role]])
    fd=os.open(root/'writer.lock',os.O_CREAT|os.O_WRONLY|os.O_NOFOLLOW,0o640);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
    connection=migrate(c) if args.role=='executor' else None
    server=None
    if args.role=='executor' and not args.once:
        sockpath=Path(c['admin_socket'])
        if sockpath.exists():sockpath.unlink()
        server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(sockpath));os.chmod(sockpath,0o600);server.listen(2);server.setblocking(False)
    while True:
        try:
            c=source.config(args.config,args.role)
            if args.role=='capture':source.science_capture(c);source.market_capture(c)
            elif args.role=='producer':producer(c)
            elif args.role=='issuer':issuer(c)
            else:
                if server:
                    try:peer,_=server.accept()
                    except BlockingIOError:peer=None
                    if peer:
                        with peer:
                            try:
                                peer.settimeout(2);uid=struct.unpack('3i',peer.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
                                if uid!=0:raise p.Rejected('admin_peer_uid')
                                raw=b''
                                while not raw.endswith(b'\n') and len(raw)<=8192:
                                    part=peer.recv(8192)
                                    if not part:raise p.Rejected('admin_partial_request')
                                    raw+=part
                                command=p.read_json(raw)
                                if len(raw)>8192:raise p.Rejected('admin_request_size')
                                outcome=tick(c,connection,command);peer.sendall(p.canonical_bytes({'status':'closed','equity':outcome['equity']})+b'\n')
                            except Exception as error:peer.sendall(p.canonical_bytes({'status':'DENY','reason':str(error)})+b'\n')
                print(json.dumps(tick(c,connection)),flush=True)
            source.atomic(root/'runtime-health.json',dict(status='healthy',role=args.role,last_success_at=source.now().isoformat(),scope=source.SCOPE))
        except Exception as error:
            print(json.dumps({'role':args.role,'status':'DENY','reason':str(error)}),flush=True)
            source.atomic(root/'runtime-health.json',dict(status='blocked',role=args.role,last_check_at=source.now().isoformat(),reason=str(error),scope=source.SCOPE))
            if args.role=='executor':
                state=json.loads(connection.execute('SELECT payload FROM state WHERE id=1').fetchone()[0]);health(c,state,source.now(),str(error))
            if args.once:raise
        if args.once:break
        time.sleep(args.poll)


if __name__=='__main__':main()
