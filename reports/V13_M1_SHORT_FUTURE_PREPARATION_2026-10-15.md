# M1 con SHORT: preparazione della verifica futura

15 ottobre 2026. **PREPARED_NOT_STARTED.** Protocollo, registratore causale e valutatore finale preparati e verificati. Nessun avvio, timer, servizio, grant o nuovo conto operativo. Originale, FAST e HALF invariati. La qualifica tecnica odierna non è un risultato forward.

Schede: protocollo `work-card-3a1e5054-c264-4262-9fc7-a341128c48a8`; preparazione `work-card-17c7410d-e45a-48c3-994a-99afa7980615`; verifica `work-card-73368f5a-72ef-4126-8dea-95243750bce4`. Evidenze nella radice workspace: `audit-evidence/v13-m1-future-preparation-20261015/`. SINGLE_AGENT, verifica dell'autore; nessuna review indipendente dichiarata.

## Cosa sarà verificato

Domanda: sugli stessi segnali futuri M1, invertire il paniere long V13 produce più valore netto che chiuderlo e restare in liquidità? Il confronto rimane condizionale ai segnali: ogni episodio conserva equity, posizioni, costi medi e storico effettivi V13 del momento. Non è una quarta curva di capitale continua e non eredita la validità scientifica dagli studi precedenti.

| Elemento | Regola preparata |
|---|---|
| Filtro M1 | BTC ≤−1% nell'ora e almeno 12/18 simboli negativi nell'ora |
| Dati | Griglia 5 minuti, prezzi già osservati, 24 ore contigue come nello studio precedente; nessuna interpolazione |
| Ingresso | Book del campione successivo, ritardo minimo 60 secondi; ricevuta entro 120 secondi dallo slot |
| Durata episodio | Sei ore sulla griglia fissata, poi sei ore senza nuovi episodi |
| Alternative | V13 effettiva; chiusura dei long; inversione dei long in short con stesso lordo iniziale |
| Termine comune | Ripristino delle quantità effettive V13 finali, con costi di rientro inclusi |
| Avvio | Ricevuta esplicita; primo slot alla mezzanotte UTC successiva alla ricevuta |
| Orizzonte | 90 giorni fissi; nessuna conclusione positiva anticipata o estensione opportunistica |

Un passaggio `+q → −q` richiede vendita di `2q`, e il ritorno richiede normalmente acquisto di `2q`. Tutta la quantità attraversa la profondità osservata una sola volta. Si applicano VWAP, 2bps avversi per lato, tick prudente, fee almeno 6bps e funding stimato con tassi verificati e mark precedente. Il test stress aggiunge 20bps su tutto il turnover, rientro incluso.

Il paniere resta quello dei 18 asset originali. Eventuali posizioni non positive già esistenti restano comuni alle alternative; la chiusura riguarda il comparto long. Se non esiste alcun long, il caso è registrato `NO_LONG_NO_INTERVENTION` e non inventa un paniere short. Le copie contengono lo storico completo: il rientro in quantità comuni è un controllo metodologico, non il sizing di una futura strategia autonoma.

## Criteri candidati fissati per la revisione finale

Questi sono criteri di ricerca proposti nel protocollo, non autorizzazioni operative. A fine periodo servono almeno 20 episodi completi, su almeno 10 giorni e 8 settimane con segnali, e almeno 95% di slot con dati validi. Un episodio ammesso ma irrisolto per dati, funding o contabilità rende la conclusione inconclusiva: non viene eliminato perché scomodo.

La misura principale è la differenza media netta SHORT−chiusura dopo il rientro. Per classificare il candidato come meritevole di ulteriore review devono essere positivi sia questa differenza sia il PnL short assoluto, anche nel costo stressato. Si riportano inoltre drawdown campionato, rimbalzi avversi, turnover, fee, funding e incertezza per blocchi settimanali. Sono pochi episodi di mercato correlati: un esito favorevole non significa strategia scientificamente validata.

Nessuna modifica di soglie, universo, durata o sorgenti dopo l'avvio. Una modifica richiede nuova versione e nuova frontiera futura, conservando tutti i dati già consumati. I controlli intermedi riguardano completezza e guasti; il valutatore finale rifiuta la valutazione prima della fine fissa.

## Cosa è stato costruito

- Registro separato per slot, input, segnali, finestre da acquisire e ricevute. La presenza di un file lock non è usata come prova di attività.
- Input consumati conservati per ogni episodio, con hash e tempi delle quotazioni. Al termine il filtro viene ricalcolato e i punti vengono confrontati con il ledger originale conservato.
- Copie SQLite originali e book ai due estremi: i dati esistenti sono letti in sola lettura. Le copie vengono verificate e sigillate con hash nello spazio del nuovo studio.
- Slot persi, ingresso/uscita mancati e dati insufficienti restano espliciti. Niente backfill di decisioni, niente sostituzione di input dopo un riavvio, niente reset del periodo.
- Errore di storage, clock o identità interrompe l'acquisizione; non produce alcun fill. Un file parziale non viene sovrascritto per simulare una ricevuta riuscita.
- Valutatore finale che ricostruisce posizioni e contabilità dai documenti conservati. Non accetta PnL libero dal modello o dall'operatore, verifica gli stessi portafogli terminali e l'identità dei flussi monetari.

Sono stati superati **36 test mirati**: 19 nuovi su futuro, causalità, restart, conflitti, storage failure, catture scadute, orizzonte e replay sintetico; 17 di regressione sul filtro e sulla contabilità. Le fixture sono marcate e rifiutate come evidenza scientifica reale. Test eseguiti anche in container temporaneo senza rete, con codice in sola lettura. Controllo tecnico corrente: 289 righe causali complete, 18 simboli, nessuna osservazione forward registrata.

## Confini e stato della consegna

Il contratto e il codice sono identificati da hash nel bundle versionato. Il protocollo non ha ricevuta di avvio e non c'è un servizio di raccolta installato da questa consegna. L'attivazione osservativa e la schedulazione restano attività To-do separate; non richiedono un nuovo download di mercato, perché il lettore usa le acquisizioni già autorizzate e attive. Qualsiasi futura diversa fonte va qualificata e autorizzata nel proprio ambito.

I minimi contrattuali reali KuCoin restano UNKNOWN; i minimi della simulazione rimangono separati. Non viene creato alcun collegamento a issuer, approvals, intent o executor. I limiti operativi e i gate delle tre strategie non sono derogati: le eventuali inversioni sono soltanto contabilità controfattuale dopo la raccolta dei dati.

Percorsi: protocollo `docs/research-protocols/v13-m1-short-prospective-v1.json`; bundle `docs/research-protocols/v13-m1-short-preparation-bundle-v1.json`; procedura `docs/V13_M1_SHORT_FUTURE_RUNBOOK_V1.md`. L'avvio deve usare quel bundle e generare una frontiera futura; la preparazione odierna non avvia il conteggio dei 90 giorni.
