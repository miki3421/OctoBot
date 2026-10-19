# Trading AI Lab — correzioni e qualifiche del 19 ottobre 2026

Le quattro priorità del check giornaliero sono state eseguite. Nessun tuning
dei segnali o dei limiti di rischio; nessun recupero retroattivo di operazioni.
Verifica dell'autore, SINGLE_AGENT; non è una review indipendente.

| Priorità | Risultato | Schedina |
| --- | --- | --- |
| Monitor automatico | Ripristinato, esteso a M1 e intraday, manifest coerenti e notificatore compatibile | `work-card-7346c1df-a816-400a-9552-aa347aa60340` |
| DAILY M1 | Causa isolata e corretta, nuovo runtime attivo sullo stesso conto | `work-card-6394a348-5342-449f-9e60-26106ea3847a` |
| Rischio FAST/HALF | Sei slot ricostruiti: scarti riprodotti dalle allocazioni effettive, senza modificare il confronto | `work-card-ca705a4d-4a76-4eb0-979d-205efa95738a` |
| Qualifica A/B/C | Valutatore congelato eseguito sulla copia coerente: **NOT_QUALIFIED** | `work-card-23902a16-23d0-4275-9a71-e4d413319f96` |
| Coerenza Qwen | Controllo più restrittivo sulle affermazioni esclusive; rapporto odierno respinto e conservato | `work-card-229b2029-a9df-4977-99d3-3dee408f57c5` |

## Monitor e notifiche

Il bundle precedente aveva programma valido e configurazione diversa dal suo
manifest. Nuovi bundle separati per monitor e notificatore, con hash coerenti:
il controllo di integrità rimane obbligatorio. Timer ogni cinque minuti.
Due cicli naturali verificati alle 12:00 e 12:05 italiane, entrambi conclusi
con successo e campioni freschi, oltre al primo avvio di verifica delle 11:56.
Oltre ai dieci container, vengono lette le proiezioni di M1 e BTC intraday:
custodia, clock, freschezza, contabilità dichiarata e DAILY M1 atteso.
Non vengono aperti dagli alert i ledger di esecuzione o le approvazioni.

I DAILY sono esposti separatamente dagli ultimi cento segnali: un giorno
mancato non scompare dal controllo solo perché arrivano nuovi NO_SIGNAL.
Lo stato intraday non viene dedotto dal vecchio motivo persistente
PRICE_MISSING quando il nuovo slot e i dati sono regolarmente aggiornati.

Sono rimasti due alert reali: spazio root sotto il 15% libero e DAILY M1
odierno mancato prima della correzione. Il secondo non viene dichiarato
recuperato artificialmente: lo slot resta MISSED. Le notifiche seguono il
notificatore già autorizzato, con dedup/cooldown; nessuna mail di prova forzata.

## M1: causa, correzione e continuità

I log del 18 e 19 ottobre mostrano `invalid or missing target weight` prima
di `execution_window_expired`. I target della proposta reale sono stringhe
canoniche; il pianificatore numerico le rifiutava. La scadenza era l'esito
finale dei tentativi falliti, non la causa iniziale.

Ora i pesi sono decodificati con il decoder canonico già esistente, sia per
la baseline in cache sia quando si consuma un intento giornaliero/rientro.
Stringhe non canoniche, NaN e infiniti restano rifiutati. I dati verificati
non vengono sostituiti con nuovi target; deadline di 120 secondi invariata.

Runtime M1 v2 isolato, con pin dei due file modificati e ricevuta root-owned
che lega identità precedente, nuova identità, conto e backup pre-aggiornamento.
I parametri del protocollo sono identici: cambiano soltanto i pin del codice.
L'identità iniziale non viene sovrascritta: la ricevuta di correzione è
aggiunta al journal. Non è un grant operativo o un'approvazione dell'issuer.

Verificati dopo il riavvio: quantità invariate, tabella ordini identica,
entrambi i DAILY storici identici, zero fill post-copia, stessa identità
iniziale e baseline attuale numerica. Il conto è healthy/OBSERVING.
La UI avverte che i ribilanciamenti mancati limitano il confronto con V13.

**Primo riscontro naturale ancora futuro:** 20 ottobre alle 00:15 UTC,
02:15 italiane. Scheda `work-card-e44856b4-c23a-4661-b4c3-65acabe87d6b` in
To-do. Il monitor controlla già l'esito dopo la finestra; non è stato creato
un trade oggi per anticipare quella verifica.

## Qualifica dello scarto FAST/HALF

Ricostruzione su copia: seed immutabile + fill realmente registrati,
covarianza delle barre congelate, book archiviati verificati per hash e clock,
equity dopo i costi. La volatilità delle quantità effettive coincide con
quella registrata dal runner entro 1e-10; anche lo scarto è riprodotto.

