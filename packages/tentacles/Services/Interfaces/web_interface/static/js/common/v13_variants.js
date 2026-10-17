/* Read-only view; no account commands. */
(()=>{'use strict';
const $=id=>document.getElementById(id),version=document.querySelector('main').dataset.version,comparison=version==='comparison';
let keys=[];const colors={ORIGINAL:'#8abfff',FAST:'#4ed6b0',HALF:'#eac47b',M1:'#c6a1ff',BTC:'#ffab80'};
let data,intraday=null,fullHistory=false,allAccounts=comparison,chartSeries=[];
const num=(v,d=2)=>v==null?'—':Number(v).toLocaleString('it-IT',{minimumFractionDigits:d,maximumFractionDigits:d});
const signed=v=>(v>0?'+':'')+num(v),date=v=>new Date(v).toLocaleString('it-IT',{timeZone:'UTC',hour12:false})+' UTC';
function node(tag,text,cls){const n=document.createElement(tag);if(text!=null)n.textContent=text;if(cls)n.className=cls;return n;}
function row(target,values){const tr=node('tr');values.forEach(v=>tr.append(node('td',v)));$(target).append(tr);return tr;}
function pnl(n,v){n.classList.add(v<0?'loss':'gain');}
// Presentation only: no saved reference or experimental protocol is changed.
const finite=v=>typeof v==='number'&&Number.isFinite(v);
function intradayView(d){
 if(!d||d.schema!==1||d.account!=='btc-intraday-m1-l5-paper-v1'||d.no_real_orders!==true||d.scope!=='SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY'||!finite(d.metrics?.equity)||!finite(d.state?.activation_at)||typeof d.stale!=='boolean'||typeof d.accounting_complete!=='boolean'||!finite(d.metrics.pnl)||!finite(d.state.last_tick)||!finite(d.state.fees)||!finite(d.state.funding)||!Number.isInteger(d.state.fills)||d.state.fills<0||!Array.isArray(d.equity)||!d.equity.every(p=>Array.isArray(p)&&p.length>=4&&finite(p[0])&&finite(p[1])))return null;
 return d;
}
function accountSeries(d){
 const series=keys.map(k=>({key:k,label:d.variants[k].label,points:d.variants[k].equity_curve.map(p=>[Date.parse(p[0]),p[1]])}));
 if(comparison&&intraday)series.push({key:'BTC',label:'BTC intraday',points:intraday.equity.map(p=>[p[0]/1e6,p[3]===1?p[1]:null])});
 return series.map(s=>({...s,points:s.points.filter(p=>Number.isFinite(p[0])&&(p[1]===null||finite(p[1]))).sort((a,b)=>a[0]-b[0])}));
}
function sharedWindow(){
 if(keys.length!==4||!intraday||intraday.stale||intraday.accounting_complete!==true||data.stale||data.fourth_stale||data.funding_debt||data.valuation_gap)return null;
 const series=accountSeries(data),buckets=series.map(s=>{const m=new Map();for(const p of s.points)if(p[0]>=intraday.state.activation_at/1e6&&finite(p[1])&&p[1]>0&&!m.has(Math.floor(p[0]/300000)))m.set(Math.floor(p[0]/300000),p);return m;});
 const common=[...buckets[0].keys()].filter(b=>buckets.every(m=>m.has(b))).sort((a,b)=>a-b);
 if(!common.length)return null;
 const first=common[0],last=common.at(-1),refs={};
 series.forEach((s,i)=>{refs[s.key]={start:buckets[i].get(first),end:buckets[i].get(last)};});
 return {first,last,refs,series};
}
function commonReturn(k,window){
 if(allAccounts){const r=window?.refs[k];return r?100*(r.end[1]/r.start[1]-1):null;}
 return k==='BTC'?null:data.variants[k].common_change_pct;
}
function intradayOverview(window){
 const card=node('article',null,'card');card.dataset.account='BTC';card.style.setProperty('--accent',colors.BTC);card.append(node('h2','BTC intraday'));
 if(!intraday){card.append(node('p','Dati non disponibili','amount'),node('p','Il conto non è verificabile al momento. Le altre strategie restano consultabili.','muted small'));}
 else{
  const s=intraday.state,complete=intraday.accounting_complete===true;
  const states={ACTIVE_WARMUP:'Raccolta iniziale',ACTIVE_OBSERVING:'In osservazione',ACTIVE:'Attivo',BLOCKED:'Sospeso',COMPLETED:'Periodo concluso'};
  card.append(node('div',num(intraday.metrics.equity)+' USDT','amount'),node('p',intraday.stale?'Aggiornamento in ritardo':states[intraday.status]||intraday.status,'badge'));
  if(!complete)card.append(node('p','Equity provvisoria: contabilità incompleta. Esclusa dalla finestra comune.','notice small'));
  if(complete){const change=node('p',signed(intraday.metrics.pnl)+' USDT dal proprio avvio');pnl(change,intraday.metrics.pnl);card.append(change);}
  card.append(node('p','Avvio: '+date(s.activation_at/1e6)+' · capitale iniziale 10.000 USDT, senza storico V13 ereditato.','muted small'));
  const pct=commonReturn('BTC',window);if(pct!=null){const common=node('p',signed(pct)+'% nella finestra comune a tutti');pnl(common,pct);card.append(common);}
  card.append(node('p','Dati iniziali: '+num(intraday.warmup_rows,0)+' / '+num(intraday.warmup_required,0)+' · '+num(s.fills,0)+' fill simulati','muted small'),node('p','Valorizzato '+date(s.last_tick/1e6),'muted small'));
 }
 const a=node('a','Apri il conto intraday →');a.href='/btc_intraday';card.append(a);$('cards').append(card);
 const pct=commonReturn('BTC',window),s=intraday?.state,complete=intraday?.accounting_complete===true;
 const r=row('comparison-rows',['BTC intraday',pct==null?'Non disponibile':signed(pct)+'%',s?date(s.activation_at/1e6):'—',complete?signed(intraday.metrics.pnl)+' USDT':'—','—',s?num(s.fees)+' USDT':'—',s?signed(s.funding)+' USDT':'—',s?.fills??'—']);
 r.dataset.account='BTC';if(pct!=null)pnl(r.children[1],pct);
 const legend=node('span','BTC intraday'+(!intraday?' · dati assenti':intraday.stale?' · dati in ritardo':''),'swatch');legend.style.setProperty('--accent',colors.BTC);$('legend').append(legend);
}
function render(d){if(!d.available){$('status').textContent=d.message||'Dati non disponibili.';return;}data=d;
keys=comparison?['ORIGINAL','FAST','HALF','M1'].filter(k=>d.variants[k]):[version.toUpperCase()];if(!comparison&&!d.variants[keys[0]]){$('status').textContent='Il conto M1 non è al momento verificabile. Le altre versioni restano disponibili.';return;}
for(const id of ['all','future','history'])$(id).classList.toggle('active',id===(allAccounts?'all':fullHistory?'history':'future'));
$('content').classList.remove('hidden');if(comparison){$('title').textContent='Tutte le strategie a confronto';$('subtitle').textContent='Originale, FAST, HALF, M1 SHORT e BTC intraday. Conti separati, capitale e date di avvio espliciti.';}$('cards').style.gridTemplateColumns=comparison?'repeat(auto-fit,minmax(210px,1fr))':'1fr';document.querySelector(`[data-nav="${version}"]`).classList.add('active');
const first=d.receipt.first_decision_slot,waiting=Date.now()<Date.parse(first),blocked=d.health.status==='BLOCKED',ended=d.health.status==='COMPLETED_AWAITING_REVIEW';
$('status').textContent=d.stale?'Aggiornamento in ritardo: i numeri mostrati sono l’ultima osservazione disponibile.':blocked?'Simulatore sospeso: '+d.health.reason:ended?'Periodo concluso. Risultati conservati, in attesa di revisione.':waiting?'Conti in osservazione. Prima decisione delle biforcazioni: '+date(first)+'.':'Simulazioni in osservazione. Ribilanciamento ordinario V13 alle 00:15 UTC.';
if(d.funding_debt||d.valuation_gap)$('status').textContent+=' Contabilità o copertura incompleta: nuovi ingressi sospesi.';
$('boundary').textContent='Copia FAST/HALF: '+date(d.receipt.economic_t0)+(d.m1?' · Copia M1: '+date(d.m1.receipt.economic_t0):'')+' · Aggiornato '+date(d.generated_at);if(d.m1&&(d.fourth_stale||d.m1.health.status==='BLOCKED'||d.m1.health.reason))$('status').textContent+=' M1: '+(d.fourth_stale?'aggiornamento in ritardo':d.m1.health.reason||'sospeso')+'.';if(!comparison&&keys[0]==='M1')$('status').textContent='M1 · '+phase(d.m1.control.phase)+(d.m1.health.reason?' · Nuovo rischio sospeso: '+d.m1.health.reason:'')+(d.fourth_stale?' · Aggiornamento in ritardo':'');
const window=comparison?sharedWindow():null;
$('cards').replaceChildren();keys.forEach(k=>{const v=d.variants[k],card=node('article',null,'card');card.style.setProperty('--accent',colors[k]);card.append(node('h2',v.label));card.append(node('div',num(v.metrics.equity)+' USDT','amount'));const change=node('p',signed(v.change)+' USDT · '+signed(v.change_pct)+'% dalla copia');pnl(change,v.change);card.append(change,node('p','Copia: '+date(v.fork_at),'muted small'));const pct=commonReturn(k,window);if(pct!=null){const common=node('p',signed(pct)+(allAccounts?'% nella finestra comune a tutti':'% dalla finestra comune V13'));pnl(common,pct);card.append(common);}card.append(node('p',v.post_fork_order_count+' nuovi fill · '+v.historical_order_count+' ereditati','muted small'));card.append(node('p','Valorizzato '+date(v.observed_at),'muted small'));const a=node('a','Apri questa versione →');a.href='/v13_variants/'+k.toLowerCase();if(comparison){card.append(a);if(k!=='M1'){const chartsLink=node('a','Grafici per simbolo →');chartsLink.href=k==='ORIGINAL'?'/v13_paper/charts':'/v13_variants/'+k.toLowerCase()+'/charts';const chartsLine=node('p');chartsLine.append(chartsLink);card.append(chartsLine);}}$('cards').append(card);});
$('legend').replaceChildren();keys.forEach(k=>{const n=node('span',d.variants[k].label,'swatch');n.style.setProperty('--accent',colors[k]);$('legend').append(n);});
$('comparison-panel').classList.toggle('hidden',!comparison);$('detail-panel').classList.toggle('hidden',comparison);$('comparison-rows').replaceChildren();
for(const k of ['ORIGINAL','FAST','HALF','M1'].filter(k=>d.variants[k])){const v=d.variants[k],pct=commonReturn(k,window),r=row('comparison-rows',[v.label,pct==null?'In attesa':signed(pct)+'%',date(v.fork_at),signed(v.change)+' USDT',num(v.drawdown_pct)+'%',num(v.fees_since_fork)+' USDT',signed(v.funding_since_fork)+' USDT',v.post_fork_order_count]);if(pct!=null)pnl(r.children[1],pct);}
if(comparison){intradayOverview(window);$('all').classList.remove('hidden');$('comparison-window').textContent=allAccounts?'Rendimento della finestra comune a tutti e cinque i conti, calcolato dalle osservazioni del grafico. Se manca una copertura condivisa verificabile, il confronto resta in attesa.':'Rendimento della finestra V13: BTC intraday non ha un riferimento in questa finestra. Per confrontare tutti scegliere Tutti · finestra comune.';}
if(!comparison){const v=d.variants[keys[0]];$('title').textContent=v.label;$('subtitle').textContent='Equity, posizioni e storico conservati alla data della propria copia.';$('cards').style.gridTemplateColumns='1fr';$('facts').replaceChildren();for(const [label,value] of [['P/L totale del conto',signed(v.metrics.pnl)+' USDT'],['P/L aperto',signed(v.metrics.unrealized_pnl)+' USDT'],['Fee dalla copia',num(v.fees_since_fork)+' USDT'],['Funding dalla copia',signed(v.funding_since_fork)+' USDT']]){const n=node('div',label,'muted small');n.append(node('strong',value));$('facts').append(n);}
$('description').textContent=keys[0]==='M1'?'V13 ordinaria con filtro M1 ogni 5 minuti: BTC a −1% o meno nell’ora e almeno 12 simboli su 18 in calo. Al segnale inverte i long in SHORT, per 6 ore; poi chiude e tenta il rientro V13. Un veto al nuovo rischio lascia consentita la chiusura protettiva dei long.':keys[0]==='ORIGINAL'?'La V13 originale prosegue con le proprie regole. Questa pagina la osserva senza modificarla.':keys[0]==='FAST'?'Filtro rapido giornaliero sui singoli simboli; riduzione dei long e blocco dei riacquisti in regime ridotto.':'Target preliminari pari alla metà di quelli V13; possibile ulteriore riduzione per pareggiare il rischio stimato con FAST.';
$('risk').textContent=keys[0]==='M1'?'Policy dedicata approvata: perdita giornaliera 2%, drawdown 10%, massimo 31,5% per asset e 90% totale. Un episodio M1 e massimo tre aumenti di rischio al giorno; 6 ore di tenuta e 6 di cooldown. Attesa 22 ore tra i ribilanciamenti ordinari. Stato: '+phase(d.m1.control.phase)+'.':'Limiti ereditati: perdita giornaliera 2%, drawdown 10%, un aumento di rischio al giorno, cooldown 22 ore. Ultima valorizzazione: '+date(v.observed_at)+'.';
$('positions').replaceChildren();v.positions.forEach(p=>{const r=row('positions',[p.symbol,num(p.quantity,6),num(p.entry,5),num(p.mark,5),signed(p.unrealized),signed(p.since_fork),p.filter==='REDUCED'?'Ridotto':p.filter==='FULL'?'Pieno':'—']);pnl(r.children[5],p.since_fork);});
$('fills').replaceChildren();$('fills-empty').textContent=v.fills.length?'':waiting?'Nessuna operazione dopo la copia: il primo slot è ancora futuro.':'Nessun fill dopo la copia; consultare gli esiti degli slot.';
v.fills.slice().reverse().forEach(f=>row('fills',[date(f.at),f.symbol,(f.quantity>0?'BUY':'SELL')+(f.kind==='M1_ENTRY'?(f.after<0?' · long → SHORT':' · chiusura long'):f.kind==='EXIT'?' · chiusura SHORT / residuo':f.protective?' · riduzione':''),num(f.quantity,6),num(f.price,5),num(f.fee,6)]));
$('inherited-title').textContent=(keys[0]==='M1'?d.m1.inherited_fills:d.inherited_fills).length+' operazioni ereditate · storico completo';$('inherited').replaceChildren();(keys[0]==='M1'?d.m1.inherited_fills:d.inherited_fills).slice().reverse().forEach(f=>row('inherited',[date(f.bar),f.symbol,f.action,num(f.quantity,6),num(f.price,5),num(f.fee,6)]));}
$('m1-episodes-panel').classList.toggle('hidden',!d.m1||(!comparison&&keys[0]!=='M1'));$('m1-episodes').replaceChildren();if(d.m1){$('m1-next').textContent='Stato: '+phase(d.m1.control.phase)+' · Primo slot futuro: '+date(d.m1.activation.first_signal_slot)+(d.m1.episodes.length?'':' · Nessun episodio ancora registrato.');d.m1.episodes.slice(0,30).forEach(e=>row('m1-episodes',[date(e.signal_at),date(e.entry_due),date(e.exit_due),({PENDING_ENTRY:'Ingresso programmato',ACTIVE:'In corso',ENTRY_MISSED:'Ingresso mancato',CLOSED_AWAITING_REENTRY:'Chiuso, rientro in attesa',COMPLETED:'Concluso'})[e.status]||e.status]));}
const slots=(!comparison&&keys[0]==='M1')?d.m1.slots:d.slots;$('slots').replaceChildren();$('slots-empty').textContent=slots.length?'':'Nessuno slot ancora eseguito. Le posizioni ereditate restano valorizzate.';
slots.slice(0,14).forEach(s=>row('slots',[date(s.slot),({EXECUTED:'Fill simulati',OBSERVED_NO_FILL:'Osservato, nessun fill',DENIED:'Rifiutato',MISSED:'Slot mancato',NO_SIGNAL:'Nessun segnale',INSUFFICIENT_INPUT:'Dati insufficienti',COOLDOWN:'Episodio / cooldown',DAILY_EPISODE_LIMIT:'Limite giornaliero M1',SCHEDULED:'Ingresso programmato',NO_LONG:'Nessun long da invertire',FILLED:'Fill simulati',NO_FILL:'Nessun fill',OVERLAY_HOLD:'Ribilanciamento sospeso durante M1'})[s.status]||s.status,s.detail.risk_gap==null?'—':num(s.detail.risk_gap*100)+'%',s.detail.reason|| (s.kind==='M1'?'Filtro M1 · '+(s.detail.feature?'BTC nell’ora '+signed(s.detail.feature.btc_60m*100)+'%':'input non disponibile'):s.detail.risk_matched?'Entro la tolleranza del 2%':'Scostamento conservato nel confronto')]));draw();}
function phase(p){return ({NORMAL:'V13 ordinaria, in attesa del segnale',PENDING_ENTRY:'SHORT programmato sul prossimo book',ACTIVE:'Episodio M1 in corso',EXIT_PENDING:'Chiusura protettiva in attesa di book',REENTRY_PENDING:'Rientro V13 in attesa dei gate'})[p]||p;}
function draw(){if(!data)return;const canvas=$('equity'),rect=canvas.getBoundingClientRect(),scale=devicePixelRatio||1,w=rect.width,h=rect.height;canvas.width=w*scale;canvas.height=h*scale;const c=canvas.getContext('2d');c.scale(scale,scale);c.clearRect(0,0,w,h);
const window=comparison&&allAccounts?sharedWindow():null,normalized=comparison&&!fullHistory&&data.fourth_available,ref=data.comparison_reference;
canvas.onmousemove=null;$('hover').textContent='';
if(comparison&&allAccounts&&!window){$('chart-title').textContent='In attesa della finestra comune a tutte le strategie';$('chart-note').textContent='Servono osservazioni complete di tutti i conti nello stesso intervallo di 5 minuti. Dati assenti, scaduti o contabilità incompleta non sono sostituiti con zero. Il confronto V13 e lo storico restano disponibili dai pulsanti.';chartSeries=[];return;}
if(!allAccounts&&normalized&&!ref){$('chart-title').textContent='In attesa della prima finestra comune';$('chart-note').textContent='Il riferimento sarà fissato alla prima osservazione disponibile per tutti e quattro i conti. Nessun allineamento scelto in base al risultato.';chartSeries=[];return;}
if(allAccounts){chartSeries=window.series.map(s=>{const r=window.refs[s.key];return {key:s.key,points:s.points.filter(p=>p[0]>=r.start[0]&&p[0]<=r.end[0]).map(p=>[p[0],p[1]===null?null:10000*p[1]/r.start[1]])};});}
else{chartSeries=keys.map(k=>{const v=data.variants[k],r=ref&&ref.points[k];let points=[...(fullHistory?(k==='M1'?v.inherited_curve:data.common_history):[]),...v.equity_curve].map(p=>[Date.parse(p[0]),p[1]]);if(normalized)points=points.filter(p=>p[0]>=Date.parse(r.at)).map(p=>[p[0],10000*p[1]/r.equity]);return {key:k,points};});if(fullHistory&&comparison&&intraday)chartSeries.push({key:'BTC',points:accountSeries(data).find(s=>s.key==='BTC').points});}
chartSeries=chartSeries.filter(s=>s.points.some(p=>finite(p[1])));const all=chartSeries.flatMap(s=>s.points).filter(p=>finite(p[1]));if(!all.length)return;
let x0=Math.min(...all.map(p=>p[0])),x1=Math.max(...all.map(p=>p[0])),y0=Math.min(...all.map(p=>p[1])),y1=Math.max(...all.map(p=>p[1]));const pad=Math.max(.5,(y1-y0)*.12);y0-=pad;y1+=pad;if(x1===x0)x1+=300000;
const left=74,right=12,top=12,bottom=34,X=t=>left+(t-x0)/(x1-x0)*(w-left-right),Y=v=>top+(y1-v)/(y1-y0)*(h-top-bottom);
c.font='11px system-ui';for(let i=0;i<5;i++){const v=y0+(y1-y0)*i/4,y=Y(v);c.strokeStyle='#304157';c.beginPath();c.moveTo(left,y);c.lineTo(w-right,y);c.stroke();c.fillStyle='#adbed5';c.fillText(num(v),2,y+4);}
c.fillText(new Date(x0).toLocaleDateString('it-IT',{timeZone:'UTC'}),left,h-8);c.textAlign='right';c.fillText(new Date(x1).toLocaleString('it-IT',{timeZone:'UTC',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit'})+' UTC',w-right,h-8);c.textAlign='left';
for(const s of chartSeries){c.strokeStyle=colors[s.key];c.lineWidth=2;c.setLineDash(s.key==='HALF'?[5,4]:[]);c.beginPath();let prev;for(const p of s.points){if(!finite(p[1])){prev=null;continue;}if(!prev||p[0]-prev[0]>1800000)c.moveTo(X(p[0]),Y(p[1]));else c.lineTo(X(p[0]),Y(p[1]));prev=p;}c.stroke();const p=s.points.filter(p=>finite(p[1])).at(-1);c.fillStyle=colors[s.key];c.beginPath();c.arc(X(p[0]),Y(p[1]),3,0,2*Math.PI);c.fill();}c.setLineDash([]);
$('chart-title').textContent=allAccounts?'Andamento nella finestra comune disponibile':fullHistory?'Storico conservato e percorsi delle versioni':normalized?'Andamento dalla finestra comune':'Equity dopo la propria copia';$('chart-note').textContent=allAccounts?'Base 10.000 punti dalla prima finestra condivisa disponibile '+date(window.first*300000)+' fino a '+date(window.last*300000)+'. Riferimenti nello stesso intervallo di 5 minuti, senza interpolazione. La finestra può avanzare con la copertura delle viste; non è un benchmark scientifico fissato. Equity effettive nelle schede, rischio e frequenza diversi.':normalized?'Base 10.000 punti: variazioni percentuali dalla prima finestra comune '+date(ref.bucket_utc)+'. Equity reali dei simulatori nelle schede. Orari del riferimento distanti al massimo '+num(ref.maximum_skew_seconds,0)+' secondi. Rischio diverso tra le strategie.':'Equity virtuale in USDT. M1 eredita lo storico alla propria data di copia; FAST e HALF sono partite prima. HALF tratteggiata; buchi oltre 30 minuti visibili. Funding stimato. BTC intraday parte da 10.000 USDT e non eredita lo storico V13: equity assolute non confrontabili come rendimento.';
canvas.onmousemove=e=>{const t=x0+Math.max(0,Math.min(1,(e.offsetX-left)/(w-left-right)))*(x1-x0);$('hover').textContent=chartSeries.map(s=>{const p=s.points.filter(p=>finite(p[1])).reduce((a,b)=>Math.abs(a[0]-t)<Math.abs(b[0]-t)?a:b);return (s.key==='BTC'?'BTC intraday':data.variants[s.key].label)+': '+num(p[1])+' · '+date(p[0]);}).join(' | ');};}
function mode(all,history){allAccounts=all;fullHistory=history;for(const id of ['all','future','history'])$(id).classList.toggle('active',id===(all?'all':history?'history':'future'));if(data)render(data);}
$('all').onclick=()=>mode(true,false);$('future').onclick=()=>mode(false,false);$('history').onclick=()=>mode(false,true);window.addEventListener('resize',draw);
async function get(url){const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),15000);try{const r=await fetch(url,{cache:'no-store',signal:controller.signal});if(!r.ok)throw Error();return await r.json();}finally{clearTimeout(timer);}}
async function refresh(){
 const results=await Promise.allSettled([get('/v13_variants/data'),...(comparison?[get('/btc_intraday/data')]:[])]);
 intraday=comparison&&results[1].status==='fulfilled'?intradayView(results[1].value):null;
 if(results[0].status==='fulfilled')render(results[0].value);else{$('status').textContent='Impossibile aggiornare il confronto. I dati eventualmente mostrati sono precedenti.';}
}
refresh();setInterval(refresh,60000);
})();
