/* Weekly M1 operator workflow. Decisions queue to a separate approval writer. */
'use strict';
(() => {
  const el=id=>document.getElementById(id);
  let current=null, token=null, action=null, pinned=null;
  const n=(v,d=2)=>new Intl.NumberFormat('it-IT',{maximumFractionDigits:d}).format(v);
  const date=v=>new Date(v).toLocaleString('it-IT',{timeZone:'Europe/Rome',timeZoneName:'short'});
  const labels={PROPOSED:'Da approvare',REJECTED:'Rifiutata',EXPIRED:'Scaduta',
    APPROVED_WAITING_NORMAL_PHASE:'Approvata · attesa fine episodio M1',APPROVED_WAITING_INPUTS:'Approvata · attesa dati',
    ACTIVE_REBALANCE_PENDING:'Approvata · ribilanciamento in preparazione',REDUCTIONS_APPLIED_WAITING_DAILY:'Riduzioni applicate · nuovi ingressi al prossimo slot giornaliero',
    APPROVED_WAITING_RISK:'Approvata · aumenti sospesi dai controlli di rischio',PARTIAL_REBALANCE:'Ribilanciamento parziale · leggere i motivi',
    APPROVED_WAITING_NEXT_SLOT:'Approvata · attesa prossimo slot utile',EXECUTED:'Ribilanciamento eseguito'};
  function cell(row,value){const e=document.createElement('td');e.textContent=value;row.append(e);return e;}
  function rows(){
    if(!current?.proposal)return;
    const p=current.proposal,filter=el('weekly-filter').value;
    el('weekly-rows').replaceChildren();
    const symbols=Object.keys(p.rows).sort((a,b)=>(p.rows[b].score||0)-(p.rows[a].score||0)||a.localeCompare(b));
    symbols.forEach(s=>{
      const added=p.selected.includes(s)&&!p.previous.includes(s),removed=p.previous.includes(s)&&!p.selected.includes(s);
      const change=p.indicative_changes[s],pos=p.indicative_positions[s];
      if(filter==='changes'&&!added&&!removed&&!change)return;
      const row=document.createElement('tr');cell(row,s);
      cell(row,p.ineligible[s]?'Dati non sufficienti':added?'Ingresso proposto':removed?'Escluso dai LONG':p.selected.includes(s)?'Selezionato':'Non selezionato');
      cell(row,p.rows[s].score===null?'—':n(p.rows[s].score,3));
      cell(row,n(pos?Math.max(0,pos.quantity)*pos.mark/p.reference_equity*100:0)+'%');
      cell(row,n(p.long_caps[s]*100)+'%');cell(row,n(p.short_caps[s]*100)+'%');
      cell(row,change?n(change.indicative_target,6):pos?n(pos.quantity,6):'0');
      cell(row,change?(change.cost_available?n(change.immediate_equity_cost,3)+' USDT':'Non quotabile'):'—');
      el('weekly-rows').append(row);
    });
  }
  function render(){
    const p=current.proposal;
    el('weekly-body').classList.remove('hidden');
    el('weekly-status').textContent=current.stale?'Stato M1 non aggiornato: approvazioni sospese.':p?(labels[current.proposal_status]||current.proposal_status):'In attesa degli input necessari per generare la revisione.';
    el('weekly-proposal').classList.toggle('hidden',!p);
    el('weekly-policy').textContent=current.policy?'Epoca attiva '+current.policy.revision+' · '+date(current.policy.activated_at)+' · aumenta il rischio solo con revisione valida fino a '+date(current.policy.valid_until):'Nessuna selezione settimanale ancora applicata al conto.';
    el('integration-badge').textContent=current.active?'Collegamento attivo · approvazione richiesta':'Collegamento pronto · attesa prima approvazione';
    if(p){
      el('weekly-id').textContent='Proposta '+p.proposal_id.slice(0,12)+' · creata '+date(p.created_at)+' · approvabile fino a '+date(p.expires_at)+'.';
      el('weekly-count').textContent=p.selected.length+' selezionati su '+Object.keys(p.rows).length+' candidati';
      el('weekly-changes').textContent=p.events.map(e=>e.replaces?e.symbol+' sostituisce '+e.replaces:e.reason==='mandatory_exit'?e.symbol+' perde il segnale':e.symbol+' entra in un posto disponibile').join(' · ')||'Nessun cambio di appartenenza; rivedere i limiti proposti.';
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
    el('weekly-dialog-title').textContent=which==='APPROVE'?'Approva questa selezione M1':'Rifiuta questa proposta';
    el('weekly-dialog-id').textContent='Proposta '+pinned.slice(0,12);el('weekly-password').value='';el('weekly-ack').checked=false;el('weekly-decision-message').textContent='';
    el('weekly-short-options').replaceChildren();
    if(which==='APPROVE')Object.keys(current.proposal.short_caps).filter(s=>current.proposal.short_caps[s]>0).sort().forEach(s=>{
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
      const response=await fetch('/v13_variants/m1/review/decision',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRFToken':token},body:JSON.stringify({proposal_id:pinned,confirmation:pinned,action,exclude_short:[...el('weekly-short-options').querySelectorAll('input:checked')].map(x=>x.value),password})});
      const value=await response.json();if(!response.ok||!value.ok)throw new Error();
      el('weekly-dialog').close();el('weekly-result').textContent=action==='APPROVE'?'Approvazione registrata. Attesa conferma del runner: nessun successo di esecuzione è presunto.':'Rifiuto registrato. Il portafoglio non viene modificato.';
      await load();
    }catch(e){el('weekly-decision-message').textContent='Decisione non registrata. Verifica password, scadenza e versione, oppure ricarica la pagina.';}
    finally{el('weekly-submit').disabled=false;}
  });
  load();setInterval(load,10000);
})();
