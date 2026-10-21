# Monitor intraday — correzione del riferimento temporale

**21 ottobre 2026: monitor v3 attivato manualmente su autorizzazione esplicita
dell’utente.** Primo avvio completato alle 08:35:52 UTC (10:35:52 italiane);
ciclo naturale delle 08:40 UTC verificato con successo. Strategie, conti, collector, soglie, grant
e notificatore SMTP non sono modificati. Il bundle v2 resta disponibile per rollback.

## Diagnosi ed evidenza

La verifica precedente ha rilevato sei campioni
`PAPER_ACCOUNT_UNAVAILABLE:intraday`, rientrati al ciclo successivo:
20 ottobre 11:30 e 14:55 UTC; 21 ottobre 03:00, 04:25, 04:45 e 07:00 UTC.
I dati conservati non includono il JSON letto o il motivo preciso del rifiuto:
**non è possibile dimostrare individualmente la causa di tutti e sei**.
Nessun riavvio aggiuntivo del conto risulta associato a questi campioni.

Il difetto riprodotto nel codice v2 è il confronto con l'ora iniziale
di `collect()`, inoltrata a `read_paper_account()`. Durante i controlli
precedenti, il produttore può pubblicare atomicamente un nuovo file.
Una pubblicazione successiva all'inizio del campione ma precedente alla fine
della lettura viene così rifiutata come futura, anche se causalmente valida.

Esempio deterministico: inizio campione T, pubblicazione T+1, lettura conclusa
T+2. Il v2 restituisce `unavailable`; il candidato restituisce `healthy`.
Lo stesso test end-to-end di `collect()` fallisce sul v2 originale e passa
sulla patch. Questo dimostra il meccanismo e la correzione, non attribuisce
retroattivamente prove mancanti ai sei episodi.

## Modifica limitata al monitor

- Ogni lettura paper usa il clock rilevato subito dopo la lettura completa
  del file; `collect()` non inoltra più il proprio timestamp iniziale.
- Una regressione dell'orologio durante la lettura causa un rifiuto.
- Timestamp realmente successivi alla fine della lettura restano rifiutati:
  nessuna tolleranza temporale aggiunta.
- Custodia, `O_NOFOLLOW`, UID, permessi, dimensione massima, soglie di
  freschezza, stato contabile e allarmi immediati restano verificati.
- La telemetria espone inizio/fine lettura, riferimento di validazione e
  codici distinti per I/O, JSON, schema, custodia, clock e scope. Non registra
  percorsi privati, JSON grezzo o testo arbitrario delle eccezioni.

La funzione è condivisa dai lettori M1 e intraday; cambia solo la loro
osservazione passiva. Nessun codice delle strategie, esecutore o ledger è
stato modificato. Il formato degli alert e la deduplicazione mail restano
compatibili con il notificatore v2.

## Verifiche effettuate

**40 test passati:** 32 su monitor/FAST/HALF/conti e 8 sul notificatore con SMTP
simulato. Coperti pubblicazione durante il campione, futuro reale di heartbeat
o market, clock regressivo, dati scaduti e soglie esatte, permessi/UID,
symlink, file mancante, JSON/schema/scope invalidi, dimensione massima,
contabilità incompleta e halt reali. Nessuna mail di prova inviata.

Comandi eseguiti dal repository canonico:

```sh
python3 -m unittest discover -s tests/unit_tests/ai_strategy_lab -p 'test_lab_*monitor.py' -v
python3 -m unittest discover -s tests/unit_tests/ai_strategy_lab -p test_lab_mail_alerts.py -v
```

Il candidato è stato inoltre eseguito sullo stesso host leggendo le proiezioni
correnti, ma con output e database di telemetria **isolati** dalle directory
del monitor operativo. Esito: nessun alert, intraday healthy, riferimento
uguale al clock di fine lettura. Questa prova non è un deploy né l'accettazione
live. `systemd-analyze verify` accetta l'unità candidata; nessun servizio
era stato riavviato durante quella prova. Nessuna scansione di integrità sui journal live.

## Pacchetto congelato e procedura di attivazione

Pacchetto locale nell'archivio delle evidenze:

```text
/var/lib/libvirt/trading-ai-lab/auto_trading_sys/audit-evidence/intraday-monitor-fix-20261021/candidate/
```

Contiene `monitor.py`, `config.json`, `trading-lab-resource-monitor.service`
e `files.sha256`. La configurazione è identica al v2; l'unità candidata
cambia soltanto `WorkingDirectory` da v2 a v3.

| Artefatto | SHA-256 |
| --- | --- |
| Codice candidato | `bc0fc6383fd1a04a321a85de459356c9b2177d9626b8e8a9108e0feddd9d2d1b` |
| Configurazione invariata | `5e561d1700a90012a3d3e98c9ce679799a1d4c4019acca07a295d3b677f75fdd` |
| Unità candidata | `99caa4979f2dc6b0d2f2f969e5131d320f74e9851e10d3f8a254df7c6b3759ec` |
| Manifest `files.sha256` | `e42cea7dff830bb4fa6250207ed89fb218596a5db341de38dc4d6a6fd6632c18` |
| Codice live v2, atteso prima del cambio | `697678a89e80161cd851b475b04ddfced776ea8c350b7ee652ad3ea44b2e9ec2` |
| Unità live attesa prima del cambio | `9bbaaab8b233adb0cd1d232b4b05e2eb1efa508014183306793c31d625b606d7` |

