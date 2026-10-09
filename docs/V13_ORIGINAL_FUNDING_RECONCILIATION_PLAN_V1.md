# V13 originale — piano candidato di riconciliazione funding

28 settembre 2026 · v1 · **PROPOSTO, NON APPROVATO E NON APPLICATO**.
Ricerca `work-card-08885cb2-7813-4113-9c9b-f85eb61391eb`; verifiche interne `work-card-14f3889d-d99b-4833-aa0d-4d41c4c2a98f`.
Conto esistente `v13-paper-v2`; preservare ordini, storico, equity e lineage.

## Evidenza locale disponibile

È stato congelato un prefisso del journal `octobot-local/shadow/market/microstructure.jsonl`, fino all'osservazione completata il **28 settembre alle 13:30:31 UTC**. Contiene 693 record, con catena hash verificata e corrispondenza ai 693 file in `records/`. Tutti i bucket dichiarati di 15 minuti sono presenti. Il record già contabilizzato dal conto è il numero 15, del 21 settembre alle 12:00:25 UTC; **678 osservazioni successive** sono presenti ma non contabilizzate.

L'inventario distingue settlement da `current_rate` e `predicted_rate`: queste ultime non sono usate. Le rilevazioni ripetute dello stesso evento non producono eventi aggiuntivi. Per ogni asset, 1.893 occorrenze successive al cursore si riducono a 21 eventi distinti, con **zero conflitti nelle rate normalizzate**.

| Posizione aperta | Settlement distinti dopo il cursore | Rate negative osservate | Riferimenti mark precedenti trovati |
|---|---:|---:|---:|
| AAVE | 21 | 0 | 21 |
| ETH | 21 | 1 | 21 |
| LINK | 21 | 1 | 21 |
| NEAR | 21 | 0 | 21 |
| SOL | 21 | 5 | 21 |
| UNI | 21 | 0 | 21 |
| XLM | 21 | 0 | 21 |
| ZEC | 21 | 0 | 21 |

Totale **168 eventi**: dal 21 settembre alle 16:00 UTC al 28 settembre alle 08:00 UTC. La sequenza coincide con l'intervallo di 8 ore dichiarato dal collector, senza buchi interni; al termine dello snapshot non è ancora trascorso tale intervallo dall'ultimo evento. Questo è un controllo della serie **osservata**, non certificazione autorevole dell'intero calendario exchange. Non si inventa un evento alle 16:00 del 28 settembre né si conclude che il costo fino alla futura ripresa sia già noto.

Il reader esistente verifica tutti i 693 record; il decoder mercato esistente accetta tutti i record per gli 8 simboli. Questi controlli non eseguono tick, issuer o ordini e non attestano ammissibilità KuCoin. Le tre copie `v13-rebuild*/v13-rebuild-funding.json` coprono ricerca fino a giugno 2026, con altra sorgente/lineage: non completano il funding KuCoin di settembre.

## Cosa questa evidenza non prova

Il ledger copiato conserva 8 ordini, 14 punti equity, 104 marks e **zero righe funding**. Gli ultimi marks risalgono al 21 settembre circa alle 12:00 UTC. Il gap contabile resta superiore al guard esistente di 20 ore: **nessun tick diretto sul book attuale**, nessun reset del cursore e nessuna modifica del guard.

I record normalizzati conservano `mark_price`, timestamp del book e tempi dichiarati di inizio/fine raccolta; non contengono il timestamp esatto di misura del mark o le risposte REST grezze con i loro tempi/hash individuali. Il timestamp del book **non è** il timestamp del mark. Il controllo di catena/archivio prova integrità interna; non prova custodia indipendente o disponibilità storica. La cattura odierna attesta il possesso dei byte oggi, senza retrodatare una ricevuta fidata.

L'assenza di conflitti fra record normalizzati non esclude conflitti già persi durante la normalizzazione: il parser corrente usa un dizionario per timestamp sui settlement di una risposta; i byte originali non sono in questo archivio. Questa conclusione riguarda i percorsi esaminati, non l'intero repository o tutte le possibili copie esterne.

Le quantità attualmente aperte sono positive. Il segno delle rate deve restare intatto: una rate negativa genera un credito nel metodo lineare già dichiarato. Non usare valore assoluto, rate prevista o zero per riempire assenze. Nessun importo di funding è stato calcolato o scritto da questo incarico.

