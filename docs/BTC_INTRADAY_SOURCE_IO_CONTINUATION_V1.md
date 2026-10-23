# BTC intraday iniziale: continuazione I/O v1

Scheda `work-card-d0b2e5a9-508b-4419-8393-0498500f0011`. Correzione dei riavvii del solo conto iniziale; non riguarda la nuova coppia SHORT / LONG + SHORT.

I quattro file del runtime v2 restano immutati in una sottodirectory `frozen` del nuovo bundle. L’entrypoint esterno verifica una ricevuta root-owned fissata al codice I/O, alla configurazione precedente, all’attivazione e alla continuazione pre-T0 originali. Invoca anche l’autorità originale, incluse le sue verifiche del protocollo e della copia storica pre-T0. Passa poi la configurazione originale alla funzione run originale. Non viene cambiata l’identità contabile o creata un’eccezione al gate pre-T0.

L’unica sostituzione in memoria è la factory del BookReader. L’adattatore delega ogni lettura e validazione al reader originale; recupera esclusivamente SQLITE_CANTOPEN, BUSY e LOCKED, anche nei codici estesi, con 250 ms di attesa tra tentativi. Non dorme il motore: il normale ramo senza book continua heartbeat e controlli protettivi. Cursore e identità del file restano fissi; il cursore avanza soltanto nel codice originale dopo persistenza e verifica delle ricevute. Errori di cronologia, clock, sostituzione file, backlog, corruzione e storage restano bloccanti. Nessun mount sorgente RW o fallback immutable, nessun allargamento delle soglie di freschezza.

Le transizioni attesa/ripresa vengono aggiunte a un file diagnostico distinto, privato e append-only nello stato del conto. Un errore di scrittura del log non è nascosto. Il log non è una ricevuta causale né un’autorizzazione. La proiezione e il monitor attuali non cambiano; un’assenza prolungata del book resta segnalabile.

## Candidato e decisione manuale

Il compose `docker-compose.btc-intraday-io-v1.yml` usa la stessa immagine per digest, UID/GID, assenza di rete, mount e soglie health del vecchio servizio. Cambiano soltanto directory runtime, entrypoint e file di configurazione esterna. La configurazione v2 e i suoi percorsi originali sono fissati dalla nuova ricevuta. Gli artefatti candidati sono in `audit-evidence/btc-old-source-io-20261023/candidate`; il manifest identifica i sei file runtime e i due nuovi documenti. Nessun file operativo esistente deve essere sovrascritto durante la preparazione.

La preparazione non autorizza il deploy. L’operatore deve decidere l’arresto e la sostituzione del solo container `octobot-btc-intraday-paper`. Nessun altro conto o collector viene interrotto.

## Sequenza di rilascio

1. Verificare manifest, ricevute e quattro file congelati; controllare immagine già presente, capacità disco e proiezione del conto. Conservare ID, avvii e contatori di tutti i container. Registrare la decisione e il checkpoint nel CP.
2. Installare il nuovo bundle in una directory runtime distinta e root-owned, con file immutabili e directory empty RO. Installare soltanto i due nuovi documenti di configurazione, root:30910, 0440, senza alterare i precedenti. Validare il compose con il progetto separato `btc-intraday-io-v1`.
3. Arrestare soltanto il vecchio container con timeout 30s, conservarne log e container rinominato `octobot-btc-intraday-paper-pre-io-v1-20261023`. Nessuna rimozione di container o volumi storici. Copiare a freddo l’intero suo stato in evidenze private; conservare la copia grezza senza aprirla RW.
4. Se il crash lascia WAL o journal, eseguire il normale recupero SQLite soltanto su una seconda copia privata. Poi integrity_check in sola lettura sulle copie. Mai scansioni o riparazioni sul book live o sui ledger attivi.
5. Avviare soltanto il servizio del nuovo compose, senza build, pull, inizializzazione o reset. Usa gli stessi file account, stress e ricevute e lo stesso nome container monitorato.
6. Verificare identità originali, T0/T1, posizioni, cash, fill, fee, funding, rischio e ancore precedenti dei journal; controllare aggiornamento UI, healthy e normale monitor. Gli altri dieci container devono conservare ID, immagine, avvio e contatore. Nessun ingresso retroattivo o fill forzato.

Il backup freddo e l’integrità delle copie sono prove di rilascio, non risultati già acquisiti dalla sola preparazione.

## Rollback

Arrestare soltanto il nuovo servizio e conservarne container e log con un nome diverso. Ridare al precedente container fermo il nome originale e avviarlo con il suo runtime/configurazione immutati. Il formato dei ledger non cambia: non ripristinare il database dal backup e non perdere le registrazioni aggiunte dopo il rilascio. Nessun replay, seed, reset dei limiti o modifica alla strategia. Conservare anche il nuovo log diagnostico separato.
