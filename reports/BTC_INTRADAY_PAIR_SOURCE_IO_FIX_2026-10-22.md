# Coppia BTC intraday — corretti i riavvii da lettura del book

22 ottobre 2026. **Correzione I/O applicata al solo runner della coppia; raccolta conservata e strategie invariate.**

## Causa e correzione

I tre errori del 22 ottobre seguono esattamente le tre riconnessioni interne del collector alle 02:21:34, 06:15:43 e 06:53:44 UTC, dopo `book stale for 5.006 seconds`. Quando l’ultimo writer SQLite chiude, vengono rimossi i sidecar WAL/SHM. Il reader montato RO non può ricrearli: SQLite 3.46.1 restituisce `SQLITE_CANTOPEN` (14) e prima questo errore terminava l’intero runner.

Il caso è stato riprodotto offline con l’immagine effettiva, writer UID 1000 e reader UID 30943 su mount RO. Il nuovo adattatore esterno attende e ritenta ogni 250 ms solo per accesso/lock transitori. Mantiene lo stesso cursore e lascia proseguire i normali heartbeat e controlli protettivi. La prova di chiusura/riapertura conferma attesa e ripresa nello stesso processo, senza saltare il primo nuovo record. Non sono state estese le soglie di freschezza e non è stato usato `immutable` o accesso RW alla sorgente. Corruzione, sostituzione, regressione, backlog e guasti dello stato restano bloccanti.

## Rilascio e conservazione

Sorgente tecnica `f7698789b31474f8dce8a7c5c30bc38e172bee48`, branch `codex/btc-pair-source-io-fix-20261022`. Nuovo runtime separato, codice e configurazioni fissati per hash. Il package qualificato `intraday_pair/` resta identico, inclusi motore, protocollo, reader originale e witness.

La ricevuta originale e il digest `89835413fa5587f8e307fe0b48e9569a0fb4fd97f48d3d6fb65374eeef16c30b` non sono stati modificati. Una ricevuta root-owned di continuazione I/O autorizza soltanto i due nuovi file, gli stessi percorsi e la configurazione precedente. Nessuna inizializzazione, nuovo esperimento, reset di rischio o grant operativo. T0/T1 invariati, minimi KuCoin ancora UNKNOWN.

Arrestato soltanto il vecchio container della coppia, conservato fermo come `octobot-btc-intraday-pair-pre-io-v2-20261022`, insieme ai suoi log e al runtime precedente. Stato copiato a freddo in 3,95 secondi. Il nuovo container è partito alle **07:52:26 UTC** con gli stessi ledger e proiezione. Gli altri dieci container conservano ID, immagine, avvio e contatore di riavvio; collector, monitor, notificatore, UI ed esecutori precedenti non sono stati riavviati o modificati.

## Verifica

- 14 nuovi test I/O/continuazione, 10 regressioni di attivazione e 37 del runner: **61 test passati**, più la riproduzione operativa offline con stesso SQLite, UID e mount RO.
- Copia grezza dello stato fermo conservata. Poiché l’arresto può lasciare transazioni interrotte, il normale recupero SQLite è stato eseguito soltanto su una seconda copia privata; tutte le sei copie recuperate superano poi `integrity_check` in sola lettura. Nessun recupero manuale o controllo pesante su sorgente/ledger live.
- Cinque identità di database confrontate esattamente; ancore precedenti di eventi/input presenti in tutti i sei journal, incluse le ricevute. Equity, quantità, costi, realizzato, high-water e stato di rischio identici alla copia precedente. I primi 124 punti della griglia sono invariati.
- La griglia è avanzata a **125 punti validi contigui su 289**, senza buchi. Entrambi i conti restano flat a 10.000 USDT virtuali, zero fill. Input nuovi con cursore e hash uguali in tutti i quattro scenari. Lettore disponibile; nuovo container healthy e zero riavvii al readback.
- Campione naturale del monitor alle **07:55:06 UTC**: healthy, nessun alert. Nessuna email di prova forzata. La causa è verificata e il comportamento di recupero è provato; ciò non equivale a una garanzia contro qualsiasi futuro tipo di guasto.

Se non intervengono buchi, la finestra si completa il **22 ottobre alle 23:35 italiane**, con prima operazione possibile dalle **23:40**, soltanto in presenza di segnale e di tutti i gate. Nessuna operazione retroattiva. Evidenze private in `audit-evidence/btc-pair-source-io-fix-20261022/`.

Schede: `work-card-dd0a1084-730e-4e5c-9718-a9db566a3014` (correzione), `work-card-6716e4d1-18e9-4a0f-ad36-b5598b1908c1` (test), `work-card-7e3d059b-288d-4b3f-9eab-9b5b32a89649` (rilascio). Correzione tecnicamente completata e in Test per il riscontro operatore; nessuna QA indipendente o approvazione scientifica dichiarata. Rollback documentato in `docs/BTC_INTRADAY_PAIR_IO_CONTINUATION_V2.md`, conservando anche gli eventi aggiunti dopo il rilascio.
