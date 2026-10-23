"""Offline attribution and advisory review; no runtime, order or grant interface.

Card work-card-37c30a2c-ad80-4eda-b1a6-f8bc7d41ab13. Inputs must be private,
coherent snapshots; this CLI refuses writable/open-live databases by contract.
"""
import argparse
import bisect
from collections import defaultdict
from contextlib import closing
import csv
import datetime as dt
from decimal import Decimal, ROUND_FLOOR
import hashlib
import json
import math
from pathlib import Path
import sqlite3

UTC=dt.timezone.utc
SIDES=('LONG','SHORT')
MAX_AGE=180.
METHOD = dict(
    scope='EXPLORATORY_ADVISORY_ONLY', windows=['since_clone', '48h', '24h'],
    minimum_mark_coverage=.95, maximum_mark_age_seconds=MAX_AGE,
    minimum_long_exposure_hours=48, reduction_fraction=.5,
    maximum_reduction_proposals=2,
    ranking='negative_long_net_per_1000_observed_notional_days',
    execution_policy_approved=False,
    cash_reallocation=False, increases_proposed=False,
)


def timestamp(value):
    x=dt.datetime.fromisoformat(value.replace('Z','+00:00'))
    if x.tzinfo is None:raise ValueError('timezone_required')
    return x.timestamp()


def iso(t):return dt.datetime.fromtimestamp(t,UTC).isoformat()


def number(v):
    if type(v) not in (int,float) or not math.isfinite(v):raise ValueError('finite_number_required')
    return float(v)


def close(a,b):return math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-6)


def side(q):return 'LONG' if q>0 else 'SHORT' if q<0 else None


def pnl(pos):
    return pos['realized_pnl']+pos['quantity']*(pos['current_price']-pos['entry_price'])+pos['funding']-pos['fees']


def account_fill(before, entry, amount, price, fee, action):
    """Independent offline average-cost accounting, reconciled to ledger state.

    BUY/SELL describe quantity direction. A crossing fill realizes only the
    old exposure; the residual starts a new cost basis at the fill price.
    """
    before, entry, amount, price, fee = map(number, (before, entry, amount, price, fee))
    if fee < 0 or price <= 0 or not amount or (before and entry <= 0):
        raise ValueError('invalid_fill')
    if action != ('BUY' if amount > 0 else 'SELL'):
        raise ValueError('invalid_fill')
    old, change = Decimal(str(before)), Decimal(str(amount))
    after = old + change
    if abs(after) <= Decimal('1e-12') * max(abs(old), abs(change)):
        after = Decimal(0)
    after = float(after)
    closed = min(abs(before), abs(amount)) if before * amount < 0 else 0.
    realized = closed * (price - entry) * (1 if before > 0 else -1)
    if not after:
        next_entry = 0.
    elif not before or before * after < 0:
        next_entry = price
    elif before * amount > 0:
        next_entry = (abs(before) * entry + abs(amount) * price) / abs(after)
    else:
        next_entry = entry
    # A negligible float residue on a full close must not get a phantom fee.
    fee_closed = abs(amount) if before and not after else closed
    return dict(after=after, entry=next_entry, realized=realized,
                closed=fee_closed, opened=abs(amount)-fee_closed)


def load_snapshot(path):
    path=Path(path).resolve()
    if not path.is_file() or path.stat().st_mode & 0o222:
        raise ValueError('read_only_snapshot_required')
    with closing(sqlite3.connect(path.as_uri()+'?mode=ro',uri=True)) as c:
        c.row_factory=sqlite3.Row;c.execute('PRAGMA query_only=ON')
        state=json.loads(c.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])
        fills=[dict(r) for r in c.execute("SELECT * FROM orders WHERE status='filled' ORDER BY bar,id")]
        funding=[dict(r) for r in c.execute('SELECT * FROM funding_events ORDER BY timestamp_ms,symbol')]
        marks=defaultdict(list)
        for r in c.execute('SELECT symbol,bar,price FROM marks ORDER BY bar,symbol'):
            marks[r['symbol']].append((timestamp(r['bar']),number(r['price'])))
        equity=c.execute('SELECT bar,equity FROM equity_history ORDER BY bar DESC LIMIT 1').fetchone()
        episodes=[]
        if c.execute("SELECT 1 FROM sqlite_master WHERE name='m1_episodes'").fetchone():
            episodes=[dict(r) for r in c.execute('SELECT id,signal_at,entry_due,exit_due,status FROM m1_episodes ORDER BY signal_at')]
        return dict(state=state,fills=fills,funding=funding,marks=marks,
                    equity_observation=dict(equity) if equity else None,episodes=episodes)


