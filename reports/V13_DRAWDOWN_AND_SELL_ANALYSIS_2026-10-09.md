# V13 — flessione, reattività e informazione dei SELL

9 ottobre 2026. Analisi richiesta dal proprietario, sola lettura della V13
originale multiasset paper. Scheda `work-card-9e7c4abc-c8d0-41a8-b351-741f6319a1ef`.
Ledger, contributi, approvazioni, codice originale e grafici UI confrontati;
nessuna modifica della strategia. Nessun outcome degli altri esperimenti letto.
Evidenze nella radice workspace: `audit-evidence/v13-decline-20261009/`.

## Quanto è scesa e da dove viene la perdita

| Punto del ledger | Equity USDT | P/L sul capitale iniziale |
| --- | ---: | ---: |
| Picco, 29 settembre 12:18 UTC | 10.198,41 | +198,41 |
| Minimo, 8 ottobre 17:50 UTC | 9.860,88 | −139,12 |
| Snapshot analizzato, 9 ottobre 08:47 UTC | 9.991,18 | −8,82 |

Dal picco al minimo: −337,54 USDT, drawdown dell'equity 3,31%. È stato
restituito tutto il profitto precedente, più 139,12 USDT di capitale iniziale.
Nello snapshot successivo una parte è stata recuperata. Questi sono punti
effettivamente registrati, non una ricostruzione delle quotazioni mancanti.

L'attribuzione per simbolo è stata ricostruita con quantità firmate, prezzi
dei fill, mark ai tre istanti, fee e funding. La somma riconcilia l'equity
ai tre punti con errore inferiore a 0,000001 USDT. Non sono sommati come delta
i campi realized_pnl delle righe research, che rappresentano cumulati.

| Simbolo | Contributo alla flessione picco→minimo, USDT |
| --- | ---: |
| HBAR | −46,30 |
| LINK | −33,48 |
| XLM | −26,76 |
| UNI | −23,64 |
| AVAX | −23,34 |

Tutti i 18 simboli hanno contributo negativo in quell'intervallo, compresi
asset che mantengono un P/L cumulato positivo. Non basta quindi rimuovere chi
oggi è in perdita: anche precedenti vincitori hanno restituito profitto.
Il portafoglio ha esposizione direzionale comune, tutta long negli intenti
esaminati. Esposizione lorda al picco circa 22,90%, nello snapshot circa 21,90%.

Circa 332,86 USDT della flessione provengono dal movimento economico delle
posizioni; fee aggiuntive 0,98 e funding stimato −3,70. I prezzi di fill
includono spread/slippage: non si sottraggono nuovamente. Il costo dominante
è mantenere esposizione durante il calo, non le commissioni.

## Perché aggiornare ogni giorno non ha significato uscire ogni giorno

La V13 congelata usa dual momentum 30/120 giorni, pesi strategici ricalcolati
ogni sette giorni e covarianza su 60 giorni. Il forward conserva gli stessi
pesi fra i ricalcoli. Il paper riceve una proposta giornaliera e aggiusta le
quantità al peso assegnato: le piccole operazioni quotidiane non sono una
nuova selezione strategica completa.

Ricalcolo strategico alla chiusura del 29 settembre: 15 long, gross 22,66%.
Ricalcolo del 6 ottobre: 18 long, gross 22,79%, recepito il 7 ottobre alle
00:12 UTC. Sono poi rimasti long tutti i 18, mentre alcuni segnali peggioravano.
Le normali esecuzioni giornaliere seguono l'issuer di circa 28–52 secondi;
il primo batch della migrazione è un caso distinto, circa 411 secondi.
Nel ledger research non sono registrate nuove decisioni respinte per perdita
giornaliera o drawdown: la frequenza/cooldown non spiegano un ordine di uscita
valido rimasto inevaso. Le riduzioni protettive sono esentate da questi limiti.

Ricostruzione con gli input originali: al 7 ottobre ATOM e DOGE erano già
neutrali. All'8 ottobre ATOM era SHORT grezzo e DOGE, DOT, ETH, XRP neutrali.
BTC rimaneva LONG: momentum 30 giorni circa +4,19%, 120 giorni +32,90%.
Il filtro di regime sopprime lo short di ATOM, lasciando cinque asset senza
segnale long corrente. I pesi operativi restano quelli del ricalcolo settimanale.
Anche un ricalcolo giornaliero avrebbe però lasciato long 13 asset, inclusa HBAR:
la lentezza deriva sia dal calendario sia dagli orizzonti del segnale.

