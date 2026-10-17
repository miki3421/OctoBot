"""Standalone synthetic BTC M1/L5 research paper account; no exchange/order API.

Card f20d8837. Public data enter via a local RO prospective witness only.
Existing V13 accounts and strategies are neither imported nor opened.
"""
import argparse
from collections import deque
from contextlib import closing
import copy
from decimal import Decimal, ROUND_DOWN, ROUND_CEILING, ROUND_FLOOR
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time

import btc_intraday_availability as receipt
from btc_intraday_source_qualification import NS, canonical, digest, strict

MS=1_000_000
ACCOUNT='btc-intraday-m1-l5-paper-v1'
SCOPE='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY'


def dec(x):return Decimal(str(x))

def quantity(equity,price):
    if equity<=0 or price<=0:return 0.
    notional=min(dec('.1')*dec(equity),dec('.0025')*dec(equity)/dec('.0128'),dec('.01')*dec(price))
    return float((notional/dec(price)/dec('.001')).to_integral_value(rounding=ROUND_DOWN)*dec('.001'))


def execution(row,signed_quantity,stress=False,partial=False):
    """Native L5 sizes use explicit synthetic .001 BTC mapping, never real minima."""
    side='ask' if signed_quantity>0 else 'bid'
    need=abs(dec(signed_quantity));available=sum(dec(row[f'{side}_size_{i}'])*dec('.001') for i in range(1,6))
    if need>available and not partial:return None
    amount=min(need,available)
    amount=(amount/dec('.001')).to_integral_value(rounding=ROUND_DOWN)*dec('.001')
    if amount<=0:return None
    remaining=amount;notional=Decimal(0)
    for i in range(1,6):
        used=min(remaining,dec(row[f'{side}_size_{i}'])*dec('.001'))
        notional+=used*dec(row[f'{side}_price_{i}']);remaining-=used
    if remaining>0:raise ValueError('depth_incomplete')
    multiplier=2 if stress else 1
    price=notional/amount*(1+dec('.0001')*multiplier*(1 if signed_quantity>0 else -1))
    price=(price/dec('.1')).to_integral_value(rounding=ROUND_CEILING if signed_quantity>0 else ROUND_FLOOR)*dec('.1')
    if not partial and amount*price<1:return None
    signed=amount if signed_quantity>0 else -amount
    return float(signed),float(price),float(amount*price*dec('.0006')*multiplier)


def fresh(row,at):
    return (0<=row['received_ts_ns']-row['exchange_ts_ns']<=1000*MS and
            0<=at-row['received_ts_ns']<=1000*MS and 0<=at-row['exchange_ts_ns']<=1000*MS)


