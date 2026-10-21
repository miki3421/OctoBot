'use strict';
(() => {
 const $ = id => document.getElementById(id), labels = {'control-primary':'SHORT','candidate-primary':'LONG + SHORT','control-stress':'SHORT · stress','candidate-stress':'LONG + SHORT · stress'};
 const fmt = (n,d=2) => Number(n).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d}), utc = ns => new Date(ns/1e6).toISOString().replace('T',' ').slice(0,19)+' UTC';
 const reasons = {PRESTART_WARMUP:'Raccolta prima dell’inizio comune',WARMUP:'Raccolta iniziale',WARMUP_OR_MISSING_INPUT:'Finestra causale incompleta',NO_SIGNAL:'Nessun segnale',POSITION_OR_INTENT_PENDING:'Posizione o ingresso già in corso',L5_WINDOW_INCOMPLETE:'Copertura del book incompleta',ENTRY_SCHEDULED:'Ingresso pianificato',PRICE_MISSING:'Prezzo fresco non disponibile',LONG_OPEN:'LONG aperto',SHORT_OPEN:'SHORT aperto',PROTECTIVE_CLOSE_COMPLETE:'Chiusura protettiva completata',FUNDING_PENDING:'Funding in attesa',MISSED_DEADLINE:'Slot mancato'};
 const reason = s => reasons[s] || s, cell = (tr,txt) => {const td=document.createElement('td');td.textContent=txt;tr.appendChild(td);return td;};
 let last;
 function chart(v) {
  const canvas=$('equity-chart'),dpr=window.devicePixelRatio||1,w=canvas.clientWidth,h=300;canvas.width=w*dpr;canvas.height=h*dpr;
  const c=canvas.getContext('2d');c.scale(dpr,dpr);c.clearRect(0,0,w,h);
  const names=Object.keys(labels),all=names.flatMap(k=>v.arms[k].points.filter(p=>p.complete&&Number.isFinite(p.equity)));
  if(!all.length){$('chart-note').textContent='In attesa delle prime valorizzazioni. Nessun punto di storico inventato.';return;}
  const x0=Math.min(...all.map(p=>p.at_ns)),x1=Math.max(...all.map(p=>p.at_ns));let y0=Math.min(...all.map(p=>p.equity)),y1=Math.max(...all.map(p=>p.equity));const pad=Math.max((y1-y0)*.15,1);y0-=pad;y1+=pad;
  const left=82,right=w-12,top=22,bottom=250,x=t=>left+(t-x0)/(x1-x0||1)*(right-left),y=n=>bottom-(n-y0)/(y1-y0)*(bottom-top);
  c.font='11px system-ui';c.fillStyle='#adbed5';c.strokeStyle='#2a3b53';
  for(let i=0;i<4;i++){const n=y0+(y1-y0)*i/3,yy=y(n);c.beginPath();c.moveTo(left,yy);c.lineTo(right,yy);c.stroke();c.fillText(fmt(n),3,yy+4);}
  names.forEach((k,i)=>{c.strokeStyle=i%2?'#4ed6b0':'#8abfff';c.setLineDash(i>1?[5,5]:[]);c.lineWidth=1.8;c.beginPath();let prev=null;for(const p of v.arms[k].points){if(!p.complete||!Number.isFinite(p.equity)){prev=null;continue;}if(!prev||p.at_ns-prev>120e9)c.moveTo(x(p.at_ns),y(p.equity));else c.lineTo(x(p.at_ns),y(p.equity));prev=p.at_ns;}c.stroke();});c.setLineDash([]);c.fillStyle='#adbed5';c.fillText(utc(x0).slice(5,16),left,280);c.textAlign='right';c.fillText(utc(x1).slice(5,16)+' UTC',right,280);c.textAlign='left';
  $('chart-note').textContent='Valori effettivi dei simulatori, fino alle ultime 5.000 valorizzazioni per conto (circa 42 ore). I punti incompleti e i buchi oltre 2 minuti interrompono le linee. Nessuna normalizzazione a base 10.000.';
 }
 function render(v){
  if(v.phase==='BLOCKED')throw new Error('Servizio sospeso per un errore; verifica operativa necessaria.');
  const phase={PRESTART:'Conti attivi · raccolta prima dell’inizio comune',WARMUP:'Conti attivi · completamento della finestra causale',OBSERVING:'Confronto in osservazione',COMPLETED:'Periodo concluso · in attesa di valutazione'};
  $('pair-status').textContent=v.stale?'Dati non aggiornati: i valori sotto sono l’ultima osservazione disponibile.':phase[v.phase];
  $('content').classList.remove('hidden');$('updated').textContent='Aggiornato '+utc(v.checked_at_ns)+' · solo capitale virtuale';$('accounts').replaceChildren();
  for(const k of ['control-primary','candidate-primary']){const a=v.arms[k],s=v.arms[k.replace('primary','stress')],card=document.createElement('article');card.className='card';
   const h=document.createElement('h2');h.textContent=labels[k];card.appendChild(h);const n=document.createElement('div');n.className='amount';n.textContent=fmt(a.equity)+' USDT';card.appendChild(n);
   const pnl=document.createElement('p');pnl.className=a.equity>=10000?'gain':'loss';pnl.textContent=(a.equity>=10000?'+':'')+fmt(a.equity-10000)+' USDT dal proprio avvio';card.appendChild(pnl);
   for(const text of [(a.q>0?'LONG':a.q<0?'SHORT':'FLAT')+' · '+fmt(a.q,3)+' BTC · '+a.fills+' fill simulati',reason(a.reason),'Commissioni '+fmt(a.fees)+' · funding '+fmt(a.funding)+' USDT','Stress indipendente: '+fmt(s.equity)+' USDT · '+s.fills+' fill',a.complete?'Contabilità funding completa':'Funding incompleto: equity provvisoria']){const p=document.createElement('p');p.className='small muted';p.textContent=text;card.appendChild(p);} $('accounts').appendChild(card);
  }
  const a=v.arms['control-primary'],b=v.arms['candidate-primary'],warm=Math.min(a.warmup_rows,b.warmup_rows);$('warmup').textContent=warm+' / 289';$('progress').value=warm;
  $('book-age').textContent=a.last_book_ns?fmt((v.checked_at_ns-a.last_book_ns)/1e9)+' secondi':'In attesa';$('fanout').textContent=Object.values(v.arms).every(q=>q.cursor===v.input_seq&&q.input_sha===v.input_sha)?v.input_seq+' · quattro scenari allineati':'Disallineamento: da verificare';
  $('horizon').textContent='Inizio comune '+utc(v.t0_ns)+' · termine '+utc(v.t1_ns)+'. Orari UTC.';
  $('slots').replaceChildren();const by=new Map(b.slots.map(s=>[s.slot_ns,s]));for(const s of a.slots){const tr=document.createElement('tr'),f=s.feature;cell(tr,utc(s.slot_ns));cell(tr,f?fmt(f.btc_return*100)+'%':'—');cell(tr,f?f.negative+' / '+f.positive:'—');cell(tr,reason(s.status));cell(tr,by.has(s.slot_ns)?reason(by.get(s.slot_ns).status):'Slot assente');$('slots').appendChild(tr);}
  $('trades').replaceChildren();const trades=Object.entries(v.arms).flatMap(([k,a])=>a.trades.map(t=>({...t,arm:k}))).sort((a,b)=>b.at_ns-a.at_ns).slice(0,100);for(const t of trades){const tr=document.createElement('tr');cell(tr,utc(t.at_ns));cell(tr,labels[t.arm]);cell(tr,(t.quantity>0?'BUY':'SELL')+' · '+(t.kind==='ENTRY'?(t.after>0?'apertura LONG':'apertura SHORT'):(t.before>0?'chiusura LONG':'chiusura SHORT')));cell(tr,fmt(Math.abs(t.quantity),3));cell(tr,fmt(t.price));cell(tr,fmt(t.realized,4));cell(tr,fmt(t.fee,4));$('trades').appendChild(tr);} $('trades-empty').textContent=trades.length?'':'Nessuna operazione simulata registrata. Il conto attende dati completi e un segnale ammesso.';
  chart(v);last=v;
 }
 async function load(){try{const r=await fetch('/btc_intraday_pair/data',{cache:'no-store'});if(!r.ok)throw new Error('Confronto non disponibile o non verificabile.');render(await r.json());}catch(e){$('pair-status').textContent=e.message;$('content').classList.add('hidden');}}
 window.addEventListener('resize',()=>{if(last)chart(last);});load();setInterval(load,15000);
})();
