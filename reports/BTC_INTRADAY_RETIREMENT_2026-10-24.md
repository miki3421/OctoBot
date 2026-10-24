# Ritiro ordinato del conto BTC intraday precedente

Richiesta esplicita del 24 ottobre 2026: ritirare soltanto
`octobot-btc-intraday-paper`, conservando storico e dati, aggiornando UI e
monitoraggio. **Market observer, collector scalping, nuova coppia intraday,
Originale, FAST, HALF, M1 e VM OPS rimangono attivi.**

## Candidato qualificato

Manifest `c544f393dd71ad6b63ae5ba2507627479dd24106e930f531cf5a85b54488c8b0`.
Il comando senza riferimento operatore verifica soltanto il pacchetto. Il
riferimento richiesto per il passaggio manuale è la richiesta dell'operatore
riportata sopra; non autorizza ribilanciamenti M1 o operazioni reali.

Prima di fermare il conto, entrambi gli scenari devono essere flat, senza intent
pendenti e senza funding da regolare. Si conserva il container, disabilitandone
il restart automatico, e si copia a freddo l'intero stato, incluso il witness.
Nessuna copia online a transazione lunga sul witness DELETE. La copia grezza
resta intatta; recupero e integrity check avvengono solo su un'altra copia privata.

Il sigillo di ritiro è root-owned e non modificabile dal processo del conto.
Vincola account, container, timestamp, stato flat/regolato e hash dell'ultima
proiezione. UI e monitor continuano a verificare quel sigillo: dati vecchi sono
ammessi solo come archivio esplicito, mai come osservazioni correnti. Una
proiezione cambiata, un sigillo non valido o il riavvio del servizio ritirato
restano errori. Nessun grant di esecuzione deriva dal sigillo.

La UI mantiene grafico e operazioni nella pagina esistente, etichettata come
archivio. Il confronto corrente comprende sei conti attivi. Lo storico completo
può mostrare la curva del conto ritirato, che termina all'ultima osservazione:
nessun prolungamento piatto, saldo azzerato o rendimento retroattivo. Il monitor
conserva tutti gli altri controlli e smette soltanto di aspettarsi heartbeat dal
conto esplicitamente ritirato. La mail usa gli stessi avvisi diagnostici esistenti.

## Verifiche e preservazione del lavoro locale

- **47 test mirati passati**, inclusi vincoli di custodia, modifica del saldo,
  stato aperto/pendente o non regolato, marker futuro/di altro account, runtime
  ritirato ripartito, regressioni del monitor e route GET-only della UI.
- Browser su dati catturati offline: sei schede attive, archivio distinto,
  finestra comune senza conto ritirato, curva storica disponibile, filtri
  temporali e pagina archivio desktop/mobile senza errori JavaScript.
- La nuova versione del renderer parte dal renderer già pubblicato, SHA
  `f95cdc3acfdca1b065d7b782f66be5c1ec4f06fa65463ffc4574a14ce5bb42ba`.
  Il vecchio file locale resta invariato; le modifiche locali non correlate
  rimangono fuori dal commit. I template di distribuzione sono fissati nel
  pacchetto nella radice canonica, includendo la baseline UI già esistente.
- Monitor precedente conservato, nuovo runtime separato e service unit
  verificata. L'aggiornamento non cambia soglie, strategia, ordini o credenziali.

Il passaggio operativo ferma il solo conto precedente, aggiorna la configurazione
del monitor e riavvia la sola dashboard per caricare la vista Python. Il timer
di monitoraggio viene brevemente sospeso e ripreso per evitare un campione
intermedio incoerente. L'accettazione dell'operatore rimane distinta dalle prove
dell'autore; nessuna QA indipendente è dichiarata.

## Consegna operativa verificata

Ritiro sigillato il **24 ottobre alle 17:27:14 UTC, 19:27 italiane**. Il conto
principale e lo stress erano flat e senza intent; nessuna operazione è stata
aggiunta per chiuderli. Il container è conservato fermo, con `restart=no`.
Sono rimasti **12 container attivi e healthy**. Tranne la dashboard riavviata,
gli altri undici mantengono gli stessi ID, avvio e contatori di restart; fra
questi il market observer e i collector condivisi. Le VM OPS sono inalterate.

Saldo principale finale **9.998,6320686 USDT**, P/L **−1,3679314 USDT**, **6 fill**;
saldo stress indipendente **9.996,7102308 USDT**, anch'esso con 6 fill. I due ledger
e il witness sono conservati integralmente. I tre journal della seconda copia
del backup a freddo superano `PRAGMA integrity_check` RO; la copia grezza rimane
separata e intatta. Stati e proiezione del conto ritirato restano identici dopo
la pubblicazione dell'archivio.

Browser live desktop/mobile: sei schede attive, archivio distinto e consultabile,
finestra comune corrente senza conto ritirato, curva storica conservata e nessun
errore JavaScript. Il riferimento cache del solo script archivio è stato
aggiornato dopo la distribuzione, senza toccare il sigillo o i dati. La vista
API espone `RETIRED`, `read_only_archive=true` e l'età reale dei dati; non presenta
l'archivio come un feed fresco. Il monitor v5 riconosce `status=retired`, verifica
archivio e container fermo, senza avvisi di heartbeat scaduto per questo conto.

La preparazione della ripresa M1 v2 mantiene il manifest già autorizzato
`b454f2d0…` invariato. Un preflight ha rilevato che i link degli asset UI usano
il percorso container `/workspace`: l'orchestratore crea soltanto durante il
passaggio un alias host temporaneo verso il checkout canonico, senza sostituire
percorsi esistenti, e rimuove solo l'alias che ha creato. Otto test della ripresa
verificano anche conflitti e cleanup. I due file UI del pacchetto approvato
risolvono così ai target corretti; nessun cambio di quel pacchetto, esecuzione M1
anticipata o approvazione economica è avvenuto.

Evidenze private: `audit-evidence/btc-legacy-retirement-20261024/`.
Schede `work-card-c75e2256-8f76-400e-ba13-9e742c1a416b` e
`work-card-10720850-e31f-4edc-85f9-ba981f01dc2e`.
