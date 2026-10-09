# V13 — SELL BTC, altri simboli e veto controfattuale

9 ottobre 2026. Scheda `work-card-7d58d1a7-bcf5-4aa9-be63-edea482ac6a9`.
Protocollo diagnostico fissato prima del calcolo degli esiti:
`docs/V13_BTC_VETO_DIAGNOSTIC_PROTOCOL_2026-10-09.md`.
Il ribasso era già osservato: nessun risultato qui è validazione prospettica.

## Risultato centrale

Nel periodo osservato, un veto che blocca solo nuovi acquisti migliora poco
il risultato. Un veto che chiude anche i long conserva molto più profitto.
Tuttavia il SELL BTC non nasce principalmente da un allarme ribassista BTC:
la causa dominante è la redistribuzione dei pesi quando entrano tre nuovi asset.

## Causa riprodotta dei SELL

Ribilanciamenti strategici: chiusura 29 settembre e chiusura 6 ottobre;
quest'ultimo è eseguito il 7 ottobre alle 02:12:15 italiane. BTC passa da peso
teorico 2,8733% a 2,3681%, una riduzione relativa del 17,58%.
La quantità eseguibile arrotondata passa da 0,003 a 0,002 BTC: il lotto amplifica
la riduzione effettiva al 33,33%. Non è una previsione short.

Si aggiungono ATOM, DOGE, XLM, tutti con segnale long al ricalcolo. I simboli
attivi passano da 15 a 18. Il gross teorico passa da 22,6569% a 22,7878%:
il rischio complessivo assegnato non viene tagliato, il capitale viene ripartito.

La formula originale è segnale × inverso della volatilità individuale,
normalizzato fra gli asset attivi e scalato al budget di volatilità del portafoglio.
Le covarianze a 60 giorni sono state ricostruite dalle ricevute contemporanee
di ciascuna decisione, senza usare barre successive. Tutti i pesi dei due
ribilanciamenti riproducono quelli dell'issuer entro 1e-10.

| Ricostruzione | Peso BTC | Gross |
| --- | ---: | ---: |
| Situazione precedente | 2,8733% | 22,6569% |
| Nuovi asset attivi, vecchia covarianza | 2,3775% | 22,7613% |
| Vecchi asset attivi, nuova covarianza | 2,8673% | 22,7300% |
| Situazione nuova completa | 2,3681% | 22,7878% |

Attribuzione a due fattori, mediando i due ordini di sostituzione (Shapley):
98,47% della riduzione BTC dipende dall'insieme attivo, 1,53% dalla covarianza.
Quest'ultimo fattore comprende volatilità individuale e covarianza di portafoglio;
non è una previsione del prezzo.

Il fenomeno è comune ai 15 asset già presenti:

| Simbolo | Riduzione relativa del target |
| --- | ---: |
| BTC | −17,58% |
| HBAR | −17,43% |
| LINK | −17,90% |
| ETH | −16,68% |
| AVAX | −16,62% |
| NEAR | −20,73% |

Gli altri vecchi asset sono anch'essi ridotti, circa −15%/−18%.
Questo corregge l'interpretazione puramente visiva: un calo del peso BTC
può avvenire quando aumenta la breadth long, non soltanto quando BTC peggiora.
Il veto basato sul vero momentum BTC negativo non è il veto qui studiato:
il momentum BTC resta positivo nell'episodio.

## Confronto diagnostico dei veto

Copie coerenti, separate e SHA-registrate del ledger e delle approvazioni.
Trigger: diminuzione del target BTC positivo rispetto al precedente target
strategico positivo. Un solo trigger nel campione, disponibile dall'issuer
prima del book di esecuzione del 7 ottobre. Nessuna soglia cercata sul minimo
successivo. Il veto dura fino al prossimo ricalcolo, non ancora osservato.

Snapshot finale: **9 ottobre ore 11:42:30 italiane**. Capitale iniziale 10.000 USDT.

| Braccio | Equity finale USDT | P/L USDT | Drawdown massimo osservato |
| --- | ---: | ---: | ---: |
| V13 effettiva | 9.986,63 | −13,37 | 3,31% |
| Veto ai soli aumenti/riaperture long | 9.999,76 | −0,24 | 2,80% |
| Veto più chiusura dei long già aperti | 10.133,36 | +133,36 | 1,47% |

