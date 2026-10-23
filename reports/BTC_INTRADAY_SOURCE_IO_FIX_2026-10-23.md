# Riavvii del vecchio BTC intraday — correzione I/O qualificata

23 ottobre 2026. Candidato tecnico pronto; runtime attivo ancora invariato. Grafici M1 accettati e relative schede chiuse.

## Causa verificata

I due crash delle 01:05:23 e 02:08:05 UTC del 23 ottobre seguono rispettivamente di circa 241 ms e 185 ms la riconnessione del collector dopo book stale di cinque secondi. L’ultimo writer WAL chiude e rimuove WAL/SHM; il reader RO con UID differente non può ricreare l’indice condiviso. SQLite solleva CANTOPEN (14) alla query MAX(id), propagata fino all’uscita del runner. I sei riavvii totali del vecchio conto non sono nuovi riavvii della coppia corretta.

## Correzione circoscritta

Adattatore esterno e wrapper con ricevuta root-owned, bundle distinto. Quattro sorgenti v2 originali identici per hash: motore, availability, normalizzazione e admin. Attivazione, protocollo, configurazione v2, continuazione pre-T0, copia storica e percorsi di account/stress/ricevute invariati. Il wrapper verifica nuovamente l’autorità originale, poi sostituisce soltanto la factory del reader con il delegato che attende su accesso/lock transitorio. Il loop originale continua gli heartbeat e le protezioni. Nessuna modifica a soglie, segnale SHORT, size, uscite, funding, limiti o clock. Log di recupero distinto, privato e append-only. Altri errori restano bloccanti.

## Prove completate

77 test mirati sullo stesso ambiente SQLite del runtime: recupero e bootstrap, inode, cursore, errori non ammessi e storage, posizione SHORT senza fill fittizi durante l’assenza del book, uscita protettiva latched, conservazione contabilità/rischio dopo riavvio, custodia e binding della continuazione, oltre alle regressioni complete del motore originale e delle ricevute. Sono verifiche dell’autore, non QA indipendente o evidenza scientifica.

Riproduzione offline con la stessa immagine e SQLite 3.46.1: writer UID 1000, reader UID 30943 con mount sorgente RO. Chiusura writer, errore 14, attesa e riapertura: stesso PID, evento WAIT poi RECOVER, cursore da 1 a 2 soltanto dopo le tre fasi di persistenza del witness e la lettura attuale della conferma. Nessun intervento sul collector attivo. La prima versione del solo harness creava il witness dopo la lettura e veniva correttamente respinta: corretta la sequenza del test, conservate entrambe le evidenze.

Preflight della vera configurazione e delle ricevute originali con UID/GID effettivi e mount RO: autorità verificata, nessun ledger aperto dal preflight o reinizializzato. Compose candidato valido; nessun download. Manifest e prove in audit-evidence/btc-old-source-io-20261023. I controlli di integrità dei backup saranno eseguiti solo dopo l’eventuale arresto autorizzato; non sono stati eseguiti sui ledger live.

## Residuo per attivare la correzione

Decisione manuale per sostituire il solo octobot-btc-intraday-paper, conservando il precedente container e una copia fredda dello stato. Piano e rollback in docs/BTC_INTRADAY_SOURCE_IO_CONTINUATION_V1.md. Il runtime I/O nuovo non è stato installato o avviato; nessuna strategia, account, fonte, monitor o UI è stata riavviata durante la preparazione. Minimi KuCoin UNKNOWN; ricerca sintetica soltanto, senza grant o ordini reali.

Schede: correzione work-card-d0b2e5a9-508b-4419-8393-0498500f0011; test work-card-975838bc-0469-49aa-b81f-f1491f16f055; consegna work-card-7c6b8d86-4ced-4abb-925e-f4c037820b62.
