"""Isolated V13 clone continuation. No network, issuer, grant or executor interface.

Cards: work-card-4b2d8047-414b-4d19-b5fd-5fabe6a45d7a,
work-card-a3de24f6-9426-40f4-8f57-cbaed4434e04.
The immutable full parent is the history prefix; one SQLite transaction commits
both continuations, funding, valuation and daily slot consumption.
"""
from __future__ import annotations
import argparse
import copy
import datetime as dt
import fcntl
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit, parse_qs
from octobot.ai_strategy_lab import v13_research_paper as engine
from octobot.ai_strategy_lab import v13_research_source as source
from octobot.ai_strategy_lab import v13_paper_v2 as paper
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_market_sanity as sanity
from octobot.ai_strategy_lab import v13_exposure as exposure

UTC = dt.timezone.utc
ARMS = ('FAST', 'HALF')
VERSION = 'v13-cloned-paired-simulator-v2.2'

def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()

def read(path):
    path = Path(path)
    if path.is_symlink(): raise ValueError('symlink_input')
    raw = gzip.decompress(path.read_bytes()) if path.suffix == '.gz' else path.read_bytes()
    return json.loads(raw)

def ro(path):
    c = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA query_only=ON')
    return c

def dump(v): return json.dumps(v, sort_keys=True, separators=(',', ':'), allow_nan=False)

def verified_market(record, universe, instant):
    if record['record_hash'] != p.digest({k:v for k,v in record.items() if k != 'record_hash'}):
        raise ValueError('market_hash')
    if record['scope'] != source.SCOPE or set(record['quotes']) != set(universe): raise ValueError('market_scope')
    for symbol, q in record['quotes'].items():
        sanity.structure_and_time(symbol, q, record, instant)
        if q['fee_rate'] < .0006 or q['min_quantity'] is not None or q['min_notional'] is not None:
            raise ValueError('simulation_contract_changed')
    return record

def closes(snapshot, universe, slot):
    """Only the exact 61 contiguous closed days available by the decision slot."""
    day = slot.date()-dt.timedelta(days=1)
    if snapshot['day'] != day.isoformat() or p.timestamp(snapshot['published_at']) > slot:
        raise ValueError('daily_cutoff')
    if snapshot['snapshot_id'] != p.digest({k:v for k,v in snapshot.items() if k != 'snapshot_id'}):
        raise ValueError('snapshot_hash')
    rows = {s:{} for s in universe}
    for receipt in snapshot['requests']:
        if p.timestamp(receipt['received_at']) > p.timestamp(snapshot['published_at']): raise ValueError('receipt_future')
        url = urlsplit(receipt['url'])
        raw = bytes.fromhex(receipt['raw_hex'])
        if hashlib.sha256(raw).hexdigest() != receipt['raw_sha256']: raise ValueError('raw_hash')
        if url.netloc != 'fapi.binance.com' or url.path != '/fapi/v1/klines': continue
        query = parse_qs(url.query); symbol = query['symbol'][0]
        if symbol not in rows or query.get('interval') != ['1d']: raise ValueError('daily_identity')
        for row in json.loads(raw):
            opened = dt.datetime.fromtimestamp(int(row[0])/1000, UTC)
            date = opened.date()
            if date > day: continue
            if opened.time() != dt.time() or int(row[6]) != int(row[0])+86400000-1: raise ValueError('bar_boundaries')
            price = float(row[4])
            if not math.isfinite(price) or price <= 0: raise ValueError('close_invalid')
            if date in rows[symbol] and rows[symbol][date] != price: raise ValueError('conflicting_bar')
            rows[symbol][date] = price
    dates = [day-dt.timedelta(days=k) for k in range(60,-1,-1)]
    return {s:[rows[s][d] for d in dates] for s in universe}