La [regola MMTech pubblicata il 19 ottobre](https://control-plane.mmtech.website/v1/kb/documents/company-kb-abffa3c0-0268-4e0d-9177-ef4e0b04bfef)
richiede: “The operator performs the manual deploy and acceptance.”
L'attivazione e l'accettazione non sono sostituite dai test locali o dal push.
In questa sessione l’utente ha delegato espressamente l’attivazione manuale
del solo monitor v3 e la verifica. L’accettazione finale dell’operatore resta
distinta dal collaudo tecnico svolto dall’autore.

Procedura per il solo monitor, da eseguire al gate manuale:

1. Verificare gli hash attesi di codice/unità live e del manifest candidato;
   verificare `sha256sum --check files.sha256` nella directory candidata.
   Fermarsi in caso di drift rispetto alla tabella.
2. Conservare l'unità live in un backup root-owned, senza modificare il bundle
   `/opt/trading-lab-resource-monitor-v2` e il database di telemetria esistente.
3. Installare i quattro file candidati nella nuova directory root-owned
   `/opt/trading-lab-resource-monitor-v3`, verificando nuovamente gli hash.
   Nessuna installazione di pacchetti o acquisizione Internet necessaria.
4. Sospendere brevemente il solo timer monitor e attendere/terminare l'eventuale
   oneshot corrente; installare l'unità candidata in
   `/etc/systemd/system/trading-lab-resource-monitor.service`.
   Non fermare notificatore, container, collector o conti.
5. Eseguire `systemctl daemon-reload`, avviare il singolo servizio monitor e
   ripristinare il timer. Se l'avvio fallisce, ripristinare subito unità v2,
   daemon-reload, servizio e timer, preservando gli errori.
6. Collaudo post-deploy con responsabilità QA distinta dai test d'autore:
   verificare hash/WorkingDirectory effettivi, risultato del servizio,
   nuovi campi diagnostici, freschezza dello status e il successivo ciclo
   naturale. Verificare notificatore e conti senza inviare falsi alert.
7. L'operatore accetta l'esito; solo allora la scheda produzione può diventare
   Done. Un periodo senza episodi non prova retroattivamente la causa dei sei
   alert: i nuovi codici servono anche alla diagnosi di eventuali ricorrenze.

Rollback: ripristinare l'unità salvata con WorkingDirectory v2, daemon-reload,
avvio del monitor e riattivazione del timer; nessun reset di telemetria, mail
dedup o journal paper. Entrambe le versioni usano la stessa configurazione
e gli stessi percorsi di output operativi.

## Tracciamento e limiti della consegna

- Produzione: `work-card-6b5dba12-d761-4d92-866a-bc727e3ceeee`.
- Test locali: `work-card-2e98351a-24c9-4048-8c8f-3887a22531f7`.
- Preparazione/consegna: `work-card-29339115-6b2b-4898-8c4b-bf1ea2e74931`.

Repository canonico unico, nessun worktree/clone aggiuntivo. Base effettiva
`412176d4077c2247257a3c7311771866798d13ba`, ramo dedicato
`codex/intraday-monitor-clock-20261021`. Il monitor era non tracciato su questa
base: Git registra il file completo; il confronto con il live v2 riguarda
solo i blocchi modificati descritti sopra. La base esistente e il lavoro
locale estraneo sono conservati, senza merge a main o riscrittura della storia.
Test d'autore SINGLE_AGENT; nessuna review indipendente o accettazione
finale dell’utente rivendicata. Fonte operativa della diagnosi: bundle live v2
verificato per hash, non stato presunto del branch.


## Attivazione autorizzata e verifiche operative

Evidenze di questa fase, separate dal pacchetto precedente immutabile:
`audit-evidence/intraday-monitor-activation-20261021/` nella radice del workspace.

- Hash iniziali e dei quattro artefatti candidati verificati; backup dell’unità
  v2 conservato prima del cambio. Nessun drift rilevato.
- Installato esattamente il bundle congelato in `/opt/trading-lab-resource-monitor-v3`.
  Sospeso brevemente solo il timer monitor, sostituita la sola unità prevista,
  ricaricato systemd, avviato il monitor e ripristinato il timer.
- Primo campione v3: 08:35:51.655182 UTC; servizio terminato con successo
  alle 08:35:52 UTC, codice zero. M1 e intraday healthy, nessun alert;
  `validation_at == read_completed_at` per entrambi, senza clock regressivo.
- Notificatore naturale delle 08:36 UTC riuscito: `DEDUPLICATO`, zero alert
  attivi; nessuna mail di prova. Configurazione SMTP e deduplicazione conservate.
- Ciclo naturale avviato alle 08:40:04 UTC, terminato alle 08:40:05 UTC:
  codice zero, nuovi timestamp diagnostici coerenti, M1 e intraday healthy,
  zero alert e tutti i collector freschi. Il timer mantiene la cadenza di cinque minuti.
- Confronto dei dieci container prima/dopo: ID, immagine, avvio, stato,
  health e numero di riavvii identici. Nessun conto, collector o strategia riavviato.
- Hash di configurazione, timer, notificatore e bundle v2 identici al baseline;
  pagine V13, confronto e BTC intraday raggiungibili con HTTP 200.
- Telemetria e stato di deduplicazione riutilizzati senza reset; nessuna
  scansione pesante o scrittura ai journal paper.

Le verifiche post-deploy sono una fase tecnica separata dai test offline,
ma sono eseguite dallo stesso agente: non costituiscono QA indipendente.
La scheda produzione resta in Test dopo la verifica tecnica fino
all’accettazione finale dell’utente; nessun merge a main eseguito.
