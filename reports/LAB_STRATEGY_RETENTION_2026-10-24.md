# Strategie del laboratorio: quali mantenere e quali razionalizzare

**24 ottobre 2026, analisi soltanto. Nessuna strategia o collector fermati.** Scheda `work-card-2ff65e22-8a17-4acf-b084-6f7b2dd2491f`.

La perdita corrente non basta a distinguere una strategia inefficace da esposizione al mercato, costi o mancata disponibilità degli input. Oggi M1 non è la migliore nella finestra comune: FAST e HALF perdono meno, con esposizione inferiore. Non emerge una base solida per bocciare scientificamente queste tre varianti su circa una settimana; emerge invece un candidato di razionalizzazione operativa nel vecchio conto BTC intraday.

## Confronto sullo stesso periodo

Copie SQLite coerenti di Originale, M1 e FAST/HALF; integrità `ok`. Usate osservazioni grezze, evitando il campionamento indipendente delle curve UI. Primo intervallo comune dopo la prima decisione M1 del 17 ottobre, fino al 24 ottobre: **17 ottobre 11:15 → 24 ottobre circa 16:20 CEST**. 2.075 bucket comuni di cinque minuti, senza interpolazione, scarto massimo ammesso fra i riferimenti di 120 secondi e nessun buco fra bucket oltre 30 minuti. Il drawdown resta osservato ai punti campionati.

| Strategia | Rendimento nella finestra comune | Drawdown osservato nella stessa finestra |
| --- | ---: | ---: |
| FAST | −0,85% | 0,97% |
| HALF | −0,92% | 1,16% |
| M1 + SHORT | −1,04% | 1,75% |
| Originale | −1,73% | 2,55% |

Il capitale iniziale delle varianti e l'esposizione sono diversi: i rendimenti percentuali nella stessa finestra consentono una lettura migliore dei saldi assoluti, ma non sono una prova a rischio identico. M1 ha ancora i due DAILY mancati del 18–19 ottobre e soltanto due episodi SHORT; il suo vantaggio rispetto all'Originale non misura soltanto il filtro.

Nel periodo più lungo comune a Originale, FAST e HALF, dal **13 ottobre circa 17:00 al 24 ottobre 16:25 CEST**, i rendimenti sono rispettivamente −2,36%, −1,13% e −1,18%. FAST guadagna circa **5,60 USDT** rispetto a HALF in quel periodo e mostra drawdown leggermente inferiore. Quindi non è corretto bocciare FAST perché tutte le curve sono rosse. Il vantaggio è piccolo e il campione breve: non dimostra neppure che la protezione rapida abbia un vantaggio robusto sul semplice dimezzamento.

## Raccomandazione per conto

| Conto | Raccomandazione attuale | Motivazione |
| --- | --- | --- |
| Originale | Conservare invariata come riferimento | Serve a misurare gli effetti delle modifiche. È la peggiore nella finestra corrente, ma fermarla ora perderebbe il controllo richiesto dall'operatore. |
| M1 + SHORT | Priorità allo sviluppo della manutenzione | Ha contenuto parte del calo rispetto all'Originale; i LONG hanno consumato il contributo degli SHORT. La v2 richiede consenso distinto e non è inclusa nei risultati qui analizzati. |
| HALF | Conservare come controllo di rischio | È il confronto semplice necessario per capire se filtri aggiuntivi migliorano davvero qualcosa. |
| FAST | Non bocciare oggi; nessuna espansione proposta | Risultato leggermente migliore di HALF, non peggiore; valore aggiunto ancora non dimostrato su un campione sufficientemente ampio. |
| BTC intraday precedente | Primo candidato a sospensione per consolidamento, previa verifica della sostituzione | Due sole operazioni complete, confronto successivo già disponibile nei due nuovi conti e continuità degli input limitata. La motivazione sarebbe organizzativa, non una prova di perdita strutturale. |
| Nuovo SHORT controllo | Continuare osservazione qualificata | Zero fill: la redditività non è ancora misurabile. |
| Nuovo LONG + SHORT | Continuare lo stesso confronto | Zero fill: lo zero non è profitto né evidenza di robustezza. |

### Vecchio BTC intraday: costi e copertura prima del verdetto

Equity 9.998,47 USDT; **−1,53 USDT** dal proprio avvio del 17 ottobre, stress **−2,43 USDT**. Quattro fill corrispondono a **due round trip**, non a quattro operazioni complete. Realizzato lordo +0,456 USDT, commissioni 1,983 USDT: il piccolo margine lordo è assorbito dai costi. Non è una numerosità sufficiente per concludere che il segnale sia perdente.

Il contatore registra **753 slot validi su 1.902, 39,59%**, comprendendo attese di inizializzazione/ricostruzione della finestra e buchi. La misura non coincide con il tempo di salute del container. Prima di attribuire il basso numero di trade alla strategia, va distinta l'assenza di segnale dall'indisponibilità degli input.

La sospensione consigliabile sarebbe il consolidamento nel nuovo SHORT controllo, dopo avere conservato storico e configurazione e verificato la copertura delle funzioni che il vecchio conto deve rappresentare. Questa analisi non presume equivalenza perfetta fra protocolli e non autorizza spegnimenti, rimozione del collector scalping o cancellazione degli archivi.

### Nuova coppia: perché lo zero non permette una bocciatura

Alla lettura dei journal, entrambi i conti principali hanno gli stessi conteggi: 492 slot `NO_SIGNAL`, 259 `WARMUP_OR_MISSING_INPUT`, 29 `PRESTART_WARMUP` e un `L5_WINDOW_INCOMPLETE`. Nessun fill. Lo stato conserva anche il motivo `PRICE_MISSING`, mentre gli ultimi cinquanta slot della vista sono tutti `NO_SIGNAL`: quel motivo non va interpretato come una diagnosi attuale per tutti gli slot.

Si tratta di circa due giorni dall'inizio del protocollo, con parte del tempo dedicata al completamento delle finestre causali. Mancano operazioni su cui valutare rendimento netto, stop, uscite e funding. Non propongo di abbassare soglie per forzare attività.

## Decisione suggerita e limiti

Concentrerei il lavoro su **M1 e sulla sua manutenzione**, conservando Originale e HALF come controlli. La prima razionalizzazione da sottoporre a decisione è il **vecchio BTC intraday**, per sovrapposizione di scopo e problemi di copertura; non lo etichetterei come modello statisticamente bocciato. FAST, oggi leggermente migliore di HALF, merita ancora il confronto fissato. I due nuovi conti richiedono osservazioni ed episodi effettivi.

Non sono stati inventati nuovi criteri di promozione o arresto dopo aver visto il risultato, non sono stati letti outcome scientifici sigillati e nessun dato di mercato nuovo è stato scaricato per questa analisi. Script riproducibile `scripts/analyze_lab_retention.py`; aggregati e intervalli esatti in `reports/LAB_STRATEGY_RETENTION_2026-10-24.json`. Le viste e le copie complete restano private in `audit-evidence/m1-v2-ui-20261024/`.
