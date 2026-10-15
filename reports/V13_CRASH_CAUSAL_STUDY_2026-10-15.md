# V13: calo del 14–15 ottobre, cause e possibilità di reazione intraday

15 ottobre 2026. Studio offline esplorativo, SINGLE_AGENT; verifica dell'autore, non review indipendente. Originale, FAST e HALF restano invariati. Nessun nuovo servizio, download di dataset, ordine, approvazione o grant. Consultate fonti pubbliche sul contesto macroeconomico. I risultati non qualificano l'ammissibilità KuCoin: min_quantity e min_notional reali restano UNKNOWN.

Schede: ricerca `work-card-1156f73d-fe12-447d-b39f-47368739327e`; diagnostica `work-card-a70c873b-71b2-4158-afc2-2a86b5af336a`; verifica `work-card-90d7f1d1-8c63-4c90-bbab-2bc0e47adeb5`. Evidenze locali nella radice workspace: `audit-evidence/v13-crash-20261015/`.

## Risposta alla domanda

Il calo contiene un evento macro riconoscibile e una successiva accelerazione notturna. Il portafoglio era esposto nella stessa direzione su molti asset. FAST e HALF ne hanno attenuato le perdite riducendo il long; nessuna delle due è progettata per convertire automaticamente un deterioramento intraday in short.

Due regole causali semplici avrebbero aperto short redditizi in alcuni tratti. La regola più tempestiva perde, però, sull'intero campione disponibile; quella meno frequente resta debolmente positiva e sensibile ai costi. Non abbiamo dimostrato di poter prevedere questo crollo prima del primo shock. Abbiamo individuato informazioni con cui provare a reagire dopo l'inizio del deterioramento. Un calendario macro avrebbe permesso di conoscere in anticipo l'orario del rischio, non il segno della sorpresa.

## 1. Cosa è successo al conto

Copie SQLite coerenti di originale e paired, entrambe `PRAGMA integrity_check=ok`. Posizioni iniziali, costi medi, tutti i fill e gli eventi funding successivi alla biforcazione sono stati ricostruiti. Le tre equity registrate finali riconciliano con errore inferiore a 0,000001 USDT usando i rispettivi mark effettivi. Il confronto sottostante rivaluta invece tutti gli account sugli stessi prezzi originali, disponibili prima di ciascun istante: evita di attribuire al modello differenze fra clock delle quotazioni.

| Istante UTC | Ora italiana | Originale USDT | FAST USDT | HALF USDT |
|---|---|---:|---:|---:|
| 13 ottobre 14:55:36, copia | 16:55:36 | 9964,76 | 9964,76 | 9964,76 |
| 14 ottobre 12:25, prima del CPI | 14:25 | 9964,99 | 9963,77 | 9963,77 |
| 14 ottobre 12:35 | 14:35 | 9940,91 | 9952,32 | 9952,32 |
| 14 ottobre 18:30 | 20:30 | 9894,81 | 9930,34 | 9930,34 |
| 15 ottobre 02:20 | 04:20 | 9873,42 | 9921,47 | 9920,93 |
| 15 ottobre 02:30 | 04:30 | 9829,18 | 9902,85 | 9901,42 |
| 15 ottobre 07:25:03, limite comune | 09:25:03 | 9847,39 | 9910,28 | 9909,38 |

Dalla copia: originale −117,37 USDT; FAST −54,48; HALF −55,38. Le varianti conservano circa 63 USDT in più dell'originale. Questo dato riguarda un episodio breve e ribassista, non dimostra superiorità futura.

**Primo tratto, 14 ottobre 12:25→18:30 UTC:** originale −70,17; FAST/HALF −33,43 ciascuna. Tutti i 18 prezzi scendono; 15 posizioni aperte contribuiscono negativamente, tre asset sono flat. BTC −2,46%, ETH −3,33%, LINK −4,17%, NEAR −5,93%, ZEC −7,52%. I principali contributi negativi originali sono BTC −6,19, LINK −6,11, ETH −5,86 e ZEC −5,64 USDT. Prima dello shock il nozionale lordo e netto erano entrambi circa 2016 USDT per l'originale e 948 per le varianti: esposizione direzionale long comune.

