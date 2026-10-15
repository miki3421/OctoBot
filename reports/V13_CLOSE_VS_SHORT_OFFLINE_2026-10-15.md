# V13: chiudere i long oppure invertirli in short

15 ottobre 2026. Confronto offline richiesto dal proprietario. Originale, FAST e HALF invariati. Nessun nuovo servizio, ordine, grant, credenziale o download. Le copie e le evidenze dello studio precedente sono conservate. Verifica SINGLE_AGENT dell'autore, non revisione indipendente.

Schede: protocollo `work-card-fb7b6ab3-d3c6-40e0-9c00-53d1e3d7d3ad`; replay `work-card-1c625e23-0331-4fa3-a9d5-98e9fc21499e`; verifica `work-card-e24fa27e-93be-4553-8422-5fe63af48afe`. Evidenze nella radice workspace: `audit-evidence/v13-close-vs-short-20261015/`.

## Risultato

**Gli short meritano ulteriore studio con il segnale di momentum e debolezza diffusa. La semplice rottura dei minimi non sostiene invece l'inversione automatica del portafoglio.** Nel primo caso lo short supera la liquidità nel campione; nel secondo i rimbalzi producono perdite maggiori dei guadagni ottenuti negli ultimi due cali.

Questa prova usa il paniere V13 effettivo: equity, costi medi e posizioni già esistenti a ogni ingresso. Il nozionale iniziale varia da circa 1971 a 2256 USDT, con 15–18 posizioni long. Chiusura, inversione e rientro pagano tutti i costi. Non è una nuova strategia attiva né una dimostrazione di capacità predittiva fuori campione.

## Disegno fissato prima del replay

Protocollo SHA-256 `0c3290a09372c57f362a0cb0136925e970355e18ba5bac170bc455fe53d87647`. Stesse finestre, soglie e book del precedente studio, con cutoff 15 ottobre 07:25:59 UTC / 09:25:59 italiane; nessuna ricerca di parametri.

- **M1, momentum/ampiezza:** BTC perde almeno 1% in un'ora e almeno due terzi dei 18 simboli scendono sull'ora.
- **M2, minimo/ampiezza:** BTC rompe il minimo osservato delle 24 ore precedenti con la stessa debolezza diffusa.

Ingresso ritardato di almeno 60 secondi, orizzonte circa sei ore sulla griglia già fissata e sei ore di cooldown dopo l'uscita. Gli orari dei book effettivi sono registrati: gli endpoint non sono stati spostati per migliorare il profitto. Un esito M1 ancora privo di sei ore future resta censurato.

Ogni episodio riparte da una copia dello stato economico V13 a quell'istante. Le tre alternative sono:

| Alternativa | Durante la finestra | Alla fine |
|---|---|---|
| V13 effettiva | Riproduce fill e funding originali | Conserva le posizioni effettive finali |
| Chiusura / CASH | Chiude i long e resta liquida | Ricompra le quantità finali della V13 |
| Inversione / SHORT | Trasforma ogni long `+q` in short `−q`, stesso lordo iniziale | Ricopre gli short e ripristina le quantità finali V13 |

Per passare da `+q` a `−q` bisogna vendere `2q`. La profondità è consumata sulla quantità aggregata; non si riutilizza lo stesso book due volte per simulare liquidità gratuita. Il rientro da `−q` a `+q` richiede normalmente l'acquisto di `2q`. Tutte le alternative terminano con le stesse quantità e sono valutate sugli stessi mark: l'eventuale vantaggio short non è ottenuto lasciando aperta una posizione favorevole o evitando il costo del rientro.

Il ripristino delle quantità originali è un controllo metodologico. Non rappresenta il sizing autonomo di una strategia futura, che avrebbe equity e decisioni proprie. Ciascun episodio riparte dall'originale: le somme sottostanti sono somme dei risultati delle finestre, **non la curva investibile di un quarto conto**, né rendimenti cumulati sul capitale. Le finestre dei due modelli possono sovrapporsi e non vanno sommate fra modelli.

## Confronto sull'intero campione disponibile

Importi USDT, dopo inversione/chiusura, funding e ripristino comune.

| Segnale | Finestre complete | V13 effettiva | Chiusura long | Inversione SHORT | SHORT meno chiusura |
|---|---:|---:|---:|---:|---:|
| M1 momentum/ampiezza | 7 | −101,39 | −29,51 | **+39,80** | **+69,31** |
| M2 minimo/ampiezza | 10 | **+48,18** | −43,21 | **−138,78** | **−95,57** |

La liquidità perde i costi di uscita e rientro, pur non subendo il mercato durante la finestra. Gli short battono la liquidità in 4/7 episodi M1 e 5/10 episodi M2. Il solo numero di operazioni positive non descrive il rischio: per M2 il maggiore rimbalzo annulla parecchi short vincenti.

Fee totali nuove, rientro incluso: M1 CASH 18,00, SHORT 35,99; M2 CASH 25,19, SHORT 50,38. Funding stimato M1: originale −0,893, CASH 0 perché senza esposizione, SHORT +0,893. M2: circa −0,553 / 0 / +0,553. Questi zeri CASH derivano dalla quantità effettivamente nulla; non sono tassi mancanti reinterpretati come zero.

## Gli episodi che chiariscono la differenza

Orari del segnale in Italia, risultati finali dopo il ripristino. Per M2 il 14 ottobre l'ingresso è sul book delle 14:39:56, successivo al primo shock CPI delle 14:30; per il 15 ottobre il segnale precede l'accelerazione delle 04:20.

