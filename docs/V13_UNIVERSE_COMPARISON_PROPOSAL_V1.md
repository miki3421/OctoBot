# V13 · proposta di confronto 18 contro 29 asset

**30 settembre 2026 · DRAFT, non approvata e non avviata.** Il paper V13
esistente continua invariato. Nuovo esperimento candidato:
`v13-universe-expansion-research-v1`. Non è il BTC 30/120, non eredita la
validità scientifica della V13 né cambia i due esperimenti BTC programmati.
Scheda: `work-card-a194e93c-6997-401c-85cb-e953be6c44c5`.

## Domanda e confronto equo

Domanda: aggiungere un insieme congelato di crypto migliora il risultato netto
della stessa regola V13, senza un peggioramento sostanziale di rischio e costi?

Proponiamo **due simulazioni nuove**, separate dal conto V13 oggi attivo:

| | Controllo A | Variante B |
| --- | --- | --- |
| Universo | I 18 asset V13 originali | Gli stessi 18 + 11 candidate con dati verificati |
| Avvio | Stesso futuro slot UTC approvato | Stesso slot |
| Stato iniziale | Flat, 10.000 USDT virtuali | Flat, 10.000 USDT virtuali |
| Strategia | Regola V13 originale | Stessa regola, input universo ampliato |
| Segnale/ribilanciamento | Daily 30/120, ogni 7 giorni | Identici e sincronizzati |
| Parametri | Volatilità target 13,5%, lordo 90%, asset 31,5% | Identici |

Le 11 aggiunte proposte sono QNT, SUI, PUMP, HYPE, TAO, INJ, ENA, XMR, ASTER,
ARB, ONDO. Derivano dal filtro esplorativo congelato **prima** delle misure:
nessuna selezione sulla correlazione o sul profitto. PEPE rimane nella rosa
originale di 12, ma viene proposto **in sospeso** nel confronto v1 per il mapping
non provato. Nessun sostituto; includerlo più avanti richiede nuova versione
prima del relativo periodo valutativo. L'owner deve approvare questa scelta.

Non confrontare il P/L cumulato di B col conto operativo esistente: quel conto
ha altre posizioni e un'altra storia. A è un controllo nuovo che usa l'universo
originale, non un clone della sua autorità o dei suoi risultati. I conti A/B
non esistono ancora e non hanno issuer, grant, ledger o servizi attivati.

## Fase preliminare proposta: 14 giorni di qualità dati

Prima dei fill: osservare tutti i 29 asset per 14 giorni consecutivi, con
book KuCoin depth20 ogni 15 minuti, metadata giornalieri delle due venue,
daily Binance chiuse e funding pubblicato. Stesse scadenze, ricevute e clock
per A e B; richieste entro 60 secondi dal medesimo slot, book recenti alla
ricezione entro 60 secondi. Nessuna credenziale. Raccolta candidata distinta
dagli observer esistenti; **l'autorizzazione una tantum precedente è esaurita**.

Piano nominale: 38.976 GET book + 406 daily + 406 funding + 28 metadata =
**39.816 GET** in 14 giorni (29 asset). Massimo proposto 42.000 tentativi,
comprensivi di pagine o retry; cap disco raw compresso 512 MiB. Al limite:
arresto della raccolta e segnalazione, nessuna cancellazione. Nessun rinnovo
automatico. 429/418 o errori persistenti sospendono la raccolta. Implementazione
e autorizzazione specifica di questa fase sono ancora da ottenere.

Criteri candidati prima di iniziare: copertura ≥95% per asset e per slot
completo dell'intero paniere, nessun buco comune oltre 2 ore; p95 dello spread
≤20 bps; bid **e** ask con almeno 3.150 USDT di nozionale visibile in almeno
95% dei campioni validi di ogni asset. 3.150 è il massimo peso iniziale
31,5% × 10.000, non una quantità d'ordine o una prova di slippage accettabile.
Depth20 può coprire distanze di prezzo diverse: riportare anche distanza del
livello estremo e costo VWAP della quantità teorica, senza inventare fill.
Non confondere 20 bps di spread con i 2 bps di slippage avverso del simulatore.

I numeri sono **soglie proposte, non approvate**. Se un asset fallisce, non
rimuoverlo silenziosamente: il paniere proposto non supera la qualifica.
Rivedere la proposta con nuova versione, mantenendo le evidenze e dichiarando
consumato il periodo già osservato. Nessuna analisi di profitto in questa fase.