def replay(fills,cutoff):
    q=entry=realized=fees=0.
    for f in fills:
        if timestamp(f['bar'])>cutoff:break
        amount=number(f['quantity']);price=number(f['price']);fee=number(f['fee'])
        if fee<0 or price<=0 or amount==0 or f['action']!=('BUY' if amount>0 else 'SELL'):
            raise ValueError('invalid_fill')
        a=account_fill(q,entry,amount,price,fee,f['action'])
        realized+=a['realized'];fees+=fee;entry=a['entry'];q=a['after']
    return dict(q=q,entry=entry,realized=realized,fees=fees)


def price_before(marks,t,max_age=MAX_AGE):
    i=bisect.bisect_right(marks,(t,float('inf')))-1
    if i<0 or not 0<=t-marks[i][0]<=max_age:raise ValueError('boundary_mark_missing')
    return marks[i]


def attribution(fills,funding,marks,start,end,*,start_mark=None,end_mark=None):
    """Window net = realized delta + open-PnL change - fees + recorded funding.

    Signed funding uses the quantity recorded at settlement; a reversing fill
    splits fees proportionally and assigns realization only to the closed leg.
    Exposure uses previous observed prices for at most 180s, with no interpolation.
    """
    if end<=start:raise ValueError('invalid_window')
    fills=sorted(fills,key=lambda f:(timestamp(f['bar']),f['id']))
    marks=sorted((number(t),number(p)) for t,p in marks)
    if any(p<=0 for _,p in marks):raise ValueError('invalid_mark')
    initial=replay(fills,start);q=initial['q'];entry=initial['entry']
    if start_mark is None:
        try:mark_at,mark=price_before(marks,start)
        except ValueError:
            if q:raise
            mark_at,mark=start,None
    else:mark_at,mark=start_mark
    if mark_at>start or (q and start-mark_at>MAX_AGE):raise ValueError('boundary_mark_missing')
    if mark is not None and mark<=0:raise ValueError('invalid_mark')
    stats={s:dict(realized=0.,fees=0.,funding=0.,turnover=0.,exposure_seconds=0.,covered_exposure_seconds=0.,notional_seconds=0.,new_episodes=0,closed_episodes=0,carried_episodes=int(side(q)==s),observed_drawdown=0.) for s in SIDES}
    initial_u={s:q*(mark-entry) if side(q)==s else 0. for s in SIDES}
    peak={s:0. for s in SIDES};last=start;count=0
    events=[]
    for t,p in marks:
        if start<t<=end:events.append((t,1,(t,p)))
    for f in fills:
        t=timestamp(f['bar'])
        if start<t<=end:events.append((t,2,f))
    for f in funding:
        t=number(f['timestamp_ms'])/1000
        if start<t<=end:events.append((t,0,f))
    def accrue(t):
        nonlocal last
        if q:
            s=stats[side(q)];s['exposure_seconds']+=t-last
            covered=max(0.,min(t,mark_at+MAX_AGE)-last) if mark is not None else 0.
            s['covered_exposure_seconds']+=covered
            s['notional_seconds']+=abs(q)*mark*covered if mark is not None else 0.
        last=t
    def observe(t):
        if q and (mark is None or t-mark_at>MAX_AGE):return
        for name in SIDES:
            s=stats[name];u=q*(mark-entry) if side(q)==name else 0.
            net=s['realized']+u-initial_u[name]-s['fees']+s['funding']
            peak[name]=max(peak[name],net);s['observed_drawdown']=max(s['observed_drawdown'],peak[name]-net)
    for t,kind,event in sorted(events,key=lambda x:(x[0],x[1])):
        accrue(t)
        if kind==1:mark_at,mark=event
        elif kind==0:
            qty=number(event['quantity']);amount=number(event['amount'])
            if qty==0 and abs(amount)>1e-10:raise ValueError('funding_without_side')
            if qty:stats[side(qty)]['funding']+=amount
        else:
            amount=number(event['quantity']);price=number(event['price']);fee=number(event['fee'])
            if fee<0 or price<=0 or not amount or event['action']!=('BUY' if amount>0 else 'SELL'):raise ValueError('invalid_fill')
            a=account_fill(q,entry,amount,price,fee,event['action'])
            old_side=side(q);new_side=side(a['after']);closed=a['closed'];opened=a['opened']
            if closed:
                s=stats[old_side];s['realized']+=a['realized'];s['fees']+=fee*closed/abs(amount);s['turnover']+=closed*price
                if new_side!=old_side:s['closed_episodes']+=1
            if opened:
                s=stats[new_side];s['fees']+=fee*opened/abs(amount);s['turnover']+=opened*price
                if old_side!=new_side:s['new_episodes']+=1
            q=a['after'];entry=a['entry'];count+=1
        observe(t)
    accrue(end)
    if end_mark is None:
        try:mark_at,mark=price_before(marks,end)
        except ValueError:
            if q:raise
    else:mark_at,mark=end_mark
    if mark_at>end or (q and end-mark_at>MAX_AGE):raise ValueError('boundary_mark_missing')
    observe(end)
    for name,s in stats.items():
        s['open_pnl_start']=initial_u[name];s['open_pnl_end']=q*(mark-entry) if side(q)==name else 0.
        s['net']=s['realized']+s['open_pnl_end']-s['open_pnl_start']-s['fees']+s['funding']
        s['coverage']=s['covered_exposure_seconds']/s['exposure_seconds'] if s['exposure_seconds'] else None
        s['notional_days']=s.pop('notional_seconds')/86400
        s['net_per_1000_notional_days']=s['net']*1000/s['notional_days'] if s['notional_days'] else None
        s['mean_notional']=s['notional_days']*86400/s['covered_exposure_seconds'] if s['covered_exposure_seconds'] else None
        s['active_days']=s['exposure_seconds']/86400
    return dict(start=iso(start),end=iso(end),days=(end-start)/86400,sides=stats,net=sum(x['net'] for x in stats.values()),quantity=q,entry=entry,fill_count=count)


