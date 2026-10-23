# Review della proposta M1 del 23 ottobre 2026

**Raccomandazione: CORREGGERE; non approvare la proposta nella forma attuale.**

Proposta `416c2b69344ea67698fdec12f4094b5673c8b6c19b484310482fe9da8b972ada`, creata il 23/10/2026 16:25:57 CEST. Review in sola lettura, SINGLE_AGENT, verifica dell'autore dell'integrazione, non revisione indipendente. Scheda `work-card-e3855103-c502-42b2-9ba9-a30e11061b3e`. Nessuna decisione di approvazione/rifiuto, ordine, modifica alla proposta, al codice operativo, ai servizi o al ledger.

Il difetto principale non è un segno sbagliato nei rendimenti: il nuovo collegamento combina una rotazione ampia, una diversa cadenza di calcolo e un aumento dell'esposizione SHORT potenziale. La review tecnica precedente non aveva valutato adeguatamente questi effetti economici prima di mostrare la proposta come approvabile.

## Segnali verificati e confronto con V13

Verificati SHA-256, tempi e byte di **30 ricevute scientifiche e 88 di mercato** già archiviate; nessun nuovo download di prezzi. Le 121 daily sono contigue dal 24 giugno al 22 ottobre 2026, chiuse e disponibili prima della proposta. Tutte le chiusure normalizzate coincidono con le risposte Binance archiviate. La proposta completa è stata riprodotta identica, inclusi hash, selezione, pesi e stime. Nessun dato futuro utilizzato.

La derivazione originale V13 è stata ricalcolata con i suoi artefatti congelati e le risposte archiviate, senza rete: target identici alla proposta originale attiva. I rendimenti 30/120 alla data del 22 ottobre coincidono per tutti i 18 simboli comuni. Quindi la differenza non nasce da due serie di prezzi discordanti.

| Simbolo | Rendimento 30 giorni | Rendimento 120 giorni | Segnale attuale |
| --- | ---: | ---: | --- |
| AAVEUSDT | -0,89% | 82,63% | Neutro |
| BCHUSDT | -20,41% | 44,45% | Neutro |
| BTCUSDT | -5,54% | 33,31% | Neutro |
| DOTUSDT | -8,76% | 25,19% | Neutro |
| LTCUSDT | -6,56% | 42,91% | Neutro |
| NEARUSDT | 10,35% | 148,40% | LONG |
| QNTUSDT | 153,71% | 172,96% | LONG |
| XMRUSDT | 4,52% | 90,69% | LONG |

I cinque LONG proposti in chiusura hanno momentum a 30 giorni negativo e a 120 positivo: il doppio momentum diventa neutro, non SHORT. AAVE è vicino alla soglia, con -0,89% a 30 giorni. XLM ha invece segnale grezzo SHORT, disabilitato dal filtro BTC: la formula sintetica della UI «perde il segnale» nasconde ragioni differenti. Le 17 esclusioni dall'universo non corrispondono a 17 vendite: dodici sono già FLAT.

La V13 originale mantiene il vettore dell'ultimo ricalcolo **20 ottobre**, secondo i sette giorni ancorati al 1 settembre; la nuova proposta usa direttamente le daily del **22 ottobre**. Dopo l'approvazione, `v13_m1_managed.baseline()` ricalcolerebbe inoltre i pesi ogni giorno, mentre la membership cambierebbe il lunedì. Si cambiano quindi selezione, fase settimanale e frequenza dei segnali/pesi insieme. Non è un confronto che isola il solo cambio di coin.

La proposta non usa P/L M1 per lato, durata o persistenza delle perdite: nessuna metrica del conto entra in `weekly.signals()`. È una selezione momentum completa, diversa dalla prima proposta mirata AAVE/LTC. Ridurre esposizioni con segnale deteriorato è motivato dalla regola; definirle tutte «coin non profittevoli» non sarebbe supportato da questa analisi.

## Pesi e impatto sulla fotografia del conto

| Metrica | Attuale alla proposta | Proposta |
| --- | ---: | ---: |
| Equity virtuale di riferimento | 9919,17 USDT | Stessa base, meno costi |
| LONG detenuti / previsti | 6 | 3 |
| Esposizione LONG lorda | 25,63% | 18,29% |
| Esposizione NEAR | 2,21% | 4,79% |
| XMR, nuovo ingresso | 0% | 11,11% |
| QNT, nuovo ingresso | 0% | 2,38% |
| Volatilità annualizzata stimata del LONG | 13,54% | 13,50% |
| Riferimento SHORT: specchio degli attuali LONG / nuovo budget | 25,63% | 41,71% |
| Volatilità annualizzata stimata a pieno utilizzo SHORT | 13,54% | 22,24% |