Il veto ingressi migliora di 13,13 USDT; quello con uscita di 146,72 USDT.
La differenza viene soprattutto dall'esposizione già presente, non dai soli
nuovi acquisti. L'uscita non recupera i guadagni persi prima del 7 ottobre.

| Costi totali della finestra | V13 | Veto ingressi | Veto più uscita |
| --- | ---: | ---: | ---: |
| Fee USDT | 3,70 | 3,36 | 4,43 |
| Funding stimato USDT | −7,99 | −7,86 | −7,34 |
| Fill simulati | 127 | 99 | 98 |

Chiusure aggiuntive e quantità diverse sono prezzate sul book conservato,
con profondità sufficiente, VWAP, 2bps avversi, tick e fee del simulatore.
Funding: medesime rate e mark precedente stimato, applicati alle quantità
effettivamente rimaste nel controfattuale. Gli aumenti sono scartati; i SELL
sono limitati alla quantità ancora detenuta, senza mai diventare short.
Nessun valore minimo KuCoin viene inferito: entrambi restano UNKNOWN.
Questi bracci non dimostrano ammissibilità di ordini reali.

## Chi avrebbe beneficiato e chi no

Differenza rispetto alla V13 per simbolo alla fine della copia:

| Simbolo | Veto ingressi, USDT | Veto più uscita, USDT |
| --- | ---: | ---: |
| DOGE | +12,82 | +12,82 |
| XLM | +11,57 | +11,57 |
| ADA | +0,06 | +13,85 |
| SOL | +0,58 | +13,57 |
| AVAX | −0,02 | +12,30 |
| UNI | +0,31 | +12,20 |
| ETH | 0,00 | +11,54 |
| LTC | +0,09 | +10,58 |
| LINK | +0,13 | +10,21 |
| HBAR | +0,05 | +8,09 |
| BTC | 0,00 | +5,86 |
| ATOM | −11,45 | −11,45 |

Con uscita, 17/18 simboli migliorano nella finestra; ATOM peggiora perché
il veto perde il suo successivo guadagno. Bloccare la riapertura di XLM e
l'ingresso DOGE aiuta; chiudere i long precedenti protegge gli altri contributi.
Questa non è una conclusione che quei simboli vadano sempre esclusi.

## Limiti e prossimo esperimento

È un confronto a ordini abbinati, non un nuovo motore con equity/target
ricalcolati. Prezzi e tempi appartengono alla baseline; non si modellano impatto
di mercato, nuove scelte future o esiti oltre la copia. La curva controfattuale
è ancorata all'equity osservata e modificata dalle differenze di cashflow;
non si inventano osservazioni nel buco antecedente al 28 settembre.

Il funding resta stimato e gli eventi sono temporalmente sovrapposti. Un solo
trigger e un mercato in ribasso non distinguono un buon filtro BTC da un taglio
generalizzato del rischio che sarebbe stato vantaggioso dopo qualunque
indicatore coincidente. Mancano episodi in cui il taglio è seguito da rialzo.

Prima di un forward: distinguere la riduzione dovuta a nuovi asset da quella
dovuta a rischio/indebolimento BTC; confrontare un trigger BTC specifico con
un controllo generale di portafoglio; congelare ingresso, uscita e rientro
in una sola variante. Non promuovere il semplice SELL BTC o invertire tutti
i SELL in short. L'ipotesi sulle uscite resta interessante: il campione mostra
che la gestione dell'esposizione già aperta è decisiva.

## Evidenze e verifiche

Script riproducibili: `scripts/analyze_v13_allocation_change.py` e
`scripts/analyze_v13_btc_veto.py`. Dati fuori da Git:
`audit-evidence/v13-btc-veto-20261009/` nella radice del workspace.
Cinque test sintetici verificano limiti delle quantità, costi, funding,
immutabilità degli input e rifiuto di book futuri o alterati. Il replay reale
è stato ripetuto sullo stesso input con risultati identici; errore finale
di riconciliazione della baseline zero. Nessuna verifica è dichiarata indipendente.

Scheda in Test per la qualificazione: diagnosi completata, validazione
scientifica futura non avviata. Nessun nuovo servizio o percorso operativo.