def review_account(account,seed,start,end):
    state=account['state'];symbols=sorted(seed['state']['positions'])
    if set(state['positions'])!=set(symbols):raise ValueError('universe_mismatch')
    result={};all_fills=defaultdict(list);all_funding=defaultdict(list)
    for f in account['fills']:all_fills[f['symbol']].append(f)
    for f in account['funding']:all_funding[f['symbol']].append(f)
    for symbol in symbols:
        s=state['positions'][symbol];base=seed['state']['positions'][symbol];fills=all_fills[symbol];full=replay(fills,end)
        if not all(close(full[k],s[field]) for k,field in [('q','quantity'),('entry','entry_price'),('realized','realized_pnl'),('fees','fees')]):
            raise ValueError('state_replay_mismatch:'+symbol)
        if not close(sum(number(f['amount']) for f in all_funding[symbol]),s['funding']):raise ValueError('funding_reconciliation:'+symbol)
        # The clone is a true economic seed; inherited open PnL is deducted.
        windows={}
        for label,a in [('since_clone',start),('48h',max(start,end-48*3600)),('24h',max(start,end-24*3600))]:
            v=attribution(fills,all_funding[symbol],account['marks'][symbol],a,end,
                          start_mark=(timestamp(base['last_mark_at']),base['current_price']) if a==start else None,
                          end_mark=(end,s['current_price']))
            v['complete_requested_window']=label=='since_clone' or end-start >= (48 if label=='48h' else 24)*3600
            windows[label]=v
        expected=pnl(s)-pnl(base)
        if not close(windows['since_clone']['net'],expected):raise ValueError('clone_delta_reconciliation:'+symbol)
        result[symbol]=dict(current_quantity=s['quantity'],current_mark=s['current_price'],current_entry=s['entry_price'],inherited_net=pnl(base),since_clone=expected,windows=windows)
    equity=seed['state']['initial_equity']+sum(pnl(s) for s in state['positions'].values())
    if account.get('equity_observation') and not close(equity,account['equity_observation']['equity']):
        raise ValueError('equity_history_reconciliation')
    return dict(symbols=result,equity=equity,equity_observation=account.get('equity_observation'),
                episodes=account.get('episodes',[]),net_since_clone=sum(x['since_clone'] for x in result.values()))


