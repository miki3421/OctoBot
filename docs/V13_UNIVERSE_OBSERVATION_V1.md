# Universo V13 e lista candidati · vista osservativa v1

30 settembre 2026. Pagina `/v13_candidates`, collegata da `/v13_paper`.
La richiesta approvata è rendere consultabili le possibili aggiunte e le ragioni
di inclusione/esclusione dalla **lista di ricerca**. Non modifica i 18 asset
della V13, non avvia un esperimento, non promuove simboli al paper.

## Fonte e classificazione

La pagina legge esclusivamente l'ultima `market.json` già pubblicata dal
collector V13 e la prima ricevuta associata, relativa a KuCoin Futures
`/api/v1/contracts/active`. Nessun download, collector, timer o dipendenza nuova.
Controlla proprietario del file, permessi, hash del record, identità e hash della
ricevuta, hash dei byte originali, endpoint esatto, esito HTTP/API e tempi.
Il contratto locale dell'universo originale resta fissato al suo SHA-256
`5dfa8ade1eb8b22bf92fe6c88658d4a433be80def181b97d73f4f9bd380911b8`.
Questa verifica attesta la coerenza con la cattura locale del custode;
non è una firma dell'exchange o una valutazione scientifica.

| Gruppo | Regola della sola vista |
| --- | --- |
| V13 attuale | I 18 simboli e il mapping del contratto originale. Restano visibili anche se assenti dalla risposta pubblica, con avviso. Non sono il conteggio delle posizioni aperte. |
| Da approfondire | Nuovo simbolo con `status=Open`, `quoteCurrency=USDT`, `settleCurrency=USDT`, `isInverse=false`, `assetClass=CRYPTO`, `marketStage=NORMAL`, `expireDate=null` esplicito. |
| Fuori ambito | Almeno un metadata dichiara un'incompatibilità con il formato della lista: altra classe/valuta, inverso, scadenza, mercato preliminare o contratto non aperto. Motivo esplicito. |
| Dati incompleti | Nessuna incompatibilità nota ma almeno un campo necessario alla classificazione manca o è invalido. |

I filtri sono criteri descrittivi di questa vista, **non criteri approvati di
ammissione all'esperimento**. Data di prima apertura e turnover delle ultime
24 ore vengono dalla risposta. La prima non prova disponibilità di candele;
il secondo non dimostra liquidità persistente né rendimento. L'ordinamento
iniziale confronta solo turnover con quotazione USDT, poi il nome; altre valute
e dati mancanti vengono dopo. Non usa rialzi recenti o risultati della strategia.

Per nuove candidate sono esplicite quattro verifiche ancora da fare: storico
daily/funding continuo, spread/profondità nel tempo, mapping con dati Binance,
costi e correlazioni con la V13. Nessuno storico per nuove coin viene dichiarato
inesistente: qui non è stato verificato. Nessuna soglia quantitativa viene
inventata. `min_quantity` e `min_notional` restano null/UNKNOWN.

## UI e isolamento

Ricerca per contratto o alias originale (BTC → XBT), filtri, ordinamento,
paginazione da 25 righe e motivazioni espandibili. Aggiornamento ogni 60 secondi.
Oltre 15 minuti la cattura rimane consultabile come **non recente**: è una
soglia della UI, non modifica alcun gate di esecuzione. Cattura futura, alterata,
mancante o illeggibile: elenco non disponibile, righe precedenti rimosse.
Nessun valore sostitutivo per dati mancanti; zero osservato resta distinto da null.

Le due route usano i controlli esistenti di login, termini e profilo. L'API è
GET, `Cache-Control: no-store`, con proiezione pubblica ridotta, senza percorsi
locali o payload raw. Il browser inserisce dati come testo, senza HTML dinamico.
Il modulo non legge ledger, credenziali, ricerche BTC sigillate o risultati Qwen;
non scrive e non è importato da strategy, issuer o executor.

## Prossimo lavoro, non avviato

Proporre criteri e una rosa più piccola prima di raccogliere nuovi storici o
valutare una variante. Un eventuale confronto va definito e versionato prima
dei risultati, con autorizzazioni specifiche per nuove acquisizioni. La V13
attuale rimane il riferimento invariato.
