# Rapporto giornaliero Qwen V13 — contratto V1

29 settembre 2026. Autorizzazione owner: «procedi pure», sul rapporto con andamento, contributi dei simboli, punti di forza e fragilità. Card contratto `work-card-6a5305d1-9d12-4f75-8969-210a00305511`; calcoli `work-card-d9aa3d09-f1cd-444a-b84a-d8dc02c41410`; Qwen `work-card-68075645-e700-4fbd-ae6d-32e2d76c0dd4`; UI `work-card-50341162-cf53-4d16-8a97-3cb65706d6ea`; verifiche `work-card-0ca20c17-c4dd-4bb9-a927-b73a596df3cc`.

Questo è un osservatore descrittivo del conto V13 multiasset di ricerca. Nessuna proposta, ordine, auto-approvazione, modifica di parametri o valutazione dei risultati BTC sigillati. Sostituisce il riquadro editoriale ritirato con una funzione distinta; non cambia i protocolli degli esperimenti.

## Calcoli e copertura

Lettura SQLite `mode=ro`, unica transazione: stato, fill eseguiti ed equity osservata. P/L per simbolo dall'attivazione = realizzato + quantità × (mark − prezzo medio) + funding − commissioni. Include anche simboli ora flat. Totale riconciliato con equity dell'ultima osservazione; incoerenze negano lo snapshot. Gli importi non vengono calcolati dal modello. Funding resta stimato.

Fill e riduzioni sono contatori distinti; una riduzione parziale non è un trade indipendente chiuso. Nessun win rate, Sharpe, annualizzazione o certificazione di redditività da un campione corto. Contributo assoluto non significa rendimento per capitale né qualità comparabile fra asset con esposizioni diverse. Concentrazione dell'esposizione e dei contributi positivi distinte.

Finestre 24h, 7 giorni e dall'attivazione: variazione fra equity realmente osservate, estremi espliciti. Nessuna interpolazione. Confine distante oltre tre minuti, assenza di storico sufficiente, dati vecchi o gap oltre trenta minuti rendono la copertura incompleta. Drawdown è osservato; lacune possono nascondere picchi e perdite. Dati mancanti restano UNKNOWN/indisponibili e non zero.

## Modello e output non fidato

Modello già installato Qwen3.6-35B-A3B UD-Q4_K_XL, alias `moe-private`, server llama.cpp fisso su loopback 8090. Nessun download, installazione, servizio cloud o tool. Temperatura zero, seed 13120, thinking disabilitato, massimo 900 token, timeout richiesta 90 secondi. Il worker salta slot condiviso occupato. Non modifica il modello.

Input: soli fatti numerici e frasi prodotte dal calcolatore, simboli validati, ID delle evidenze e timestamp. Nessuna nota libera, URL fornita dal modello, prompt esterno, journal BTC, credenziale o contatto. Output JSON con sintesi, punti di forza, fragilità e cose da osservare; riferimenti validi globali ai dati correlati, mostrati separatamente. La specifica V1 con riferimenti per punto ha fallito tre casi sintetici: Qwen restituiva stringhe anziché oggetti. Il formato piatto V1.1 è una correzione del trasporto e i tre test tecnici sono passati, ma la review semantica ha trovato “quasi totalità” per un contributo del 74%: esito qualità FAIL. V1.2 aggiunge un controllo quantitativo sugli aggettivi di concentrazione e qualifica tre scenari distinti; due passano, mentre il caso positivo resta FAIL per numeri nel testo e un riferimento improprio alla significatività statistica. V1.3 ne vieta la pubblicazione, ammettendo solo le etichette esatte delle finestre con riferimento valido: tre scenari distinti PASS. Il primo rapporto reale V1.3 ha negato un simbolo citato senza riferimento; una seconda richiesta ha prodotto riferimenti validi. V1.4 aggiunge il riferimento esatto del simbolo e della finestra nominati tramite il sistema, senza interpretare il testo come prova. Sono riferimenti ai dati correlati, non attestazioni semantiche. I parametri scientifici della strategia sono invariati. Il modello non riporta nuove cifre nel testo: le evidenze numeriche vengono mostrate dal sistema. Il validatore rifiuta struttura/riferimenti non validi, HTML, numeri inventati, autorizzazioni e istruzioni di trading. Non dimostra la verità semantica di ogni frase: il testo è sempre interpretazione di Qwen, le cose da osservare sono ipotesi, mai validazione scientifica.

## Isolamento, cache e frequenza

Correzione di trasporto del 1 ottobre 2026: l'etichetta esatta `24h` nel testo
del modello viene normalizzata in `24 ore` prima del collegamento delle fonti,
soltanto se esiste l'evidenza `window_24h`. Il rapporto conserva la forma
canonica già ammessa dal contratto V1.4; input originale non modificato.
Durate diverse, cifre aggiuntive e numeri inventati restano soggetti allo stesso
validatore. Nessun cambiamento a prompt, sampling, calcoli o frequenza.

Worker UID/GID 30915 già separato, home inaccessibili, sorgente root-owned/hash-pinned in stage distinto, nessun gruppo/mount ledger, approvals, control, BTC o socket Docker. Legge solo API ristrette e server modello su loopback; scrive solo la propria sottodirectory nella cache esistente, con record immutabili e pubblicazione atomica. UI legge cache su mount RO, senza inferenze per visita.

Un rapporto per giorno UTC; timer alle 06:00 UTC, prima generazione alla consegna. Copertura e timestamp del rapporto congelati, tabella corrente etichettata separatamente. Report più vecchio di 32h o campione/hash alterato non mostrato. Busy/offline, timeout, output invalido o storage failure non cambiano il conto. Il giorno già pubblicato non è ricalcolato al riavvio. Il vecchio timer editoriale resta disabilitato; Qwen BTC shadow resta separato.

## Accettazione prima dell'attivazione

Test sintetici: riconciliazione long/short/flat e costi, contatori riduzioni, gap e finestre incomplete, lettura coerente/RO, numeri non finiti, output con injection/fatti inventati/riferimenti mancanti, cache stale/tamper, replay dello stesso giorno, busy/offline/storage failure. Qualificazione locale del nuovo prompt con fixture esplicitamente sintetiche: guadagno concentrato, perdita per costi, copertura incompleta. Oracoli fissati prima della prima richiesta; esiti e tempi conservati, nessun tuning sul risultato.

Browser desktop/mobile; conservazione pin V13/BTC, runtime paper, PID del modello, quarantena e integrità SQLite. Verifiche dell'autore SINGLE_AGENT, non review indipendente. Minimi KuCoin UNKNOWN; validazione exchange-faithful BLOCKED.