## Fase valutativa proposta: 180 giorni forward

Partenza solo dopo qualifica, test del runner e approvazione dell'owner:
`start_utc = null` fino ad allora. 180 giorni UTC consecutivi; nessuna modifica
al paniere o ai parametri. Warm-up causale comune, almeno 121 chiusure daily
contigue; i 366 giorni già scaricati servono a sviluppo e warm-up, non sono
out-of-sample. La selezione è basata sui contratti oggi disponibili: nessuna
pretesa di backtest storico senza survivorship bias.

Il runner deve fissare la stessa fase di ribilanciamento per i due bracci e
dimostrare la parità del controllo A con la funzione V13 originale. Non
riscrivere i file originali fissati dagli hash; usare un adattatore isolato e
versionato, con nuova lineage e nessuna promozione automatica.

Regole economiche candidate uguali: fill sul book osservato, cap alla profondità,
VWAP più 2 bps avversi, fee max(taker pubblica, 6 bps), funding esplicitamente
stimato; minimi simulati separati 1 incremento / 1 USDT. Riproporre per entrambi
stop nuovi ingressi a perdita giornaliera 2% o drawdown 10%, un aumento di rischio
al giorno UTC e cooldown 22 ore, senza reset al riavvio. **L'approvazione della
policy del conto V13 non viene trasferita automaticamente ai due conti nuovi.**
Minimi reali KuCoin UNKNOWN e gate exchange-faithful invariati.

Dati comuni mancanti: nessun nuovo rischio in entrambi i bracci; riduzioni
protettive restano separate, senza inversioni. Valutazioni mancanti non
interpolate; registrare mancati ingressi, fee, funding, turnover e shortfall
di quantità. Delisting/sospensioni non comportano rimpiazzi: sospendere il nuovo
rischio sul confronto e classificare la valutazione come non completata.

## Metriche e decisione finale candidata

Metrica primaria: differenza fra i rendimenti netti finali B e A, con lo stesso
capitale iniziale; riportare separatamente costi, funding stimato e P/L aperto.
Secondarie: drawdown, volatilità, turnover, esposizione, concentrazione e
contributi per simbolo; turnover/fill non sono osservazioni indipendenti.

Prima della valutazione finale richiedere tutti i 180 giorni trascorsi, almeno
95% degli slot con dati comuni validi, nessun cambio di codice/parametri o
lineage e almeno 20 decisioni di ribilanciamento comuni. In caso contrario:
**INCONCLUSIVE**, senza estendere il periodo finché appare favorevole.

Esito candidato «merita ulteriore ricerca»: delta netto positivo, rendimento
netto B positivo e drawdown B non superiore ad A di oltre 2 punti percentuali.
Altrimenti «nessun miglioramento dimostrato da questa prova». Nessuna soglia
può autorizzare trading reale o modificare la V13. Mostrare l'incertezza con
bootstrap a blocchi di 7 giorni sulla serie **appaiata** dei rendimenti netti
(10.000 repliche, seed 13029, intervallo percentile 95% del delta cumulato);
non presentarlo come prova definitiva con soli 180 giorni/26 settimane circa.

Monitoraggio quotidiano della salute; verifica operativa settimanale. Una
dashboard può mostrare progressi descrittivi ma nessuna decisione anticipata
di efficacia o ottimizzazione sui risultati intermedi. La raccolta durante
i 180 giorni avrà un piano e un'autorizzazione propri: i 14 giorni non la coprono.

## Decisioni richieste prima dell'esecuzione

| Decisione | Raccomandazione candidata | Cosa rimane fermo |
| --- | --- | --- |
| Universo | A=18, B=29; PEPE sospeso, nessun sostituto | Freeze finale del confronto |
| Qualifica | 14 giorni e soglie esplicite sopra | Collector separato e GET periodiche |
| Confronto | 180 giorni, due conti flat da 10.000, regole simmetriche | Runner, issuer e ledger dei nuovi bracci |
| Esito scientifico | Criteri e incertezza predefiniti, nessuna promozione | Valutazione conclusiva |

L'owner può approvare o modificare la proposta. In questo checkpoint vengono
consegnati documenti e UI; nessuna di queste decisioni è registrata come approvata.
