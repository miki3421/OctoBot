# Qwen BTC shadow — preregistrazione forward candidata

29 settembre 2026 · **PROPOSTA PER DECISIONE, FORWARD NON ATTIVO**.
Card: `work-card-9c0ca8ad-26eb-420f-92f4-9083becf01b7`.
La scelta BTC contro 30/120 e la preparazione sintetica sono state confermate
dal proprietario. Questa proposta completa le scelte scientifiche mancanti;
non le presenta come già approvate e non avvia il Day 1.

## Identità, ipotesi e artefatti

Esperimento separato `qwen-btc-direction-shadow-v1`. Ipotesi primaria:
Qwen produce uno score direzionale medio maggiore della baseline 30/120
sugli stessi input causali. Non è un'ipotesi di profitto netto o di
miglioramento del portafoglio V13 multiasset. Nessun risultato della ricerca
BTC originale viene letto, trasferito o usato per selezionare il challenger.

La qualificazione è `SYNTHETIC_NON_FORWARD`, lineage
`933c8f6c67e3cc1ea1f05d17e71753383f2c84e399746b76099321ab672276e7`.
Il relativo runner V1 rifiuta uno scope live. Per il futuro forward serve
una versione e un bundle distinti, con nuova lineage congelata prima del
Day 1; nessun semplice cambio di flag rende il codice sintetico operativo.

Modello già presente: Qwen3.6-35B-A3B UD-Q4_K_XL, SHA-256 locale
`707a55a8a4397ecde44de0c499d3e68c1ad1d240d1da65826b4949d1043f4450`.
Server llama.cpp SHA-256
`16b060f4c2f65d5f83dbbdab01efdf5d6826e73127024b5e2157df261f490ee5`,
build `b1-60b06ab`; template SHA-256
`55d4931433fe502b794226ee7f4d206a6bdd436ac9f80eb7d8ebb4c639f9ea0c`.
I checksum locali identificano gli artefatti; non verificano il distributore.
Endpoint solo loopback, CPU già disponibile, nessun download, installazione,
cloud o spesa esterna. Un tentativo al giorno, nessun tuning automatico.

Il prompt futuro conserverà l'ipotesi e lo schema della prova sintetica,
cambiando esplicitamente la descrizione dello scope a forward. Prompt esatto,
template, codice collector/adattatore/baseline/runner/evaluator, librerie,
sampling e ambiente saranno fissati nel bundle finale. Sampling candidato:
temperatura 0, seed 13120, thinking disabilitato, massimo 128 token. Timeout
globale candidato 35 secondi; nessun retry della generazione. Un timeout è
un esito del confronto. Modello/prompt diversi richiedono nuova versione e
dati successivi mai osservati; nessun riuso della finestra per scegliere.

## Custodia, clock e calendario proposti

GET pubbliche KuCoin Classic Futures `XBTUSDTM`, senza credenziali, con raw
e receipt indipendenti. Nessun mount, lettura o riuso di raw/journal/outcome
del BTC V2.2 sigillato. Entrambi i rami ricevono lo stesso snapshot di 121
close daily UTC già chiusi e contigui; ultimo close della barra iniziata il
giorno precedente. Lag minimo dieci minuti. Le feature provengono soltanto
dai dati ricevuti e verificati prima della decisione. L'hash raw e i tempi
di ricezione sono provenienza separata dall'hash e dall'identità causale.

Il Day 1 sarà una data UTC esatta futura, scelta dopo decisione esplicita,
freeze, prova di custodia e provisioning. Non è il Day 1 del BTC V2.2.
Proposta: **180 slot consecutivi**, ciascuno alle 00:10 UTC; snapshot e due
record terminali entro 00:20 UTC. Nessun backfill di proposte: mancanze o
guasti chiudono lo slot MISSING, senza spostare la finestra. Reservation
prima dell'inferenza; concorrenti/restart non generano nuove risposte.

Fine decisioni = Day 1 + 179 giorni. Ultimo outcome non prima di Day 1 +
180 giorni, dopo chiusura e acquisizione causale. Review unica non prima di
Day 1 + 181 giorni alle 00:30 UTC, dopo verifica completezza. Le date esatte
saranno nel manifest di attivazione prima del primo slot; nessuna estensione
basata sui risultati. Se l'outcome manca, resta mancante.