**Secondo tratto, 15 ottobre 02:20→02:30 UTC:** originale −44,23; FAST −18,62; HALF −19,51. BTC −0,95%, ma DOT −4,19%, AVAX −3,73%, ADA −3,26%, ETH −2,81%. DOT, ETH, AVAX e ADA spiegano circa 18,48 USDT della perdita originale nei dieci minuti. Il peggior intervallo osservato, 02:20:02→02:25:19 UTC, vale −43,78 USDT per l'originale. Il rischio delle altcoin non è riassunto interamente dalla variazione percentuale BTC.

Nell'intero tratto dalla copia le nuove fee originali sono appena 0,392 USDT e il funding stimato −0,473. La perdita dominante è il movimento delle posizioni, non questi addebiti. Spread e slippage sono già nei prezzi dei fill, non si sottraggono nuovamente.

## 2. Cause: cosa è documentato e cosa resta un'ipotesi

**Catalizzatore macro documentato:** il BLS ha diffuso il CPI di settembre il 14 ottobre alle 08:30 Eastern, cioè 12:30 UTC / 14:30 italiane. Inflazione mensile +0,6%, annua +3,7%, core mensile +0,3%. Il primo strappo dei nostri ledger cade nello stesso intervallo. L'orario era già annunciato nel comunicato di settembre: poteva essere conosciuto prima del movimento. Le cifre appena pubblicate non potevano esserlo. [Comunicato ufficiale](https://www.bls.gov/news.release/archives/cpi_10142026.htm), [calendario annunciato in precedenza](https://www.bls.gov/news.release/archives/cpi_09112026.htm).

