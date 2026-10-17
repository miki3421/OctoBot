# BTC intraday v2 — qualifica offline delle fonti causali

Schede: `4cd8e105` qualifica, `efd1e408` strumento, `e1d0fe15` prove,
`7faade8a` consegna. Non è un writer runtime, un simulatore o un issuer.

## Input e perimetro

Il piano `research-protocols/btc-intraday-source-qualification-v2.json` vincola
l'hash del candidato v2. Finestra tecnica 16 ottobre 13:00–17 ottobre 13:00 UTC,
24 ore precedenti di warm-up e soli 120 secondi aggiuntivi per inizializzare il
primo punto della griglia. Nessuna variazione del periodo, delle soglie o del
segnale in base ai risultati. Non è T0 né una prova forward.

La sorgente ispezionata è l'archivio del custodian pubblico V13, non il ledger
contabile o i PnL delle strategie. Si copiano i record di mercato indirizzati per
hash, le ricevute raw dei mark dei 18 simboli, i contratti e i tassi finali BTC.
I payload originali, gli hash e gli orari restano conservati in un nuovo SQLite
su disco dati. Le ricevute degli altri endpoint non necessari non sono qualificate.

L5 proviene dalla copia tecnica già qualificata, SHA-256
`1141375eb2945a09c261e9f1d7b64972d532e2debd4e8543121734d9b739e678`,
con l'indice di segmenti del benchmark verificato per hash. Non si eseguono
scansioni o integrity check sul journal scalping live.

## Verificatore

`btc_intraday_source_qualification.py` usa la sola libreria standard. I passaggi
`freeze` e `qualify` sono separati. Una copia esistente non viene sovrascritta;
una qualifica conclusa o parziale con output già presenti non viene rimpiazzata.
Un eventuale `--base-copy` deve avere database/hash verificati, stesso protocollo,
warm-up, periodo e cutoff; permette solo di conservare/estendere il prefisso.
Nessun dato o ricevuta originale viene modificato. Un output incompleto non è
un esito riuscito: la ricevuta di completamento viene scritta per ultima.

Controlli dei raw: JSON senza duplicati o non finiti, dimensioni limitate, HTTP200,
identità del capture ID, SHA dei byte, host/path/query attesi, inizio richiesta
non successivo alla ricezione, ricezione entro il cutoff e nel proprio pacchetto.
I mark devono avere contratto e granularità corretti, prezzo positivo, timestamp
exchange non futuro e valore coerente con il record derivato. Non si sostituisce
il tempo di ricezione con il timestamp exchange o con l'mtime del file.

M1 usa i mark, come il detector originale, ma dai raw verificati. Per ogni punto
si sceglie il dato già ricevuto e, conservativamente, appartenente a un pacchetto
completato entro lo slot. Età massima 120 secondi, 18 simboli presenti e 289 punti
contigui. Le astensioni rimangono nel denominatore. L'identità causale dipende
solo dalla finestra consumata: append futuri non la cambiano.

L5 ricostruisce dieci secondi completati, fresh quote e arrivo richiesto a
slot+300s+500ms. Questi sono controlli sui tempi di **ricezione**: non emettono
fill e non provano la visibilità/persistenza del book entro la scadenza.

## Funding e due orari distinti

Il calendario si ricava dai prossimi eventi osservati nei contratti, senza
reinterpretare un conto alla rovescia come timestamp assoluto né assumere otto
ore fisse. Un calendario invalido resta visibile. I tassi regolati provengono
dall'endpoint storico: `current`/`predicted` non sono tassi finali. Rate mancanti
restano pending; rate discordanti per lo stesso evento impediscono la qualifica.

Per il mark precedente al settlement vale la ricezione raw effettiva dichiarata,
strettamente prima dell'evento, e l'età exchange massima di 60 secondi. Il
completamento di un pacchetto multiasset può essere successivo: non rende futuro
un mark già ricevuto. È consentita la riconciliazione successiva, conservando
entrambi gli orari. Questo non dimostra che l'intero pacchetto fosse pubblicato
prima dell'evento e non può autorizzare una decisione retroattiva.

Il risultato distingue `mark_received_ns`, `mark_package_complete_ns` e
`package_complete_before_event`. Non vengono calcolati funding cashflow o PnL:
non esiste una posizione del nuovo conto a cui attribuirli.

## Limiti della qualifica

Le ricevute provano integrità locale e coerenza dei tempi dichiarati dal collector,
non firma exchange, calibrazione indipendente dell'orologio o commit storico.
Le tabelle L5 conservano ricevuto/exchange, ma non il tempo di commit di ciascun
batch. Un intervallo di commit nominale di un secondo non certifica una scadenza
per ogni evento. L'mtime del file non è un sostituto.

Per il futuro esecutore occorrerà una ricevuta di disponibilità/visibilità e
persistenza osservata dal consumer, con limiti temporali verificati. Non si
ricostruiranno queste prove per il passato. L5 senza raw originari conserva inoltre
il limite già documentato sulla ricostruzione indipendente del payload.

Un esito positivo sulle finestre ricevute non equivale alla readiness del conto.
Non qualifica automaticamente tutti gli archivi del repository, non approva il
protocollo e non modifica Originale, FAST, HALF, M1 paper o osservazione M1.
Minimi reali KuCoin ancora UNKNOWN; mapping sintetico e sua natura invariati.
Nessun download, installazione, grant, riavvio o nuovo servizio.
