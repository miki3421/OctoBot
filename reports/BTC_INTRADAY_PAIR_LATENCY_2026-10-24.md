# Coppia BTC intraday: diagnosi e correzione della pipeline

**Stato: candidato preparato, passaggio operativo manuale ancora da autorizzare.**
SHORT controllo e LONG + SHORT mantengono conti, T0/T1, equity, posizioni, storico,
segnali, soglie, quantità, costi, funding e protezioni. Nessun ingresso retroattivo.

## Cause misurate

La persistenza del collector era configurata a un secondo, contro il limite di
freschezza di un secondo dell'esecutore. Il book arrivava al reader in gruppi di
circa undici righe da 100 ms. Alle 15:15 UTC, per esempio, tra i batch l'esecutore
registrava heartbeat senza nuovi book; la successiva quotazione veniva processata
alle 15:15:01.626, oltre la scadenza 15:15:01.500. I tre ingressi delle 15:15,
15:20 e 15:35 sono scaduti; quello delle 15:40 è stato eseguito e poi chiuso dalla
protezione STALE_DATA. Non era assenza del segnale: BTC era sotto −1% nell'ora,
con 17–18 simboli su 18 in calo.

La conferma persistente dell'input richiedeva inoltre circa 58–146 ms nel campione.
La valorizzazione comune ogni cinque minuti introduceva un altro blocco: SQLite
usava l'indice temporale, rileggeva tutti gli eventi ammissibili e li riordinava
per sequenza. Su una copia coerente con **1.329.387 eventi**, ciascuna query
impiegava circa **944–984 ms**, ripetuta per quattro scenari nel ciclo esecutore.

## Correzione qualificata

- Commit del collector ogni **100 ms**. Nessuna variazione della sottoscrizione
  pubblica o dei dati raccolti, nessun timestamp riscritto.
- Query equivalente con scansione inversa della chiave di sequenza, senza
  riordinamento dell'intero storico. Sulla stessa copia i tre tempi diventano
  **0,082 / 0,011 / 0,459 ms** e gli hash dei record selezionati coincidono.
- Riserva di **2 GiB** per l'audit completo dello storico al riavvio: la prova
  ha già superato i 512 MiB precedenti. Quota CPU ancora 0,75; nessuna estensione
  della freschezza o della finestra di esecuzione.

Il package originale della strategia e la ricevuta di attivazione non vengono
modificati. Una sottoclasse esterna cambia soltanto il piano SQL della
valorizzazione; il nuovo wrapper verifica prima tutti i vincoli esistenti della
continuazione I/O. Nuovi file e configurazioni sono fissati per hash.

## Prove

- **74 test unitari/regressioni distinti passati**: 61 esistenti, 13 nuovi su
  equivalenza SQL, cutoff e acknowledgment tardivi/mancanti, custodia della
  continuazione, gate manuale, posizioni/intent pendenti e persistenza dei dati.
- Il confronto AST conferma che l'unica differenza della valorizzazione è il
  suggerimento del piano SQL e che il ciclo operativo conserva la stessa logica.
- Il test del collector confronta righe complete e aggregati: contenuti identici
  dopo flush, con visibilità anticipata della nuova configurazione.
- La verifica con UID/GID operativi e mount RO ha superato senza mock tutti i
  pin e i tre livelli di custodia (attivazione, continuazione I/O, nuova
  continuazione tecnica), senza montare alcun conto live.
- Prova completa sintetica, senza rete, con immagine SQLite effettiva e quota
  **0,75 CPU**: 38 batch, **172 ms mediana**, **240 ms p95**, **250 ms massimo**
  dalla ricezione al completamento dei quattro conti. Posizioni conservate con
  dati regolari; una pausa reale della pubblicazione attiva ancora STALE_DATA e
  l'uscita usa soltanto nuove quotazioni successive alla ripresa.
- Avvio riuscito su copia dell'intero storico: **346 secondi**, picco RSS
  **1.312 MiB**, quattro stati contabili esattamente identici dopo il caricamento,
  1.329.469 input e 3.988.504 eventi del witness verificati. Questo conferma
  la necessità della riserva di memoria. Nessun journal live viene ricostruito
  o verificato pesantemente. Con la quota CPU operativa il fermo può durare
  circa dieci minuti, non soltanto qualche secondo.
- Tutti i **sei journal della copia offline** superano `PRAGMA integrity_check`
  in sola lettura. Le verifiche pesanti sono avvenute esclusivamente sulla copia.

Queste sono verifiche dell'autore, non QA indipendente o validazione di profitto.
Non garantiscono l'assenza di ritardi sotto qualsiasi carico futuro. I fill e le
opportunità già perse restano nello storico originale, senza correzioni a posteriori.

## Incidente durante la diagnostica

Alle **15:54:00 UTC** la copia coerente del witness live ha mantenuto troppo a
lungo una transazione di lettura sul suo journal SQLite in modalità DELETE.
L'operazione era in sola lettura ma ha comunque impedito il commit del writer:
`Witness.append -> sqlite3.OperationalError: database is locked`. È un errore
della procedura diagnostica dell'autore, non un movimento del mercato.

Il lock è stato rilasciato al termine della copia. Il riavvio automatico ha però
incontrato il limite RAM di 512 MiB durante la verifica dell'intero storico:
il kernel ha registrato OOM nel cgroup della coppia, per esempio alle 15:57:32,
16:01:07 e 16:04:36 UTC. Il nuovo pacchetto non era ancora applicato. Il servizio
precedente è quindi in riavvio, con proiezione BLOCKED, non healthy.

Tutti i quattro conti risultano flat e senza intent pendenti, con 2 fill nei
due scenari primari e 4 nei due stress. Non sono stati cancellati, ripristinati
o riscritti ledger, equity o fill. La verifica completa della copia è riuscita
con 2 GiB e stati identici; la consegna manuale del candidato include il recupero
del runner con memoria sufficiente. Gli altri dodici servizi rimangono in
esecuzione. I futuri backup del witness in modalità DELETE devono essere presi
solo a writer fermo: non mantenere transazioni RO lunghe sul live.

## Consegna

Manifest `e08c51daef896bbaeb16d3b34eb6c52b57b1d07852eeba442ecd55060466199a`.
Il comando senza flag operativo ha verificato il pacchetto e confermato
`activated=false`. I due servizi da riavviare sono il runner della coppia e il
collector pubblico scalping condiviso. Nessun riavvio della UI o degli altri
esecutori. Backup a freddo, container precedenti e runtime restano conservati.

La verifica dell'intero storico rende il riavvio più lungo di un semplice
restart di processo. Se manca un punto della griglia, la finestra di 289 punti
contigui dovrà ricostruirsi, potenzialmente per circa 24 ore: non viene aggirata.
Guida e rollback: `docs/BTC_INTRADAY_PAIR_LATENCY_V1.md`.

Evidenze private: `audit-evidence/intraday-pair-latency-20261024/`.
Schede: `work-card-48fa3a4c-3c6b-44e0-8d70-09bad0722efd` e
`work-card-c1536bad-3108-40a4-9819-7ba31f89b4ba`.
