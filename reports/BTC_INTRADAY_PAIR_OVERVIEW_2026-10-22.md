# Confronto generale: integrazione dei due nuovi conti BTC intraday

22 ottobre 2026. Corretto il completamento mancante in `/v13_variants`: la pagina dedicata esisteva, ma le due nuove strategie non erano incluse nella panoramica generale.

Ora sono visibili **sette conti**: V13 originale, FAST, HALF, V13 + M1, BTC intraday iniziale, BTC intraday SHORT controllo e BTC intraday LONG + SHORT. I due nuovi conti hanno scheda, riga della tabella, legenda, curva e link alla propria pagina dedicata. Capitale iniziale, inizio del confronto, raccolta causale, saldo, posizione e numero di fill rimangono espliciti.

La modalità predefinita e i filtri 24 ore / 7 giorni / tutto lo storico mantengono le equity effettive in USDT virtuali. Ogni nuova curva usa soltanto osservazioni realmente pubblicate, senza storico V13 ereditato. La modalità rendimento comune richiede ora copertura verificabile di tutti e sette i conti, successiva all’inizio comune dei nuovi bracci. Una proiezione assente, scaduta, con identità errata o funding incompleto non viene sostituita con zero e non produce un confronto parziale. La modalità percentuale V13 continua a includere soltanto i quattro conti V13.

## Verifica

Prova browser sulla UI effettivamente servita passata su desktop e mobile: sette schede, righe e voci di legenda; equity coincidenti con la proiezione; entrambi i nuovi colori nel grafico; filtri periodo in USDT; link alla pagina dedicata funzionante. Provati in sola risposta browser una finestra condivisa a sette conti e i quattro errori dichiarati, senza alterare dati o processi. Hover e nomi delle curve verificati. Pagine di dettaglio FAST, HALF e M1 conservate. Nessun errore JavaScript e nessuna richiesta esterna o richiesta di scrittura.

Controllo sintattico JavaScript e `git diff --check` passati. Tutti gli undici container conservano identità, immagine, data di avvio e contatori di riavvio; nessun servizio è stato riavviato. Nessuna modifica a policy, conti, collector, monitor, ricevute o package della strategia qualificata. Minimi KuCoin ancora UNKNOWN.

I due asset preesistenti della panoramica erano locali non tracciati: vengono inclusi in Git per rendere consegnabile questa integrazione, conservando il comportamento preesistente. Il delta rispetto alla UI realmente presente prima dell’intervento è conservato separatamente nelle evidenze; le altre modifiche locali rimangono intatte. Nessun merge su main e nessuna QA indipendente dichiarata.

Evidenze private: `audit-evidence/btc-pair-overview-20261022/`, comprese schermate, report browser, preimmagini e patch circoscritta. Schede: `work-card-5742c933-3141-4f72-ba60-c77bdc2812c0` (UI), `work-card-4424a50a-6deb-4ff4-891b-21d7ec9b6ab4` (verifica), `work-card-b48056d2-4d39-43f5-8417-c4d4c709d2b0` (consegna). UI in Test per il riscontro dell’operatore; completamento tecnico verificato.
