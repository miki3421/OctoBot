---
name: auto-trading-operations
description: Operate, extend, review, test, or deploy the local OctoBot guarded-AI paper-trading project. Use for any change to the custom LLM strategy, deterministic risk controls, SQLite AI-decision journal, local web UI, local profile, Ollama connectivity, KuCoin paper-trading configuration, Docker deployment, or project requirements in this repository.
---

# Auto Trading Operations

Mantieni questo fork di OctoBot come piattaforma locale, auditabile e solo di
paper trading. Dalla radice del workspace leggi `spec.md`, fonte dei requisiti
evolutivi, prima di cambiare comportamento o architettura.

## Contesto e confini

- Lavora nel fork `octobot-source/`, sul branch di lavoro corrente; non trattare
  la radice del workspace come sostituto del repository Git.
- Le estensioni principali vivono in `packages/tentacles/`; il profilo locale è
  `packages/tentacles/profiles/local_ai_trading/`.
- Non abilitare trading reale, API key reali, operazioni di deposito/prelievo o
  una coppia/exchange aggiuntivi senza richiesta esplicita dell'utente.
- Mantieni l'istanza iniziale limitata a KuCoin Futures, `BTC/USDT:USDT` e
  paper trading. Un `BUY` apre un long e un `SELL` apre uno short soltanto nel
  simulatore futures configurato per questo profilo.
- Il profilo operativo predefinito usa `decision_mode: deterministic_alignment`:
  non deve dipendere da Mac, Ollama, API key o servizi Cloud. Un esperimento LLM
  richiede autorizzazione esplicita, una chiave fuori dal repository e nessun
  segreto nei log o nel journal.

## Invarianti della strategia AI

Le proposte LLM sono non affidabili fino alla validazione. Mantieni il Risk
Guard deterministico e non aggirabile tra la risposta del modello e qualsiasi
segnale/ordine.

- Interroga il modello solo a chiusura candela, una volta ogni almeno 900 s per
  simbolo, con timeout di 60 s, temperatura 0 e JSON validato da schema rigido.
- Passa al modello soltanto indicatori TA disponibili su `15m`, `1h` e `4h`;
  non inventare dati di prezzo, notizie o stato del portafoglio.
- Per un ingresso, conserva almeno: confidenza `0.70`, intensità `0.30`, stop
  loss `<= 2%`, reward/risk `>= 1.5`, orizzonte `<= 1440` minuti e intensità
  inoltrata limitata a `0.55`.
- In qualunque errore (timeout, JSON/schema invalido, dati insufficienti o
  rifiuto del guard) emetti un segnale neutro e non creare ordini.
- Le protezioni operative restano deterministiche per entrambe le direzioni:
  esposizione massima 10%, stop iniziale 1%, attivazione a +1,2%, stop
  protetto a +1%, uscita massima dopo 24 ore e nessun take profit fisso,
  tramite `DailyTradingMode` esclusivamente in paper trading.
- Non eseguire chiamate LLM in backtesting salvo abilitazione esplicita. Usa il
  replay del segnale guardato registrato per lo stesso timestamp di chiusura
  candela; se manca una riga, pubblica un segnale neutro e non creare ordini.

## Audit e dati

- Registra ogni proposta, inclusi `HOLD`, errori e rifiuti, nel journal SQLite
  append-only configurato tramite `AI_DECISIONS_DB_PATH` (predefinito
  `/octobot/user/ai_decisions.sqlite`).
- Conserva input, versione prompt/modello, output strutturato, esito del guard
  e motivazioni. Tratta i dati del journal come sensibili: la UI deve essere
  locale e sola lettura.
- Per collegare ordini, esecuzioni o P&L, progetta una migrazione SQLite
  additiva e retrocompatibile; non riscrivere le righe storiche. Collega i
  record con identificatori stabili e registra gli eventi separatamente quando
  l'ordine o la posizione cambiano stato.
- Verifica una modifica al journal con `PRAGMA integrity_check`, test su DB
  temporaneo e almeno un caso di errore/guard-rifiuto senza ordine.

## Procedura operativa

1. Ispeziona `spec.md`, `git -C octobot-source status --short` e i file
   interessati. Preserva sempre modifiche locali non correlate.
2. Esplicita i limiti di sicurezza impattati e implementa la modifica più
   piccola che soddisfa la richiesta.
3. Aggiorna configurazione, profilo, UI e documentazione solo se il
   comportamento lo richiede; non introdurre dipendenze cloud per comodità.
4. Esegui controlli proporzionati: `git diff --check`, test unitari mirati e,
   per integrazioni, una prova end-to-end esclusivamente in paper trading.
5. Riporta cosa è stato verificato, ciò che non è stato possibile verificare e
   ogni nuova assunzione. Aggiorna `spec.md` se cambia una decisione operativa
   o lo stato del progetto.

## Docker locale

Usa `Dockerfile.local` e `docker-compose.local.yml` per l'immagine di sviluppo.
Mantieni persistenti e fuori dall'immagine i volumi `octobot-local/user`,
`tentacles`, `logs` e `backtesting`. Prima di ricreare un container, verifica
destinazioni, variabili d'ambiente e stato dei dati; non eliminare volumi o
journal senza autorizzazione esplicita.
