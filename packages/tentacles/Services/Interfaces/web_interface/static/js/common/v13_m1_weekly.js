/* Weekly M1 operator workflow. Decisions queue to a separate approval writer. */
'use strict';
(() => {
  const el=id=>document.getElementById(id);
  let current=null, token=null, action=null, pinned=null, pinnedComponents;
  const v3=p=>p?.version==='m1-gradual-long-short-v3';
  const v2=p=>p?.version==='m1-long-maintenance-v2'||v3(p);
  const n=(v,d=2)=>new Intl.NumberFormat('it-IT',{maximumFractionDigits:d}).format(v);
  const date=v=>new Date(v).toLocaleString('it-IT',{timeZone:'Europe/Rome',timeZoneName:'short'});
  const labels={ACTIVE_SUCCESSOR:'Nuova strategia attiva · versione precedente ritirata',SUPERSEDED:'Sostituita · conservata nello storico',PROPOSED:'Da approvare',REJECTED:'Rifiutata',EXPIRED:'Scaduta',ARCHIVED_V1_NOT_APPROVABLE:'Archiviata · sostituita dalla v2',
    APPROVED_WAITING_NORMAL_PHASE:'Approvata · attesa fine episodio M1',APPROVED_WAITING_INPUTS:'Approvata · attesa dati',
    ACTIVE_REBALANCE_PENDING:'Approvata · ribilanciamento in preparazione',REDUCTIONS_APPLIED_WAITING_DAILY:'Riduzioni registrate · verifiche successive in attesa',
    APPROVED_WAITING_RISK:'Approvata · aumenti sospesi dai controlli di rischio',PARTIAL_REBALANCE:'Ribilanciamento parziale · leggere i motivi',
    APPROVED_WAITING_NEXT_SLOT:'Approvata · attesa prossimo slot utile',EXECUTED:'Ribilanciamento eseguito'};
  function cell(row,value){const e=document.createElement('td');e.textContent=value;row.append(e);return e;}
  const autoReasons={ALL_REQUIRED_CHECKS_PASSED:'Controlli superati',WAITING_CURRENT_DAILY:'Storico giornaliero incompleto',NO_POSITIVE_SIGNAL:'Segnale LONG assente',WAITING_SECOND_POSITIVE_DAY:'Attesa seconda conferma giornaliera',SIGNAL_TOO_WEAK:'Forza del segnale insufficiente',LONG_BUDGET_OR_WEEKLY_LIMIT:'Budget, rischio o slot settimanale non disponibili',WAITING_VALID_BOOK_COSTS_FUNDING:'Book, costi o funding non qualificati',SCORE_BELOW_THRESHOLD:'Punteggio sotto soglia',SIGNAL_RECOVERED:'Segnale recuperato: riduzione sospesa',COST_LIMIT:'Costi stimati oltre lo 0,20% per andata e ritorno',SPREAD_LIMIT:'Spread oltre lo 0,10%',QUANTITY_BELOW_MINIMUM:'Quantità sotto il minimo del contratto paper'};
  function automatic(){
    const a=current.automatic_review;let box=el('automatic-review');
    if(!a){box?.remove();return;}
    if(!box){box=document.createElement('section');box.id='automatic-review';el('weekly-policy').before(box);}
    box.replaceChildren();
    const title=document.createElement('h3');title.textContent='Approvazione automatica ponderata · attiva';box.append(title);
    const line=document.createElement('p');line.textContent='Soglia '+a.rules.threshold+'/100. Dati 25 · segnale 30 · liquidità 20 · costi 15 · budget 10. Un veto blocca la proposta anche con punteggio alto. Il punteggio misura i controlli, non la probabilità di guadagno.';box.append(line);
    const scope=document.createElement('p');scope.textContent='Budget SHORT conservato: '+n(a.short_budget*100)+'%. Nuovi LONG: '+(a.allow_admissions?'massimo due simboli nuovi alla settimana, fino all’1% ciascuno, entro il budget LONG del '+n(a.long_budget*100)+'%, con due giorni positivi.':'disabilitati.')+' Nessun riacquisto dei simboli esclusi; ingressi allo slot giornaliero, con book successivo e controlli di rischio.';box.append(scope);
    const latest=a.history.find(x=>x.kind==='DAILY_RENEWAL_AND_WEEKLY_SELECTION');
    const status=document.createElement('p');status.textContent=a.input_status?'Dati non qualificati: nessuna nuova approvazione.':latest?'Ultima revisione automatica: '+date(latest.at)+' · nuovi simboli approvati: '+(latest.details.admitted.join(', ')||'nessuno')+'.':'Prima revisione in attesa dei dati.';box.append(status);
    Object.entries(current.policy?.automatic_admissions||{}).forEach(([symbol,v])=>{const line=document.createElement('p');line.textContent=symbol+' · approvato '+date(v.approved_at)+' · '+({PENDING:'ingresso in attesa dello slot e dei controlli',CONSUMED:'permesso utilizzato · nessun riacquisto',CANCELLED:'ingresso annullato'}[v.status]||v.status)+' · quantità attuale '+n(current.positions[symbol]?.quantity||0,6);box.append(line);});
    if(latest){
      const table=document.createElement('table'),head=document.createElement('tr');['Candidato nuovo','Esito','Punti','Motivo'].forEach(t=>cell(head,t));table.append(head);
      latest.details.candidates.forEach(r=>{const row=document.createElement('tr');cell(row,r.symbol);cell(row,{APPROVED:'Approvato',DEFERRED:'Rinviato',REJECTED:'Respinto'}[r.status]||r.status);const score=cell(row,n(r.score,1)+'/100');score.title=Object.entries(r.components).map(([k,v])=>k+': '+n(v,1)).join(' · ');const reasons=r.reasons.map(x=>autoReasons[x]||x);const reason=cell(row,reasons.slice(0,2).join(' · '));reason.title=reasons.join(' · ');reason.style.whiteSpace='normal';reason.style.minWidth='240px';table.append(row);});const wrap=document.createElement('div');wrap.className='table-wrap';wrap.append(table);box.append(wrap);
    }
    const daily=a.daily_review;if(daily){const line=document.createElement('p');line.textContent='Review giornaliera dal '+date(daily.since)+': '+daily.fill_count+' fill, commissioni '+n(daily.fees,3)+' USDT, realizzato meno le commissioni di questi fill '+n(daily.closed_pnl_less_current_fill_fees,3)+' USDT. Questa cifra esclude P/L aperto, funding e costi precedenti; non è il rendimento del conto.';box.append(line);}
    const details=document.createElement('details'),summary=document.createElement('summary');summary.textContent='Registro per la review giornaliera · '+a.history.length+' decisioni recenti';details.append(summary);
    a.history.slice(0,20).forEach(r=>{const p=document.createElement('p');p.textContent=date(r.at)+' · '+r.kind+' · '+r.status+' · '+r.decision_id.slice(0,12);details.append(p);});box.append(details);
    el('weekly-approve').hidden=true;el('weekly-reject').hidden=true;
    el('weekly-auth-note').textContent='Delega automatica attiva per questo conto paper. Le approvazioni e gli esiti di esecuzione restano distinti e registrati; non occorre una password per ogni revisione.';
    el('integration-badge').textContent='Approvazione automatica attiva';
    el('weekly-scope-note').textContent='Riduzioni graduali sui LONG esistenti, budget SHORT invariato e nessun riacquisto automatico. I nuovi ingressi qualificati usano solo spazio disponibile nel budget LONG e un permesso di acquisto utilizzabile una volta.';
  }
  function rows(){
    if(!current?.proposal)return;
    const p=current.proposal,filter=el('weekly-filter').value;
    el('weekly-rows').replaceChildren();
    const symbols=Object.keys(p.rows).sort((a,b)=>(p.rows[b].score||0)-(p.rows[a].score||0)||a.localeCompare(b));
    symbols.forEach(s=>{
      const added=p.selected.includes(s)&&!p.previous.includes(s),removed=p.previous.includes(s)&&!p.selected.includes(s);
      const change=p.indicative_changes[s],pos=v3(p)&&current.active?{quantity:current.positions[s]?.quantity||0,mark:current.positions[s]?.current_price||0}:p.indicative_positions[s];
      if(filter==='changes'&&(v2(p)?!change:!added&&!removed&&!change))return;
      const row=document.createElement('tr');cell(row,s);
      cell(row,v2(p)?change?'Riduzione LONG':pos?.quantity?'Quantità confermata':'Nessun ingresso incluso':p.ineligible[s]?'Dati non sufficienti':added?'Ingresso proposto':removed?'Escluso dai LONG':p.selected.includes(s)?'Selezionato':'Non selezionato');
      cell(row,v2(p)||p.rows[s].score===null?'—':n(p.rows[s].score,3));
      cell(row,n(pos?Math.max(0,pos.quantity)*pos.mark/(current.metrics?.equity||p.reference_equity)*100:0)+'%');
      cell(row,n((v3(p)&&current.active?(current.policy.quantity_ceilings[s]||0)*(pos?.mark||0)/(current.metrics?.equity||p.reference_equity):p.long_caps[s])*100)+'%');cell(row,n(p.short_caps[s]*100)+'%');
      cell(row,v2(p)?n((v3(p)&&current.active?current.policy.quantity_ceilings[s]:p.quantity_ceilings[s])||0,6):change?n(change.indicative_target,6):pos?n(pos.quantity,6):'0');
      cell(row,change?(change.cost_available?n(change.immediate_equity_cost,3)+' USDT':'Non quotabile'):'—');
      el('weekly-rows').append(row);
    });
  }
  function render(){
    const p=current.proposal;
    el('weekly-body').classList.remove('hidden');
    el('weekly-status').textContent=current.stale?'Stato M1 non aggiornato: approvazioni sospese.':current.successor?'Nuova strategia attiva · versione precedente ritirata':p?(labels[current.proposal_status]||current.proposal_status):'In attesa degli input necessari per generare la revisione.';
    el('weekly-proposal').classList.toggle('hidden',!p);
    el('weekly-policy').textContent=current.policy?'Epoca attiva '+current.policy.revision+' · '+date(current.policy.activated_at)+' · aumenta il rischio solo con revisione valida fino a '+date(current.policy.valid_until):'Nessuna selezione settimanale ancora applicata al conto.';
    el('integration-badge').textContent=current.active?'Collegamento attivo · approvazione richiesta':'Collegamento pronto · attesa prima approvazione';
    if(p){
      el('weekly-title').textContent=v3(p)?'M1 · gestione graduale + SHORT':v2(p)?'Manutenzione LONG · versione 2':'Selezione settimanale · conto M1';
      el('weekly-approve').textContent=v2(p)?'Approva riduzioni LONG':'Approva selezione M1';
      el('weekly-id').textContent='Proposta '+p.proposal_id.slice(0,12)+' · creata '+date(p.created_at)+' · approvabile fino a '+date(p.expires_at)+'.';
      el('weekly-count').textContent=v2(p)?p.events.length+' riduzioni · budget SHORT invariato':p.selected.length+' selezionati su '+Object.keys(p.rows).length+' candidati';
      el('weekly-changes').textContent=p.events.map(e=>e.reason==='long_reduction'?e.symbol+': riduzione LONG, SHORT conservato':e.replaces?e.symbol+' sostituisce '+e.replaces:e.reason==='mandatory_exit'?e.symbol+' perde il segnale':e.symbol+' entra in un posto disponibile').join(' · ')||'Nessuna variazione eseguibile nella fotografia.';
      const summary=el('weekly-risk-summary');summary.classList.toggle('hidden',!v2(p));
      if(v2(p))summary.textContent='LONG: '+n(p.summary.long_before*100)+'% → '+n(p.summary.long_after*100)+'%. Budget SHORT per gli episodi M1: '+n(p.summary.short_before*100)+'% → '+n(p.summary.short_after*100)+'%, invariato; non si somma al LONG. Turnover indicativo '+n(p.summary.turnover)+' USDT; costo '+n(p.summary.estimated_cost,3)+' USDT. Nuove coin: nessuna. Cadenza dei segnali: Originale. Candidato '+p.candidate_id.slice(0,12)+', fotografia '+date(p.candidate_as_of)+'.';
      el('weekly-scope-note').textContent=v2(p)?'Approvi soltanto i tetti di quantità LONG mostrati. Le quantità rimaste e la liquidità non vengono riallocate automaticamente. QNT, XMR e qualsiasi aumento del budget SHORT richiedono un’altra proposta e un consenso separato. Quantità e costi sono indicativi; i fill usano dati successivi al consenso.':'Al massimo due nuovi ingressi o sostituzioni per settimana; i pesi sono limiti approvabili. Le esclusioni LONG non rimuovono automaticamente il budget SHORT.';
      if(v3(p)){
        const fractions=p.stage_rule.remaining_fractions;
        el('weekly-count').textContent='Sei LONG · '+fractions.length+' tappe · SHORT conservato';
        el('weekly-policy').textContent=current.successor?'Versione attiva dal '+date(current.successor.activated_at)+' · conto e storico conservati · versione precedente ritirata. Revisione del nuovo rischio entro '+date(current.policy.valid_until):el('weekly-policy').textContent;
        el('weekly-scope-note').textContent='Quantità residue previste: '+fractions.map(v=>n(v*100)+'%').join(' → ')+'. Le tappe successive attendono almeno 24 ore dalla riduzione eseguita e un nuovo giorno di dati con segnale non positivo. In caso di recupero la riduzione si ferma, senza riacquisti. Anche il rientro dopo uno SHORT non ricostituisce LONG. Budget SHORT per simbolo invariato; nessuna nuova coin.';
        el('weekly-changes').textContent=p.affected.map(s=>s+': '+n(p.initial_quantities[s],6)+' → '+p.indicative_changes[s].stages.map(q=>n(q,6)).join(' → ')).join(' · ');
        let detail=el('successor-progress');
        if(!detail){detail=document.createElement('div');detail.id='successor-progress';el('weekly-scope-note').after(detail);}
        detail.replaceChildren();
        const title=document.createElement('h3');title.textContent='Avanzamento delle riduzioni';detail.append(title);
        const statuses={REDUCTION_PENDING:'Riduzione in attesa di book',WAITING_NEXT_REVIEW:'Attesa prossima verifica',RECOVERED_NO_REBUY:'Segnale recuperato · nessun riacquisto',LONG_CLOSED:'LONG chiuso · SHORT disponibile',WAITING_DATA:'Dati insufficienti · tetto conservato'};
        p.affected.forEach(s=>{const line=document.createElement('p'),g=current.reduction_progress?.[s];line.textContent=s+' · LONG attuale '+n(Math.max(0,current.positions?.[s]?.quantity||0),6)+' · tetto '+n(current.policy?.quantity_ceilings[s]??p.quantity_ceilings[s],6)+' · '+(g?(statuses[g.status]||g.status)+' · tappa '+(g.stage+1):'Prima riduzione in preparazione');detail.append(line);});
        if(current.successor_input_status){const line=document.createElement('p');line.textContent='Attesa di dati giornalieri freschi: nessuna riduzione aggiuntiva basata su dati mancanti.';detail.append(line);}
      }
      rows();
    }
    const expired=p&&new Date(p.expires_at)<new Date();
    const can=Boolean(p&&current.approval_ready&&!current.stale&&!expired&&current.proposal_status==='PROPOSED');
    el('weekly-approve').disabled=!can;el('weekly-reject').disabled=!can;
    el('weekly-auth-note').textContent=!current.approval_ready?'Approvazioni non disponibili finché il canale dell’operatore non è configurato.':expired?'La proposta è scaduta; non può essere applicata.':'La password protegge solo le decisioni; il web non accede al ledger di esecuzione.';
    const last=current.last_execution;
    el('weekly-execution').textContent=last?(labels[last.status]||last.status)+' · '+date(last.at)+(last.action.entry_block?' · motivo: '+last.action.entry_block:'')+(last.action.notes?.length?' · '+last.action.notes.map(x=>x.symbol+': '+x.reason).join('; '):''):'Nessun ribilanciamento da approvazione ancora registrato.';
    el('weekly-history').replaceChildren();
    current.reviews.forEach(r=>{const row=document.createElement('tr');cell(row,date(r.week));cell(row,r.id.slice(0,12));cell(row,labels[r.status]||r.status);cell(row,r.decision_id?r.decision_id.slice(0,12):'—');el('weekly-history').append(row);});
    automatic();
  }
  async function load(){
    try{
      const response=await fetch('/v13_variants/m1/review/weekly',{cache:'no-store',credentials:'same-origin'});
      if(!response.ok)throw new Error();const value=await response.json();
      if(!value.available)throw new Error();current=value;token=value.csrf_token;render();
    }catch(e){current=null;el('weekly-body').classList.add('hidden');el('weekly-status').textContent='Selezione settimanale non disponibile o non verificabile. Nessuna decisione viene inviata.';}
  }
  function open(which){
    if(!current?.proposal)return;action=which;pinned=current.proposal.proposal_id;
    pinnedComponents=v2(current.proposal)?current.proposal.approval_components:undefined;
    el('weekly-dialog-title').textContent=which==='APPROVE'?(v2(current.proposal)?'Approva solo le riduzioni LONG v2':'Approva questa selezione M1'):'Rifiuta questa proposta';
    el('weekly-dialog-id').textContent='Proposta '+pinned.slice(0,12);el('weekly-password').value='';el('weekly-ack').checked=false;el('weekly-decision-message').textContent='';
    el('weekly-short-options').replaceChildren();
    el('weekly-dialog-scope').textContent=v2(current.proposal)?'Il consenso riguarda soltanto la manutenzione LONG. Budget SHORT invariato; nessuna nuova coin e nessun aumento di rischio SHORT incluso. Il runner attende la fine di un eventuale episodio M1 e usa un book successivo al consenso. La quantità ridotta non viene ricomprata automaticamente.':'Le riduzioni vengono pianificate sul primo book successivo utile; nuovi ingressi attendono lo slot ordinario e i controlli di rischio.';
    if(which==='APPROVE'&&!v2(current.proposal))Object.keys(current.proposal.short_caps).filter(s=>current.proposal.short_caps[s]>0).sort().forEach(s=>{
      const label=document.createElement('label'),box=document.createElement('input');box.type='checkbox';box.value=s;
      label.append(box,document.createTextNode(' Escludi lo SHORT per '+s));el('weekly-short-options').append(label,document.createElement('br'));
    });
    el('weekly-dialog').showModal();el('weekly-password').focus();
  }
  el('weekly-approve').addEventListener('click',()=>open('APPROVE'));el('weekly-reject').addEventListener('click',()=>open('REJECT'));
  el('weekly-cancel').addEventListener('click',()=>{el('weekly-password').value='';el('weekly-dialog').close();});
  el('weekly-dialog').addEventListener('close',()=>{el('weekly-password').value='';});
  el('weekly-filter').addEventListener('change',rows);
  el('weekly-submit').addEventListener('click',async()=>{
    if(!el('weekly-ack').checked){el('weekly-decision-message').textContent='Conferma di aver letto la proposta.';return;}
    const password=el('weekly-password').value;el('weekly-password').value='';el('weekly-submit').disabled=true;
    try{
      const response=await fetch('/v13_variants/m1/review/decision',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({proposal_id:pinned,confirmation:pinned,action,components:pinnedComponents,exclude_short:[...el('weekly-short-options').querySelectorAll('input:checked')].map(x=>x.value),password})});
      const value=await response.json();if(!response.ok||!value.ok)throw new Error();
      el('weekly-dialog').close();el('weekly-result').textContent=action==='APPROVE'?'Approvazione registrata. Attesa conferma del runner: nessun successo di esecuzione è presunto.':'Rifiuto registrato. Il portafoglio non viene modificato.';
      await load();
    }catch(e){el('weekly-decision-message').textContent='Decisione non registrata. Verifica password, scadenza e versione, oppure ricarica la pagina.';}
    finally{el('weekly-submit').disabled=false;}
  });
  load();setInterval(load,10000);
})();
