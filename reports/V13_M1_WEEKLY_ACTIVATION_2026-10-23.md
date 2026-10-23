# M1 — gestione settimanale attivata sul conto esistente

**23 ottobre 2026, circa 16:26 italiane.** Passaggio operativo esplicitamente autorizzato dall'utente: stesso conto M1, due servizi dedicati e riavvio della sola dashboard. Autorizzata separatamente la generazione di una password casuale locale per le sole approvazioni. SINGLE_AGENT; verifiche dell'autore, non QA indipendente. Scheda `work-card-8f398480-1842-4f8e-88d1-947756d0916c`.

## Disponibile in UI

`/v13_variants/m1/review` mostra la proposta settimanale sui 29 candidati, ragioni di ingresso/esclusione, tetti LONG, budget SHORT separati, quantità e costi indicativi, scadenza, storico e risultato effettivo. I pulsanti Approva/Rifiuta sono disponibili e protetti dalla password dedicata, conferma esplicita, origine coincidente e token CSRF. La consultazione resta libera. La password non è riportata in Git, report, chat, log o evidenze; nel servizio è presente soltanto il verificatore scrypt.

La prima proposta reale è **Da approvare**. Non è stata approvata o rifiutata dall'agente. Al primo avvio propone NEAR, QNT e XMR per il portafoglio ordinario; gli altri budget SHORT ancora presenti sono espliciti e modificabili nella conferma. Una proposta usa soltanto le informazioni disponibili al suo congelamento: prezzi successivi non la rigenerano nella stessa settimana. La validità scientifica resta UNASSESSED, nessuna conclusione di redditività.

Dopo l'approvazione dell'operatore, il runner pianifica le riduzioni sul primo book successivo utile, attende il normale slot giornaliero per nuovi ingressi ordinari e impedisce riacquisti dei LONG esclusi. Gli SHORT continuano a dipendere dal filtro M1 e dal budget separato approvato. Una proposta registrata non garantisce fill: tutti i controlli esistenti restano attivi. Il pulsante non scrive ordini direttamente.

## Passaggio e dati conservati

- Nuovo runner sul medesimo `account.sqlite`, account `v13-m1-short-paper-v1-5e761f0cedac`, runtime root-owned v3 identificato dal manifest preparato.
- Vecchio runner v2 conservato come container fermo, con restart disabilitato; nessun processo concorrente sul ledger.
- Backup fresco con M1 fermo, integrità SQLite `ok`. Dopo l'avvio, seconda copia coerente in sola lettura, integrità `ok`.
- **286 righe orders e 87 fill M1 identici prima/dopo**, stessa identità iniziale, stesse quantità, prezzi di ingresso, realizzato, commissioni, generazioni e patrimonio iniziale. Contatori giornalieri e ultimo aumento invariati, high-water non resettato. Mark ed equity continuano ad aggiornarsi naturalmente.
- Zero decisioni nel nuovo `approvals.sqlite`, nessuna policy settimanale ancora attivata e nessun nuovo simbolo aggiunto al ledger prima del consenso.
- Nove altri container conservano ID, ora di avvio e conteggio riavvii. Originale, FAST, HALF, osservazione M1 e conti intraday invariati. Solo M1 è stato sostituito e `octobot-local` riavviato; aggiunti collector e broker dedicati.
- Tredici servizi operativi healthy dopo il passaggio; vecchio container M1 conservato e spento. Collector pubblico: daily e quotazioni presenti per 29 simboli, senza etichetta fixture.

Il primo avvio del collector ha evidenziato tre sottodirectory archivio mancanti nel preparatore (`raw`, `science`, `market`). Sono state create con proprietario UID 30944; il preparatore è stato corretto per i rilasci futuri. Nessun dato cancellato, nessuna soglia cambiata. Il collector ha quindi acquisito e pubblicato i dati reali ed è healthy. Il runner M1 è stato fermato soltanto dopo avere verificato la nuova fonte.

## Verifiche sul runtime pubblicato

Browser reale desktop e mobile sulla dashboard operativa: proposta reale disponibile, canale di autenticazione pronto, 29 righe, dialogo di conferma e password eliminata dal campo dopo l'invio. Password volutamente errata respinta dal broker reale; richiesta priva di CSRF e origine diversa respinte. Proposta ancora PROPOSED e policy assente dopo i test. Nessuna credenziale valida utilizzata nel browser di test e nessun consenso reale fornito dall'agente.

Verificate anche le sei pagine: confronto strategie, conto M1, grafici M1, Originale, BTC intraday e confronto intraday. Nessun errore JavaScript o richiesta esterna nel percorso verificato; nessuna eccedenza orizzontale su mobile.

UID e mount effettivi verificati: collector 30944 con sole scritture ai dati propri; broker 30945 con scrittura del solo DB approvazioni e socket; M1 30943 con scrittura del ledger esistente e lettura delle approvazioni, senza verificatore password. Broker e M1 senza rete. Il web non monta i due ledger in scrittura. Le verifiche locali precedenti restano **68 test passati** più browser-to-ledger su copia privata con book esplicitamente sintetici e cinque riduzioni reali nel simulatore.

Evidenze locali: `audit-evidence/m1-weekly-activation-20261023/`: backup prima/dopo, controlli del ledger, autorizzazione, custodia dei nuovi servizi, confronto container, risultato browser e screenshot. Manifest di attivazione separato dal manifest immutabile preparato, nessun segreto esportato. I dati completi restano fuori Git.

## Residuo e accettazione

Il collegamento operativo richiesto è consegnato. Restano la **prima approvazione specifica dell'operatore in UI**, il riscontro del conseguente ribilanciamento e l'accettazione finale prima di chiudere le schede. Questa autorizzazione al caricamento non viene estesa al consenso su una selezione. Gli aumenti possono attendere il prossimo slot o restare negati per rischio, dati o liquidità; la pagina distingue queste attese dal successo effettivo.

Nessun trade reale, grant operativo, cambiamento di quarantena o soglia P0. `min_quantity` e `min_notional` KuCoin reali restano UNKNOWN su tutti i nuovi input; il paper usa il contratto sintetico separato. Readiness exchange-faithful **BLOCKED**.