La cronaca contemporanea collega il ribasso alle preoccupazioni su inflazione e tassi. È una spiegazione coerente con la coincidenza temporale locale; la sola coincidenza non identifica una causa unica. Il comunicato BLS non misura il consenso degli economisti: non è stato inventato uno score storico di sorpresa macro per il modello. [The Block, 14 ottobre](https://www.theblock.co/news/markets/2026-10-14-bitcoin-falls-below-82000-core-inflation-fed-rate-hike-418582).

**Fragilità di contesto:** la ricerca Glassnode del 14 ottobre descrive deflussi ETF, domanda debole e livelli di liquidazione su entrambi i lati del prezzo. È contesto, non un segnale univoco di short. La pagina usa anche dati di quel giorno e osservazioni già successive al CPI; non è stata retroinserita tra gli input disponibili prima dello shock. Non sono stati acquisiti dataset on-chain o sottoscrizioni. [Glassnode](https://research.glassnode.com/the-week-onchain-week-41-2026/).

**Informazione già nei nostri archivi:** i raw KuCoin `contracts/active` conservano openInterest e funding. Verificati hash raw e identificatori dei quattro snapshot dell'evento. Open interest BTC, nel campo nativo contratti: 9.651.639→9.511.959 fra 12:25 e 12:35 del 14 (−1,45%); 10.038.077→9.923.751 fra 02:20 e 02:25 del 15 (−1,14%). Anche i book scendono: non è soltanto un cambiamento artificiale della contabilità. Prezzo in discesa e open interest in diminuzione sono compatibili con smontaggio di posizioni; non distinguono chiusure volontarie e liquidazioni forzate. Funding positivo non prova da solo un eccesso direzionale: ogni contratto futures ha un lato long e uno short.

**Limite della spiegazione:** non è identificata con evidenza primaria univoca la singola notizia/ordine che ha avviato l'accelerazione notturna. Mancano nel dataset usato il flusso delle liquidazioni effettive, gli aggressori dei trade e una cronologia causale delle notizie. Il CPI è un catalizzatore plausibile del primo episodio; attribuirgli ogni successivo movimento sarebbe più forte dell'evidenza.

## 3. Perché V13 e FAST non hanno aperto short

La V13 conserva il segnale lento 30/120 giorni e il ricalcolo strategico settimanale. Il riaggiustamento delle quantità quotidiano non è una valutazione intraday del regime. Un SELL di riduzione long non è automaticamente un target negativo.

La protezione denominata FAST resta **giornaliera**: due chiusure sotto la media a 10 giorni riducono un long; non è un rilevatore di crolli minuto per minuto e non inventa short. Il nome «rapida» è relativo al ricalcolo settimanale. HALF riduce strutturalmente i target. Durante le ore fra decisioni, entrambe mantengono le quantità assegnate.

Il 14 ottobre i target FAST e HALF coincidevano. Il 15 il rischio stimato sulle quantità effettive, dopo l'arrotondamento, è 4,831% annualizzato contro 5,216%, scarto relativo 7,38% oltre la tolleranza del 2%. È una stima da covarianza, non volatilità realizzata. Lo slot è registrato `risk_matched=false`: il piccolo vantaggio corrente FAST non può essere attribuito pulitamente al timing.

## 4. Due modelli diagnostici causali, senza scegliere il vincitore dopo i risultati

Protocollo salvato prima del calcolo, SHA-256 `4099a3c8a0350153ffca87a7f5a0e5149c5a2685d74d16e1785471aa464e9c14`. La scelta nasce comunque da un episodio già visto: resta studio esplorativo in-sample, non preregistrazione su dati intatti.

Prezzi dei 18 asset, griglia 5 minuti, ultimo prezzo ricevuto non oltre 120 secondi prima dello slot. Finestra complessiva 28 settembre 20:10→15 ottobre 07:25 UTC: 4739 righe complete e cinque mancanti. Una finestra con buchi non produce segnale; servono 24 ore contigue. Nessuna interpolazione, nessuna barra futura.

- **M1, momentum e ampiezza:** BTC perde almeno 1% in un'ora e almeno due terzi dei 18 simboli sono negativi nello stesso intervallo.
- **M2, rottura e ampiezza:** BTC scende sotto il minimo osservato delle 24 ore precedenti, escluso il punto attuale, con la stessa ampiezza negativa.

Su ciascun trigger si confrontano BTC long, cash, BTC short. Budget nozionale di riferimento 1000 USDT su capitale teorico 10.000, quantità arrotondata per difetto al passo 0,001 BTC. Il nozionale effettivo varia un poco per l'arrotondamento; non sono i pesi o l'equity controfattuale dell'intero portafoglio V13. Il cash non presuppone la vendita gratuita di una V13 già aperta.

Ingresso al campione successivo, dopo almeno 60 secondi; book verificato già disponibile a quel campione; durata 6 ore, poi 6 ore senza nuovi ingressi. Episodi non sovrapposti dentro ciascun modello. Book VWAP con profondità sufficiente, slippage avverso 2bps per lato, fee almeno 6bps per lato, funding ricalcolato sulla quantità con supporto verificato. Trentadue archivi book con hash verificati. Il fair mark serve al segnale, non come prezzo di fill garantito. Non si modellano stop intratrade o marginazione: è una diagnostica a nozionale limitato, non un motore short completo.

| Modello | Episodi completi | Short positivi | Short netto USDT | Long sugli stessi episodi USDT | Cash |
|---|---:|---:|---:|---:|---:|
| M1: momentum/ampiezza | 7 | 3 | +14,69 | −35,89 | 0 |
| M2: minimo 24h/ampiezza | 10 | 4 | −38,75 | +7,46 | 0 |

M1 ha un ulteriore episodio aperto il 15 ottobre alle 05:50 UTC: censurato, non contato come guadagno né come perdita finale. I modelli possono sovrapporsi fra loro e non sono prove indipendenti. Sono pochi episodi dello stesso periodo, non migliaia di crash indipendenti.

**Tempestività nei due eventi:**

- Prima del CPI, alle 12:25 UTC, BTC era +0,33% sull'ora; solo 3/18 simboli negativi. Nessuno dei due modelli prevedeva short. Alle 12:30 il campione contiene ancora prezzi antecedenti al comunicato: non si usa la successiva discesa per anticipare il segnale.
- M2 scatta alle 12:35 UTC, dopo il primo shock; ingresso simulato sul book delle 12:39:56, uscita 18:39:51: **+12,80 USDT**. È reazione, non previsione del primo salto.
- M1 scatta alle 13:10 UTC; ingresso 13:14:53, uscita 19:14:53: **+6,22 USDT**. Conferma più lenta, parte del ribasso già passata.
- M2 scatta di nuovo il 15 alle 00:50 UTC; ingresso 00:54:24, quindi prima del calo delle 02:20: **+7,26 USDT** a sei ore. Questo è un esempio di avviso utile prima di una successiva accelerazione, non prima dell'intero episodio ribassista.

**Falsi allarmi e robustezza:** lo stesso M2 il 13 ottobre alle 00:50 avrebbe aperto uno short, seguito da un rimbalzo BTC di circa 2,97% in sei ore: **−30,52 USDT**. Prima del 14 ottobre M2 totalizza −58,80; i due episodi recenti recuperano +20,05 senza renderlo positivo. M1 totalizza +8,48 prima del 14 e +6,22 nell'episodio recente, ma quattro short su sette perdono. Con un ulteriore costo di 20bps complessivi per operazione, M1 scende a circa +1,45 USDT, M2 a −58,14. Massima escursione avversa al mark dentro un episodio: circa 7,66 e 30,47 USDT rispettivamente; sono campionamenti, non massimi tick-by-tick. Nessuna annualizzazione, selezione di nuove soglie o profitto garantito.

## 5. Quale modello ha senso costruire dopo questa indagine

La lacuna concreta è un controllo del rischio **intraday**, con regole esplicite di rientro e con un modulo short distinto. Aggiungere soltanto un LLM che commenti il grafico non risolve né il ritardo né l'esecuzione. Per questa domanda un primo modello quantitativo interpretabile è più verificabile: regressione logistica regolarizzata che stimi la probabilità di una perdita ampia del paniere nelle prossime 1–6 ore. Da confrontare con soglie semplici e con un controllo cash, non soltanto con la V13 long.

| Componente | Evidenza utilizzabile | Cosa manca prima di validarlo |
|---|---|---|
| Prezzi, ampiezza, volatilità, correlazione intraday | Prezzi locali multiasset già osservati | Periodi intraday più lunghi, più regimi e qualifica dei collector storici; 16 giorni non bastano |
| Open interest, funding, basis, profondità | Raw pubblici già acquisiti e book verificabili | Dataset causale regolare, unità e disponibilità temporale qualificate, controllo dei buchi |
| Eventi macro | Orario CPI preannunciato verificabile | Archivio point-in-time del calendario, consenso e primo dato pubblicato; nessuna serie retroattivamente rivista |
| Liquidazioni e flusso aggressore | Non inclusi in questa diagnosi | Sorgente autorevole, copertura e raccolta eventualmente autorizzate; nessun acquisto/installazione in questo incarico |
| Short come azione | Book e contabilità simulata diagnostica | Trigger, budget, durata/stop, uscita, rientro, funding e falso allarme fissati prima; validazione futura |

La probabilità di stress dovrebbe prima governare «non aumentare / ridurre / cash». Per autorizzare uno short serve evidenza aggiuntiva che la prosecuzione negativa superi costi e rischio di rimbalzo: i due problemi non sono equivalenti. Una copertura BTC protegge solo una parte del rischio delle altcoin, come mostra il secondo strappo.

Proposta minima, non nuova strategia attivata: qualificare offline i raw già presenti; definire target di rischio a livello paniere e split temporali; addestrare solo sul passato con scaling causale; usare walk-forward con purge/embargo almeno pari all'orizzonte, costi stressati e poche varianti predefinite; congelare il modello prima di una futura osservazione separata. Conservare la V13 e le due biforcazioni come riferimenti. Nessuna promozione sulla base del solo episodio che ha motivato la ricerca.

## 6. Verifiche e riproducibilità

Sette test mirati coprono stabilità rispetto a barre future, rifiuto di gap/prezzi invalidi, minimo passato escluso il punto corrente, ritardo di esecuzione, cooldown, esito censurato, fee bilaterali, funding UNKNOWN e profondità insufficiente. Tutti superati. I tre conti sono riconciliati; copie e archivi utilizzati hanno manifest SHA-256. Una differenza iniziale di 0,0434 USDT nella ricostruzione FAST dipendeva da mark osservati a clock diversi: risolta confrontando prima ciascun conto con il proprio mark e poi tutti su un clock comune, senza alterare ledger.

Codice separato: `octobot/ai_strategy_lab/v13_crash_diagnostic.py`; riproduzione `scripts/v13_crash_20261015.py`; prove `tests/unit_tests/ai_strategy_lab/test_v13_crash_diagnostic.py`. Nessuna importazione dal percorso operativo. Non aperti gli outcome sigillati BTC/A-B-C. Non toccati i servizi di trading, le policy o il monitoraggio.
