# V13 A/B/C — integrazione del ciclo operativo

8 ottobre 2026. Scheda work-card-56a72d4d-956c-47f1-b7b5-47bbc74546a1.

## Codice aggiunto

- Controller periodico con stato atomico WAITING/BLOCKED/EXPIRED/COMMITTED/OBSERVED/ERROR; nessuna segnalazione di successo dopo un errore.
- Consumer delle osservazioni: equity, funding e rischio aggiornati senza nuovi segnali né fill. Scrittura serializzata con i ribilanciamenti nello stesso ledger. Conti mai creati dal percorso di osservazione.
- Finestra di esecuzione esplicita nella configurazione di rilascio, misurata dallo slot originale e ricontrollata sotto lock prima del commit. Nessun rinnovo al riavvio. Nessun valore operativo di durata è stato approvato o installato implicitamente.
- Intent store leggibile in sola lettura dall’esecutore; collector, producer ed executor devono avere UID separati. Configurazioni root-owned e pin esterni richiesti dagli ingressi di servizio.
- Collector forward con endpoint pubblici già delimitati, validazione delle ricevute, nessun recupero oltre deadline, nessun nuovo download dei job completati dopo riavvio. Risposte 418/429 producono arresto persistente e revisione manuale.
- Produttore periodico con slot originario, sorgenti raw verificate e sigillo monouso; non recupera il primo slot mancato e non riproduce decisioni già sigillate al riavvio.
- Chiusura amministrativa su comando root-owned con hash esterno, conto, stato delle posizioni, ID e scadenza. Quantità rilette sotto lock; riduzioni senza inversione o aumento. Con copertura funding incompleta la chiusura conserva il cursore del debito, espone equity netta non determinata e consente la riconciliazione successiva senza doppio addebito. Nessun aumento di rischio viene abilitato.
- Tre ingressi espliciti: scripts/run_v13_abc_service.py, scripts/run_v13_abc_collector.py e scripts/run_v13_abc_producer.py. Nessun timer, container o unità installato/avviato.

## Verifica e limiti

**105 test passati**, inclusi diniego di replay amministrativo, chiusura a funding incompleto e recupero del debito sulle quantità storiche. Suite offline e risultati in audit-evidence/v13-operational-20261008/ alla radice del laboratorio. Prove sintetiche, senza rete. Verificati scadenza al riavvio e sotto lock, divieto di scrittura agli intenti, osservazioni senza fill, recupero dei job e arresto persistente dopo rate-limit.

**Non è una consegna operativa attiva.** La readiness reale continua a negare l’avvio. Il servizio non costituisce un grant e non interpreta il contratto storico approvato come approvazione del nuovo codice.

Restano necessari:
1. Autorizzazione alla raccolta periodica e verifica pubblica ricevuta dall’owner in questa sessione. Acquisite29risposte funding correnti HTTP200 con tempi e SHA-256; nessun servizio periodico avviato.
2. Calendario funding documentato e validato, esito finale di qualifica dal 16 ottobre 00:00 UTC, bundle e start comune autorizzati.
3. Verifica del pacchetto operativo su identità e directory effettive, compreso il percorso amministrativo. Il collaudo attuale è offline con autorità simulate: non sostituisce questa verifica né il gate di ammissione, che resta chiuso.
4. Configurazione concreta degli UID, directory e durata intenti, installazione controllata e collaudo del servizio effettivo. Gli ingressi CLI non equivalgono a tali operazioni.

Il paper V13 esistente e i suoi dati non sono stati modificati. Minimi KuCoin UNKNOWN. Download pubblici autorizzati registrati; nessun grant operativo o riavvio eseguito. Le evidenze precedenti sono conservate.

## Evidenza ufficiale funding

KuCoin documenta variazioni automatiche della frequenza, anche senza annuncio separato, dal17agosto2026: [annuncio ufficiale](https://www.kucoin.com/announcement/en-kucoin-futures-to-launch-automatic-funding-fee-settlement-interval-adjustment-mechanism-2026-08-17). Il [metodo pubblico current funding](https://www.kucoin.com/docs-new/rest/futures-trading/funding-fees/get-current-funding-rate) espone granularity, timePoint e fundingTime. La fotografia corrente non certifica tutta la sequenza storica o futura: non viene convertita in un calendario costante.

Occorre una raccolta prospettica dei cambi di calendario e la verifica di continuità rispetto ai regolamenti; il solo collector riusato per book/daily/funding storico non chiude questo requisito. Non si dichiara quindi il lavoro operativo terminato né la readiness positiva.
