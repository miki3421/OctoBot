# M1 — metriche per simbolo e prime proposte di ribilanciamento

Dalla copia del **2026-10-17T09:09:06.762912+00:00** al mercato comune **2026-10-23T11:56:53.907809+00:00** (6.12 giorni).
Valori in USDT virtuali. Analisi esplorativa del conto M1 esistente; Originale come riferimento.

M1: equity **9950.61**, variazione dalla copia **+43.31**. Originale: equity **9879.74**, variazione sullo stesso periodo **-27.56**.
Entrambi partono dalla stessa copia economica. Lo storico precedente è conservato, ma il suo P/L non viene contato come risultato nuovo.

Il contributo nuovo M1 è **+5.18 LONG** e **+38.13 SHORT**, con fee e funding inclusi. La differenza rispetto all’Originale comprende anche variazioni di esposizione e ribilanciamento.

## Proposte concrete sul solo conto M1

Sono quantità indicative al momento della fotografia, **non ordini applicati**. Il capitale liberato resterebbe liquido, senza aumentare altri simboli.

| Simbolo | LONG netto dalla copia / ultime 48h | SHORT netto dalla copia | Quantità LONG prima → proposta | Peso prima → dopo | Costo immediato stimato |
| --- | ---: | ---: | ---: | ---: | ---: |
| AAVEUSDT | -10.51 / -14.48 | +7.81 | 2.61 → 1.3 | 3.88% → 1.93% | 0.216 |
| LTCUSDT | -7.37 / -10.90 | +8.83 | 8.2 → 4.1 | 4.86% → 2.43% | 0.357 |

La proposta libererebbe circa **435.64 USDT** di esposizione LONG, con costo immediato indicativo complessivo di **0.574 USDT**.
Il costo comprende differenza fra mark e fill sul book archiviato, slippage avverso di 2 bps e fee di almeno 6 bps. Non è una quotazione eseguibile adesso; profondità e quantità andrebbero ricontrollate al momento della decisione.

**Interazione importante:** M1 apre gli SHORT invertendo i LONG posseduti. Dimezzare un LONG ridurrebbe anche il successivo SHORT su quel simbolo. LTC resta complessivamente positivo grazie agli SHORT: la proposta riguarda il LONG, non l’eliminazione del simbolo. Prima di applicarla serve definire come mantenere separati i due budget e impedire che il ribilanciamento ordinario ricompri subito la quantità ridotta.

## Tutti i simboli: risultato nuovo, distinto per lato

| Simbolo | M1 netto | LONG netto | SHORT netto | LONG ultime 48h | Originale stesso periodo | Posizione M1 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| AVAXUSDT | -3.43 | -3.74 | +0.31 | +0.00 | -3.94 | FLAT |
| AAVEUSDT | -2.69 | -10.51 | +7.81 | -14.48 | -16.99 | LONG 2.61 |
| DOTUSDT | -1.72 | +2.44 | -4.16 | +10.94 | +7.18 | LONG 292 |
| ADAUSDT | -0.08 | +0.19 | -0.28 | +0.00 | +0.39 | FLAT |
| ATOMUSDT | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | FLAT |
| DOGEUSDT | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | FLAT |
| XLMUSDT | +0.00 | +0.00 | +0.00 | +0.00 | +0.00 | FLAT |
| LTCUSDT | +1.46 | -7.37 | +8.83 | -10.90 | -15.98 | LONG 8.2 |
| LINKUSDT | +1.73 | +1.22 | +0.51 | +0.00 | +0.78 | FLAT |
| HBARUSDT | +2.08 | +1.04 | +1.04 | +0.00 | +0.21 | FLAT |
| UNIUSDT | +2.13 | +1.95 | +0.19 | +0.00 | +1.62 | FLAT |
| XRPUSDT | +2.64 | +2.67 | -0.03 | +0.00 | +2.86 | FLAT |
| SOLUSDT | +2.64 | +2.49 | +0.16 | +0.00 | +2.36 | FLAT |
| ETHUSDT | +3.27 | +1.97 | +1.30 | +0.00 | +0.63 | FLAT |
| ZECUSDT | +5.27 | +5.19 | +0.09 | +0.00 | +5.20 | FLAT |
| BTCUSDT | +5.50 | -2.86 | +8.36 | -11.29 | -10.26 | LONG 0.01 |
| BCHUSDT | +12.16 | +6.23 | +5.93 | +3.36 | +0.71 | LONG 1.13 |
| NEARUSDT | +12.34 | +4.27 | +8.07 | -2.80 | -2.35 | LONG 45.2 |

DOT richiede una revisione distinta del lato SHORT: non va ridotto il LONG solo perché il totale del simbolo è negativo. HBAR e AVAX sono già FLAT: nessuna vendita proposta. BTC resta sotto osservazione: soddisfa i criteri di deterioramento LONG, ma questa prima proposta seleziona solo le due peggiori intensità di perdita, non tutti i simboli negativi.

## Metodo, qualità e limiti

Per ogni conto, simbolo, lato e finestra (dalla copia, 48h, 24h), JSON e CSV riportano: realizzato, P/L aperto iniziale e finale, fee, funding registrato, netto, turnover, tempo esposto, copertura, nozionale medio osservato, episodi e drawdown osservato in USDT.
**Netto = realizzato della finestra + P/L aperto finale − P/L aperto iniziale − fee + funding.** Le inversioni separano chiusura e nuova esposizione; le fee sono ripartite sulle quantità dei due lati. Gli acquisti che chiudono SHORT contribuiscono al lato SHORT. I riacquisti giornalieri non sono trattati come episodi indipendenti.
La copertura usa solo l’ultimo mark già osservato, valido per massimo 180 secondi; nessuna interpolazione attraverso i buchi. Il ranking divide il netto LONG per i nozionali-giorno osservati e lo esprime per 1.000 USDT-giorno: è un indicatore diagnostico, non un rendimento annualizzato né un confronto a pari rischio. Il drawdown è osservato sui campioni disponibili, non garantisce quello fra due campioni.
La regola esplorativa propone al massimo due riduzioni del 50%: LONG attuale, netto LONG negativo dalla copia e nelle ultime 48h, almeno 48 ore di esposizione LONG e copertura dei mark almeno 95% in entrambe le finestre. Le soglie sono una proposta di manutenzione, non una policy approvata o una preregistrazione scientifica.
Il campione comprende **2 episodi M1**, solo 6.12 giorni, con mercati correlati. I ribilanciamenti M1 mancati del 18–19 ottobre alterano il confronto: il vantaggio rispetto all’Originale non misura soltanto il filtro SHORT. Non è dimostrato che le riduzioni avrebbero migliorato il passato o miglioreranno il futuro.
Il funding è una stima registrata dal simulatore, attribuita al lato della quantità registrata e al tempo di settlement; il ritardo di acquisizione non è ricostruito. Nessuna certificazione di settlement reale.
Le copie M1, Originale e seed sono state riconciliate per quantità, costo medio, realizzato, fee, funding e saldo. I controlli di integrità sono stati eseguiti sulle copie offline. Seed e input sono identificati con SHA-256 nel JSON.
Originale e conto M1 non sono stati modificati. Nessuna nuova coin, nessun ordine, nessun grant, nessuna modifica al rischio o alla quarantena. I minimi del contratto KuCoin restano UNKNOWN; le stime usano esclusivamente il contratto sintetico del paper.

Scheda sviluppo: `work-card-37c30a2c-ad80-4eda-b1a6-f8bc7d41ab13`. Verifica: `work-card-3ed5dd7b-b2d4-4791-a643-4e60c20e3bf7`.
