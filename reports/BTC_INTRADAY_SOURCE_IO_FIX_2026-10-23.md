# Riavvii del vecchio BTC intraday — correzione I/O qualificata

23 ottobre 2026. Correzione applicata e verificata sul solo conto intraday iniziale. Grafici M1 accettati e relative schede chiuse.

## Causa verificata

I due crash delle 01:05:23 e 02:08:05 UTC del 23 ottobre seguono rispettivamente di circa 241 ms e 185 ms la riconnessione del collector dopo book stale di cinque secondi. L’ultimo writer WAL chiude e rimuove WAL/SHM; il reader RO con UID differente non può ricreare l’indice condiviso. SQLite solleva CANTOPEN (14) alla query MAX(id), propagata fino all’uscita del runner. I sei riavvii totali del vecchio conto non sono nuovi riavvii della coppia corretta.

## Correzione circoscritta

Adattatore esterno e wrapper con ricevuta root-owned, bundle distinto. Quattro sorgenti v2 originali identici per hash: motore, availability, normalizzazione e admin. Attivazione, protocollo, configurazione v2, continuazione pre-T0, copia storica e percorsi di account/stress/ricevute invariati. Il wrapper verifica nuovamente l’autorità originale, poi sostituisce soltanto la factory del reader con il delegato che attende su accesso/lock transitorio. Il loop originale continua gli heartbeat e le protezioni. Nessuna modifica a soglie, segnale SHORT, size, uscite, funding, limiti o clock. Log di recupero distinto, privato e append-only. Altri errori restano bloccanti.

## Prove completate

77 test mirati sullo stesso ambiente SQLite del runtime: recupero e bootstrap, inode, cursore, errori non ammessi e storage, posizione SHORT senza fill fittizi durante l’assenza del book, uscita protettiva latched, conservazione contabilità/rischio dopo riavvio, custodia e binding della continuazione, oltre alle regressioni complete del motore originale e delle ricevute. Sono verifiche dell’autore, non QA indipendente o evidenza scientifica.

Riproduzione offline con la stessa immagine e SQLite 3.46.1: writer UID 1000, reader UID 30943 con mount sorgente RO. Chiusura writer, errore 14, attesa e riapertura: stesso PID, evento WAIT poi RECOVER, cursore da 1 a 2 soltanto dopo le tre fasi di persistenza del witness e la lettura attuale della conferma. Nessun intervento sul collector attivo. La prima versione del solo harness creava il witness dopo la lettura e veniva correttamente respinta: corretta la sequenza del test, conservate entrambe le evidenze.

Preflight della vera configurazione e delle ricevute originali con UID/GID effettivi e mount RO: autorità verificata, nessun ledger aperto dal preflight o reinizializzato. Compose candidato valido; nessun download. Manifest e prove in audit-evidence/btc-old-source-io-20261023. I controlli di integrità dei backup saranno eseguiti solo dopo l’eventuale arresto autorizzato; non sono stati eseguiti sui ledger live.

## Rilascio verificato e accettazione residua

L’utente ha autorizzato esplicitamente la sostituzione. Runtime separato installato con gli stessi sei file qualificati, immagine, UID/GID, mount, isolamento e soglie health. La ricevuta I/O finale registra la decisione specifica; attivazione e configurazioni precedenti sono immutate. Commit sorgente 0176c019d0a73614298b6206772498aacade9c22; branch codex/btc-intraday-source-io-20261023 pubblicato nel repository.

Conservato fermo il precedente container come octobot-btc-intraday-paper-pre-io-v1-20261023, insieme al runtime v2. Copia fredda dell’intero stato in 17,62 secondi, preservata grezza. Recupero standard SQLite soltanto su una seconda copia privata; integrity_check RO positivo per primario, stress e availability. Nessun controllo di integrità completo sui ledger o sul collector live.

Nuovo container avviato il 23 ottobre alle 08:50:32 UTC (10:50 italiane). I controlli originali sulle catene complete, incluso il witness da 1.467.900 record, hanno richiesto circa sei minuti: durante questa fase il monitor ha correttamente rilevato conto stale/unhealthy. Non sono stati indeboliti i controlli né effettuati ulteriori riavvii. Dopo il completamento: healthy, zero riavvii e proiezione fresca. Gli slot scaduti restano registrati come tali, senza ricostruzione retroattiva.

Identità, T0/T1 e rischio di entrambi i conti coincidono con la copia precedente. Primario: cash/equity 9.998,4725824 USDT virtuali, FLAT, quattro fill, fee 1,9834176, funding zero, realizzato 0,456. Stress: equity 9.997,5693748, quattro fill. Tutti i fill e le ancore degli eventi nei tre database sono conservati; nuovi eventi avanzano normalmente. Nessun reset di capitale, storico o limiti.

Percorso utente reale /btc_intraday verificato nel browser: equity, raccolta, provenienza della diagnostica, grafico e aggiornamento dati; desktop/mobile senza errori JavaScript o overflow. Il conto è ACTIVE_WARMUP, ultimo campione 79/289: le interruzioni precedenti e la pausa non vengono riempite retroattivamente. Questo non equivale a un’operazione simulata già eseguita dalla nuova versione.

Tutti gli undici container healthy. Gli altri dieci hanno conservato ID, immagine, avvio e contatore di riavvii; nessuna modifica a strategie, collector, UI o configurazione del monitor. Eseguito un controllo passivo manuale con il monitor esistente alle 08:57:51 UTC: intraday healthy, nessun suo alert; resta il precedente FORK_RISK_MISMATCH, fuori da questo intervento. Nessun invio di email di prova. Minimi KuCoin UNKNOWN, niente grant o ordini reali.

Le schede implementazione e consegna restano in Test per l’accettazione finale dell’operatore. Le prove sono dell’autore; nessuna QA indipendente dichiarata. Piano e rollback in docs/BTC_INTRADAY_SOURCE_IO_CONTINUATION_V1.md, senza ripristino dei database o perdita dei nuovi eventi. Il costo crescente del controllo integrale all’avvio va considerato nella scheda già esistente sul dimensionamento degli archivi.

Schede: correzione work-card-d0b2e5a9-508b-4419-8393-0498500f0011; test work-card-975838bc-0469-49aa-b81f-f1491f16f055; consegna work-card-7c6b8d86-4ced-4abb-925e-f4c037820b62.
