# FAST/HALF nel monitor automatico e nelle mail — 14 ottobre 2026

Attivati i controlli del nuovo simulatore `octobot-v13-forks` e dei due conti
FAST/HALF nel monitor esistente, eseguito ogni cinque minuti. Il controllo
comprende ora otto container. Il notificatore usa lo stesso canale SMTP,
destinatario, stato persistente e timer già autorizzati.

## Controlli aggiunti

- Presenza, identità e custodia della proiezione appaiata; heartbeat del
  simulatore recente entro 180 secondi.
- Valorizzazione di ciascun conto recente entro 420 secondi: la normale griglia
  di cinque minuti non produce falsi allarmi dopo tre minuti.
- Simulatore bloccato, funding corrente incompleto e gap di valorizzazione.
- Identità contabile: equity, realizzato, aperto, commissioni, funding e
  contributi per simbolo riconciliano. Valori non finiti, fee negative o equity
  non positiva sono segnalati. Il monitor verifica queste identità dalla
  proiezione, senza accedere o scrivere nei ledger di trading.
- Ultimo slot giornaliero dovuto: mancante, mancato o rifiutato sono esiti
  distinti. Nessun allarme prima della finestra di 120 secondi, prima del primo
  slot previsto o dopo la conclusione ordinaria del periodo sperimentale.
- Scostamento del rischio stimato oltre il 2%, secondo il protocollo esistente.

La precedente osservazione di funding incompleto, già recuperata, resta un
contatore informativo: non genera un allarme permanente. Un debito attuale
continua a essere segnalato. Il monitor non certifica profitto, adeguatezza della
strategia o ammissibilità KuCoin.

## Mail e frequenza

Nuove etichette italiane per gli errori FAST/HALF. Conservati:

- nessuna mail quando lo stato sano rimane invariato;
- primo problema notificato, aggiornamenti distanziati di 30 minuti;
- promemoria dopo 24 ore e avviso di rientro;
- stato persistente e retry dopo errore SMTP;
- retry del controllo Docker e conferma dopo due campioni per la sola
  impossibilità transitoria di leggere i container.

Non è stata inviata una mail sintetica o forzata. Il primo ciclo live del
notificatore ha concluso `DEDUPLICATO`, con zero alert. Le condizioni reali
successive useranno automaticamente il canale esistente.

## Verifica e consegna

**30 test passano**: 10 del monitor esistente, 12 nuovi su conti, tempi, guasti,
slot, contabilità, recupero e SMTP simulato, più 8 del notificatore esistente.
I test includono dati mancanti/manomessi, account scambiato, timestamp futuro,
valorizzazione a cinque minuti, esiti senza fill e fine ordinaria del periodo.
Compilazione Python e `git diff --check` verificati.

Batch composto soltanto da `monitor.py`, configurazione del monitor,
`alerts.py` e rispettivi manifest SHA-256. I due timer sono stati sospesi
brevemente per la sostituzione dei pacchetti e poi ripristinati; unità,
credenziali, stato mail e dati storici non sono stati sostituiti. Le directory
precedenti sono conservate come rollback. Il rollback arresta soltanto i due
timer, ripristina i pacchetti precedenti, rigenera il campione con il monitor
precedente e riavvia i timer; non modifica i conti.

Primo campione live: otto container, FAST/HALF `healthy`, contabilità coerente,
ultimo slot `EXECUTED`, scostamento rischio zero, nessun allarme. Anche il primo
ciclo programmato successivo ha concluso correttamente. Nessun container di
strategia o della UI riavviato. Il monitor resta passivo e non legge credenziali
SMTP; solo il notificatore continua a usare la credenziale systemd esistente.

Evidenze locali: `audit-evidence/fork-monitor-20261014` nel workspace del lab.
Schedine:

- implementazione: `work-card-cace20f4-caf9-46c0-ba0d-b3422ee0e7e9`;
- qualifica: `work-card-90d4c7cf-ead9-46e6-95ec-c5698ac3336a`;
- consegna: `work-card-5340541f-9590-4b7a-936b-ab5f1df0a330`.

Esecuzione SINGLE_AGENT; verifica dell'autore, non review indipendente.