| Segnale | Episodio | V13 effettiva | Chiusura | SHORT |
|---|---|---:|---:|---:|
| M1 | 14 ottobre 15:10 | −24,57 | −3,80 | **+16,68** |
| M2 | 14 ottobre 14:35 | −48,47 | −3,56 | **+40,93** |
| M2 | 15 ottobre 02:50 | −58,33 | −3,67 | **+50,53** |
| M2 | 13 ottobre 02:50, rimbalzo | **+112,34** | −4,46 | **−121,83** |

Quindi sì: sul crollo più recente lo short del paniere avrebbe aggiunto profitto alla protezione in liquidità. La stessa regola M2 avrebbe però invertito il portafoglio prima del forte recupero del 13 ottobre. Non basta riconoscere una rottura: bisogna distinguere una prosecuzione ribassista da un esaurimento della vendita.

Prima del 14 ottobre M1 totalizza già SHORT +23,13 contro CASH −25,70; nell'ultimo episodio aggiunge +16,68 contro −3,80. Il risultato M1 non deriva interamente dall'ultimo calo, ma resta basato su appena sette finestre dello stesso breve periodo. M2 prima del 14 totalizza SHORT −230,24 contro CASH −35,97; i due episodi recenti recuperano +91,46 contro −7,23 senza compensare il danno precedente.

## Rischio, costi e limiti

La peggiore finestra short M1 perde 34,36 USDT; M2 perde 121,83. La maggiore discesa dal massimo osservato dentro una finestra è 76,17 per M1 SHORT e 121,83 per M2 SHORT, contro 4,70 e 5,11 per CASH. Sono drawdown su campioni di cinque minuti, non massimi tick-by-tick e non il drawdown di una strategia continua. I buchi della griglia restano visibili: non sono interpolati per minimizzare il rischio.

Sensibilità con **20bps aggiuntivi su tutto il turnover controfattuale**, entrata e rientro inclusi:

| Segnale | Chiusura, costo stressato | SHORT, costo stressato | Differenza SHORT−chiusura |
|---|---:|---:|---:|
| M1 | −89,49 | −80,16 | +9,33 |
| M2 | −127,17 | −306,70 | −179,53 |

M1 mantiene un piccolo vantaggio relativo sulla liquidità sotto questo stress, ma il risultato short assoluto diventa negativo. Il beneficio è sensibile alla qualità di esecuzione. M2 peggiora nettamente.

I fill usano book pubblici archiviati, VWAP, slippage avverso 2bps per lato, arrotondamento prudente al tick e fee almeno 6bps per lato. Il passo quantità è precisione; il minimo nozionale di apertura è quello **simulato** di 1 USDT. Minimi KuCoin reali sempre UNKNOWN. Questo confronto non certifica ammissibilità degli ordini KuCoin.

Funding: eventi effettivi presenti negli archivi dei tassi, copertura e intervalli verificati, quantità detenuta al settlement e mark locale strettamente precedente entro 30 minuti. Resta una stima contabile, non un addebito exchange reale. Copertura mancante, book insufficiente o quantità non rappresentabile negano l'episodio. Tutte le 17 finestre complete dei due modelli sono risultate calcolabili; una finestra M1 incompleta rimane censurata.

Non sono stati aggiunti stop, take profit o altre soglie dopo aver letto i risultati. Non sono rieseguiti issuer, permessi di ingresso o limiti operativi di frequenza/cooldown: uno short è nuova esposizione direzionale, non una semplice riduzione protettiva. L'esito economico condizionale non implica che l'attuale catena operativa possa o debba eseguirlo. Policy e gate delle tre strategie attive restano invariati.

## Valutazione e lavoro successivo

M1 è un candidato concreto per studiare gli short: nel replay del paniere produce un vantaggio rispetto alla chiusura e mantiene una parte del vantaggio anche fuori dall'ultimo episodio. I pochi eventi e la sensibilità ai costi impediscono di considerarlo pronto per l'attivazione. M2 non giustifica un'inversione automatica con queste regole e questo orizzonte.

Il lavoro successivo utile è qualificare i dati intraday già raccolti e definire un test futuro congelato che confronti CASH e SHORT sullo stesso trigger M1, con budget, uscita, costi stressati e criteri di arresto espliciti. Qualsiasi affinamento con open interest, volatilità o profondità sarebbe una nuova versione da verificare; non viene inserito in questo confronto per migliorarne l'esito. Nessuna quarta strategia attivata.

## Verifiche e riproduzione

Ricostruite tutte le 189 operazioni originali e gli eventi funding del ledger conservato: quantità, prezzi medi, realizzato, fee e funding coincidono con lo stato salvato; equity finale riconciliata sotto 0,000001 USDT. Il prefisso storico non viene perso né i profitti realizzati sommati una seconda volta.

Dieci nuovi test verificano contabilità, attraversamento long→short, profondità aggregata, atomicità del paniere, tick avverso, minimi simulati, funding mancante/futuro e costi del ripristino. Passano anche i sette test causali del modello precedente: **17 test unitari superati**. Per ogni finestra sono verificate identità distinte sui flussi monetari, gross iniziale uguale e quantità terminali identiche. È una verifica dell'autore, non una review indipendente.

Codice isolato: `octobot/ai_strategy_lab/v13_close_short_diagnostic.py`; replay `scripts/v13_close_short_20261015.py`; prove `tests/unit_tests/ai_strategy_lab/test_v13_close_short_diagnostic.py`. Le sorgenti sono le copie immutabili dello studio `v13-crash-20261015`, verificate contro il suo manifest. Nessuna scrittura nei ledger o nelle configurazioni attive; nessuna lettura degli outcome sigillati BTC/A-B-C.
