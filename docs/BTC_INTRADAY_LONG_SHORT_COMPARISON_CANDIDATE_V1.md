# BTC intraday LONG + SHORT — preparazione del confronto

21 ottobre 2026 · **Candidato offline, non attivato; validità scientifica UNASSESSED.**
Il [contratto numerico](research-protocols/btc-intraday-long-short-comparison-candidate-v1.json)
e il kernel `btc_intraday_long_short_candidate.py` sono nuovi e separati.
Non sono modificati protocollo, sorgenti, ledger, posizioni o schedulazione
del conto intraday esistente, né Originale, FAST, HALF, M1 o le osservazioni.
Nessun nuovo conto, grant o processo è creato da questa preparazione.

## Ipotesi e segnali

Il filtro attuale cerca soltanto ribassi. La candidata aggiunge un'ipotesi LONG
simmetrica, fissata prima di nuove osservazioni e **non validata**:

| Condizione su un'ora | Controllo SHORT-only | Candidata LONG + SHORT |
| --- | --- | --- |
| BTC ≤ −1% e almeno 12/18 simboli con ritorno < 0 | SHORT | SHORT |
| BTC ≥ +1% e almeno 12/18 simboli con ritorno > 0 | Nessun segnale | LONG |
| Altre condizioni complete | Nessun segnale | Nessun segnale |
| Input mancanti, tardivi o non causali | MISSING | MISSING |

L'universo resta quello dei 18 simboli originali, BTC incluso. Un ritorno zero
non contribuisce a nessuno dei due conteggi. Si decide ogni cinque minuti UTC,
con 289 punti contigui di warm-up e quote di tutti i simboli già ricevute e
persistite al rispettivo cutoff, vecchie al massimo 120 secondi. Il rendimento
orario usa il punto attuale e quello di dodici intervalli prima. La decisione
scade dopo 30 secondi. Non si recuperano ingressi persi con informazioni tardive.

Il kernel produce solo decisioni `research_only=true`, `issuable=false`.
L'identità dipende da versione, braccio, slot e hash dei prezzi causali:
aggiungere dati futuri o cambiare un timestamp non-feature ancora ammissibile
non cambia una decisione passata. La provenienza raw e le ricevute di custodia
restano evidenze separate, da verificare nel futuro runner.

## Esecuzione, rischio e costi comuni

La size assoluta mantiene la formula attuale:

`N = min(0,10 × equity, 0,0025 × equity / 0,0128, 0,010 × prezzo BTC)`

`|q| = floor(N / prezzo / 0,001) × 0,001 BTC`.

Il segno è positivo per LONG e negativo per SHORT. Al fill la quantità può solo
diminuire, considerando anche equity dopo i costi; nessun aumento per superare
un minimo. Esposizione massima 10%, perdita giornaliera 2%, drawdown 10%,
una sola posizione o intento alla volta, nessun pyramiding, nessuna quota
giornaliera e nessun cooldown aggiunto. Un segnale opposto durante la posizione
si registra ma non provoca inversione né una nuova uscita. Solo dopo flat
confermato può essere ammesso un nuovo slot strettamente successivo.

| Regola | LONG | SHORT |
| --- | --- | --- |
| Apertura | BUY sulla profondità ask | SELL sulla profondità bid |
| Chiusura | SELL sulla profondità bid | BUY sulla profondità ask |
| Stop 1% dal prezzo effettivo d'ingresso | Bid ≤ ingresso × 0,99 | Ask ≥ ingresso × 1,01 |
| Take profit 2% | Bid ≥ ingresso × 1,02 | Ask ≤ ingresso × 0,98 |
| Tempo massimo | Sei ore dal fill | Sei ore dal fill |

L'ingresso segue lo slot successivo (+300 secondi), latenza 500 ms e finestra
ulteriore di un secondo; richiede dieci secondi L5 completati e profondità
intera sui cinque livelli. Le uscite usano un book nuovo dopo latenza,
possono ridurre parzialmente e mantengono il residuo pendente. Il prezzo del
trigger non è un fill garantito; un recupero non annulla un'uscita già richiesta.
Priorità: amministrazione, integrità/contabilità, rischio, stop, tempo, take profit.

Fee **6 bps per fill**, slippage aggiuntivo avverso **1 bps**, oltre a spread
e VWAP osservati. BUY arrotondato al tick verso l'alto, SELL verso il basso.
Scenario stress indipendente per ciascun braccio: latenza 1 secondo, fee 12 bps,
slippage 2 bps, debiti funding doppi e crediti nulli; propri fill, uscite e rischio.
Stessa tariffa non significa stessi costi totali: numero di trade, profondità
e tempo esposto possono differire e vanno riportati.

Il contratto resta **sintetico**: conversione assunta 0,001 BTC per unità raw,
passo/minimo simulato 0,001 BTC, minimo nozionale simulato 1 USDT, tick 0,1 USDT.
I veri minimi KuCoin restano **UNKNOWN**; nessuna prova qui certifica P0-03
o ammissibilità exchange-faithful.

