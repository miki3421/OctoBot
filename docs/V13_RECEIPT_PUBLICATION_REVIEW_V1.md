# V13 originale — integrazione ricevute e pubblicazione, candidato offline

28 settembre 2026. Scheda `work-card-6f157fda-6e1c-47e4-af41-88368045c0f6`;
test interni `work-card-3fdd6ea6-217d-415d-963e-5c8e0328c389`.
**SYNTHETIC_ARCHITECTURE_ONLY, inattivo, readiness BLOCKED.**

`v13_receipt_publication_review.py` collega le due librerie congelate di cattura
e pubblicazione originale attraverso una nuova configurazione root-owned,
versione, marker e witness SQLite. Non cambia codice scientifico, vecchi helper,
issuer o executor. Non contiene client HTTP né entrypoint di servizio.

Il percorso di prova è:

`risposte di fixture → ricevute + ACK della cattura → inventario originale RO
→ manifest completo del publisher → ACK della pubblicazione → ricalcolo originale
su copia → ricevuta derivazione → ACK della derivazione → verifica RO`

La configurazione deve pinnare entrambe le configurazioni preesistenti,
inventario, ACK del publisher archivio, head della cattura e una mappa completa
delle dipendenze raw. Per ogni risposta: path/hash dell'artefatto compresso,
hash dei byte decompressi, metodo/URL esatti, purpose scientifico Binance,
tipo daily/funding, simbolo, capture ID/hash e ACK/hash devono coincidere.
Copertura mancante, extra, uso di book KuCoin, scambio di simbolo o timestamp
prima della conferma negano la pubblicazione. JSON/status corretti da soli
non certificano la semantica: questa è verificata dal ricalcolo originale.

Journal e daily normalizzate sono pinnati nell'inventario e ricalcolati dal
verifier originale; il contesto storico iniziale resta il bundle di ricerca
congelato, verificato dall'implementation lock. Le ricevute sintetiche di oggi
non sono ricevute delle acquisizioni storiche di quel bundle.

La derivazione richiama realmente `v13_original_publication_review.derive`,
che invoca il verifier e le funzioni originali congelate. Non accetta un vettore
proposto dal chiamante. Le unit test usano double esplicitamente etichettati
per esercitare il collegamento; la prova dell'archivio originale senza double
è distinta e non viene presentata come E2E positivo di cattura contemporanea.

`snapshot_id` usa solo versione, lineage, universo, slot e causal_input_hash.
Identità di cattura, manifest e ACK appartengono alla provenienza del bundle e
possono cambiare senza cambiare lo snapshot scientifico. Il manifest conserva
anche tutte le dipendenze originali, senza riscrivere journal storici.

`current_fixture_bundle_available_at` è il massimo delle osservazioni
post-commit di catture, pubblicazione e derivazione e del completamento del
verifier. Non è un tempo operativo. Il ricalcolo non può precedere l'ACK della
pubblicazione. Ogni ACK attesta un oggetto già fsynced e un evento SQLite già
committato; non attesta il proprio fsync futuro. I clock sono soltanto fixture;
nessun bound operativo, freshness o skew viene approvato.

Solo il publisher scrive il nuovo manifest, solo il verifier la derivazione,
solo il witness il proprio intero SQLite e gli ACK. La strategia legge soltanto.
I writer verificano gli UID effettivi; UID numerici nei container non installano
utenti host. I due witness precedenti e quello dell'integrazione hanno database
distinti; i permessi filesystem non separano tabelle. Non esistono scritture in
approvals.sqlite o execution.sqlite.

Replay identico riconferma fsync senza cambiare la prima osservazione. Una morte
dopo commit ma prima dell'ACK richiede riconciliazione esplicita dell'head: il
vecchio head non viene accettato automaticamente. Un DB restaurato viene negato
con i pin successivi conservati fuori dal restore. Riavvolgere anche i pin
esterni resta indistinguibile: nessun witness monotono operativo è installato.

Il catalogo capture v1 contiene campioni `limit=2`; gli URL dei raw originali
includono altre finestre e paginazioni. Anche byte identici non permettono di
assegnare a quei raw una ricevuta con URL diverso. La prova reale ricalcola il
portafoglio originale, poi nega questa copertura incompatibile. Per nuove
acquisizioni serve un catalogo versionato completo con controlli semantici e
paginazione, seguito dalle decisioni di custodia/clock e autorizzazione HTTP.

`source_available_at_operational=null`, storico `UNRESOLVED`, ricevute storiche
`MISSING`, research-only invariato e issuable false. Le quattro policy sono
UNCONFIGURED; min_quantity e min_notional UNKNOWN. Nessuna prova di ammissibilità
KuCoin o validità predittiva, grant, deployment, avvio o modifica di quarantena.
