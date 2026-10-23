/* Read-only M1 review. Card 7756c81b. No order, approval or mutation endpoints. */
'use strict';
(() => {
  let review;
  const el = id => document.getElementById(id);
  const number = (v, digits=2) => v === null ? '—' : new Intl.NumberFormat('it-IT', {minimumFractionDigits:digits,maximumFractionDigits:digits}).format(v);
  const signed = v => (v > 0 ? '+' : '') + number(v);
  const date = v => new Date(v).toLocaleString('it-IT', {timeZone:'UTC',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}) + ' UTC';
  const text = (id, value) => { el(id).textContent = value; };
  function cell(row, value, numeric) {
    const td = document.createElement('td');
    td.textContent = value;
    if (numeric !== undefined) td.className = numeric < 0 ? 'loss' : numeric > 0 ? 'gain' : '';
    row.append(td); return td;
  }
  function metric(id, value) {
    text(id, signed(value)+' USDT');el(id).classList.toggle('loss',value<0);el(id).classList.toggle('gain',value>0);
  }
  function detail() {
    const symbol = el('review-symbol').value, window = el('review-window').value;
    const sides = ['m1','original'].flatMap(account => ['LONG','SHORT'].map(side => review[account].symbols[symbol].windows[window].sides[side]));
    const fields = [
      ['Risultato netto · USDT','net',signed],['Realizzato nella finestra · USDT','realized',signed],
      ['P/L aperto iniziale · USDT','open_pnl_start',signed],['P/L aperto finale · USDT','open_pnl_end',signed],
      ['Commissioni · USDT','fees',v=>number(v,4)],['Funding stimato · USDT','funding',v=>number(v,4)],
      ['Ore esposte','exposure_seconds',v=>number(v/3600)],['Copertura dei mark','coverage',v=>v===null?'—':number(v*100)+'%'],
      ['Nozionale medio osservato · USDT','mean_notional',number],['Drawdown osservato · USDT','observed_drawdown',number],
      ['Episodi ereditati dalla finestra','carried_episodes',v=>number(v,0)],['Nuovi episodi','new_episodes',v=>number(v,0)],['Episodi chiusi','closed_episodes',v=>number(v,0)]
    ];
    el('review-detail').replaceChildren();
    fields.forEach(([label,key,format])=>{
      const row=document.createElement('tr');cell(row,label);sides.forEach(s=>cell(row,format(s[key]),key==='net'?s[key]:undefined));el('review-detail').append(row);
    });
  }
  function metrics() {
    const window=el('review-window').value;
    const records=Object.entries(review.m1.symbols).sort((a,b)=>a[1].windows[window].net-b[1].windows[window].net);
    const sample=records[0][1].windows[window];
    text('metrics-period',date(sample.start)+' → '+date(sample.end)+' · risultati netti della finestra; quantità alla fotografia finale.');
    el('review-symbols').replaceChildren();
    records.forEach(([symbol,s])=>{
      const w=s.windows[window], l=w.sides.LONG, sh=w.sides.SHORT, original=review.original.symbols[symbol].windows[window];
      const row=document.createElement('tr');cell(row,symbol);cell(row,signed(w.net),w.net);cell(row,signed(l.net),l.net);cell(row,signed(sh.net),sh.net);
      cell(row,number(l.fees+sh.fees,4));cell(row,number(l.funding+sh.funding,4));cell(row,signed(original.net),original.net);
      cell(row,s.current_quantity===0?'FLAT':(s.current_quantity>0?'LONG ':'SHORT ')+number(Math.abs(s.current_quantity),6));
      const td=cell(row,'');const button=document.createElement('button');button.textContent='Vedi';button.setAttribute('aria-label','Dettagli '+symbol);
      button.addEventListener('click',()=>{el('review-symbol').value=symbol;detail();el('detail-title').scrollIntoView({behavior:'smooth',block:'start'});});td.append(button);el('review-symbols').append(row);
    });detail();
  }
  function proposals() {
    el('review-proposals').replaceChildren();let freed=0,cost=0;
    review.proposals.filter(p=>p.action.startsWith('RIDUZIONE')).forEach(p=>{
      const card=document.createElement('article');card.className='proposal';const h=document.createElement('h3');h.textContent=p.symbol+' · riduzione LONG';card.append(h);
      const badge=document.createElement('span');badge.className='badge';badge.textContent='Proposta · non applicata';card.append(badge);
      const list=document.createElement('dl'),c=p.indicative_cost;
      function fact(label,value){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value;list.append(dt,dd);}
      if(c.available){
        fact('Quantità LONG prima → proposta',number(p.current_quantity,6)+' → '+number(c.indicative_quantity_after,6));
        fact('Peso del conto prima → proposto',number(p.current_weight_pct)+'% → '+number(p.indicative_weight_after_pct)+'%');
        fact('Esposizione liberata',number(c.freed_mark_notional)+' USDT');fact('Costo immediato stimato',number(c.estimated_immediate_equity_cost,3)+' USDT');freed+=c.freed_mark_notional;cost+=c.estimated_immediate_equity_cost;
      }else fact('Stima di esecuzione','Non disponibile con la profondità o i minimi della fotografia.');
      const s=review.m1.symbols[p.symbol].windows;
      fact('LONG netto · dalla copia / ultime 48 ore',signed(s.since_clone.sides.LONG.net)+' / '+signed(s['48h'].sides.LONG.net)+' USDT');
      fact('SHORT netto · dalla copia',signed(s.since_clone.sides.SHORT.net)+' USDT');card.append(list);
      const reason=document.createElement('p');reason.className='small muted';reason.textContent='LONG negativo in entrambe le finestre; priorità alla perdita rispetto all’esposizione osservata. Il risultato SHORT non giustifica l’eliminazione del simbolo.';card.append(reason);el('review-proposals').append(card);
    });
    text('proposal-total','Totale indicativo: '+number(freed)+' USDT liberati, da tenere liquidi; '+number(cost,3)+' USDT di costo immediato. Nessuna operazione applicata.');
  }
  async function start() {
    try {
      const response=await fetch('/v13_variants/m1/review/data',{cache:'no-store',credentials:'same-origin'});
      if(!response.ok)throw new Error('unavailable');const payload=await response.json();
      if(!payload.available||payload.maintenance_active!==false||payload.review.execution_authorized!==false)throw new Error('unverified');
      review=payload.review;
      text('review-status',(payload.stale?'Fotografia oltre 24 ore: rivedere i dati prima di decidere. ':'Fotografia verificata della revisione. ')+'Proposte non applicate. Nessun aggiornamento automatico del portafoglio.');
      text('review-period',date(review.start)+' → '+date(review.end)+' · questa è una fotografia, non il saldo corrente.');
      metric('m1-result',review.m1.net_since_clone);metric('original-result',review.original.net_since_clone);
      const totals=['LONG','SHORT'].map(side=>Object.values(review.m1.symbols).reduce((n,s)=>n+s.windows.since_clone.sides[side].net,0));
      text('side-result',signed(totals[0])+' / '+signed(totals[1]));text('review-sample',number(review.days)+' giorni');text('review-episodes',review.m1.episodes.length+' episodi M1 · mercati correlati');
      text('review-identity','Revisione del 23 ottobre 2026 · identità '+payload.report_id.slice(0,16)+' · storico precedente conservato ed escluso dal risultato nuovo.');
      Object.keys(review.m1.symbols).sort().forEach(symbol=>{const option=document.createElement('option');option.value=symbol;option.textContent=symbol;el('review-symbol').append(option);});
      el('review-symbol').value='AAVEUSDT';proposals();metrics();el('review-content').classList.remove('hidden');
    }catch(error){el('review-content').classList.add('hidden');text('review-status','Revisione M1 non disponibile o non verificabile. Metriche e proposte non vengono mostrate.');}
  }
  el('review-window').addEventListener('change',metrics);el('review-symbol').addEventListener('change',detail);start();
})();