def frame(rows,cutoff):
    """Ten completed fresh receive-seconds in one raw session/gap segment."""
    before=[r for r in rows if r['received_ts_ns']<=cutoff]
    if not before or not fresh(before[-1],cutoff):return False
    session=before[-1]['session_id'];segment=[];last=None
    for r in before:
        if r['session_id']!=session:
            segment=[];last=None;continue
        if last is not None and r['received_ts_ns']-last>5000*MS:segment=[]
        if 0<=r['received_ts_ns']-r['exchange_ts_ns']<=1000*MS:
            segment.append(r);last=r['received_ts_ns']
    end=cutoff//NS
    covered={r['received_ts_ns']//NS for r in segment if (end-10)*NS<=r['received_ts_ns']<end*NS
             and (r['received_ts_ns']//NS+1)*NS-r['exchange_ts_ns']<=1000*MS}
    return covered==set(range(end-10,end))


def seed(t0):
    return dict(account=ACCOUNT,scope=SCOPE,t0=t0,t1=t0+90*86400*NS,cash=10000.,q=0.,entry=0.,
                stress_cash=10000.,stress_entry=0.,fees=0.,funding=0.,realized=0.,high_water=10000.,
                drawdown_halt=False,integrity_halt=False,daily=None,pending=None,position_generation=0,entry_at=None,
                last_fill_book=None,last_slot=None,last_mid=None,last_book_ns=None,last_market_received=None,reason='WARMUP',
                activation_at=None,slots=0,valid_slots=0,fills=0,last_tick=None)


class Engine:
    def __init__(self,path,t0,bundle_sha,clock=None,initialize=False,after_commit=None,stress_mode=False):
        try:self._open(path,t0,bundle_sha,clock,initialize,after_commit,stress_mode)
        except BaseException:
            if hasattr(self,'db'):self.db.close()
            if hasattr(self,'lock'):self.lock.close()
            raise

    def _open(self,path,t0,bundle_sha,clock=None,initialize=False,after_commit=None,stress_mode=False):
        self.path=Path(path);self.clock=clock or receipt.Clock();self.failed=False
        self.stress_mode=stress_mode;self.latency_ms=1000 if stress_mode else 500
        if self.path.is_symlink() or (not initialize and not self.path.is_file()) or (initialize and self.path.exists()):
            raise ValueError('new_account_or_exact_continuation_required')
        self.lock=open(str(path)+'.lock','a');fcntl.flock(self.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        self.db=sqlite3.connect(path,timeout=.2);self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL');self.db.execute('PRAGMA synchronous=FULL')
        self.after_commit=after_commit or (lambda:None)
        self.books=deque();self.last_visibility=None
        self.identity=dict(account=ACCOUNT,protocol=receipt.PROTOCOL_SHA,bundle_sha=bundle_sha,t0=t0,scope=SCOPE)
        if stress_mode:self.identity['scenario']='PROTOCOL_V2_STRESS_INDEPENDENT'
        if initialize:
            self.db.executescript('''
            CREATE TABLE identity(payload TEXT NOT NULL);
            CREATE TABLE admin_claims(nonce TEXT PRIMARY KEY,at_ns INTEGER,payload TEXT);
            CREATE TABLE state(id INTEGER PRIMARY KEY CHECK(id=1),payload TEXT NOT NULL);
            CREATE TABLE events(seq INTEGER PRIMARY KEY,kind TEXT,at_ns INTEGER,payload TEXT,previous TEXT,sha TEXT UNIQUE);
            CREATE TABLE acknowledgements(seq INTEGER PRIMARY KEY,commit_returned_ns INTEGER);
            CREATE TABLE slots(slot_ns INTEGER PRIMARY KEY,status TEXT,payload TEXT);
            CREATE TABLE grid(slot_ns INTEGER PRIMARY KEY,valid INTEGER,payload TEXT);
            CREATE TABLE marks(capture TEXT PRIMARY KEY,symbol TEXT,received INTEGER,exchange_ns INTEGER,available INTEGER,price REAL);
            CREATE INDEX mark_asof ON marks(symbol,received);
            CREATE TABLE calendars(capture TEXT PRIMARY KEY,received INTEGER,available INTEGER,tau INTEGER,interval_ms INTEGER,valid INTEGER);
            CREATE TABLE announced(tau INTEGER PRIMARY KEY);
            CREATE INDEX calendar_latest ON calendars(valid,received);
            CREATE TABLE rates(capture TEXT,tau INTEGER,available INTEGER,rate REAL,PRIMARY KEY(capture,tau));
            CREATE INDEX rate_event ON rates(tau,available);
            CREATE TABLE funding(tau INTEGER PRIMARY KEY,status TEXT,q REAL,mark REAL,rate REAL,amount REAL,observed INTEGER,payload TEXT);
            CREATE TABLE fills(id TEXT PRIMARY KEY,at_ns INTEGER,quantity REAL,price REAL,fee REAL,realized REAL,payload TEXT);
            CREATE TABLE equity(at_ns INTEGER PRIMARY KEY,equity REAL,stress_equity REAL,complete INTEGER,q REAL);
            ''')
            self.s=seed(t0);self.s['activation_at']=self.clock.sample()['utc_ns']
            with self.db:
                self.db.execute('INSERT INTO identity VALUES(?)',(canonical(self.identity).decode(),))
                self.db.execute('INSERT INTO state VALUES(1,?)',(canonical(self.s).decode(),))
        elif strict(self.db.execute('SELECT payload FROM identity').fetchone()[0])!=self.identity:
            raise ValueError('continuation_identity_mismatch')
        self.s=strict(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        if self.s['last_tick'] and self.clock.sample()['utc_ns']<self.s['last_tick']:
            raise ValueError('clock_regression_across_restart')
        self.previous='0'*64;self.seq=0
        for r in self.db.execute('SELECT * FROM events ORDER BY seq'):
            body={k:r[k] for k in ('seq','kind','at_ns','previous')};body['payload']=strict(r['payload'])
            if r['seq']!=self.seq+1 or r['previous']!=self.previous or digest(body)!=r['sha']:
                raise ValueError('account_chain_corrupted')
            self.seq=r['seq'];self.previous=r['sha']
        late_ack=False
        for r in self.db.execute('SELECT e.payload,a.commit_returned_ns FROM events e JOIN acknowledgements a USING(seq)'):
            deadline=strict(r['payload']).get('entry_commit_deadline_ns')
            if deadline and r['commit_returned_ns']>deadline:late_ack=True
        if self.seq and digest(strict(self.db.execute('SELECT payload FROM events ORDER BY seq DESC LIMIT 1').fetchone()[0])['state'])!=digest(self.s):
            raise ValueError('account_state_chain_mismatch')
        if not initialize and not self.seq:raise ValueError('activation_event_missing')
        if initialize:self.transaction('ACTIVATION',self.s['activation_at'],lambda:None)
        if late_ack and not self.s['integrity_halt']:
            self.transaction('RECOVERY_LATE_COMMIT_HALT',self.clock.sample()['utc_ns'],lambda:self.s.update(integrity_halt=True,reason='LATE_ENTRY_COMMIT_INCIDENT'))
        if self.s['pending'] and self.s['pending']['kind']=='ENTRY':
            ack=self.db.execute('SELECT commit_returned_ns FROM acknowledgements WHERE seq=?',(self.s['pending']['commit_seq'],)).fetchone()
            if not ack or ack[0]>self.s['pending']['slot']+30*NS:
                self.transaction('RECOVERY_ENTRY_CANCELLED',self.clock.sample()['utc_ns'],lambda:self.s.update(pending=None,reason='UNCONFIRMED_OR_LATE_ENTRY_COMMIT'))
        if self.seq and not self.db.execute('SELECT 1 FROM acknowledgements WHERE seq=?',(self.seq,)).fetchone():
            if self.s['q']:
                self.transaction('RECOVERY_UNCONFIRMED_POSITION',self.clock.sample()['utc_ns'],lambda:self.s.update(integrity_halt=True,reason='UNCONFIRMED_POSITION_COMMIT'))

    def close(self):self.db.close();self.lock.close()

    def transaction(self,kind,now,mutate):
        if self.failed:raise ValueError('account_storage_fault_latched')
        old=copy.deepcopy(self.s)
        try:
            self.db.execute('BEGIN IMMEDIATE');detail=mutate() or {}
            deadline=old['pending']['deadline'] if old['pending'] and old['pending']['kind']=='ENTRY' and not old['q'] and self.s['q'] else None
            if deadline:
                fill=self.db.execute('SELECT payload FROM fills ORDER BY at_ns DESC LIMIT 1').fetchone()
                times=strict(fill[0]);deadline=min(deadline,times['exchange']+1000*MS,times['received']+1000*MS)
            if deadline and self.clock.sample()['utc_ns']>deadline:raise ValueError('entry_commit_deadline_missed')
            body=dict(seq=self.seq+1,kind=kind,at_ns=now,previous=self.previous,
                      payload=dict(detail=detail,state=self.s,entry_commit_deadline_ns=deadline))
            sha=digest(body)
            self.db.execute('UPDATE state SET payload=? WHERE id=1',(canonical(self.s).decode(),))
            self.db.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(body['seq'],kind,now,canonical(body['payload']).decode(),self.previous,sha))
            self.db.commit();returned=self.clock.sample()['utc_ns']
            self.seq=body['seq'];self.previous=sha;self.after_commit()
            with self.db:self.db.execute('INSERT INTO acknowledgements VALUES(?,?)',(self.seq,returned))
            if deadline and returned>deadline:
                self.transaction('LATE_ENTRY_COMMIT_INCIDENT',returned,lambda:self.s.update(integrity_halt=True,reason='LATE_ENTRY_COMMIT_INCIDENT'))
            return returned
        except BaseException:
            self.db.rollback();self.failed=True
            self.s=strict(self.db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            raise

    def market(self,payload,proof):
        now=proof['observed_visible']['utc_ns']
        def apply():
            for item in payload['normalized']:
                kind,row=item['kind'],item['value']
                if kind=='mark':
                    capture,pkg,received,declared,symbol,exchange,price=row
                    self.db.execute('INSERT OR IGNORE INTO marks VALUES(?,?,?,?,?,?)',(capture,symbol,received,exchange,now,price))
                elif kind=='calendar':
                    capture,pkg,received,declared,tau,interval,valid=row
                    self.db.execute('INSERT OR IGNORE INTO calendars VALUES(?,?,?,?,?,?)',(capture,received,now,tau,interval,valid))
                    if valid:self.db.execute('INSERT OR IGNORE INTO announced VALUES(?)',(tau,))
                elif kind=='rate':
                    for capture,pkg,received,declared,tau,rate in row:
                        self.db.execute('INSERT OR IGNORE INTO rates VALUES(?,?,?,?)',(capture,tau,now,rate))
            received=[item['value'][2] for item in payload['normalized'] if item['kind']=='mark']
            if received:self.s['last_market_received']=max(received)
            self.reconcile(now)
            return dict(input_receipt=proof['data_sha256'],known_at_ns=now)
        self.transaction('MARKET_INPUT',now,apply)

    def q_before(self,tau):
        return math.fsum(r[0] for r in self.db.execute('SELECT quantity FROM fills WHERE at_ns<?',(tau,)))

    def reconcile(self,now):
        for r in self.db.execute('SELECT tau FROM announced WHERE tau<=? AND tau NOT IN (SELECT tau FROM funding)',(now,)).fetchall():
            tau=r[0]
            if self.db.execute('SELECT 1 FROM funding WHERE tau=?',(tau,)).fetchone():continue
            q=self.q_before(tau)
            boundary=self.db.execute('SELECT 1 FROM fills WHERE quantity>0 AND at_ns BETWEEN ? AND ? LIMIT 1',(tau-60*NS,tau+60*NS)).fetchone()
            no_exposure=not q and not boundary
            self.db.execute('INSERT INTO funding VALUES(?,?,?,?,?,?,?,?)',(tau,'FLAT' if no_exposure else 'PENDING',q,None,None,0. if no_exposure else None,now,'{}'))
        for r in self.db.execute("SELECT * FROM funding WHERE status='PENDING'").fetchall():
            if now<=r['tau']+60*NS:continue  # wait for protective-exit uncertainty window, not an assumed rate
            rates=self.db.execute('SELECT DISTINCT rate FROM rates WHERE tau=? AND available<=?',(r['tau'],now)).fetchall()
            mark=self.db.execute("SELECT * FROM marks WHERE symbol='BTCUSDT' AND received<? AND available<=? ORDER BY received DESC LIMIT 1",(r['tau'],now)).fetchone()
            if len(rates)!=1 or not mark or not 0<=r['tau']-mark['exchange_ns']<=60*NS:continue
            rate=rates[0][0];amount=-r['q']*mark['price']*rate
            # Boundary exit uncertainty: use less favourable of before/after quantities.
            nearby=self.db.execute('SELECT at_ns,quantity FROM fills WHERE quantity>0 AND at_ns BETWEEN ? AND ?', (r['tau']-60*NS,r['tau']+60*NS)).fetchall()
            bounds=[amount]
            for fill in nearby:
                before=self.q_before(fill['at_ns'])
                bounds.extend([-before*mark['price']*rate,-(before+fill['quantity'])*mark['price']*rate])
            amount=min(bounds)
            if self.stress_mode:amount=2*amount if amount<0 else 0.
            self.s['cash']+=amount;self.s['funding']+=amount
            self.s['stress_cash']+=amount if self.stress_mode else (2*amount if amount<0 else 0.)
            if self.s['daily'] and r['tau']<=self.s['daily']['midnight_ns']:
                self.s['daily']['base']+=amount
            self.db.execute("UPDATE funding SET status='SETTLED',mark=?,rate=?,amount=?,observed=?,payload=? WHERE tau=?",(mark['price'],rate,amount,now,canonical(dict(mark_capture=mark['capture'],rate_count=len(rates),bounds=bounds,effective_at=r['tau'],observed_at=now)).decode(),r['tau']))

    def equity(self,mid=None,stress=False):
        mid=mid if mid is not None else self.s['last_mid']
        if self.s['q'] and mid is None:return None
        return self.s['stress_cash' if stress else 'cash']+self.s['q']*((mid or 0)-self.s['stress_entry' if stress else 'entry'])

    def accounting_complete(self):
        return not self.db.execute("SELECT 1 FROM funding WHERE status='PENDING' LIMIT 1").fetchone()

    def risk(self,now,mid):
        equity=self.equity(mid)
        if equity is None or equity<=0:return 'EQUITY_UNKNOWN'
        if self.accounting_complete():self.s['high_water']=max(self.s['high_water'],equity)
        if equity<=self.s['high_water']*.9:self.s['drawdown_halt']=True
        if self.s['integrity_halt']:return 'INTEGRITY_HALT'
        if self.s['drawdown_halt']:return 'DRAWDOWN_HALT'
        day=now//(86400*NS)
        if not self.s['daily'] or self.s['daily']['day']!=day:
            midnight=day*86400*NS
            prior=[r for r in self.books if r['received_ts_ns']<=midnight and fresh(r,midnight)]
            known=(not self.s['q']) or bool(prior)
            base_mid=(prior[-1]['bid_price_1']+prior[-1]['ask_price_1'])/2 if prior else mid
            self.s['daily']=dict(day=day,midnight_ns=midnight,base=self.equity(base_mid),known=known,halt=False)
        daily=self.s['daily']
        if not daily['known']:return 'UTC_BASELINE_UNKNOWN'
        if not self.accounting_complete():return 'FUNDING_PENDING'
        if equity<=daily['base']*.98:daily['halt']=True
        return 'DAILY_LOSS_HALT' if daily['halt'] else None

    def grid_point(self,slot,now):
        inputs={};universe=self.protocol['signal']['universe']
        for symbol in universe:
            row=self.db.execute('SELECT * FROM marks WHERE symbol=? AND received<=? AND available<=? ORDER BY received DESC LIMIT 1',(symbol,slot,slot)).fetchone()
            if row and 0<=slot-row['exchange_ns']<=120*NS:
                inputs[symbol]=dict(price=row['price'],capture=row['capture'],received=row['received'],exchange_ns=row['exchange_ns'],available=row['available'])
        valid=len(inputs)==18
        self.db.execute('INSERT INTO grid VALUES(?,?,?)',(slot,int(valid),canonical(inputs).decode()))
        rows=self.db.execute('SELECT * FROM grid WHERE slot_ns<=? ORDER BY slot_ns DESC LIMIT 289',(slot,)).fetchall()[::-1]
        complete=(len(rows)==289 and all(r['valid'] for r in rows) and all(b['slot_ns']-a['slot_ns']==300*NS for a,b in zip(rows,rows[1:])))
        feature=None
        if complete:
            latest=strict(rows[-1]['payload']);hour=strict(rows[-13]['payload'])
            returns={s:latest[s]['price']/hour[s]['price']-1 for s in universe}
            feature=dict(btc_return=returns['BTCUSDT'],negative=sum(v<0 for v in returns.values()),input_hash=digest([strict(r['payload']) for r in rows]))
        return complete,feature,len(rows)

    def signal_slot(self,slot,now,proof):
        if self.db.execute('SELECT 1 FROM slots WHERE slot_ns=?',(slot,)).fetchone():return
        s=self.s;status='NO_SIGNAL';details={};complete=False
        if now>slot+30*NS:status='MISSED_DEADLINE'
        else:
            complete,feature,rows=self.grid_point(slot,now)
            details=dict(feature=feature,warmup_rows=rows,input_receipt=proof)
            if now<s['t0']:status='PRESTART_WARMUP'
            elif now>=s['t1']:status='OBSERVATION_ENDED'
            elif not complete:status='WARMUP_OR_MISSING_INPUT'
            elif s['q'] or s['pending']:status='POSITION_OR_INTENT_PENDING'
            elif not frame(self.books,slot):status='L5_WINDOW_INCOMPLETE'
            elif feature['btc_return']>-.01 or feature['negative']<12:status='NO_SIGNAL'
            else:
                ref=next((r for r in reversed(self.books) if r['received_ts_ns']<=slot),None)
                mid=(ref['bid_price_1']+ref['ask_price_1'])/2 if ref else None
                veto=self.risk(now,mid) if mid else 'PRICE_MISSING'
                calendar=self.db.execute('SELECT * FROM calendars WHERE valid=1 AND received<=? AND available<=? ORDER BY received DESC LIMIT 1',(slot,slot)).fetchone()
                due=slot+300*NS+self.latency_ms*MS
                if not calendar or now-calendar['received']>300*NS or calendar['tau']<due:veto=veto or 'FUNDING_CALENDAR_MISSING'
                elif abs(due-calendar['tau'])<=60*NS:veto=veto or 'FUNDING_BOUNDARY'
                if slot+300*NS+500*MS+1000*MS+21600*NS+500*MS+1000*MS>s['t1']:veto=veto or 'INSUFFICIENT_HORIZON'
                q=quantity(self.equity(mid),mid) if mid else 0.
                if q<=0:veto=veto or 'BELOW_SYNTHETIC_STEP'
                if veto:status=veto
                else:
                    status='ENTRY_SCHEDULED'
                    s['pending']=dict(kind='ENTRY',commit_seq=self.seq+1,slot=slot,due=due,deadline=due+1000*MS,quantity=q,id=digest(dict(account=ACCOUNT,slot=slot,input_hash=feature['input_hash'])))
                    details['admitted_opportunity']=copy.deepcopy(s['pending'])
        s['last_slot']=slot;s['slots']+=int(slot>=s['t0']);s['valid_slots']+=int(slot>=s['t0'] and complete)
        self.db.execute('INSERT INTO slots VALUES(?,?,?)',(slot,status,canonical(details).decode()))
        s['reason']=status

    def fill(self,row,amount,now,kind):
        result=execution(row,amount,stress=self.stress_mode,partial=kind=='EXIT')
        if result is None:return False
        q,price,fee=result;stress=execution(row,q,stress=True,partial=kind=='EXIT')
        if stress is None:raise ValueError('stress_depth_mismatch')
        old=self.s['q'];realized=0.;stress_realized=0.
        if kind=='ENTRY':
            if old or q>=0:raise ValueError('entry_position_mismatch')
            self.s.update(entry=price,stress_entry=stress[1],entry_at=now,position_generation=self.s['position_generation']+1)
        else:
            if old>=0 or not 0<q<=-old+1e-10:raise ValueError('close_increased_or_reversed')
            realized=q*(self.s['entry']-price);stress_realized=q*(self.s['stress_entry']-stress[1])
        self.s['q']=round(old+q,9)
        self.s['cash']+=realized-fee;self.s['stress_cash']+=stress_realized-stress[2]
        self.s['realized']+=realized;self.s['fees']+=fee;self.s['fills']+=1
        self.s['last_fill_book']=row['id']
        if not self.s['q']:self.s.update(entry=0.,stress_entry=0.,entry_at=None)
        ident=digest(dict(account=ACCOUNT,generation=self.s['position_generation'],kind=kind,book=row['id']))
        detail=dict(kind=kind,book=row['id'],received=row['received_ts_ns'],exchange=row['exchange_ts_ns'],before=old,after=self.s['q'],equity_impact=q*((row['bid_price_1']+row['ask_price_1'])/2-price)-fee,stress_price=stress[1],stress_fee=stress[2],stress_realized=stress_realized,synthetic=True)
        self.db.execute('INSERT INTO fills VALUES(?,?,?,?,?,?,?)',(ident,now,q,price,fee,realized,canonical(detail).decode()))
        return True

    def administrative_close(self,command,now):
        if (command.get('schema')!=1 or command.get('account')!=ACCOUNT or command.get('action')!='CLOSE_ONLY' or
                command.get('administrator')!=dict(uid=0,channel='AUTHENTICATED_LOCAL_ROOT_OWNED_FILE') or
                command.get('generation')!=self.s['position_generation'] or
                command.get('position_id')!=ACCOUNT+':'+str(self.s['position_generation']) or
                not command.get('issued_ns',now+1)<=now<=command.get('expires_ns',0) or
                command['expires_ns']-command['issued_ns']>60*NS or self.s['q']>=0 or
                type(command.get('maximum_quantity_btc')) not in (int,float) or
                not math.isfinite(command['maximum_quantity_btc']) or command['maximum_quantity_btc']<=0 or
                abs(self.s['q'])>command['maximum_quantity_btc']+1e-10):
            raise ValueError('administrative_identity_expiry_or_quantity')
        nonce=command.get('nonce','')
        if len(nonce)!=32 or any(c not in '0123456789abcdef' for c in nonce):raise ValueError('administrative_nonce')
        if self.db.execute('SELECT 1 FROM admin_claims WHERE nonce=?',(nonce,)).fetchone():return False
        def apply():
            self.db.execute('INSERT INTO admin_claims VALUES(?,?,?)',(nonce,now,canonical(command).decode()))
            self.s['pending']=dict(kind='EXIT',due=now+self.latency_ms*MS,created=now,reason='ADMIN_CLOSE')
            self.s['reason']='ADMIN_CLOSE_PENDING'
        self.transaction('ADMIN_CLOSE_ACCEPTED',now,apply)
        return True

    def primary_opportunity(self,primary,now,proof):
        """Counterfactual only: no independent directional selection or old replay."""
        slot=primary['slot_ns']
        if self.db.execute('SELECT 1 FROM slots WHERE slot_ns=?',(slot,)).fetchone():return
        details=strict(primary['payload']);op=details.get('admitted_opportunity')
        status='PRIMARY_NOT_ADMITTED'
        if op:
            if now>slot+30*NS:status='STRESS_ADMISSION_MISSED'
            elif self.s['q'] or self.s['pending']:status='STRESS_PRIOR_POSITION_OR_INTENT'
            elif slot+300*NS+1000*MS+1000*MS+21600*NS+1000*MS+1000*MS>self.s['t1']:status='STRESS_INSUFFICIENT_HORIZON'
            elif not frame(self.books,slot):status='STRESS_L5_WINDOW_INCOMPLETE'
            else:
                ref=next((r for r in reversed(self.books) if r['received_ts_ns']<=slot),None)
                mid=(ref['bid_price_1']+ref['ask_price_1'])/2 if ref else None
                block=self.risk(now,mid) if mid else 'PRICE_MISSING'
                if block:status='STRESS_'+block
                else:
                    pending=copy.deepcopy(op);pending.update(commit_seq=self.seq+1,due=slot+301*NS,deadline=slot+302*NS,
                                                            id=digest(dict(primary_intent=op['id'],scenario='STRESS')))
                    self.s['pending']=pending;status='STRESS_ENTRY_SCHEDULED'
        detail=dict(primary_status=primary['status'],primary_intent=op,input_receipt=proof)
        self.db.execute('INSERT INTO slots VALUES(?,?,?)',(slot,status,canonical(detail).decode()))
        self.s['last_slot']=slot;self.s['reason']=status
        self.s['slots']+=int(slot>=self.s['t0'])
        self.s['valid_slots']+=int(slot>=self.s['t0'] and details.get('feature') is not None)

    def tick(self,rows,proof,primary_slots=None):
        now=self.clock.sample()['utc_ns']
        if proof['observed_visible']['utc_ns']>now:raise ValueError('future_visibility_proof')
        if rows:
            for row in rows:self.books.append(row)
            cutoff=rows[-1]['received_ts_ns']-40*NS
            while self.books and self.books[0]['received_ts_ns']<cutoff:self.books.popleft()
        def apply():
            s=self.s;s['last_tick']=now
            if s['last_book_ns'] and rows and rows[0]['received_ts_ns']<s['last_book_ns']:raise ValueError('book_receive_regression')
            self.reconcile(now)
            current=next((r for r in reversed(self.books) if fresh(r,now)),None)
            veto='PRICE_MISSING'
            if current:
                mid=(current['bid_price_1']+current['ask_price_1'])/2
                s.update(last_mid=mid,last_book_ns=current['received_ts_ns'])
                veto=self.risk(now,mid)
            # Protective intent persists even without a quote; it never fabricates a fill.
            overdue=self.db.execute("SELECT MIN(tau) FROM funding WHERE status='PENDING'").fetchone()[0]
            exit_reason=None
            if s['q']:
                if not current:exit_reason='STALE_DATA'
                elif veto and veto!='FUNDING_PENDING':exit_reason=veto
                elif overdue and now-overdue>900*NS:exit_reason='FUNDING_OVERDUE'
                elif current['ask_price_1']>=s['entry']*1.01:exit_reason='STOP_LOSS'
                elif now>=s['entry_at']+21600*NS:exit_reason='TIME_EXIT'
                elif current['ask_price_1']<=s['entry']*.98:exit_reason='TAKE_PROFIT'
            if exit_reason and (not s['pending'] or s['pending']['kind']!='EXIT'):
                s['pending']=dict(kind='EXIT',due=now+self.latency_ms*MS,created=now,reason=exit_reason)
            pending=s['pending']
            if pending and pending['kind']=='ENTRY':
                if now>pending['deadline']:
                    s.update(pending=None,reason='ENTRY_MISSED_PERSISTENCE_DEADLINE')
                elif now>=pending['due']:
                    candidate=next((r for r in self.books if r['received_ts_ns']>=pending['due'] and fresh(r,now)),None)
                    if candidate:
                        block=veto or ('L5_WINDOW_INCOMPLETE' if not frame(self.books,candidate['received_ts_ns']) else None)
                        calendar=self.db.execute('SELECT * FROM calendars WHERE valid=1 AND available<=? ORDER BY received DESC LIMIT 1',(now,)).fetchone()
                        if not calendar or now-calendar['received']>300*NS or calendar['tau']<now or abs(now-calendar['tau'])<=60*NS:block=block or 'FUNDING_CALENDAR_OR_BOUNDARY'
                        amount=min(pending['quantity'],quantity(self.equity(s['last_mid']),s['last_mid']))
                        if amount<=0:block=block or 'BELOW_SYNTHETIC_STEP'
                        while amount>0 and not block:
                            estimate=execution(candidate,-amount,stress=self.stress_mode)
                            if estimate is None:break
                            post_equity=self.equity(s['last_mid'])-estimate[2]+(-amount)*(s['last_mid']-estimate[1])
                            if amount*estimate[1]<=.1*post_equity+1e-9:break
                            amount=round(amount-.001,9)
                        if not block and amount>0 and self.fill(candidate,-amount,now,'ENTRY'):
                            s.update(pending=None,reason='SHORT_OPEN')
                        else:s.update(pending=None,reason=block or 'ENTRY_DEPTH_INSUFFICIENT')
            pending=s['pending']
            if pending and pending['kind']=='EXIT' and now>=pending['due']:
                candidate=next((r for r in self.books if r['received_ts_ns']>=pending['due'] and r['id']!=s['last_fill_book'] and fresh(r,now)),None)
                if candidate and self.fill(candidate,-s['q'],now,'EXIT'):
                    if not s['q']:s.update(pending=None,reason='PROTECTIVE_CLOSE_COMPLETE')
                    else:s['pending']['due']=now+self.latency_ms*MS
            if self.stress_mode:
                for primary in primary_slots or []:self.primary_opportunity(primary,now,proof['data_sha256'])
            else:
                slot=now//(300*NS)*(300*NS)
                first=self.s['activation_at']//(300*NS)*(300*NS)+300*NS
                previous=s['last_slot']
                missing=(previous+300*NS) if previous is not None else first
                while missing<slot:
                    self.signal_slot(missing,now,proof['data_sha256']);missing+=300*NS
                if slot>=first and now>=slot+2*NS:self.signal_slot(slot,now,proof['data_sha256'])
            s['reason']=s['reason'] if s['pending'] or s['q'] else (veto or s['reason'])
            last=self.db.execute('SELECT MAX(at_ns) FROM equity').fetchone()[0]
            if last is None or now-last>=30*NS:
                self.db.execute('INSERT INTO equity VALUES(?,?,?,?,?)',(now,self.equity(),self.equity(stress=True),int(self.accounting_complete() and (not s['q'] or current is not None)),s['q']))
            return dict(input_receipt=proof['data_sha256'],visibility_ns=now)
        returned=self.transaction('TICK',now,apply)
        # An intent committed too late is cancelled before any possible future fill.
        pending=self.s['pending']
        if pending and pending['kind']=='ENTRY' and pending['commit_seq']==self.seq and returned>pending['slot']+30*NS:
            self.transaction('LATE_DECISION_CANCELLED',returned,lambda:self.s.update(pending=None,reason='LATE_DECISION_COMMIT'))

    def view(self,now):
        s=self.s;row_count=self.db.execute('SELECT COUNT(*) FROM grid').fetchone()[0]
        valid_tail=self.db.execute('SELECT slot_ns,valid FROM grid ORDER BY slot_ns DESC LIMIT 289').fetchall()
        full=0
        for i,r in enumerate(valid_tail):
            if not r['valid'] or (i and valid_tail[i-1]['slot_ns']-r['slot_ns']!=300*NS):break
            full+=1
        recent=[dict(r) for r in self.db.execute('SELECT * FROM slots ORDER BY slot_ns DESC LIMIT 50')]
        for r in recent:r['detail']=strict(r.pop('payload'))
        fills=[dict(r) for r in self.db.execute('SELECT * FROM fills ORDER BY at_ns DESC LIMIT 100')]
        for r in fills:r['detail']=strict(r.pop('payload'))
        points=[list(r) for r in self.db.execute('SELECT at_ns,equity,stress_equity,complete FROM equity ORDER BY at_ns DESC LIMIT 5000')][::-1]
        age=(now-s['last_book_ns'])/NS if s['last_book_ns'] else None
        status='ACTIVE_PAPER' if now>=s['t0'] else 'ACTIVE_PRESTART'
        if full<289:status='ACTIVE_WARMUP'
        if now>=s['t1']:status='OBSERVATION_ENDED'
        if s['integrity_halt'] or s['drawdown_halt']:status='ACTIVE_RISK_HALTED'
        if self.failed:status='BLOCKED_STORAGE'
        return dict(schema=1,scope=SCOPE,account=ACCOUNT,status=status,checked_at_ns=now,state=s,
                    metrics=dict(equity=self.equity(),pnl=self.equity()-10000,stress_equity=self.equity(stress=True)),
                    accounting_complete=self.accounting_complete(),market_age_seconds=(now-s['last_market_received'])/NS if s['last_market_received'] else None,warmup_rows=full,warmup_required=289,book_age_seconds=age,slots=recent,fills=fills,equity=points,
                    real_min_quantity='UNKNOWN',real_min_notional='UNKNOWN',scientific_validity='UNASSESSED',
                    frequency_limits=False,normalization='synthetic .001 BTC/native; fee 6bps, slippage 1bp; stress 2x',
                    no_real_orders=True)


def atomic(path,value):
    path=Path(path);temporary=path.with_suffix('.tmp')
    with open(temporary,'wb') as f:f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def authority(config):
    raw=Path(config['protocol']).read_bytes()
    if hashlib.sha256(raw).hexdigest()!=receipt.PROTOCOL_SHA:raise ValueError('protocol_changed')
    activation_path=Path(config['activation'])
    if activation_path.is_symlink() or activation_path.stat().st_uid!=0 or activation_path.stat().st_mode&0o022:
        raise ValueError('activation_receipt_owner')
    activation=strict(activation_path.read_bytes())
    if activation['account']!=ACCOUNT or activation['scope']!=SCOPE or activation['protocol_sha256']!=receipt.PROTOCOL_SHA or not activation['paper_activation_authorized'] or activation.get('real_orders') is not False or activation.get('operational_grants') is not False or activation.get('exchange_credentials') is not False:raise ValueError('activation_identity')
    pins=activation['code_pins']
    if config.get('continuation'):
        path=Path(config['continuation'])
        if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:raise ValueError('continuation_owner')
        continuation=strict(path.read_bytes())
        if (continuation['account']!=ACCOUNT or continuation['base_activation_sha256']!=hashlib.sha256(activation_path.read_bytes()).hexdigest() or
                continuation['protocol_sha256']!=receipt.PROTOCOL_SHA or continuation['recorded_ns']>=activation['t0_ns'] or
                continuation['scope']!='PRE_T0_ZERO_FILL_PROTOCOL_CONFORMANCE_FIX'):
            raise ValueError('continuation_identity')
        snapshot=Path(config['continuation_snapshot'])
        if snapshot.is_symlink() or snapshot.stat().st_uid!=0 or snapshot.stat().st_mode&0o022:raise ValueError('continuation_snapshot_owner')
        if hashlib.sha256(snapshot.read_bytes()).hexdigest()!=continuation['primary_snapshot_sha256']:raise ValueError('continuation_snapshot_hash')
        with closing(sqlite3.connect(snapshot.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)) as db:
            state=strict(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
            identity=strict(db.execute('SELECT payload FROM identity').fetchone()[0])
            if (db.execute('SELECT COUNT(*) FROM fills').fetchone()[0]!=0 or state['q']!=0 or state['cash']!=10000 or
                    state['t0']!=activation['t0_ns'] or identity['bundle_sha']!=digest(activation)):
                raise ValueError('continuation_not_zero_fill_prestart')
        pins=continuation['code_pins']
    if set(pins)!={'btc_intraday_paper.py','btc_intraday_availability.py','btc_intraday_source_qualification.py','btc_intraday_admin.py'}:
        raise ValueError('runtime_pin_set')
    for name,sha in pins.items():
        if hashlib.sha256((Path(__file__).parent/name).read_bytes()).hexdigest()!=sha:raise ValueError('runtime_code_changed:'+name)
    return raw,activation


def run(config):
    raw,activation=authority(config)
    clock=receipt.Clock();witness=receipt.Witness(config['receipts'],clock)
    engine=Engine(config['db'],activation['t0_ns'],digest(activation),clock,initialize=False)
    stress=Engine(config['stress_db'],activation['t0_ns'],digest(activation),clock,initialize=False,stress_mode=True)
    engine.protocol=strict(raw);stress.protocol=strict(raw);reader=receipt.BookReader(config['book'],clock)
    def stress_slots():
        last=stress.s['last_slot'] if stress.s['last_slot'] is not None else -1
        return [dict(r) for r in engine.db.execute('SELECT * FROM slots WHERE slot_ns>? ORDER BY slot_ns',(last,))]
    def projection():
        now=clock.sample()['utc_ns'];v=engine.view(now)
        v['metrics']['stress_equity']=stress.equity()
        v['stress_equity_history']=[list(r) for r in stress.db.execute('SELECT at_ns,equity,complete FROM equity ORDER BY at_ns DESC LIMIT 5000')][::-1]
        v['stress']=dict(method='PROTOCOL_V2_INDEPENDENT_1000MS_OWN_RISK_EXITS',equity=stress.equity(),q=stress.s['q'],
                         fills=stress.s['fills'],reason=stress.s['reason'],accounting_complete=stress.accounting_complete())
        # The old primary-only fee diagnostic is retained in its original ledger but never presented as v2 stress.
        for point in v['equity']:point[2]=None
        atomic(config['output'],v)
    market_key=None;published=0;market_checked=0
    try:
        while True:
            now=clock.sample()['utc_ns']
            if now-market_checked>=NS:
                record,_=receipt.read_blob(Path(config['source'])/'market.json');market_checked=now
                if record['record_hash']!=market_key:
                    key,payload,start,end,received=receipt.read_market(config['source'],engine.protocol,clock)
                    compact=dict(market_hash=key,normalized=payload['normalized'],
                                 raw_receipts=[dict(capture_id=r['capture_id'],raw_sha256=r['raw_sha256']) for r in payload['receipts']])
                    # Prior source bytes may warm features, never create a past decision.
                    try:
                        data,_=witness.observe('market',key,compact,start,end,received)
                        proof=witness.available_now(data,clock.sample()['utc_ns']+NS);engine.market(compact,proof);stress.market(compact,proof)
                    except receipt.Denied as error:
                        if str(error)!='duplicate_observation':raise
                    market_key=key
            command=Path(config['control'])/'close.json'
            if command.exists():
                if command.is_symlink() or command.stat().st_uid!=0 or command.stat().st_mode&0o022:
                    raise ValueError('administrative_file_owner')
                cmd=strict(command.read_bytes())
                if not engine.db.execute('SELECT 1 FROM admin_claims WHERE nonce=?',(cmd.get('nonce',''),)).fetchone():
                    try:engine.administrative_close(cmd,clock.sample()['utc_ns'])
                    except ValueError as error:
                        if str(error)!='administrative_identity_expiry_or_quantity':raise
            result=reader.poll()
            if result:
                payload,start,end=result;rows=payload['rows'];last=rows[-1]['id']
                data,_=witness.observe('book',str(rows[0]['id'])+':'+str(last),payload,start,end,max(r['received_ts_ns'] for r in rows))
                proof=witness.available_now(data,clock.sample()['utc_ns']+NS)
                engine.tick(rows,proof);stress.tick(rows,proof,stress_slots());reader.cursor=last
            elif now-published>=5*NS:
                proof=dict(data_sha256='NO_NEW_BOOK_NO_FILL',observed_visible=dict(utc_ns=now))
                engine.tick([],proof);stress.tick([],proof,stress_slots())
            if now-published>=5*NS:
                projection();published=now
            time.sleep(.05)
    except BaseException as error:
        try:
            value=engine.view(time.time_ns());value.update(status='BLOCKED',error=type(error).__name__+':'+str(error));atomic(config['output'],value)
        finally:engine.close();stress.close();witness.close()
        raise


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);args=parser.parse_args()
    os.umask(0o027)
    config_path=Path(args.config)
    if config_path.is_symlink() or config_path.stat().st_uid!=0 or config_path.stat().st_mode&0o022:
        raise ValueError('root_owned_read_only_configuration_required')
    run(strict(config_path.read_bytes()))
