# FAST e HALF — grafici per simbolo, 13 ottobre 2026

Consegnati `/v13_variants/fast/charts` e `/v13_variants/half/charts`, con
collegamenti nelle pagine dei conti e nella pagina comparativa. Ogni pagina
mostra i 18 grafici, apre il dettaglio del simbolo e offre intervalli 24 ore,
7 giorni o tutto lo storico. BUY/SELL descrivono il lato; il dettaglio spiega
apertura, aumento, riduzione, chiusura o inversione della posizione.

I marker vuoti identificano le operazioni ereditate dalla V13; quelli pieni
identificano i fill della specifica biforcazione. Una linea viola indica il
punto di copia. Il filtro consente di mostrare tutte le operazioni, solo le
ereditate o solo quelle dopo la biforcazione. Origine visibile anche nella
tabella e nel dettaglio selezionabile.

Accanto ai SELL compare un indicatore di profitto, perdita, pareggio, nessuna
esposizione chiusa oppure dato non disponibile. Esito definito come P/L
realizzato della parte chiusa meno la commissione del fill: non include le
commissioni precedenti o il funding e non è il rendimento completo del trade.
Una nuova apertura short non viene etichettata come perdita solo per la fee.
Il dettaglio mantiene distinti realizzato e impatto immediato sull'equity.

## Dati e verifiche

Il nuovo adattatore legge la proiezione atomica del conto e il ledger dei
prezzi esistente. Verifica identità FAST/HALF, tempi e custodia della
proiezione; confronta ogni riga ereditata con il prefisso presente nel ledger;
ricostruisce il prezzo medio e il P/L per fill, evitando di sommare campi
cumulativi. Quantità e prezzo medio finali devono riconciliare con la variante.
Le operazioni originali successive alla copia non entrano nelle biforcazioni.
Per i nuovi fill verifica anche quantità prima/dopo e realizzato dichiarato.

I prezzi pubblici sono condivisi; i marker appartengono al singolo conto.
I prezzi sono limitati alle ultime 20.000 osservazioni per simbolo, con
segnalazione di troncamento e gap. Lo storico dei fill è completo. La panoramica
riduce soltanto i punti visualizzati, conservando estremi e interruzioni.
Per il mark esatto dei nuovi fill verifica hash e tempo del book archiviato;
se manca, l'impatto equity resta sconosciuto, senza sostituzione con altri mark.
La cache conserva solo i riferimenti necessari, non tutti i book e i funding.

- **23 test contabili e di lettura** passano: 12 della base e 11 nuovi, inclusi
  vendita FAST e acquisto HALF sullo stesso simbolo, isolamento dal conto
  originale, prefisso alterato, replay, futuro, costo medio incoerente,
  mark mancante, archivio manomesso, custodia e mancata creazione del DB.
- Dati reali: 18 simboli e 164 fill ereditati in entrambe le panoramiche;
  nessun fill di biforcazione presente al momento della verifica.
- Browser desktop/mobile: panoramiche, dettaglio BTC, origine, filtri,
  esito SELL, API senza cache e grafici originali verificati. Nessun errore
  JavaScript o overflow orizzontale. Screenshot conservati.
- Un SELL post-fork in perdita è stato verificato con dati sintetici intercettati
  **solo nel browser di test**, mai scritti in journal o proiezioni reali.
- Compilazione Python, `git diff --check` e integrità SQLite verificati.

Nessuna modifica al runner economico, alle policy, ai collector o ai ledger.
Aggiornata soltanto l'interfaccia web; i servizi di strategia conservano i propri
avvii. Nessun nuovo download di mercato, grant o credenziale.
La validità scientifica delle strategie resta da osservare nel periodo futuro.

Evidenze locali: `audit-evidence/v13-variant-charts-20261013` nel workspace del
laboratorio. Schedine:

- dati: `work-card-6567dd57-1312-4f35-9b44-dd27730d8e2c`;
- UI: `work-card-f3403e85-c668-4baf-8e1d-e04e6ddb2eea`;
- qualifica: `work-card-fc30b2f9-5ecc-48eb-a6c0-feab2106e9d1`;
- consegna: `work-card-217678ec-a57a-4e7d-835c-cdc27d75c296`.

Esecuzione SINGLE_AGENT; verifica dell'autore, non review indipendente.
