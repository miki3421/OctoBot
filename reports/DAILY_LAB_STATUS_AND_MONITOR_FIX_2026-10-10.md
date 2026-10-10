# Check giornaliero e correzione avvisi container — 10 ottobre 2026

Rilevazioni iniziali 10:41–10:50 italiane, seguite dalla verifica del monitor
corretto. Schede `work-card-48bbe814-618b-4488-bafc-367c5140f15a` (check) e
`work-card-1b0e37ea-795e-4993-9399-6bf9ccbda83c` (correzione).
Evidenze fuori da Git: `audit-evidence/daily-lab-20261010/` nella radice workspace.

## Stato del laboratorio

| Componente | Evidenza | Esito |
| --- | --- | --- |
| Paper e dashboard | Sette container healthy; pagine paper, grafici, candidate, confronto, BTC e Qwen HTTP 200 | Operativi |
| V13 paper | Equity 10.023,97 USDT alle 10:50:49 italiane, P/L cumulato +23,97; 18 posizioni e 134 fill simulati | +30,54 USDT, +0,306% rispetto all'osservazione di circa 24 ore prima |
| BTC 30/120 | 10/10 slot, integrità ok, zero overdue/conflitti | Raccolta regolare, performance sigillata |
| Qwen BTC shadow | Sette coppie conservate, scheduler false; nuovo slot non registrato | Arresto intenzionale, non nuovo guasto |
| Qwen rapporto V13 | Tentativo odierno completato in 62,269s; testo respinto per unsafe_or_invented_text | UI mostra Risposta respinta; guardia preservata |
| Market observer | Healthy, archivio coerente, ultimo successo recente | Regolare |
| Scalping observer | Connected, book/trade recenti, archivio circa 25,29 GB | Nove traceback/timeout nei log disponibili, con riconnessione; integrità completa solo offline |
| Qualifica A/B/C | 23.798 job validi, 15.960 pending, 58 missing/window_missed | Nessun nuovo mancante rispetto ai 58 del 5 ottobre; esito ancora chiuso fino al 16 ottobre |
| Funding A/B/C | 14.848/14.848 ricevute verificate, zero gap/invalidi, fino alle 10:50 italiane | Continuità, non certificazione di copertura |

Il ledger riconcilia lo snapshot giornaliero, e integrity_check in sola lettura
è ok per execution, authorization, approvals e qualification. L'audit funding
verifica anche integrità e hash. Il database scalping grande non viene sottoposto
a scansione completa sul servizio attivo. Un traceback websocket OctoBot è
presente nei log 24h; il container e i feed risultano recuperati. Nessuna
occorrenza entry_authorization_rejected nei log dei sette container.

Il paper resta RESEARCH_SIMULATION_ONLY, orders_authorized=false e
paper_orders_authorized=true nel solo contratto di simulazione. Minimi reali
KuCoin UNKNOWN; nessun gate o grant modificato. Nessun outcome scientifico
degli esperimenti sigillati è stato letto.

## Swap e storage

Circa 62 GiB RAM, 15 GiB disponibili nella rilevazione; swap totale circa
24 GiB, 12 GiB usati e 11 GiB liberi (arrotondamenti di free). Swappiness 20
e nuova riserva persistente. Non è più swap quasi pieno. L'occupazione è
cresciuta rispetto al giorno prima, senza equivalere da sola a thrashing.
Root: circa 40 GiB liberi, utilizzo 65%; disco lab circa 477 GiB liberi, 39%.
La crescita del disco condiviso richiede attribuzione, non cancellazioni.
La schedina di budget RAM rimane To-do.

## Perché arrivavano molte mail sui container

Il monitor precedente aveva TasksMax=12. Docker CLI, scritto in Go, tenta
talvolta più thread di quelli consentiti al cgroup e abortisce con
runtime/cgo: pthread_create failed. Il monitor registrava CONTAINER_STATE_UNAVAILABLE,
poi il campione successivo era regolare: si generavano coppie Problema/Recupero.
Non era evidenza di arresti dei container.

Prima della correzione: 20 campioni con ispezione fallita su 310 totali.
La prova sandboxata riproduce 6 fallimenti su 40 con limite 12 e pids.events
max=120; con limite 64, stessa ispezione e condizioni, 0/40 fallimenti e max=0.
Una prima prova più semplice mostrava 2/10 contro 0/10. Sono errori riprodotti
del client di controllo, non del daemon Docker o dei worker del lab.

## Correzione applicata

- TasksMax portato a 64; quota CPU 10%, limite RAM 128 MiB e protezioni del
  servizio mantenuti. LimitCORE=0 evita grandi dump del client in caso di abort.
- Ispezione con massimo due tentativi entro il budget del servizio. Errori
  distinti per thread, timeout, exit nonzero e risposta incompleta; niente
  stack raw o dati privati nei risultati/log del monitor.
- Inventario verificato contro i sette nomi attesi: risposta vuota o parziale
  non può risultare healthy.
- Il primo campione di sola impossibilità di lettura resta visibile negli
  allarmi raw, ma la mail richiede due campioni consecutivi, circa cinque
  minuti di conferma. Un container realmente unhealthy o fermo, e gli altri
  allarmi risorse/dati, rimangono notificabili subito.
- Il notificatore rifiuta una proiezione che tenta di filtrare allarmi reali.
  Deduplicazione persistente, aggiornamenti a 30 minuti e promemoria giornalieri
  restano attivi; nessuna mail o stato mailbox modificato.

Aggiornati solo monitor e notificatore, con copie precedenti conservate.
Timer sospesi durante la breve sostituzione, poi ripristinati. Script e
configurazione installati restano SHA-verificati a ogni avvio. Nessun container
trading, modello o collector riavviato. La capacità swap non è stata cambiata
in questo incarico.

## Verifica e limiti

18 test passano: retry, errori precisi, inventario incompleto, rifiuto di
filtri impropri, conferma dei fallimenti di lettura, guasto reale immediato,
deduplicazione/recovery, TLS e storage. Dieci esecuzioni del servizio finale
passano tutte al primo tentativo, sette container ogni volta, nessun allarme.
Integrity_check ok per telemetria e stato notifiche; timer entrambi active,
servizi Result=success.

Il primo tentativo di dieci avvii manuali troppo ravvicinati ha incontrato
StartLimitBurst=5/10s. È un limite del test amministrativo, non del timer
ogni cinque minuti. Resettato solo il limite del servizio del monitor e ripetuta
la verifica con intervalli adeguati; la protezione di avvio è rimasta invariata.

Il test non garantisce che non ci saranno guasti futuri del daemon o della
rete: questi rimangono espliciti. La soglia di conferma riguarda soltanto
l'assenza di visibilità del controllo, non la disponibilità del trading.

Il rifiuto odierno del rapporto Qwen è un problema distinto: il tentativo
conserva la ragione ma non il testo respinto, quindi non è possibile qui
attribuirlo a una frase specifica. Nuova schedina To-do
`work-card-86784e1c-8464-41dd-a52e-821adeea9413` per qualificare la diagnostica
del validatore senza indebolirne le regole o avviare un altro esperimento.