Archivi e journal shadow appartenenti a ruoli separati dalla strategia V13,
dal suo issuer/executor e dalla ricerca BTC originale. Il modello non legge
filesystem o database e non ha tool. Il writer registra input, risposta,
validazione, tempi, astensioni, MISSING e conflitti; record immutabili e
outcome in registro distinto, append-only. Accesso di lettura UI soltanto
alla proiezione autorizzata. Nessun grant o percorso d'ordine.

## Statistica e soglie candidate, da approvare PRIMA dei dati

Per ogni giorno con outcome disponibile:
`score = sign(decision) × ln(close[d+1]/close[d])`.
LONG vale +1, SHORT −1, NO_PROPOSAL 0. Lo zero dell'astensione è solo la
definizione di questo score: non è un costo, rendimento economico o dato
mancante imputato. MISSING e outcome assenti non sono mai zero. Il close
origine viene dal record originario; il close successivo da una nuova
acquisizione indipendente dopo la sua maturazione.

Endpoint primario: media di `score_Qwen − score_baseline` sui giorni
con entrambi i record validi e lo stesso outcome maturo. Giorni di astensione
valida sono inclusi; giorni MISSING di almeno un ramo esclusi dalla media,
ma sempre inclusi nei denominatori di copertura dei 180 slot. Riportare
separatamente copertura di ogni ramo e congiunta, motivi dei MISSING e
attività direzionale, per rendere visibile una selezione dovuta a guasti.

Intervallo proposto: circular moving-block bootstrap sui **180 slot di
calendario**, blocchi di 14 giorni con wrap-around, 13 inizi campionati per
replica con `random.Random(13120).randrange(180)`, concatenazione e troncamento
a 180. Diecimila repliche; omettere dalla media soltanto i giorni senza
confronto valido. Una replica senza confronti rende la review invalida.
CI percentile bilaterale 95%, interpolazione lineare su indice `(N−1)×p`
per percentili 2,5% e 97,5%. Non cambiare a test unilaterale dopo i dati.

Gate di **evidenza direzionale candidata**, congiunti:

- Almeno 170 confronti giornalieri validi con outcome maturo su 180.
- Per ciascun ramo almeno 60 proposte direzionali mature, di cui almeno
  20 LONG e 20 SHORT. Se un regime non compare, esito INSUFFICIENTE,
  senza rilassare le soglie.
- Nessun buco o conflitto irrisolto, nessun cambio di artefatto o violazione
  causale. Un guasto registrato MISSING non è un buco di registrazione.
- Media della differenza >0 e limite inferiore del CI bilaterale 95% >0.

Descrittivi prefissati: singoli score e attività dei rami, hit rate solo
sulle rispettive proposte direzionali mature, sottoperiodi 1–60/61–120/
121–180 e regimi definiti dal segno di r120. Nessun score probabilistico,
Brier o ECE; il modello non emette probabilità calibrate. Nessuna selezione
post-hoc di un sottogruppo come endpoint primario o correzione del prompt
durante la finestra. Un PASS richiede comunque review umana; non abilita
issuer, simulatore o trading.

## Visibilità ed economia

Durante i 180 giorni la UI candidata mostra calendario, stati terminali,
latenza, motivi MISSING, integrità e maturità; esiti e statistiche comparative
restano sigillati fino alla review. Nessun feedback di performance al modello.
Una lettura anticipata che guida modifiche consuma la finestra per quella
nuova versione. Il paper V13 e il suo osservatore possono continuare, senza
trasferire a Qwen shadow performance o storico del loro conto.

Lo score close-to-close non è P/L realizzabile alle 00:10. Simulazione
economica e costi sono un protocollo successivo: richiedono prezzi eseguibili,
fee, spread, profondità/slippage e funding osservati. Mai sostituire costi
assenti con zero. Minimi reali KuCoin UNKNOWN e gate P0 invariati.

## Stato di preparazione e decisioni rimaste

È disponibile il runner sintetico e una qualificazione separata. Prima di
qualsiasi forward restano: decisione sulle soglie/calendario/visibilità di
questa proposta, autorizzazione esplicita alle sue GET pubbliche indipendenti,
bundle della versione live con collector/evaluator/custodia e test, data
esatta Day 1 e approvazione finale del bundle. Questi elementi non sono
approvati dalla semplice accettazione di una prova sintetica. Nessun timer
forward, grant operativo, ordine o nuova integrazione è abilitato qui.