def reduction_cost(qty,quote):
    """Indicative mark-to-fill equity cost using archived bids and synthetic rules."""
    step=number(quote['step']);mark=number(quote['mark_price'])
    if qty<=0 or step<=0 or mark<=0:raise ValueError('invalid_reduction')
    lots=Decimal(str(qty))/Decimal(str(step))
    if abs(lots-lots.to_integral_value())>Decimal('1e-8'):
        return dict(available=False,reason='current_quantity_off_grid')
    target_d=(Decimal(str(qty))*Decimal('0.5')/Decimal(str(step))).to_integral_value(rounding=ROUND_FLOOR)*Decimal(str(step))
    if not target_d:return dict(available=False,reason='cannot_halve_without_full_close')
    target=float(target_d);amount=float(Decimal(str(qty))-target_d);remaining=amount;gross=0.
    for level in quote['bids']:
        quantity=number(level['base_quantity']);price=number(level['price'])
        if quantity<0 or price<=0:raise ValueError('invalid_book')
        used=min(remaining,quantity);gross+=used*price;remaining-=used
        if remaining<=1e-10:break
    if remaining>1e-8:return dict(available=False,reason='observed_depth_insufficient')
    price=gross/amount*(1-.0002);fee=amount*price*max(.0006,number(quote['fee_rate']))
    if amount*price<number(quote['simulation_min_notional']) or amount<number(quote['simulation_min_quantity']):return dict(available=False,reason='below_simulation_minimum')
    return dict(available=True,quantity_before=qty,indicative_quantity_after=target,quantity_to_sell=amount,indicative_fill_price=price,fee=fee,estimated_immediate_equity_cost=amount*(mark-price)+fee,freed_mark_notional=amount*mark)


def proposals(m1,original,quotes):
    candidates=[];rows=[]
    for symbol,r in m1['symbols'].items():
        full=r['windows']['since_clone']['sides']['LONG'];recent=r['windows']['48h']['sides']['LONG'];q=r['current_quantity']
        eligible=(q>0 and full['net']<0 and recent['net']<0 and full['active_days']*24>=METHOD['minimum_long_exposure_hours'] and full['coverage'] is not None and full['coverage']>=METHOD['minimum_mark_coverage'] and recent['coverage'] is not None and recent['coverage']>=METHOD['minimum_mark_coverage'])
        if eligible:candidates.append((full['net_per_1000_notional_days'],symbol))
        row=dict(symbol=symbol,action='MANTIENI',reason='Nessun deterioramento LONG concorde nei due periodi.',confidence='EXPLORATORY_SHORT_HISTORY',eligible_long_reduction=eligible,ranking_value=full['net_per_1000_notional_days'],current_quantity=q,current_weight_pct=100*abs(q*r['current_mark'])/m1['equity'],original_since_clone=original['symbols'][symbol]['since_clone'],m1_since_clone=r['since_clone'],effect_on_m1='Un eventuale long ridotto riduce anche la quantita invertibile dal filtro M1.',applied=False,execution_authorized=False)
        if q==0:
            row.update(action='MANTIENI_FLAT',reason='Nessuna posizione attuale. Valutare rientro con evidenze nuove; il P/L ereditato non autorizza un nuovo ingresso.')
        elif full['net']<0 or recent['net']<0:
            row.update(action='OSSERVA_SENZA_AUMENTO_PROPOSTO',reason='Evidenza mista o insufficiente per proporre una riduzione con questa regola esplorativa.')
        if eligible:
            row['reason']='Criteri di deterioramento soddisfatti; priorita assegnata alle due peggiori intensita di perdita LONG.'
        rows.append(row)
    selected={s for _,s in sorted(candidates)[:METHOD['maximum_reduction_proposals']]}
    for r in rows:
        if r['symbol'] in selected:
            r['action']='RIDUZIONE_LONG_50_PERCENTO_DA_VALUTARE';r['reason']='Contributo LONG negativo dalla copia e nelle ultime 48h, almeno due giorni di esposizione e copertura >=95%. Soglie esplorative, policy non approvata.'
            cost=reduction_cost(r['current_quantity'],quotes[r['symbol']]);r['indicative_cost']=cost
            if cost['available']:r['indicative_weight_after_pct']=100*cost['indicative_quantity_after']*m1['symbols'][r['symbol']]['current_mark']/m1['equity']
    return rows


