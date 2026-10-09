# Funding, monitoraggio e consolidamento Git — 9 ottobre 2026

Incarico del proprietario: completare i punti 2, 3 e 4 del check giornaliero;
rimandare le mitigazioni Qwen. Modalità SINGLE_AGENT. Schedine:

- Funding: `work-card-507f0fdb-521e-48bc-a9bb-60d17ceeee9d`.
- Monitor: `work-card-355d630a-dd57-407b-af16-c4b29d82da39`.
- Git: `work-card-0e0f311f-550f-467f-8b47-b610f9b61e97`.

## Funding maturato

Nella finestra 8 ottobre 14:10–9 ottobre 06:55 UTC, 5.829 ricevute valide
su 5.829 attese. Acquisite separatamente 29 risposte pubbliche dello storico
KuCoin, con byte, hash e tempi reali di ricezione conservati fuori da Git.
La documentazione ufficiale descrive questa API come storico dei tassi a ogni
regolamento: [Get Public Funding History](https://www.kucoin.com/docs-new/rest/futures-trading/funding-fees/get-public-funding-history).

Tutti i 70 eventi maturati annunciati coincidono con lo storico, senza eventi
inattesi o transizioni discontinue. Sei simboli hanno quattro eventi e 23 ne
hanno due nella finestra. Questo chiude la riconciliazione degli eventi
osservati, non approva un calendario futuro.

Verificati anche 3.625 book dell'archivio di qualifica, senza consultare esiti
scientifici. Per 66/70 eventi è disponibile un midpoint di book ricevuto prima
del regolamento, entro il limite esistente di 900 secondi. Quattro eventi
restano MARK_UNRESOLVED:

| Simbolo | Regolamento UTC |
| --- | --- |
| AAVEUSDT | 8 ottobre 16:00 |
| ASTERUSDT | 8 ottobre 16:00 |
| ASTERUSDT | 8 ottobre 20:00 |
| ARBUSDT | 9 ottobre 00:00 |

Il midpoint è una stima causale dichiarata, non il mark ufficiale dell'exchange.
Non si sostituiscono book posteriori, non si allarga la soglia e non si usa zero
per gli eventi irrisolti. La raccolta di qualifica ogni 15 minuti è al limite
di questa soglia: timestamp e ritardi possono lasciare un evento senza stima.
Il futuro collector A/B/C già predisposto ha frequenza maggiore, ma resta
inattivo fino alle verifiche e alle decisioni di rilascio.

Lo script `scripts/review_v13_funding_marks.py` riproduce la verifica in sola
lettura e mantiene `funding_coverage_certified=false`, `execution_ready=false`.
La scheda funding rimane Test: criteri residui sono copertura senza eventi
irrisolti, calendario revisionato per l'intervallo effettivo e integrazione
operativa finale. Non sono creati calendari, grant, conti o ledger A/B/C.

## Monitor passivo attivo

`trading-lab-resource-monitor.timer` campiona ogni cinque minuti con jitter
massimo di dieci secondi. Il codice e la configurazione installati sono
verificati per SHA-256 prima di ogni esecuzione. Le letture riguardano:

- memoria disponibile, occupazione swap, contatori di swap e pressure stall;
- spazio libero e variazione dell'occupazione di root e disco laboratorio;
- stato/health/restart dei sette container, senza leggere le loro variabili;
- ultimo successo e freschezza market, scalping e paper, con intervallo tra
  successi e recupero dopo una condizione stale osservata.

Le soglie sono allarmi diagnostici: RAM disponibile sotto 10%, disco libero
sotto 15%, swap libero sotto 10%, swap attivo oltre 1 MiB/s. Freschezza: market
30 minuti, book/trade scalping 120 secondi, paper 300 secondi. Non sono limiti
di trading e non inducono arresti o cambi di posizione.

L'archivio separato è `resource-monitor/telemetry.sqlite` sul disco del lab;
`status.json` espone l'ultimo campione. Ogni record è limitato alle metriche;
nessun dato di mercato, credenziale o outcome sigillato viene copiato. Servizio
oneshot, filesystem read-only salvo il proprio archivio, rete IP negata,
segreti locali inaccessibili, RAM massima 128 MiB e quota CPU 10%. Il processo
root mantiene soltanto CAP_DAC_READ_SEARCH per leggere health privati; l'accesso
al socket Docker resta quello del root host. Il monitor non è un nuovo confine
di autorizzazione di trading.

Verifiche: cinque test su swap pieno/attivo, reboot, stale, recupero e crescita;
unità systemd validate; esecuzione reale riuscita e timer attivo; integrità
SQLite ok. Il primo avvio senza capacità di lettura riportava health privati
indisponibili; la configurazione finale li legge e li conserva senza scriverli.
Allarme corrente: swap quasi pieno. Nessuna contesa significativa è dimostrata
dal solo allarme. Non è stata toccata alcuna VM esterna.

Attribuzione iniziale, non misura della crescita: Docker circa 24,33 GB,
log di sistema 2,63 GB, stato/cache Codex 8,66 GB. Non esiste ancora una baseline
coerente per attribuire retroattivamente la differenza di spazio fra i report.
I campioni del monitor permettono da ora di quantificarla.

## Consegna Git isolata

Branch `codex/lab-consolidation-20261009`, checkout distinto dal repository
operativo; base `412176d4077c2247257a3c7311771866798d13ba`.
Selezione esplicita di sorgenti, contratti, UI, unità e test V13/P0/Qwen già
presenti, più monitor e revisione funding di questo incarico. Il manifest
originale del bundle A/B/C v8 resta invariato: questa consegna non sostituisce
gli artefatti già congelati né ne cambia i pin.

Esclusi database, raw, log, tar dei bundle, cataloghi di dati, skill locali e
report storici. Escluse anche modifiche legacy V5/diversified e i documenti
generali HISTORY/implementation plan. Tutte le modifiche del checkout operativo
restano presenti; non è cambiato il suo branch, indice o HEAD.

Verifiche nel checkout isolato, usando immagine locale fissata e rete negata:
118 test A/B/C; 327 test paper/contabilità/grafici/mercato/esposizione, con 58
subtest; 125 test issuer/executor/chiusura amministrativa/risk policy. I test
sono architetturali con fixture, non certificazioni di ammissibilità KuCoin.
Cinque test del monitor sul codice finale. Controllo diff e ricerca di segreti
senza finding nei file selezionati. Nessun download di dipendenze.

Tentativi di test iniziali con Python host senza NumPy, immagine senza pytest
e tmpfs da 256 MiB non erano ambienti adatti. Le prove finali usano dipendenze
già disponibili e tmpfs da 1 GiB; i tentativi falliti sono conservati nelle
evidenze, non reinterpretati come passaggi riusciti.

Commit e ricevuta push sono riportati nella consegna finale e nelle schedine.
Il push della branch non avvia servizi né attiva A/B/C. Il lavoro scientifico
del 16 ottobre e i quattro mark irrisolti rimangono espliciti.
