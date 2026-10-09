# Misure descrittive della rosa v1

Autorizzazione owner ricevuta il 30 settembre 2026: acquisizioni pubbliche una
tantum Binance Futures e KuCoin Futures per la rosa congelata di 12 candidate
e, per le candele, i 18 asset V13. Nessun ordine, credenziale, servizio nuovo
o ampliamento del paper. Questo piano precede l'acquisizione e il calcolo.

- Binance: `exchangeInfo`; `klines` daily, ultime 366 barre UTC chiuse;
  `fundingRate` nello stesso intervallo per le sole candidate, con paginazione
  limitata a 12 pagine da 1000 eventi. Eventuale troncamento esplicito.
- KuCoin: `contracts/active` e un `level2/depth20` per ciascuna candidata.
  Conservare bytes, URL pubblico, codice HTTP, tempi e SHA-256 di ogni richiesta.
- Mapping solo per corrispondenza esatta di asset base e USDT, contratto
  perpetual aperto sulle due venue. Non dedurre equivalenza di token con
  prefissi/moltiplicatori (es. 1000) e non sostituire simboli senza evidenza.
- Nessun riempimento delle barre mancanti. Conteggio delle date attese,
  duplicati, ordine temporale, close finito positivo, chiusura anteriore al
  limite. Barre fuori intervallo respinte. Copertura completa solo a 366/366.
- Correlazione di Pearson su **180 rendimenti giornalieri semplici** delle
  ultime 181 chiusure consecutive fino all'ultima giornata chiusa, per tutte
  le candidate e i 18 riferimenti sulle stesse date. Varianza zero o dati
  insufficienti: nessun valore. Mostrare la controparte con massimo valore
  assoluto e la correlazione con BTC, mantenendo segno e intervallo. Nessuna
  soglia di promozione o esclusione viene applicata alla correlazione.
- Book: spread sul punto medio in bps e nozionale dei livelli visibili per
  ciascun lato (quantità contratti × multiplier × prezzo). Book incrociato,
  non ordinato, incompleto o con timestamp oltre 60 secondi dalla ricezione:
  non misurabile. La misura è una fotografia datata, non una stima persistente
  della capacità eseguibile, slippage o fill.
- Funding: riportare solo eventi osservati e primo/ultimo timestamp. Non
  certificare copertura dei pagamenti in assenza di prova della frequenza
  applicabile. Non sommare rate come profitto o costo di una strategia.

Una raccolta corrente non costituisce un dataset point-in-time per un backtest
storico. Non selezionare i superstiti oggi per attribuire validità retroattiva.
Nessuna performance di trading viene calcolata o ereditata. La rosa e le sue
priorità esplorative restano congelate anche se il mapping o i dati falliscono.