Il primo conteggio diagnostico usava il pannello storico multiasset e dava
sei asset non-long. Verificati i 72 endpoint di giugno nei collector originali
SHA-pinned, il conteggio corretto è cinque. L'evidenza autorevole è
`signals-original-baseline.json`; il primo pannello è conservato come passaggio
diagnostico e non è usato per la conclusione.

I controlli paper 2% di perdita giornaliera e 10% di drawdown sospendono nuovi
ingressi; non costituiscono liquidazione automatica delle posizioni. Il calo
massimo giornaliero osservato rispetto alla prima equity dell'8 ottobre è
circa 1,81%, sotto 2%; il drawdown massimo 3,31% è sotto 10%. La V13 originale
non contiene un profit trailing stop intraday né il fast volatility brake.

## Cosa mostrano effettivamente i grafici

Ispezionate le pagine reali per HBAR, XLM, LINK, DOT, con screenshot e JSON
dei grafici conservati. Su XLM la sequenza osservata è rilevante: riduzione
vicino alla zona alta, chiusura long, successivo rientro prima di altra discesa.
È una candidata informazione da studiare, non da liquidare come irrilevante.

| Evento | Significato effettivo |
| --- | --- |
| HBAR SELL 29 settembre | 10 unità, solo 0,53% della posizione; rimangono 1.870 long |
| HBAR SELL 30 settembre | 630 unità, riduzione del 33,69%; rimangono 1.240 long |
| HBAR SELL 7 ottobre | 200 unità, riduzione del 16,13% |
| XLM SELL 29 settembre | 10 unità, riduzione del 1,33% |
| XLM SELL 30 settembre | Chiusura di tutte le 740 unità long rimaste |
| XLM BUY 7 ottobre | Nuova apertura long di 620 unità, prima del successivo ribasso |

Il grafico dà la stessa dimensione a tutti i marker: una riduzione dello 0,53%
può sembrare una svolta tanto importante quanto una chiusura completa.
Il prezzo dopo il SELL HBAR del 29 settembre è sceso circa 15,76% in 24 ore;
il SELL più consistente del giorno successivo è stato invece seguito da un
rimbalzo di circa 2,59% in 24 ore. XLM dopo la chiusura completa rimbalza circa
2,04% in 24 ore, poi scende circa 2,89% in 72 ore. L'orizzonte dello short
ipotetico cambia quindi molto l'esito.

Studio descrittivo di tutti i fill con quotazione successiva disponibile entro
180 secondi dall'orizzonte: dopo 37/63 SELL il prezzo scende nelle 24 ore; dopo
27/44 BUY scende anch'esso. A 72 ore: 28/47 SELL e 12/28 BUY. Sono eventi
sovrapposti su asset che condividono il mercato, non trade indipendenti; il
campione comprende anche la migrazione iniziale. Non è un backtest di short
netto di costi e non dimostra un vantaggio predittivo autonomo dei SELL.

## Ipotesi concreta da qualificare

La V13 può riconoscere un indebolimento e ridurre il long senza convertirlo
in short; in seguito può ricomprare per ripristinare un peso settimanale ancora
positivo. La lacuna da verificare è la persistenza/rientro del rischio, non
semplicemente il nome SELL.

Primo challenger proposto: mantenere la baseline per i nuovi ingressi, ma
definire prima del confronto una regola giornaliera di uscita/rientro quando
il segnale perde ammissibilità. Separatamente si può studiare una modalità
short: richiede un trigger significativo, quantità, regime, durata, uscita,
fee/funding e liquidità espliciti. Invertire ogni micro-ribilanciamento SELL
introdurrebbe frequenti esposizioni non presenti nella logica originale.

Questa finestra è già osservata e serve a generare l'ipotesi; l'accettazione
richiede confronto causale e periodo futuro, con costi e baseline comuni.
La selezione settimanale dell'universo A/B/C già preparata risponde a un'altra
domanda e non va implicitamente equiparata a questo controllo delle uscite.

Nuove schedine To-do:
`work-card-7d58d1a7-bcf5-4aa9-be63-edea482ac6a9` (qualificare SELL/uscite/rientri),
`work-card-9f3989ac-3597-4cc1-9c80-97d92a77f6b2` (marker per peso e significato).
Proposte di ricerca, nessuna nuova policy, previsione short o modifica al paper.