Funding: `−quantità_firmata × mark_precedente × tasso_finale_firmato`.
Con tasso positivo il LONG paga e lo SHORT riceve; con tasso negativo viceversa.
Servono calendario osservato, tasso finale e mark exchange causale, non il mid.
Importi mancanti restano pending e impediscono nuovo rischio. Restano il veto
ingresso entro ±60 secondi dal settlement, mark precedente massimo 60 secondi,
calendario massimo cinque minuti e uscita protettiva per pending oltre 15 minuti.
La gestione del confine deve considerare **anche SELL negativi che chiudono LONG**:
il filtro attuale `quantity > 0` trova solo le chiusure SHORT e non va riutilizzato
senza adattamento. Selezionare il cashflow meno favorevole fra quantità ai confini,
conservare entrambi i limiti e non riscrivere decisioni o curve già pubblicate.

## Come confrontare senza alterare il conto attuale

La candidata non può ereditare retroattivamente le performance del 17 ottobre.
Il disegno primario propone due **nuovi bracci**, entrambi flat a 10.000 USDT:

- `btc-intraday-short-control-v1`: regola SHORT attuale, costi e vincoli congelati;
- `btc-intraday-long-short-v1`: aggiunge soltanto l'ammissibilità LONG.

T0 è ancora **null**: stessa futura mezzanotte UTC dopo qualifica del bundle e
autorizzazione esplicita all'avvio. T1 = T0 + 90 giorni, senza estensioni guidate
dal PnL. Entrambi ricevono le stesse ricevute causali, ma hanno stato, esposizione,
fill e halt indipendenti. Non si confrontano solo i trade eseguiti da entrambi:
un LONG può occupare la candidata e impedirle uno SHORT successivo, effetto
che fa parte della strategia e deve restare nel risultato.

Il conto SHORT già attivo continua invariato e può essere mostrato **sullo stesso
intervallo** come contesto, con equity/posizioni iniziali e copertura esplicite.
Non è il controllo flat: ha storico, eventuali halt e fine finestra propri
(l'avvio originario del 18 ottobre termina il 16 gennaio 2027). Copiarlo ora
o confrontare guadagni da date diverse confonderebbe stato iniziale e direzione.
Non si estende la sua finestra per farla coincidere con quella nuova.

Metrica primaria: differenza del PnL netto totale LONG+SHORT meno SHORT-control
su tutta la finestra, incluse settimane senza trade. Mostrare separatamente
LONG, SHORT, costi, funding, drawdown, turnover, tempo esposto, segnali,
rifiuti/mancati fill e SHORT soppressi dall'occupazione LONG. Non dichiarare
un confronto a parità di rischio realizzato: sono uguali le regole di rischio.

Il JSON propone criteri preregistrati: almeno 20 episodi chiusi in 20 giorni e
otto settimane ISO per ciascun braccio, copertura slot ≥95%, nessuna esposizione
o contabilità irrisolta. Per una review positiva: utile candidato base/stress
positivo, drawdown entro 10%, differenze di PnL base e stress positive e limite
unilaterale 95% della differenza dei rendimenti settimanali base sopra zero.
Rendimento settimanale = variazione dell'equity fra estremi della settimana UTC,
divisa per equity al suo inizio; differenza candidata meno controllo. Includere
settimane parziali e senza trade. Bootstrap sulle differenze settimanali:
10.000 ricampionamenti con reinserimento, seed 20261021, quinto percentile
nearest-rank (`ceil(0,05 × N) − 1` dopo ordinamento). Nessun refit o selezione
dopo i risultati. Il valutatore statistico **non è implementato in questa consegna**.
Dati insufficienti danno INCONCLUSIVE, non successo; nessuna promozione automatica.

## Preparazione disponibile e lavoro successivo

Il kernel offline comprende segnale causale, sizing, stima di esecuzione,
trigger di uscita, aritmetica funding firmata e confronto descrittivo su griglia
completa identica. Non contiene writer, accesso ai conti, scheduler o rete.
Gli helper prezzo/funding non attestano custodia, freschezza o persistenza:
sono primitive, non controlli di ammissione né ledger simulati completi.

Prima di avviare i due bracci occorrono, nell'ordine:

1. Runner isolato con stato durevole, signed position/generazione, uscita
   amministrativa per entrambe le direzioni e riconciliazione funding LONG-aware.
   Replicare le tracce SHORT del riferimento, compresi confini numerici:
   il kernel usa Decimal, il runner storico usa float per rendimenti/contabilità.
   I test di parità economica coprono pricing/sizing, non l'intera macchina a stati.
2. Qualifica prospettica delle stesse ricevute per entrambi, stress indipendenti,
   fault injection/riavvio/storage, confronto senza cancellare i buchi, bundle
   immutabile e valutatore scientifico congelato. Nessun fill retrodatato.
3. Autorizzazione dell'avvio esatto, receipt comune T0/T1, conti separati,
   monitoraggio e pagina UI distinti. Questo incarico prepara, non attiva.

Le schedine To-do rendono visibile questo seguito; i conti esistenti restano
in esecuzione. Il kernel e le fixture non provano redditività, efficacia LONG
o ammissibilità KuCoin.
