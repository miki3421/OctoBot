# BTC intraday — revisione dei limiti di frequenza

17 ottobre 2026. Candidato v2 **non attivato**, stesso esperimento e conto proposti.

Rimossi su richiesta utente:

- massimo giornaliero di opportunità/ingressi, senza sostituirlo con un cap di due;
- cooldown dopo chiusura, veto o tentativo mancato.

Con conto flat e nessun ingresso/uscita pendente, il successivo slot M1 valido può
aprire una nuova posizione, anche se il segnale ribassista persiste. Ogni slot resta
univoco e non può essere eseguito due volte. I tentativi respinti rimangono nel
registro, senza consumare quote o imporre attese.

Restano una sola posizione alla volta, griglia M1 di cinque minuti, esposizione
massima 10%, limite di perdita giornaliera 2%, drawdown 10%, stop/take profit e
orizzonte massimo sei ore. Costi, funding, causalità e regole sui dati mancanti
sono identici al candidato v1. Questi guard non sono stati rimossi dalla richiesta
contestuale sui limiti di frequenza e restano proposte inerti per il nuovo conto.

Contratto aggiornato: `docs/research-protocols/btc-intraday-m1-l5-paper-candidate-v2.json`.
Protocollo: `docs/BTC_INTRADAY_M1_L5_PROTOCOL_CANDIDATE_V2.md`.
La versione v1 e le sue evidenze sono conservate, nessuna riscrittura dello storico.
Nessun conto, grant, policy runtime, servizio, ordine o modifica a Originale, FAST,
HALF, M1 paper e osservazione M1. Il conto BTC separato resta da implementare.

Verifiche documentali: confronto v1/v2, pin del predecessore, lineage ricalcolata,
sezioni scientifiche/contabili e guard di rischio immutati; nessuna nuova prova
runtime o lettura di outcome economici. Il valore `null` dei massimi giornalieri
significa assenza di cap, mentre il cooldown è esplicitamente zero.

Schedine revisione: `34617df1`, `e4c2388d`, `5bd4e669`. Le attività successive
su join causale, simulatore, QA e riesame restano To-do e useranno il candidato v2.

Lineage v2: `b4753f728549429c813d117af29a204ef2a80941c9066acc8807f4edf496c88e`.
SHA-256 contratto v2: `bbc19094ac23b8b13a0d82919802f2ede3787add5eda2e13f0f2d8489861493b`.