Il LONG totale scende: non è un aumento di leva del portafoglio ordinario. Ma il modello continua a mirare al 13,5% annuo stimato, quindi meno capitale investito non equivale qui a un pari calo di rischio modellato. Queste volatilità sono descrittive, su una sola finestra storica di 60 rendimenti, non previsioni certificate o limiti garantiti.

Cinque chiusure complete: AAVE, BCH, BTC, DOT e LTC. Tre acquisti/aumenti: NEAR, QNT e XMR. La rotazione teorica è **3912,16 USDT, 39,44% dell'equity**, su otto operazioni. NEAR viene più che raddoppiato: non si sta soltanto liberando liquidità senza aumentare i superstiti.

La UI stima un costo immediato di 5,58 USDT; il simulatore effettivo, eseguito esclusivamente in memoria sulle medesime quantità e sul medesimo book, dà **5,74 USDT**, di cui 2,35 di fee. La differenza di circa 0,15 USDT deriva dal trattamento effettivo dei prezzi/tick: il preview è indicativo. Il realizzato delle chiusure sarebbe circa -9,92 USDT, ma era già contenuto nel P/L aperto e non va sottratto di nuovo all'equity. Funding successivo e prezzi futuri non sono inclusi.

All'atto della proposta, il gate «un solo ribilanciamento ordinario al giorno» negherebbe i tre aumenti e consentirebbe le cinque riduzioni. Prima del successivo slot resterebbe solo il LONG NEAR esistente, circa **2,21%** dell'equity. L'esito non è quindi una transizione simultanea garantita fra due portafogli. Dopo un consenso reale potrebbero esserci attese, prezzi differenti e fill parziali.

### Perché XMR pesa tanto

L'allocazione è stata ricalcolata anche con formula indipendente: coincide con il codice V13. Il punteggio sceglie i simboli, il peso usa la volatilità inversa e la covarianza; non sono la stessa graduatoria. Le volatilità annualizzate osservate sono XMR 60,29%, NEAR 139,73%, QNT 281,46%.

XMR riceve il **60,76% del capitale LONG investito**, pur essendo l'11,11% dell'intera equity. Nel modello il suo contributo alla varianza è invece circa 31,32%: non è corretto dire che abbia il 61% di tutto il rischio. Il calcolo è coerente, ma manca un limite di concentrazione relativo al paniere e una transizione graduale per una nuova coin. Il cap assoluto esistente del 31,5% per asset non risolve questa concentrazione relativa.

A titolo di sola sensibilità aritmetica statica, un -10% isolato di XMR sulla posizione proposta varrebbe circa -110,23 USDT; non è una probabilità o previsione, né simula la reazione M1.

### Il budget SHORT è il problema più sostanziale

Il vecchio M1 specchierebbe gli attuali LONG: riferimento 2542,42 USDT, 25,63%. La proposta conserva quei budget e somma quelli di QNT/XMR e l'aumento NEAR: massimo approvabile **4136,85 USDT, 41,71%, +62,71%** rispetto al riferimento corrente.

A pieno utilizzo, lo stesso modello di covarianza stima circa 22,24% annuo per lo SHORT, contro 13,54% del riferimento. È una capacità potenziale: servono il filtro M1, dati, liquidità e tutti i gate; non è un ordine certo. Rimane entro 90% lordo e 31,5% per asset, ma non conserva il rischio economico precedente. Questo effetto del nuovo collegamento andava valutato ed esposto prima dell'approvazione.

## Qualità delle ammissioni

I book della fotografia e le daily sono sufficienti per il controllo puntuale implementato. Non dimostrano affidabilità nel tempo. La qualifica A/B/C 2–16 ottobre resta NOT_QUALIFIED; QNT aveva profondità sufficiente nel 94,4858% dei campioni contro 95% richiesto. Questo non prova che l'ordine paper da circa 238 USDT sia impossibile — il vecchio test usava 3.150 USDT — ma un book odierno non annulla il risultato storico. Occorre una motivazione d'ammissione proporzionata alla quantità reale, separata dal semplice punteggio momentum. QNT ha inoltre +153,71% a 30 giorni e volatilità elevata: un punteggio forte non è una previsione di profitto futuro.

