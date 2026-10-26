/* Read-only accounting windows, refreshed from the published M1 projection. */
'use strict';
(() => {
  let review;
  const el=id=>document.getElementById(id);
  const finite=v=>typeof v==='number'&&Number.isFinite(v);
  const number=(v,d=2)=>finite(v)?new Intl.NumberFormat('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d}).format(v):'—';
  const signed=v=>finite(v)?(v>0?'+':'')+number(v):'—';
  const date=v=>new Date(v).toLocaleString('it-IT',{timeZone:'Europe/Rome',year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',timeZoneName:'short'});
  const text=(id,value)=>{el(id).textContent=value;};
  function cell(row,value,numeric){const td=document.createElement('td');td.textContent=value;if(finite(numeric))td.className=numeric<0?'loss':numeric>0?'gain':'';row.append(td);return td;}
  function metric(id,value){text(id,signed(value)+' USDT');el(id).classList.toggle('loss',finite(value)&&value<0);el(id).classList.toggle('gain',finite(value)&&value>0);}
  function detail(){
    const symbol=el('review-symbol').value,period=el('review-window').value;
    const sides=['m1','original'].flatMap(account=>['LONG','SHORT'].map(side=>review[account].symbols[symbol].windows[period].sides?.[side]));
    const fields=[['Risultato netto · USDT','net',signed],['Realizzato nel periodo · USDT','realized',signed],['P/L aperto iniziale · USDT','open_pnl_start',signed],['P/L aperto finale · USDT','open_pnl_end',signed],['Commissioni · USDT','fees',v=>number(v,4)],['Funding registrato · USDT','funding',v=>number(v,4)],['Ore esposte','exposure_seconds',v=>number(v/3600)],['Copertura dei mark','coverage',v=>finite(v)?number(v*100)+'%':'—'],['Nozionale medio osservato · USDT','mean_notional',number],['Drawdown osservato · USDT','observed_drawdown',number],['Episodi già aperti a inizio periodo','carried_episodes',v=>number(v,0)],['Nuovi episodi','new_episodes',v=>number(v,0)],['Episodi chiusi','closed_episodes',v=>number(v,0)]];
    el('review-detail').replaceChildren();
    fields.forEach(([label,key,format])=>{const row=document.createElement('tr');cell(row,label);sides.forEach(s=>cell(row,s?format(s[key]):'—',key==='net'?s?.[key]:undefined));el('review-detail').append(row);});
  }
  function metrics(){
    if(!review)return;
    const period=el('review-window').value,window=review.periods[period],total=review.m1.totals[period],originalTotal=review.original.totals[period];
    metric('m1-result',total.net);metric('original-result',originalTotal.net);
    text('side-result',signed(total.long_net)+' / '+signed(total.short_net));text('review-sample',number(window.days)+' giorni');
    text('review-episodes',window.crosses_version_boundary?'Il periodo comprende anche la versione precedente':'Periodo della versione selezionata');
    text('metrics-period',date(window.start)+' → '+date(window.end)+(window.complete_requested_window?'':' · periodo disponibile più breve della finestra richiesta')+'. Posizioni alla fine di questo periodo.');
    text('reconciliation-status',total.available?'Somma dei simboli riconciliata con la variazione dell’equity. LONG e SHORT includono fee, funding registrato e variazione del P/L aperto.':'Totale non disponibile: mancano mark validi ai confini per '+total.unavailable_symbols.join(', ')+'. I dati mancanti restano indicati con —.');
    const records=Object.entries(review.m1.symbols).sort((a,b)=>(a[1].windows[period].net??Infinity)-(b[1].windows[period].net??Infinity)||a[0].localeCompare(b[0]));
    el('review-symbols').replaceChildren();
    records.forEach(([symbol,s])=>{
      const w=s.windows[period],l=w.sides?.LONG,sh=w.sides?.SHORT,original=review.original.symbols[symbol].windows[period];
      const row=document.createElement('tr');cell(row,symbol);cell(row,signed(w.net),w.net);cell(row,signed(l?.net),l?.net);cell(row,signed(sh?.net),sh?.net);
      cell(row,l?number(l.fees+sh.fees,4):'—');cell(row,l?number(l.funding+sh.funding,4):'—');
      const reference=cell(row,signed(original.net),original.net);if(!review.original.symbols[symbol].in_universe)reference.title='Simbolo fuori dall’universo dell’Originale: nessuna esposizione su questo conto.';
      cell(row,!w.available?'—':w.quantity===0?'FLAT':(w.quantity>0?'LONG ':'SHORT ')+number(Math.abs(w.quantity),6));
      const td=cell(row,''),button=document.createElement('button');button.type='button';button.textContent='Vedi';button.setAttribute('aria-label','Dettagli '+symbol);button.addEventListener('click',()=>{el('review-symbol').value=symbol;detail();el('detail-title').scrollIntoView({behavior:'smooth',block:'start'});});td.append(button);el('review-symbols').append(row);
    });detail();
  }
  async function start(){
    try{
      const response=await fetch('/v13_variants/m1/review/data',{cache:'no-store',credentials:'same-origin'});if(!response.ok)throw Error();
      const payload=await response.json();if(!payload.available||payload.review.schema!==2||payload.review.execution_authorized!==false)throw Error();
      const previousSymbol=el('review-symbol').value;review=payload.review;
      text('review-status',payload.stale?(payload.refresh_failed?'Ultimo aggiornamento fallito. ':'Dati oltre la soglia di freschezza. ')+'Ultima osservazione valida: '+date(review.end)+'.':'Dati aggiornati al '+date(review.end)+' · calcolo ogni 5 minuti.');
      text('review-period','Nuova gestione dal '+date(review.epoch_start)+' · copia del conto del '+date(review.start)+'. Orari italiani.');
      text('review-identity','Calcolato il '+date(review.generated_at)+' · identità '+payload.report_id.slice(0,16)+' · stessa fine periodo per M1 e Originale.');
      const symbols=Object.keys(review.m1.symbols).sort();el('review-symbol').replaceChildren();symbols.forEach(symbol=>{const option=document.createElement('option');option.value=symbol;option.textContent=symbol;el('review-symbol').append(option);});el('review-symbol').value=symbols.includes(previousSymbol)?previousSymbol:symbols.includes('BTCUSDT')?'BTCUSDT':symbols[0];
      metrics();el('review-content').classList.remove('hidden');
    }catch(error){el('review-content').classList.add('hidden');text('review-status','Metriche M1 aggiornate non disponibili o non verificabili. La selezione automatica e il conto restano consultabili nella sezione sopra.');}
  }
  el('review-window').addEventListener('change',metrics);el('review-symbol').addEventListener('change',detail);start();setInterval(start,60000);
})();