| Slot UTC | Scarto teorico prima della quantizzazione | Scarto relativo sulle quantità effettive | Entro 2% |
| --- | ---: | ---: | --- |
| 14 ottobre | 0% | 0,0000% | Sì |
| 15 ottobre | 0% | 7,3825% | No |
| 16 ottobre | 0% | 2,7791% | No |
| 17 ottobre | 0% | 0,5205% | Sì |
| 18 ottobre | 0% | 6,3304% | No |
| 19 ottobre | 0% | 1,8012% | Sì |

Il pareggiamento continuo funziona; la parità non sopravvive necessariamente
alle quantità discrete. Esempio del 15 ottobre: residuo di peso BTC FAST
rispetto al target continuo −0,8231 punti percentuali. Con un conto da circa
10.000 USDT, un incremento da 0,001 BTC pesa già circa lo 0,8% dell'equity.
Nei sei slot i dettagli non registrano veto di ingresso o note di esecuzione:
non attribuiamo questo scarto a un rifiuto che non risulta nelle evidenze.

Non emerge un errore aritmetico nel calcolo del rischio registrato; emerge
il limite del modello continuo applicato alle quantità eseguibili e ai costi.
Tre dei sei slot sono entro tolleranza: non si può presentare oggi tutto il
campione come confronto a rischio equivalente. Nessuna tolleranza allargata,
quantità aumentata o osservazione eliminata. Un eventuale pareggiamento
discreto richiederà una proposta versionata prima di cambiare lo studio.

## A/B/C: esito finale dei dati, non dei rendimenti

Periodo congelato 2–16 ottobre. Backup SQLite coerente, integrity_check OK,
binding di attivazione verificato dal CLI originale, replay di tutte le
ricevute con il valutatore immutabile. Nessuna acquisizione aggiuntiva.

Copertura comune book 99,8512%; massimo buco comune 30 minuti; metadata,
daily e risposte funding completi nel criterio previsto. Non passa invece
la frequenza minima del 95% di profondità sufficiente su entrambi i lati:

| Simbolo | Frequenza osservata di profondità sufficiente |
| --- | ---: |
| ARB | 86,7362% |
| ASTER | 68,3308% |
| QNT | 94,4858% |

Esito **NOT_QUALIFIED**. Pagina A/B/C aggiornata con questi numeri e con lo
stato non avviato. Non sono stati esclusi a posteriori i tre simboli o
abbassate le soglie. Le risposte funding non certificano ogni settlement/mark.
Il pacchetto A/B/C resta bloccato; nessun nuovo conto avviato.

## Qwen e verifica live

Il validatore verifica che un'affermazione di contributi positivi esclusivi
citi effettivamente tutti i simboli con contributo netto positivo. Il prompt
chiede descrizioni non esclusive. È un controllo semantico circoscritto,
non una certificazione generale di tutte le frasi del modello.

Il rapporto del 19 ottobre, che definiva NEAR/LINK gli unici positivi pur
avendone cinque nelle evidenze, ora è `rejected: unsupported_exclusivity`.
Il suo hash originale e i metadati del tentativo sono conservati, senza
riscrittura o nuova inferenza. Anche una precedente ricevuta ready non può
nascondere il rifiuto. Il prossimo ciclo rimane quello giornaliero ordinario.

Collaudo: 105 test mirati passati; dopo l'ultimo affinamento sul clock del
rapporto sono stati rieseguiti i 39 test Qwen/analitici, tutti passati.
Verificati replay monouso, pesi reali serializzati, upgrade esplicito e restart,
clock/stale, rifiuti semantici, alert e SMTP simulato/dedup. Browser reale:
tre pagine HTTP200, stato A/B/C e avviso M1 visibili, nuovo JS caricato,
Qwen respinto via API, nessun errore JavaScript.

Riavviati solo il conto M1 corretto e l'interfaccia condivisa. Identità e
tempi di avvio di FAST/HALF, executor Originale e BTC intraday invariati;
nessuna modifica all'osservazione M1 o alla ricerca BTC/Qwen shadow.

## Rilascio, evidenze e residui

Codice principale `b8786ac7a784d4ac6a0dbb15c2be38ede9dc026b`; affinamento
Qwen `3eae0a48` (commit completo nel checkpoint). Bundle e manifest privati
legano il candidato ai servizi effettivi; vecchi bundle, unità e configurazioni
conservati. Il rollback non ripristina né riavvolge un ledger: se una versione
non è compatibile con lo stato corrente, il solo conto interessato resta
fermo per review. Mai ricreare il conto dal seed o recuperare fill scaduti.

Evidenze private: `audit-evidence/lab-remediation-20261019/`, non incluse in Git.
Test/consegna: `work-card-57008d50-57f2-4901-8bf8-a68e090fdc8b` e
`work-card-2c2c14b9-cb91-48d2-8091-c4f8f95e7ff2`.

Residui: primo DAILY naturale M1; osservazione del rischio FAST/HALF con il
limite documentato; eventuale nuovo piano A/B/C dopo l'esito negativo;
verifica della crescita root su `work-card-b0fec86e-aeca-4f3c-9f12-c9dbf4917275`.
Nessuna nuova strategia o operazione reale. Minimi KuCoin UNKNOWN;
ammissibilità exchange-faithful ancora BLOCKED.
