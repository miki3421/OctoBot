# BTC intraday SHORT / LONG + SHORT — avvio del confronto

21 ottobre 2026. **ATTIVO, in raccolta prospettica.** Autorizzazione manuale dell’utente acquisita per i soli due nuovi conti paper, UI e monitoraggio. Nessun ordine reale, credenziale exchange, grant operativo o cambiamento ai conti precedenti.

## Consegna

- Pagina `/btc_intraday_pair`, raggiungibile dalla sidebar: due conti, equity effettiva in USDT virtuali, raccolta comune, segnali, operazioni con effetto LONG/SHORT e scenari stress distinti. Verificata su desktop e mobile, compresi errori, dati scaduti e disponibilità del menu.
- Controllo `btc-intraday-short-control-v1` e candidato `btc-intraday-long-short-v1`: 10.000 USDT virtuali ciascuno, flat, zero fill iniziali, nessun rendimento ereditato. Il conto intraday precedente rimane distinto e invariato.
- Servizio `octobot-btc-intraday-pair` healthy: nessuna rete, filesystem radice e sorgenti in sola lettura; scrittura limitata al nuovo stato e alla sua proiezione pubblica. Nessun volume anonimo. Pacchetto della strategia identico al bundle già qualificato; wrapper di avvio e pubblicazione separato e fissato per hash nella ricevuta.
- Monitor v4 attivo ogni cinque minuti; controllo di freschezza, contabilità, integrità e allineamento dei quattro scenari. Riutilizza gli alert mail esistenti e il loro stato, senza cambiare credenziali, destinatari o frequenze. Primo campione manuale e ciclo naturale delle 21:35 UTC senza alert. Notificatore verificato al successivo ciclo ordinario, senza email di prova forzata.

## Calendario

Inizio comune **22 ottobre 2026, 00:00 UTC** (02:00 italiane). Termine **20 gennaio 2027, 00:00 UTC**. La raccolta è già in corso dal 21 ottobre alle 21:31 UTC; primo punto valido alle 21:35 UTC.

Servono 289 punti contigui di cinque minuti su tutti i 18 simboli. Senza buchi, il primo completamento è previsto non prima del **22 ottobre alle 21:35 UTC**. Le opportunità precedenti non vengono recuperate né inventate. Un servizio healthy e una curva iniziale piatta confermano l’avvio tecnico, non una valutazione positiva della strategia.

## Verifiche ed evidenze

87 test mirati passati: 10 nuovi controlli di attivazione/proiezione, 37 regressioni del runner, 32 del monitor e 8 del notificatore. Le prove browser comprendono risposte sintetiche dichiarate; il successivo controllo della pagina effettivamente servita è passato senza errori JavaScript o richieste esterne. Nove pagine/API nuove e preesistenti rispondono HTTP 200.

Sei copie fredde dei database iniziali superano `integrity_check`; nessuna scansione pesante dei ledger o database sorgente attivi. Riavvio del solo nuovo runner verificato senza reset: identità, ricevuta, orizzonte e saldi conservati, cursori in avanzamento. Primo slot reale condiviso registrato come `PRESTART_WARMUP`, senza operazioni.

Confermati invariati 352 file dei runtime protetti precedenti. Tutti i nove collector/esecutori preesistenti mantengono ID, immagine, avvio e contatore di riavvio; è stata ricaricata soltanto l’interfaccia condivisa `octobot-local`. Tutti gli undici container del laboratorio risultano healthy.

Sorgente di rilascio `ec32563d3c7ed060746fc4692411af278e5116e1`, pubblicata sul branch `codex/btc-intraday-pair-activation-20261021`. Modifiche estranee nella working copy conservate; nel controller è stato committato soltanto il nuovo import e le due route. Nessun merge su main e nessuna QA indipendente dichiarata. Evidenze private conservate in `audit-evidence/btc-intraday-pair-activation-20261021/`; runbook in `docs/BTC_INTRADAY_PAIR_ACTIVATION_V1.md`.

## Cosa resta

La preparazione e l’avvio tecnico sono completati. Restano la raccolta automatica, l’osservazione futura e l’accettazione della UI da parte dell’operatore. Qualità della copertura e crescita dei nuovi archivi vanno seguite nei normali controlli: non viene promessa capacità per 90 giorni sulla sola misura iniziale. La valutazione scientifica rimane `UNASSESSED`; i minimi reali KuCoin rimangono `UNKNOWN` e l’operatività fedele all’exchange resta bloccata.

Schede: `work-card-8fd80afc-9599-40ca-abf9-68d2d2d082a9` (attivazione), `work-card-f96c38d0-c015-4ecc-880f-769ccc48f055` (UI), `work-card-0ad819dc-076f-4cba-888a-4266e41f9d93` (monitor), `work-card-79f8f65b-8eb4-4659-a7b6-990b89002850` (verifiche), `work-card-aef0dcc2-df33-4f8f-ba4f-99d0acee29ae` (consegna).