def risk_targets(states, targets, prices, filters):
    import numpy as np
    symbols = sorted(targets)
    x = np.array([prices[s] for s in symbols], dtype=float).T
    if x.shape != (61,len(symbols)) or not np.isfinite(x).all() or (x<=0).any(): raise ValueError('risk_history')
    returns = x[1:]/x[:-1]-1
    sample = np.atleast_2d(np.cov(returns, rowvar=False, ddof=1))
    covariance = .8*sample+.2*np.diag(np.diag(sample))
    next_filters = dict(filters)
    weights = {}
    for s in symbols:
        a = prices[s]
        below = all(a[i] < sum(a[i-9:i+1])/10 for i in (59,60))
        above = all(a[i] > sum(a[i-9:i+1])/10 for i in (59,60))
        if below: next_filters[s] = 'REDUCED'
        elif above: next_filters[s] = 'FULL'
    for arm in ARMS:
        equity = paper.totals(states[arm], require_positive=False)['equity']
        if equity <= 0: raise ValueError('risk_equity')
        w = []
        for s in symbols:
            target = float(targets[s])
            if not math.isfinite(target): raise ValueError('target_nonfinite')
            if arm == 'HALF': target *= .5
            elif target > 0 and next_filters[s] == 'REDUCED':
                position = states[arm]['positions'][s]
                target = min(target*.5, max(0,position['quantity'])*position['current_price']/equity)
            w.append(target)
        w = np.array(w)
        cap = min(1., .90/max(float(abs(w).sum()),1e-30), .315/max(float(abs(w).max()),1e-30))
        weights[arm] = w*cap
    def vol(w): return math.sqrt(max(0.,365*float(w@covariance@w)))
    before = {arm:vol(w) for arm,w in weights.items()}
    common = min(before.values())
    result = {arm:dict(zip(symbols,map(float,w*(common/before[arm] if before[arm]>0 else 0)))) for arm,w in weights.items()}
    return result, next_filters, covariance, before, common

def apply_pair(states, targets, prices, filters, record, instant, funding_debt, force_reductions=False):
    """Pure paired execution. Caller persists every result in a single transaction."""
    import numpy as np
    result = copy.deepcopy(states)
    weights, filters, covariance, before, common = risk_targets(result,targets,prices,filters)
    blocks = {arm:engine.risk_gate(result[arm],instant,paper.totals(result[arm],require_positive=False)['equity']) for arm in ARMS}
    allow = not funding_debt and not any(blocks.values()) and not force_reductions
    plans = {arm:engine.research_plan(result[arm],record['quotes'],weights[arm],allow) for arm in ARMS}
    # A veto on either arm must never leave the other free to add risk.
    paired_vetoes = {'spread_or_mark_divergence', 'below_simulated_notional_1_USDT'}
    if allow and any(n['reason'] in paired_vetoes for _,notes in plans.values() for n in notes):
        reduced = apply_pair(states,targets,prices,filters,record,instant,funding_debt,force_reductions=True)
        reduced[3]['shared_entry_block'] = 'paired_market_or_minimum_veto'
        return reduced
    fills, notes = [], []
    for arm in ARMS:
        state = result[arm]
        legs, skipped = plans[arm]
        notes.extend(dict(arm=arm,**n) for n in skipped)
        increased = False
        for leg in legs:
            s = leg['symbol']; position = state['positions'][s]
            candidate = copy.deepcopy(state)
            old = copy.deepcopy(position)
            paper.apply_fill(candidate['positions'][s],leg['quantity'],leg['price'],leg['fee'])
            qty, marks = exposure.quantities_and_marks(candidate)
            snap = exposure.snapshot(qty,marks,paper.totals(candidate,require_positive=False)['equity'],.90,.315)
            if snap['breaches'] and not leg['protective']:
                return apply_pair(states,targets,prices,filters,record,instant,funding_debt,force_reductions=True)
            state = candidate;result[arm] = state
            position = state['positions'][s]
            if old['quantity'] == 0 or old['quantity']*position['quantity'] < 0:
                position['generation'] = old.get('generation',0)+1
            position['position_id'] = p.digest(dict(account=state['fork_account'],symbol=s,generation=position.get('generation',1)))
            fills.append(dict(arm=arm,at=instant.isoformat(),**leg,before=old['quantity'],after=position['quantity'],
                              realized_delta=position['realized_pnl']-old['realized_pnl'],market_hash=record['record_hash'],
                              position_id=position['position_id']))
            increased |= not leg['protective']
        if increased:state['risk_policy_state'].update(daily_entries=1,last_increase_at=instant.isoformat())
        state['order_count'] += sum(f['arm']==arm for f in fills)
    vols = {}
    for arm in ARMS:
        state=result[arm];eq=paper.totals(state,require_positive=False)['equity']
        w=np.array([state['positions'][s]['quantity']*state['positions'][s]['current_price']/eq for s in sorted(targets)])
        vols[arm]=math.sqrt(max(0.,365*float(w@covariance@w)))
    gap=abs(vols['FAST']-vols['HALF'])/max(vols.values()) if max(vols.values()) else 0.
    return result,filters,fills,dict(blocks=blocks,funding_debt=funding_debt,notes=notes,weights=weights,
        candidate_volatility=before,common_target_volatility=common,realized_allocation_volatility=vols,risk_gap=gap,
        risk_matched=gap<=.02)

