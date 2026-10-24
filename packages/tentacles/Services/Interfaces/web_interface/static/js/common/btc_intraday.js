'use strict';
(() => {
const $=id=>document.getElementById(id), num=(x,d=2)=>Number.isFinite(x)?x.toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d}):'—', at=x=>x?new Date(x/1e6).toISOString().replace('T',' ').slice(0,19):'—';
const labels={WARMUP:'Raccolta iniziale',EXIT_PENDING:'Chiusura protettiva in corso',PRESTART_WARMUP:'Raccolta prima dell’avvio',WARMUP_OR_MISSING_INPUT:'Finestra non ancora completa',NO_SIGNAL:'Nessun segnale M1',PRICE_MISSING:'Book fresco non disponibile',SHORT_OPEN:'SHORT aperto',ENTRY_SCHEDULED:'Ingresso programmato',ENTRY_MISSED_PERSISTENCE_DEADLINE:'Ingresso saltato: dati tardivi',L5_WINDOW_INCOMPLETE:'Finestra book incompleta',PROTECTIVE_CLOSE_COMPLETE:'Chiusura protettiva completata',POSITION_OR_INTENT_PENDING:'Posizione o operazione già in corso',FUNDING_PENDING:'Funding in attesa',FUNDING_CALENDAR_MISSING:'Calendario funding assente',DAILY_LOSS_HALT:'Stop giornaliero',DRAWDOWN_HALT:'Stop per drawdown',MISSED_DEADLINE:'Scadenza mancata',FUNDING_BOUNDARY:'Vicino al regolamento funding'};
// Diagnostic presentation only; a recent accepted book never grants an entry.
function activity(v){
 const s=v.state,latest=(v.slots||[]).reduce((a,b)=>!a||b.slot_ns>a.slot_ns?b:a,null);
 const note=latest?'Ultimo slot registrato: '+at(latest.slot_ns)+' UTC · '+(labels[latest.status]||latest.status)+'.':'Nessuno slot ancora registrato.';
 const result=text=>({text,note});
 if(v.retired===true)return {text:'Ritirato · storico conservato',note:'Nessuna nuova operazione. Questo archivio conserva il risultato finale dell’esperimento precedente.'};
 if(v.stale)return result('Dati non aggiornati');
 if(v.status.startsWith('BLOCKED'))return result('Conto fermo: '+(v.error||'verifica richiesta'));
 if(v.status==='ACTIVE_RISK_HALTED'||s.daily?.halt||s.drawdown_halt||s.integrity_halt)return result('Nuovi ingressi sospesi dal rischio'+(s.pending?.kind==='EXIT'?' · '+labels.EXIT_PENDING:''));
 if(s.pending)return result(s.pending.kind==='ENTRY'?labels.ENTRY_SCHEDULED:labels.EXIT_PENDING);
 if(s.q<0)return result(labels.SHORT_OPEN);
 if(v.status==='OBSERVATION_ENDED')return result('Periodo di osservazione concluso');
 if(v.status==='ACTIVE_PRESTART')return result('In attesa del primo giorno di osservazione');
 if(v.warmup_rows<v.warmup_required)return result(labels.WARMUP);
 if(s.reason==='PRICE_MISSING'){
  if(!Number.isFinite(v.book_age_seconds))return result('Ultimo book accettato non verificabile');
  if(v.book_age_seconds>1)return result('Ultimo book accettato non aggiornato');
  if(!latest)return result('In attesa della prima valutazione');
  if(v.checked_at_ns-latest.slot_ns>330e9)return result('Ultima valutazione non recente');
  return result('Ultimo slot: '+(labels[latest.status]||latest.status));
 }
 return result(labels[s.reason]||s.reason);
}
let points=[],stressPoints=[],retirement=null;
function cell(tr,value,cls){const td=document.createElement('td');td.textContent=value;if(cls)td.className=cls;tr.append(td);}
function chart(){
const canvas=$('chart'),r=canvas.getBoundingClientRect(),dpi=window.devicePixelRatio||1;
canvas.width=r.width*dpi;canvas.height=r.height*dpi;
const c=canvas.getContext('2d');c.scale(dpi,dpi);const w=r.width,h=r.height,pad=48;
const primary=points.map(p=>[p[0],p[1],p[3]]), series=[[primary,'#4ed6b0'],[stressPoints,'#eac47b']];
const all=series.flatMap(([data])=>data).filter(p=>p[2]&&Number.isFinite(p[1]));
if(!all.length)return;
const ys=all.map(p=>p[1]);let low=Math.min(...ys),high=Math.max(...ys);
if(high-low<2){low-=1;high+=1;}
const times=all.map(p=>p[0]),x0=Math.min(...times),x1=Math.max(...times);
const xx=t=>pad+(w-pad-10)*(t-x0)/(x1-x0||1),yy=y=>h-30-(h-45)*(y-low)/(high-low);
c.font='11px system-ui';c.fillStyle='#adbed5';
for(let i=0;i<4;i++){const y=low+(high-low)*i/3;c.strokeStyle='#2a3b53';c.beginPath();c.moveTo(pad,yy(y));c.lineTo(w,yy(y));c.stroke();c.fillText(num(y),0,yy(y)+4);}
for(const [data,color] of series){c.strokeStyle=color;c.lineWidth=1.7;c.beginPath();let previous=null;
for(const p of data){if(!p[2]||!Number.isFinite(p[1])){previous=null;continue;}
if(!previous||p[0]-previous[0]>120e9)c.moveTo(xx(p[0]),yy(p[1]));else c.lineTo(xx(p[0]),yy(p[1]));previous=p;}c.stroke();}
c.fillText(at(x0).slice(5,16),pad,h-8);c.fillText(at(x1).slice(5,16)+' UTC',Math.max(pad,w-150),h-8);
}
async function update(){try{const response=await fetch('/btc_intraday/data',{cache:'no-store'});if(!response.ok)throw Error('Risposta non disponibile');const v=await response.json();if(!v.available&&v.available!==undefined)throw Error(v.message||'Conto non disponibile');retirement=v.retired===true?v.retirement:null;const s=v.state;$('content').classList.remove('hidden');const shown=activity(v);$('status').textContent=(v.retired||v.stale||v.status.startsWith('BLOCKED')?'':'Conto intraday paper · ')+shown.text;$('updated').textContent='Aggiornato '+at(v.checked_at_ns)+' UTC';$('equity-title').textContent=v.accounting_complete?'Equity virtuale':'Equity provvisoria · funding pending';$('equity').textContent=num(v.metrics.equity)+' USDT';$('pnl').textContent=(v.metrics.pnl>=0?'+':'')+num(v.metrics.pnl)+' USDT';$('pnl').className='amount '+(v.metrics.pnl>=0?'gain':'loss');$('position').textContent=s.q<0?'SHORT':'FLAT';$('quantity').textContent=num(s.q,3)+' BTC';$('fills-count').textContent=s.fills;$('warmup').textContent=v.warmup_rows+' / '+v.warmup_required;$('progress').value=v.warmup_rows;$('book-age').textContent=num(v.book_age_seconds,2)+' s';$('reason').textContent=shown.text;$('reason-note').textContent=shown.note;$('engine-note').textContent='Motivo memorizzato dal motore: '+s.reason+' · '+(s.reason==='PRICE_MISSING'?'Book non disponibile durante un controllo. Questo motivo può restare memorizzato dopo nuovi book accettati; non descrive da solo lo stato attuale.':labels[s.reason]||s.reason);$('warmup-note').textContent='Servono 289 punti consecutivi di 5 minuti, su tutti i 18 mark. I buchi restano visibili e possono prolungare l’attesa.';$('window').textContent='Conto creato: '+at(s.activation_at)+' UTC · Finestra scientifica: '+at(s.t0)+' → '+at(s.t1)+' UTC.';points=v.equity;stressPoints=v.stress_equity_history||[];chart();$('chart-empty').textContent=points.length<2?'Prime valorizzazioni in raccolta.':'';$('slots').replaceChildren();for(const r of v.slots){const tr=document.createElement('tr'),f=r.detail.feature;cell(tr,at(r.slot_ns));cell(tr,f?num(f.btc_return*100)+'%':'—');cell(tr,f?f.negative+' / 18':'—');cell(tr,labels[r.status]||r.status);$('slots').append(tr);}$('slots-empty').textContent=v.slots.length?'':'Il primo slot futuro viene registrato automaticamente.';$('fills').replaceChildren();for(const f of v.fills){const tr=document.createElement('tr');cell(tr,at(f.at_ns));cell(tr,f.quantity<0?'SELL · apertura SHORT':'BUY · chiusura SHORT');cell(tr,num(f.quantity,3));cell(tr,num(f.price));cell(tr,num(f.realized,4),f.realized>=0?'gain':'loss');cell(tr,num(f.fee,4));cell(tr,num(f.detail.equity_impact,4),f.detail.equity_impact>=0?'gain':'loss');$('fills').append(tr);}$('fills-empty').textContent=v.fills.length?'':'Nessuna operazione: il conto attende finestra completa e segnale valido.';}catch(e){$('status').textContent='Conto temporaneamente non verificabile: '+e.message;}}
const renderArchive=()=>{if(retirement){document.querySelector('h1').textContent='BTC intraday precedente · archivio';document.title='BTC intraday · archivio ritirato';$('updated').textContent='Ritirato il '+at(retirement.retired_at_ns)+' UTC · dati finali congelati';$('book-age').textContent='Archivio';$('warmup-note').textContent='Raccolta terminata per questo conto. I nuovi conti SHORT controllo e LONG + SHORT proseguono separatamente.';$('operating-note').textContent='Questo conto è stato ritirato. Equity, grafici e operazioni sono congelati e restano consultabili.';}};
window.addEventListener('resize',chart);const refresh=async()=>{await update();renderArchive();};refresh();setInterval(refresh,5000);
})();