## Metodo raccomandato per la sola riconciliazione paper

Proporre una **riconciliazione ritardata e dichiaratamente stimata**, compatibile con la formula legacy `-quantità detenuta × mark precedente osservato × rate regolata`. Richiede accettazione umana dei limiti dell'archivio; non è il mark esatto di settlement né un nuovo criterio operativo già configurato.

Per ogni evento usare un riferimento mark da un record dichiarato interamente completato **prima** del settlement. Nell'inventario la prima rate, delle 16:00 del 21 settembre, compare nel record completato alle 16:00:25; il riferimento candidato è il record delle 15:45, completato alle 15:45:24. Non usare il mark del record post-settlement come se fosse già disponibile prima. La stessa regola identifica un riferimento per tutti i 168 eventi; resta una selezione diagnostica basata su tempi dichiarati, senza certificazione della loro disponibilità storica.

Prima di applicare, verificare che il conto non sia cambiato rispetto al backup e ricostruire le quantità tramite i fill fino a ogni evento. Per il prefisso esaminato non esistono fill dopo gli 8 ordini del 21 settembre; la continuità delle quantità va comunque riconfermata sotto il lock del futuro writer. La chiave di deduplicazione è contratto/asset e timestamp di settlement, legata al conto e alla nuova ricevuta di riconciliazione.

La ricevuta candidata dovrà legare hash del ledger di partenza e del bundle dati, riferimenti delle rate e dei marks, quantità/segno/unità, evento economico `settlement_at`, disponibilità verificata ove realmente attestabile e nuovo `accounted_at`. Il replay storico non sarà presentato come trading forward avvenuto nei giorni precedenti. Non modificare i 14 punti equity originali: l'eventuale punto di riconciliazione dovrà essere nuovo, datato all'effettiva contabilizzazione e distinto da quelli storici.

Il futuro calcolo e commit dovranno avvenire prima su copia, senza ordini; importi, funding events, state e ricevuta saranno atomici, con unicità/replay e fallimenti verificati. Nessuna claim o approval retroattiva. Prima della migrazione effettiva occorrerà generare un **nuovo bundle candidato** riferito allo stato riconciliato, conservando la precedente evidenza e senza riutilizzare il suo epoch come se lo stato fosse identico. Il cutoff dati andrà aggiornato prima della reale ripresa: questa analisi si ferma alle 13:30 UTC del 28 settembre.

## Decisioni e ordine del lavoro

| Decisione | Opzioni | Raccomandazione motivata | Cosa resta bloccato |
|---|---|---|---|
| Qualità accettabile per la riconciliazione storica paper | Stima su archivio normalizzato con limiti dichiarati; evidenza aggiuntiva delle risposte/marks storici | Accettare la stima legacy solo dopo review esplicita: i 168 eventi e i riferimenti esistono già, senza acquisizioni aggiuntive per questa proposta | Calcolo ammesso e applicazione al conto finché il criterio non è approvato |
| Custodia e disponibilità | Ricevuta odierna per revisione retrospettiva; pipeline futura con ricevute indipendenti di acquisizione/pubblicazione | Separare i due ruoli: nessuna retrodatazione delle prove e nuovo contratto di provenance per il futuro | Issuance reale e nuovi tick del writer fidato |
| Cutover contabile e policy | Ricevuta atomica più nuovo punto esplicito; diversa semantica approvata dal proprietario | Preservare tutto lo storico; decidere giorno iniziale, contatori e cooldown senza reset automatici | Migrazione applicata, policy e avvio |

Ordine minimo: (1) completare il contratto di provenance/disponibilità multiasset già in To Do; (2) review e decisione sul criterio qui proposto; (3) implementare un riconciliatore solo su copie con prove di replay/guasto; (4) chiusura amministrativa originale, integrazione e review indipendente; (5) decisioni di binding/epoch/writer/policy e successivo batch autorizzato. Le raccomandazioni non costituiscono approvazioni.

`min_quantity` e `min_notional` rimangono **UNKNOWN** e bloccano soltanto le aperture KuCoin-faithful; i quattro controlli operativi rimangono **UNCONFIGURED**. Nessun issuer, grant, policy, collector, conto operativo o quarantena è stato modificato. Evidenze in `audit-evidence/v13-funding-reconciliation-20260928T133115Z/`: snapshot compresso e hash, inventario eventi/marks, riferimenti ai file archivio, verifica interna e preservazione.