def run(directory):
    directory=Path(directory);receipt=json.loads((directory/'clone-receipt.json').read_text());seed_path=directory/'snapshots/exact-seed.sqlite'
    if hashlib.sha256(seed_path.read_bytes()).hexdigest()!=receipt['seed_sha256']:raise ValueError('seed_hash')
    manifest=json.loads((directory/'snapshot-manifest.json').read_text())
    for name in ('m1','original'):
        if hashlib.sha256((directory/'snapshots'/f'{name}.sqlite').read_bytes()).hexdigest()!=manifest[name]['sha256']:
            raise ValueError('snapshot_hash:'+name)
    seed=load_snapshot(seed_path);m1=load_snapshot(directory/'snapshots/m1.sqlite');original=load_snapshot(directory/'snapshots/original.sqlite')
    start=timestamp(receipt['economic_t0']);end=timestamp(m1['state']['m1_last_market_at'])
    if timestamp(original['state']['last_market_at'])!=end:raise ValueError('snapshots_require_common_market_cutoff')
    seed_ids={(f['id'],f['symbol']):(f['quantity'],f['price'],f['fee']) for f in seed['fills']}
    for acc in (m1,original):
        prefix={(f['id'],f['symbol']):(f['quantity'],f['price'],f['fee']) for f in acc['fills'] if f['id']<=max(k[0] for k in seed_ids)}
        if prefix!=seed_ids:raise ValueError('inherited_prefix_mismatch')
    a=review_account(m1,seed,start,end);b=review_account(original,seed,start,end)
    market=json.loads((directory/'market-at-cutoff.json').read_text());raw={k:v for k,v in market.items() if k!='record_hash'}
    if hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()!=market['record_hash'] or timestamp(market['observed_at_end'])!=end:raise ValueError('market_hash_or_cutoff')
    for s,p in a['symbols'].items():
        if not close(p['current_mark'],market['quotes'][s]['mark_price']):raise ValueError('market_mark_mismatch')
    provenance=dict(seed_sha256=receipt['seed_sha256'],m1_sha256=manifest['m1']['sha256'],original_sha256=manifest['original']['sha256'],market_record_hash=market['record_hash'])
    return dict(schema=1,scope='EXPLORATORY_ADVISORY_ONLY_NO_ORDERS',method=METHOD,provenance=provenance,account_id=receipt['account_id'],start=iso(start),end=iso(end),days=(end-start)/86400,original_reference='same_seed_same_period_different_exposure',funding_basis='recorded_simulator_estimates_at_settlement_time; observation_lag_not_reconstructed',risk_limits_unchanged=True,execution_authorized=False,history_inherited_not_scored=True,scientific_validity='UNASSESSED',m1=a,original=b,proposals=proposals(a,b,market['quotes']))


def write_reports(result, output):
    """Write a new advisory artifact set; never update an existing report."""
    output=Path(output)
    files=[output,output.with_suffix('.csv'),output.with_suffix('.md')]
    if len(set(files))!=3 or any(p.exists() for p in files):raise ValueError('new_outputs_required')
    with output.open('x') as f:json.dump(result,f,indent=2,allow_nan=False);f.write('\n')
    metrics=list(result['m1']['symbols'].values())[0]['windows']['since_clone']['sides']['LONG']
    fields=['account','symbol','window','side','start','end','days','complete_requested_window']+list(metrics)
    with files[1].open('x',newline='') as f:
        writer=csv.DictWriter(f,fieldnames=fields,lineterminator='\n');writer.writeheader()
        for name in ('m1','original'):
            for symbol,record in result[name]['symbols'].items():
                for window,w in record['windows'].items():
                    for direction,values in w['sides'].items():
                        writer.writerow(dict(account=name,symbol=symbol,window=window,side=direction,
                                             **{k:w[k] for k in ('start','end','days','complete_requested_window')},**values))
    with files[2].open('x') as f:f.write(markdown_report(result))


