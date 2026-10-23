# Metriche offline M1 e proposte sul conto esistente

Scheda: `work-card-37c30a2c-ad80-4eda-b1a6-f8bc7d41ab13`.
Verifica: `work-card-3ed5dd7b-b2d4-4791-a643-4e60c20e3bf7`.
Consegna: `work-card-f2ed3248-179d-4649-ac7c-74982722246d`.

L'analizzatore `octobot/ai_strategy_lab/v13_m1_symbol_review.py` produce una
fotografia diagnostica del conto M1 e dell'Originale. Non importa i runner,
non accede alla rete, non crea intent o ordini e non modifica database,
pesi, rischio, scheduling o universo operativo. Funziona con la sola libreria
standard Python, anche come script diretto senza inizializzare OctoBot.

## Input e periodo comune

Preparare una directory di evidenza privata con questi file:

- `snapshots/m1.sqlite` e `snapshots/original.sqlite`: copie SQLite coerenti,
  chiuse e rese non scrivibili. Acquisirle con backup brevi; nessun controllo
  pesante di integrità sul database operativo.
- `snapshots/exact-seed.sqlite`: copia byte per byte del seed immutabile M1.
  Una copia logica SQLite può avere un header differente e non sostituisce
  la verifica SHA-256 del seed originale.
- `snapshot-manifest.json`: SHA-256 delle due copie, tempi di acquisizione,
  dimensioni e risultato dei controlli eseguiti offline.
- `clone-receipt.json`: ricevuta della copia M1 con `economic_t0`, `seed_sha256`
  e `account_id`.
- `market-at-cutoff.json`: record archiviato del mercato esatto usato per
  l'ultimo stato M1, con `record_hash`, mark e book. Non usare il mercato
  corrente al posto di quello della fotografia.

La fine deve coincidere con `m1_last_market_at` di M1 e `last_market_at`
dell'Originale. Non si usa il vecchio `last_success_at` ereditato da M1.
L'analizzatore verifica hash, prefisso ereditato delle operazioni, identità
dell'universo, replay di quantità/costo medio/realizzato/fee, funding,
contributi rispetto al seed e saldo contro l'ultima equity registrata.
Una mancata riconciliazione interrompe la produzione del report.

Il flag filesystem di sola lettura è un contratto dell'input, non una prova
che un percorso arbitrario non sia operativo. Fornire esclusivamente copie
private; non cambiare permessi ai ledger vivi per farli accettare dal tool.

## Esecuzione

Dalla radice del repository, indicando percorsi verso le copie offline:

```bash
python3 -B octobot/ai_strategy_lab/v13_m1_symbol_review.py \
  --input /percorso/evidenza-privata \
  --output /percorso/nuova-consegna/review.json
```

La directory di output deve già esistere. Il comando crea tre file nuovi:
JSON completo, CSV per conto/simbolo/lato/finestra e rapporto Markdown.
Non sovrascrive report già esistenti. Le 18 coin, due conti, due lati e tre
finestre producono 216 righe nel CSV.

## Interpretazione e proposte

Il netto esclude il risultato maturato prima della copia, compreso il P/L
aperto ereditato. Fee sulle inversioni e funding sono attribuiti ai lati
LONG e SHORT separatamente. Un BUY può chiudere uno SHORT profittevole;
un SELL non implica una nuova posizione SHORT.

Le finestre sono dalla copia, ultime 48 ore e ultime 24 ore. I mark
precedenti valgono per massimo 180 secondi; i buchi non vengono interpolati.
Il denominatore del ranking è il nozionale-tempo effettivamente coperto.
Nessun Sharpe annualizzato viene dedotto da questo piccolo campione.

La prima regola esplorativa seleziona al massimo due LONG con risultato
negativo sia dalla copia sia nelle ultime 48 ore, almeno 48 ore di
esposizione LONG e almeno 95% di copertura in entrambe le finestre. Ordina
per intensità di perdita su 1.000 USDT-giorno osservati e propone circa metà
quantità, arrotondando il residuo al passo sintetico. Nessun aumento,
nuovo simbolo o redistribuzione della liquidità. Quantità fuori passo,
profondità insufficiente, minimi sintetici e chiusura totale forzata sono
segnalati invece di inventare un fill.

Questa regola è una proposta esplorativa, non una policy attiva o una
validazione della redditività futura. Gli hash fissano gli input della
diagnosi, non trasformano l'analisi retrospettiva in una preregistrazione.

M1 inverte i LONG detenuti: dimezzarli riduce anche la capacità SHORT
successiva. Prima dell'integrazione operativa occorre una policy esplicita
per i due budget e per evitare riacquisti automatici della quota ridotta.
Non basta sostituire un peso nel report. La decisione deve introdurre una
nuova epoca di manutenzione del solo conto M1, conservandone lo storico e
lasciando l'Originale come riferimento.

La consegna del 23 ottobre è in `reports/V13_M1_SYMBOL_REVIEW_2026-10-23.*`.
L'integrazione in UI è tracciata dalla scheda
`work-card-7756c81b-3d80-48cd-836a-c9fa1dbe4e57`; quella nel conto dalla
`work-card-026c44e2-f248-41ac-aa1f-da68db8f1e98`.

## Verifica mirata

```bash
PYTHONPATH=octobot/ai_strategy_lab python3 -B -m unittest discover \
  -s tests/unit_tests/ai_strategy_lab -p test_v13_m1_symbol_review.py -v
```

I test includono P/L ereditato, inversioni e copertura SHORT, fee, funding,
episodi, buchi temporali, input futuri, saldi alterati, arrotondamenti,
profondità, esportazione e conservazione degli input e dei report.
La consegna corrente è stata eseguita anche con l'immagine locale del lab,
rete disabilitata e copie montate in sola lettura, senza riavviare servizi.

I minimi reali KuCoin restano `UNKNOWN`. I costi indicativi usano il book
archiviato e i minimi del contratto sintetico di ricerca; non attestano
ammissibilità KuCoin né equivalenza a un'esecuzione reale.
