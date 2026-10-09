# Collector candidato per la qualifica V13 18/29

30 settembre 2026. **IMPLEMENTATO, verificato offline; NON INSTALLATO, NON ATTIVO.**
Scheda implementazione `work-card-a412674a-d488-40fd-81a4-7103db569108`;
prove `work-card-37b485cd-810c-413a-aecb-a70947f78614`;
consegna UI `work-card-d21438a8-8308-4d22-8de8-b1c01c6f680b`.

Il protocollo confermato resta quello con SHA-256
`09f855a5af1b3945bf6bb9e9bca4a1676599d6c0c633da66387af650c460e49d`.
Il modulo `octobot/ai_strategy_lab/v13_universe_qualification.py` vincola
l'esatto piano JSON e la ricevuta di approvazione. Non modifica questi documenti,
il paper V13 attivo, BTC 30/120, Qwen shadow o le loro sorgenti congelate.
Non importa issuer, executor, strategia o credenziali. Non crea conti A/B.

## Calendario e dati

Un futuro inizio alle 00:00 UTC determina esattamente 14 giorni e 39.816 GET:
38.976 book KuCoin depth20, 406 daily Binance del giorno UTC precedente,
406 risposte funding KuCoin dello stesso giorno precedente e 28 cataloghi.
I 29 simboli sono fissati nel piano, PEPE resta sospeso senza sostituzione.

Le richieste book sono previste ogni 15 minuti; i cataloghi alle 00:00,
daily e funding alle 00:10. Ogni richiesta deve iniziare e terminare entro
60 secondi dal proprio slot. Il controllo prima della rete viene ripetuto
dopo il commit del tentativo. Un dato tardivo viene conservato come invalido.
La serializzazione può produrre slot incompleti se la sorgente è lenta:
la copertura è da misurare sui dati reali, non garantita dai test sintetici.
Niente retry automatici, backfill dei book o rinnovo oltre 14 giorni.

I due cataloghi validi dello stesso giorno devono confermare tutti i 29
contratti, con identità, quotazione/margine USDT, stato attivo e perpetual.
Il mapping BTC/XBT è esplicito; nessuna normalizzazione dei prefissi 1000.
Un contratto assente o cambiato impedisce le richieste dei simboli per quel
paniere, senza selezionare sostituti. I cataloghi integrali sono conservati.

Per i book si verificano timestamp, livelli ordinati e non incrociati,
valori finiti e multiplier; vengono registrati spread, profondità per lato,
distanza del livello estremo e VWAP della quantità teorica corrispondente a
3.150 USDT al mid. Se la profondità non basta, VWAP resta non disponibile:
non è un fill. Daily: una barra chiusa del giorno precedente, senza barra
futura. Funding: timestamp unici nella finestra richiesta; numero di punti
osservati, **non certificazione di completezza delle regolazioni**.
`min_quantity` e `min_notional` restano UNKNOWN (`null`), senza inferenze.

## Persistenza e guasti

Archivio dedicato `qualification.sqlite`, distinto dai ledger operativi.
SQLite usa `synchronous=FULL` e rollback journal DELETE. Piano completo e
binding dell'attivazione vengono registrati una sola volta, prima dell'inizio.
L'inizializzazione è esclusiva: archivio esistente, mancante alla ripresa o
corrotto non viene ricreato. Nessuna cancellazione o riparazione automatica.

Il processo acquisisce un lock esclusivo reale; non deduce attività dalla
presenza del file `.lock`. Ogni tentativo riserva fisicamente nel DB lo spazio
massimo della risposta e viene confermato prima della rete. Corpo compresso,
SHA-256, orari, HTTP, esito e metriche sono poi confermati insieme. Un arresto
tra le due transazioni lascia `uncertain`: niente retry, contatore e spazio
riservato rimangono addebitati. Un errore del DB interrompe il ciclo; il chiamante
riceve un errore, non un esito di salute positivo.

Massimo 42.000 tentativi e 512 MiB di corpi compressi, incluse le riserve
incerte. I 2.184 tentativi teoricamente disponibili oltre il calendario non
abilitano retry in questa versione. Cataloghi limitati a 4 MiB non compressi,
altre risposte a 64 KiB. Una risposta eccessiva conserva un prefisso dichiarato
incompleto e non vale come dato valido. Il cap raw non è il limite totale del
filesystem: DB, indici, rollback journal e margine libero richiedono spazio
aggiuntivo da dimensionare prima del rilascio.

HTTP 418/429 sospende senza ripresa automatica, anche se il corpo è troppo
lungo. Tre risposte consecutive errate sospendono; un timeout conta come
fallimento. Il contatore sopravvive al riavvio. Clock arretrato, budget
raggiunto o fine periodo producono stop persistente. Non esiste comando di
reset/resume del fermo: occorre revisione manuale conservando le evidenze.
I payload validi e invalidi ricevuti restano archiviati; non esiste pruning.

## Avvio ancora non autorizzato

Il comando `plan --repo ...` verifica il piano senza rete. `initialize` e `tick`
richiedono un file di attivazione esterno, root-owned, non scrivibile da gruppo
o altri, dentro directory root-owned non scrivibili. **Nessun file di questo
tipo è stato creato.** Il protocollo approvato non è quel file.

Il futuro documento deve fissare schema_version=1, plan_sha256,
collector_sha256, collector_uid non-root, storage_root privato (0700),
start_utc/end_utc esattamente distanti 14 giorni, attempt_cap=42000,
compressed_raw_bytes_cap=536870912, owner_decision_reference,
periodic_downloads_authorized=true, service_activation_authorized=true,
orders_authorized=false. L'identità del processo deve coincidere col documento.
Il digest dell'intero documento lega l'archivio: cambiarlo non riusa lo stato.

L'identità, il servizio, il filesystem dedicato, la disponibilità disco e il
manifest di rilascio sono ancora da predisporre e verificare. Il servizio
futuro dovrà avere accesso soltanto a codice in lettura e al proprio archivio,
senza mount di journal scientifici, ledger, grant o credenziali. La rete deve
restare confinata ai GET pubblici previsti; il client rifiuta redirect e proxy
ambientali. L'isolamento OS non è provato dalla sola classe Python.

Non ci sono timer, unità installate o download di mercato in questa consegna.
L'autorizzazione una tantum precedente è esaurita; la raccolta periodica
richiede una decisione specifica, secondo la regola aziendale sui download.

## Evidenza e lavoro successivo

La suite usa solo trasporto, risposte e clock sintetici, con socket negati nel
processo di test. Copre calendario, dati futuri/tardivi, identità, replay,
concorrenza, quote, storage guasto, clock arretrato, riavvio e SIGKILL di un
processo figlio. L'attivazione simulata dei test non è una ricevuta operativa.
Queste prove dimostrano proprietà del collector; non dimostrano copertura reale,
liquidità, redditività o ammissibilità KuCoin. Sono verifiche dell'autore,
non una review indipendente.

Restano: rilascio isolato e autorizzazioni; 14 giorni di acquisizione effettiva;
valutatore finale delle soglie del protocollo, da realizzare prima di leggere
l'esito della qualifica; poi runner e conti A/B per la fase distinta di 180
giorni. Nessun PASS di qualità o di performance viene emesso dal collector.