class Runner:
    def __init__(self, config, *, initialize=False):
        self.c=config;self.protocol=read(config['protocol']);self.universe=self.protocol['universe']
        self.t0=p.timestamp(self.protocol['activation']['t0'])
        if sha(config['seed']) != self.protocol['fork']['parent_db_sha256']:raise ValueError('seed_hash')
        for path,h in self.protocol['source_code_pins'].items():
            if sha(Path(config['repo'])/path)!=h:raise ValueError('source_code_pin:'+path)
        exists=Path(config['db']).exists()
        if initialize and exists:raise ValueError('refusing_reinitialize')
        if not initialize and not exists:raise ValueError('continuation_missing_no_reset')
        self.seed=ro(config['seed']);self.original=ro(config['original'])
        self.parent=json.loads(self.seed.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        self.db=sqlite3.connect(config['db'],timeout=10)
        self.db.row_factory=sqlite3.Row
        self.db.execute('PRAGMA journal_mode=DELETE');self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript('''
        CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS states(arm TEXT PRIMARY KEY,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS slots(slot TEXT PRIMARY KEY,status TEXT NOT NULL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS fills(id TEXT PRIMARY KEY,arm TEXT,at TEXT,symbol TEXT,quantity REAL,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS funding(arm TEXT,symbol TEXT,at INTEGER,amount REAL,payload TEXT,PRIMARY KEY(arm,symbol,at));
        CREATE TABLE IF NOT EXISTS observations(at TEXT PRIMARY KEY,market_hash TEXT,payload TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS inputs(day TEXT PRIMARY KEY,payload TEXT NOT NULL);
        ''')
        self.identity=dict(protocol_sha256=sha(config['protocol']),parent_snapshot_sha256=sha(config['seed']),runner_sha256=sha(__file__))
        saved=self.meta('identity')
        if saved and saved!=self.identity:
            self.close();raise ValueError('continuation_identity_changed')
        if not saved and not initialize:
            self.close();raise ValueError('continuation_identity_missing_no_reset')
        if not saved:
            if self.db.execute('SELECT COUNT(*) FROM states').fetchone()[0]:raise ValueError('partial_initialization')
            now=source.now();slot=now.replace(hour=0,minute=15,second=0,microsecond=0)
            if slot<=now:slot+=dt.timedelta(days=1)
            receipt=dict(**self.identity,version=VERSION,economic_t0=self.t0.isoformat(),first_decision_slot=slot.isoformat(),
                         end_exclusive=self.protocol['activation']['end_exclusive'],account_ids=self.protocol['fork']['account_ids'],
                         inherited_equity=paper.totals(self.parent)['equity'],inherited_positions=self.parent['positions'],
                         inherited_risk_state=self.parent['risk_policy_state'],data_cutoff=now.isoformat(),
                         scope='RESEARCH_SIMULATION_ONLY_NO_EXECUTOR_LINK')
            with self.db:
                self.put('identity',self.identity);self.put('receipt',receipt);self.put('filters',{s:'FULL' for s in self.universe})
                for arm in ARMS:
                    state=copy.deepcopy(self.parent);state['fork_account']=receipt['account_ids'][arm]
                    self.db.execute('INSERT INTO states VALUES(?,?)',(arm,dump(state)))
        self.receipt=self.meta('receipt')

    def meta(self,key):
        row=self.db.execute('SELECT payload FROM meta WHERE key=?',(key,)).fetchone()
        return json.loads(row[0]) if row else None
    def put(self,key,value):self.db.execute('INSERT OR REPLACE INTO meta VALUES(?,?)',(key,dump(value)))
    def states(self):return {r['arm']:json.loads(r['payload']) for r in self.db.execute('SELECT * FROM states')}

    def prepare_input(self, slot):
        day=(slot.date()-dt.timedelta(days=1)).isoformat()
        row=self.db.execute('SELECT payload FROM inputs WHERE day=?',(day,)).fetchone()
        if row:return json.loads(row[0])
        c=self.c['derivation'];proposal=source.owned_json(Path(c['proposals'])/'latest.json',c['uids']['producer'])
        if proposal['proposal_id']!=p.digest({k:v for k,v in proposal.items() if k!='proposal_id'}):raise ValueError('proposal_hash')
        if proposal['day']!=day or p.timestamp(proposal['created_at'])>slot:raise ValueError('proposal_cutoff')
        snap=source.owned_json(Path(c['source'])/'science'/(p.require_hash(proposal['snapshot_id'])+'.json'),c['uids']['capture'])
        series=closes(snap,self.universe,slot)
        derived=source.derive(c,snap,with_identity=True)
        if any(proposal[k]!=v for k,v in derived.items()):raise ValueError('proposal_derivation')
        contract=read(Path(c['repo'])/'docs/contracts/v13-research-paper-v1.json')
        if proposal['scope']!=source.SCOPE or proposal['lineage']!=contract['scientific_lineage_ref'] or proposal['contract_sha256']!=c['contract_sha256'] or proposal['account']!=c['account'] or proposal['epoch']!=c['epoch']:
            raise ValueError('proposal_identity')
        item=dict(day=day,targets=derived['targets'],prices=series,proposal_id=proposal['proposal_id'],snapshot_id=snap['snapshot_id'])
        with self.db:self.db.execute('INSERT INTO inputs VALUES(?,?)',(day,dump(item)))
        return item

    def fund(self,states,record):
        """Do not advance cursors across unverified gaps. Both arms or neither."""
        result=copy.deepcopy(states);rows=[];end=p.timestamp(record['observed_at_end']);endms=int(end.timestamp()*1000)
        for arm,state in result.items():
            for s,pos in state['positions'].items():
                q=record['quotes'][s];cursor=p.timestamp(pos['funding_cursor']);ms=int(cursor.timestamp()*1000)
                points=q['funding'];interval=q['funding_interval_ms']
                if type(interval)!=int or not 0<interval<=86400000 or not points:raise ValueError('funding_coverage_missing:'+s)
                events=[v for v in points if ms<v['timestamp_ms']<=endms]
                if points[-1]['timestamp_ms']+interval<=endms:raise ValueError('funding_latest_missing:'+s)
                if events and events[0]['timestamp_ms']-ms>interval:raise ValueError('funding_gap_start:'+s)
                if any(b['timestamp_ms']-a['timestamp_ms']>interval for a,b in zip(events,events[1:])):raise ValueError('funding_gap_middle:'+s)
                for event in events:
                    when=event['timestamp_ms'];at=dt.datetime.fromtimestamp(when/1000,UTC).isoformat()
                    if self.db.execute('SELECT 1 FROM funding WHERE arm=? AND symbol=? AND at=?',(arm,s,when)).fetchone():continue
                    if self.seed.execute('SELECT 1 FROM funding_events WHERE symbol=? AND timestamp_ms=?',(s,when)).fetchone():continue
                    quantity=self.parent['positions'][s]['quantity']+math.fsum(r[0] for r in self.db.execute('SELECT quantity FROM fills WHERE arm=? AND symbol=? AND at<?',(arm,s,at)))
                    mark=self.original.execute('SELECT bar,price FROM marks WHERE symbol=? AND bar<? ORDER BY bar DESC LIMIT 1',(s,at)).fetchone()
                    if quantity and (not mark or (p.timestamp(at)-p.timestamp(mark['bar'])).total_seconds()>1800):raise ValueError('funding_reference_missing:'+s)
                    reference=float(mark['price']) if mark else None
                    rate=exposure.number(event['rate'],'funding rate')
                    amount=-quantity*reference*rate if quantity else 0.
                    if not math.isfinite(amount):raise ValueError('funding_nonfinite')
                    pos['funding']+=amount
                    rows.append(dict(arm=arm,symbol=s,at=when,amount=amount,quantity=quantity,reference_mark=reference,
                                     reference_at=mark['bar'] if mark else None,rate=rate,market_hash=record['record_hash']))
                pos['funding_cursor']=end.isoformat()
        return result,rows

    def book_for_slot(self,slot,now):
        deadline=slot+dt.timedelta(seconds=120);candidates=[]
        root=Path(self.c['derivation']['source'])/'market'
        for path in root.iterdir():
            # mtime is only an index hint; archived timestamps/hash qualify every result.
            if not slot.timestamp()-120 <= path.stat().st_mtime <= deadline.timestamp()+120:continue
            v=read(path)
            if slot<=p.timestamp(v['observed_at_start'])<=p.timestamp(v['observed_at_end'])<=min(now,deadline):
                try:verified_market(v,self.universe,now)
                except ValueError:continue
                candidates.append(v)
        return min(candidates,key=lambda x:(x['observed_at_end'],x['record_hash'])) if candidates else None

    def recover_passive_grid(self, record):
        """Reconstruct held quantities during downtime; never reconstruct trades."""
        last=self.db.execute('SELECT MAX(at) FROM observations').fetchone()[0]
        start=p.timestamp(last) if last else self.t0
        end=p.timestamp(record['observed_at_end'])
        grid=dt.datetime.fromtimestamp((int(start.timestamp())//300+1)*300,UTC)
        while grid+dt.timedelta(seconds=300)<end:
            states=self.states();marks={}
            for s in self.universe:
                row=self.original.execute('SELECT bar,price FROM marks WHERE symbol=? AND bar<=? ORDER BY bar DESC LIMIT 1',(s,grid.isoformat())).fetchone()
                if not row or (grid-p.timestamp(row['bar'])).total_seconds()>300:
                    with self.db:self.put('valuation_gap',dict(at=grid.isoformat(),reason='missing_causal_grid_mark'))
                    return
                marks[s]=row['price']
            historical=dict(record,observed_at_end=grid.isoformat());debt=None;rows=[]
            try:states,rows=self.fund(states,historical)
            except (ValueError,KeyError,TypeError) as error:debt=str(error)
            observation=dict(states={},funding_debt=debt,reconstructed=True,source_market_hash=record['record_hash'])
            for arm,state in states.items():
                for s,mark in marks.items():state['positions'][s].update(current_price=mark,last_mark_at=grid.isoformat())
                metrics=paper.totals(state,require_positive=False)
                engine.risk_gate(state,grid,metrics['equity']);observation['states'][arm]=metrics
            original=self.original.execute('SELECT bar,equity,pnl FROM equity_history WHERE bar<=? ORDER BY bar DESC LIMIT 1',(grid.isoformat(),)).fetchone()
            if original and (grid-p.timestamp(original['bar'])).total_seconds()<=300:
                observation['states']['ORIGINAL']=dict(equity=original['equity'],pnl=original['pnl']);observation['original_at']=original['bar']
            with self.db:
                for arm,state in states.items():self.db.execute('UPDATE states SET payload=? WHERE arm=?',(dump(state),arm))
                for f in rows:self.db.execute('INSERT INTO funding VALUES(?,?,?,?,?)',(f['arm'],f['symbol'],f['at'],f['amount'],dump(f)))
                self.db.execute('INSERT INTO observations VALUES(?,?,?)',(grid.isoformat(),record['record_hash'],dump(observation)))
            grid+=dt.timedelta(seconds=300)

    def tick(self,now=None):
        now=now or source.now();first=p.timestamp(self.receipt['first_decision_slot'])
        slot=now.replace(hour=0,minute=15,second=0,microsecond=0)
        ended=now>=p.timestamp(self.receipt['end_exclusive'])
        if ended:
            with self.db:self.put('health',dict(status='COMPLETED_AWAITING_REVIEW',checked_at=now.isoformat(),reason='fixed_horizon_reached'))
            return
        # Record skipped sessions, without any retrospective simulated orders.
        pending=first
        with self.db:
            while pending+dt.timedelta(seconds=120)<now:
                self.db.execute('INSERT OR IGNORE INTO slots VALUES(?,?,?)',(pending.isoformat(),'MISSED',dump({'reason':'outside_execution_window'})))
                pending+=dt.timedelta(days=1)
        due=slot>=first and slot<=now<=slot+dt.timedelta(seconds=120) and not self.db.execute('SELECT 1 FROM slots WHERE slot=?',(slot.isoformat(),)).fetchone()
        record=self.book_for_slot(slot,now) if due else None
        action=due and record is not None
        if record is None:record=read(Path(self.c['derivation']['source'])/'market.json')
        verified_market(record,self.universe,now)
        self.recover_passive_grid(record)
        at=p.timestamp(record['observed_at_end'])
        last=self.db.execute('SELECT MAX(at) FROM observations').fetchone()[0]
        if last and at<p.timestamp(last):raise ValueError('clock_or_capture_regression')
        # 5-minute observation grid; daily action is also an observation.
        if not action and last and int(at.timestamp())//300==int(p.timestamp(last).timestamp())//300:
            with self.db:self.put('health',dict(status='OBSERVING',checked_at=now.isoformat(),reason=self.meta('funding_debt')))
            return
        states=self.states();debt=None;funding_rows=[]
        try:states,funding_rows=self.fund(states,record)
        except (ValueError,KeyError,TypeError) as error:debt=str(error)
        for state in states.values():
            for s,q in record['quotes'].items():state['positions'][s].update(current_price=q['mark_price'],last_mark_at=q['mark_timestamp'])
            engine.risk_gate(state,at,paper.totals(state,require_positive=False)['equity'])
        filters=self.meta('filters');fills=[];outcome=None;status=None
        if action:
            try:
                item=self.prepare_input(slot)
                states,filters,fills,outcome=apply_pair(states,item['targets'],item['prices'],filters,record,at,debt or self.meta('valuation_gap'))
                outcome.update(proposal_id=item['proposal_id'],snapshot_id=item['snapshot_id'],market_hash=record['record_hash'])
                status='EXECUTED' if fills else 'OBSERVED_NO_FILL'
            except (ValueError,KeyError,TypeError) as error:status='DENIED';outcome={'reason':str(error)}
            # Never backdate an action if reconstruction ran past the window.
            if source.now()>slot+dt.timedelta(seconds=120):raise ValueError('execution_deadline_expired')
        original=json.loads(self.original.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        observation={'states':{},'funding_debt':debt,'original_at':original.get('last_success_at')}
        for arm,state in dict(states,ORIGINAL=original).items():
            observation['states'][arm]=paper.totals(state,require_positive=False)
        # No side effect before this all-or-nothing transaction. Disk failure rolls back both arms.
        with self.db:
            if action:self.db.execute('INSERT INTO slots VALUES(?,?,?)',(slot.isoformat(),status,dump(outcome)))
            for arm,state in states.items():self.db.execute('UPDATE states SET payload=? WHERE arm=?',(dump(state),arm))
            for f in fills:self.db.execute('INSERT INTO fills VALUES(?,?,?,?,?,?)',(p.digest(dict(f,slot=slot.isoformat())),f['arm'],f['at'],f['symbol'],f['quantity'],dump(f)))
            for f in funding_rows:self.db.execute('INSERT INTO funding VALUES(?,?,?,?,?)',(f['arm'],f['symbol'],f['at'],f['amount'],dump(f)))
            self.db.execute('INSERT OR IGNORE INTO observations VALUES(?,?,?)',(at.isoformat(),record['record_hash'],dump(observation)))
            self.put('filters',filters);self.put('funding_debt',debt)
            self.put('health',dict(status='OBSERVING',checked_at=now.isoformat(),reason=debt))

    def close(self):
        self.db.close();self.seed.close();self.original.close()

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',required=True);parser.add_argument('--once',action='store_true');parser.add_argument('--initialize',action='store_true')
    args=parser.parse_args();os.umask(0o027);config_path=Path(args.config)
    if config_path.is_symlink() or config_path.stat().st_uid!=0 or config_path.stat().st_mode&0o022:raise ValueError('config_custody')
    c=read(config_path)
    if os.geteuid()!=c['runner_uid']:raise ValueError('runner_identity')
    lock=open(str(c['db'])+'.lock','a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    runner=Runner(c,initialize=args.initialize)
    from octobot.ai_strategy_lab.v13_fork_view import publish
    while True:
        try:runner.tick()
        except Exception as error:
            with runner.db:runner.put('health',dict(status='BLOCKED',checked_at=source.now().isoformat(),reason=str(error)))
            print(dump({'status':'BLOCKED','reason':str(error)}),flush=True)
        publish(runner)
        if args.once:break
        time.sleep(20)
    runner.close()

if __name__=='__main__':main()