Fonte interna precedente: `reports/LAB_PRIORITY_REMEDIATION_2026-10-19.md`, sezione A/B/C. Per il principio generale, [Investor.gov — allocazione e diversificazione](https://www.investor.gov/introduction-investing/getting-started/asset-allocation) distingue allocazione e distribuzione del rischio: il numero e i pesi degli investimenti vanno valutati insieme. La raccomandazione qui deriva dai dati e dal codice del lab, non da una raccomandazione esterna su singole crypto.

## Correzione raccomandata, non applicata

1. Separare la manutenzione delle posizioni esistenti dall'ammissione di nuove coin e dall'aumento dei loro budget SHORT. Consentire decisioni distinte in UI, con nuovo identificatore/versione e nessuna riscrittura della proposta archiviata.
2. Prima fase protettiva graduale: sospendere i riacquisti dei LONG deteriorati e ridurli parzialmente, senza raddoppiare NEAR o ridistribuire automaticamente la liquidità. L'eventuale uscita completa deve essere esplicita, con distinzione fra perdita del momentum, dati mancanti e perdita economica persistente. Non inventare ora soglie «ottimali» sulla singola settimana osservata.
3. Mantenere il massimo SHORT aggregato coerente con il budget precedente: i nuovi ingressi devono ripartirlo, oppure richiedere una decisione separata e visibile di aumento del rischio. Esibire in UI totale precedente/proposto, contributi al rischio stimato e peggioramento della concentrazione.
4. Conservare una cadenza di calcolo esplicita e comparabile con la V13, evitando di cambiare insieme universo, fase e frequenza dei segnali/pesi. Il filtro M1 intraday rimane separato e invariato.
5. Valutare QNT/XMR come ammissioni graduali dedicate, con cap iniziale di transizione e controllo di liquidità alla quantità proposta, senza fingere superata la qualifica A/B/C. Nessuna attesa scientifica aggiuntiva viene inventata come prerequisito assoluto al paper di ricerca; i limiti dell'evidenza devono essere chiari.

Per rendere concreta l'alternativa, ho calcolato due sole sensibilità sulle stesse quantità, book e costi; nessuna ottimizzazione o esecuzione:

| Alternativa illustrativa | LONG lordo dopo | Turnover USDT | Costo immediato USDT | Nuove coin |
| --- | ---: | ---: | ---: | ---: |
| Proposta corrente completa | 18,29% | 3912,16 | 5,74 | 2 |
| Dimezzare i cinque LONG uscenti, NEAR invariato | 13,90% | 1163,57 | 1,73 | 0 |
| Dimezzare solo AAVE/LTC come nella bozza iniziale | 21,29% | 430,90 | 0,78 | 0 |

Il dimezzamento è un esempio comprensibile di gradualità, non la prova che il 50% sia la soglia migliore. Queste alternative non sono proposte approvabili nel sistema attuale e non ne modificano lo stato: servono una versione corretta e consenso esplicito. Non usare il pulsante della proposta corrente per applicare una variante discussa a parole.

## Metodo e custodia

Script riproducibile `scripts/review_m1_weekly_proposal.py`, immagine Python locale già usata dal runtime, rete disabilitata e mount dei dati operativi in sola lettura. Nessuna istanza Runner o Store operativa; il planner puro produce soltanto risultati in memoria. Originale ricostruita con payload archiviati e artefatti congelati. Copie coerenti dei due ledger e delle approvazioni, integrity_check `ok` eseguito sulle copie.

La copia del conto era successiva alla proposta: per ricostruire la fotografia sono state conservate quantità/entry/fee e sottratti soltanto gli eventi funding successivi presenti nel journal (netto -0,21 USDT). Verificata assenza di trade successivi; dopo il riavvolgimento l'equity coincide con il riferimento della proposta. Non è stato cambiato alcun saldo operativo.

Evidenze private in `audit-evidence/m1-proposal-review-20261023/`: proposta, science, book, copie SQLite, manifest, confronto originale e risultati numerici. Nessun dato grezzo o segreto incluso nel commit. Restano UNKNOWN i minimi KuCoin reali e BLOCKED la readiness exchange-faithful; tutte le sensibilità si riferiscono al contratto sintetico del paper.

## Schedine residue

- `work-card-39a46574-e72f-4502-89b3-ce2d5366451c` — Proposta M1 v2: transizione graduale e budget SHORT aggregato: **To-do**. Nessuna implementazione o attivazione eseguita in questa review.
- `work-card-18bcbced-ced7-4cac-b795-4be9217a1d7e` — UI M1: riepilogo rischio e decisioni separate sulle variazioni: **To-do**. Nessuna implementazione o attivazione eseguita in questa review.

Verifica finale: stesso hash della proposta, stato PROPOSED, zero decisioni registrate, nessuna policy di manutenzione applicata; runtime/configurazioni e tredici servizi operativi invariati e healthy.