def markdown_report(r):
    def money(value):return f'{value:+.2f}'
    a,b=r['m1'],r['original']
    lines=[
        '# M1 — metriche per simbolo e prime proposte di ribilanciamento', '',
        f"Dalla copia del **{r['start']}** al mercato comune **{r['end']}** ({r['days']:.2f} giorni).",
        'Valori in USDT virtuali. Analisi esplorativa del conto M1 esistente; Originale come riferimento.', '',
        f"M1: equity **{a['equity']:.2f}**, variazione dalla copia **{money(a['net_since_clone'])}**. "
        f"Originale: equity **{b['equity']:.2f}**, variazione sullo stesso periodo **{money(b['net_since_clone'])}**.",
        'Entrambi partono dalla stessa copia economica. Lo storico precedente è conservato, ma il suo P/L non viene contato come risultato nuovo.', '',
        f"Il contributo nuovo M1 è **{money(sum(s['windows']['since_clone']['sides']['LONG']['net'] for s in a['symbols'].values()))} LONG** "
        f"e **{money(sum(s['windows']['since_clone']['sides']['SHORT']['net'] for s in a['symbols'].values()))} SHORT**, con fee e funding inclusi. "
        'La differenza rispetto all’Originale comprende anche variazioni di esposizione e ribilanciamento.', '',
        '## Proposte concrete sul solo conto M1', '',
        'Sono quantità indicative al momento della fotografia, **non ordini applicati**. Il capitale liberato resterebbe liquido, senza aumentare altri simboli.', '',
        '| Simbolo | LONG netto dalla copia / ultime 48h | SHORT netto dalla copia | Quantità LONG prima → proposta | Peso prima → dopo | Costo immediato stimato |',
        '| --- | ---: | ---: | ---: | ---: | ---: |',
    ]
    selected=[p for p in r['proposals'] if p['action'].startswith('RIDUZIONE')]
    for p in selected:
        s=a['symbols'][p['symbol']];w=s['windows'];cost=p['indicative_cost']
        target=f"{p['current_quantity']:g} → {cost['indicative_quantity_after']:g}" if cost['available'] else 'non quotabile'
        weight=f"{p['current_weight_pct']:.2f}% → {p['indicative_weight_after_pct']:.2f}%" if cost['available'] else 'non quotabile'
        expense=f"{cost['estimated_immediate_equity_cost']:.3f}" if cost['available'] else cost['reason']
        lines.append(f"| {p['symbol']} | {money(w['since_clone']['sides']['LONG']['net'])} / {money(w['48h']['sides']['LONG']['net'])} | {money(w['since_clone']['sides']['SHORT']['net'])} | {target} | {weight} | {expense} |")
    if not selected:lines+=['', 'Nessun simbolo soddisfa i criteri della prima proposta; nessuna riduzione forzata.']
    costs=[p['indicative_cost'] for p in selected if p['indicative_cost']['available']]
    lines+=['',
        f"La proposta libererebbe circa **{sum(c['freed_mark_notional'] for c in costs):.2f} USDT** di esposizione LONG, "
        f"con costo immediato indicativo complessivo di **{sum(c['estimated_immediate_equity_cost'] for c in costs):.3f} USDT**.",
        'Il costo comprende differenza fra mark e fill sul book archiviato, slippage avverso di 2 bps e fee di almeno 6 bps. Non è una quotazione eseguibile adesso; profondità e quantità andrebbero ricontrollate al momento della decisione.', '',
        '**Interazione importante:** M1 apre gli SHORT invertendo i LONG posseduti. Dimezzare un LONG ridurrebbe anche il successivo SHORT su quel simbolo. '
        'LTC resta complessivamente positivo grazie agli SHORT: la proposta riguarda il LONG, non l’eliminazione del simbolo. '
        'Prima di applicarla serve definire come mantenere separati i due budget e impedire che il ribilanciamento ordinario ricompri subito la quantità ridotta.', '',
        '## Tutti i simboli: risultato nuovo, distinto per lato', '',
        '| Simbolo | M1 netto | LONG netto | SHORT netto | LONG ultime 48h | Originale stesso periodo | Posizione M1 |',
        '| --- | ---: | ---: | ---: | ---: | ---: | ---: |',
    ]
    for symbol,s in sorted(a['symbols'].items(),key=lambda item:item[1]['since_clone']):
        w=s['windows'];sides=w['since_clone']['sides'];q=s['current_quantity']
        position=f"{'LONG' if q>0 else 'SHORT'} {abs(q):g}" if q else 'FLAT'
        lines.append(f"| {symbol} | {money(s['since_clone'])} | {money(sides['LONG']['net'])} | {money(sides['SHORT']['net'])} | {money(w['48h']['sides']['LONG']['net'])} | {money(b['symbols'][symbol]['since_clone'])} | {position} |")
    lines+=['',
        'DOT richiede una revisione distinta del lato SHORT: non va ridotto il LONG solo perché il totale del simbolo è negativo. '
        'HBAR e AVAX sono già FLAT: nessuna vendita proposta. BTC resta sotto osservazione: soddisfa i criteri di deterioramento LONG, '
        'ma questa prima proposta seleziona solo le due peggiori intensità di perdita, non tutti i simboli negativi.', '',
        '## Metodo, qualità e limiti', '',
        'Per ogni conto, simbolo, lato e finestra (dalla copia, 48h, 24h), JSON e CSV riportano: realizzato, P/L aperto iniziale e finale, '
        'fee, funding registrato, netto, turnover, tempo esposto, copertura, nozionale medio osservato, episodi e drawdown osservato in USDT.',
        '**Netto = realizzato della finestra + P/L aperto finale − P/L aperto iniziale − fee + funding.** '
        'Le inversioni separano chiusura e nuova esposizione; le fee sono ripartite sulle quantità dei due lati. '
        'Gli acquisti che chiudono SHORT contribuiscono al lato SHORT. I riacquisti giornalieri non sono trattati come episodi indipendenti.',
        'La copertura usa solo l’ultimo mark già osservato, valido per massimo 180 secondi; nessuna interpolazione attraverso i buchi. '
        'Il ranking divide il netto LONG per i nozionali-giorno osservati e lo esprime per 1.000 USDT-giorno: è un indicatore diagnostico, '
        'non un rendimento annualizzato né un confronto a pari rischio. Il drawdown è osservato sui campioni disponibili, non garantisce quello fra due campioni.',
        'La regola esplorativa propone al massimo due riduzioni del 50%: LONG attuale, netto LONG negativo dalla copia e nelle ultime 48h, '
        'almeno 48 ore di esposizione LONG e copertura dei mark almeno 95% in entrambe le finestre. '
        'Le soglie sono una proposta di manutenzione, non una policy approvata o una preregistrazione scientifica.',
        f"Il campione comprende **{len(a['episodes'])} episodi M1**, solo {r['days']:.2f} giorni, con mercati correlati. "
        'I ribilanciamenti M1 mancati del 18–19 ottobre alterano il confronto: il vantaggio rispetto all’Originale non misura soltanto il filtro SHORT. '
        'Non è dimostrato che le riduzioni avrebbero migliorato il passato o miglioreranno il futuro.',
        'Il funding è una stima registrata dal simulatore, attribuita al lato della quantità registrata e al tempo di settlement; '
        'il ritardo di acquisizione non è ricostruito. Nessuna certificazione di settlement reale.',
        'Le copie M1, Originale e seed sono state riconciliate per quantità, costo medio, realizzato, fee, funding e saldo. '
        'I controlli di integrità sono stati eseguiti sulle copie offline. Seed e input sono identificati con SHA-256 nel JSON.',
        'Originale e conto M1 non sono stati modificati. Nessuna nuova coin, nessun ordine, nessun grant, nessuna modifica al rischio o alla quarantena. '
        'I minimi del contratto KuCoin restano UNKNOWN; le stime usano esclusivamente il contratto sintetico del paper.', '',
        'Scheda sviluppo: `work-card-37c30a2c-ad80-4eda-b1a6-f8bc7d41ab13`. '
        'Verifica: `work-card-3ed5dd7b-b2d4-4791-a643-4e60c20e3bf7`.', '',
    ]
    return '\n'.join(lines)


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--input',required=True);p.add_argument('--output',required=True);args=p.parse_args();out=Path(args.output)
    if out.exists():raise ValueError('new_output_required')
    result=run(args.input);write_reports(result,out)
    print(json.dumps(dict(start=result['start'],end=result['end'],m1=result['m1']['net_since_clone'],original=result['original']['net_since_clone'],proposals=[(x['symbol'],x['action']) for x in result['proposals'] if x['action'].startswith('RIDUZIONE')])))

if __name__=='__main__':main()
