# Trading AI Lab — adattatore e verifier V13 offline v1

Implementazione candidata del 28 settembre 2026. Scheda
`work-card-fe78a248-3d67-45fa-86b0-bbc5eed8e71e`; verifica tecnica interna
`work-card-b98fb679-5014-4b81-99fd-e5e5c09f7993`.
**Attivazione BLOCKED. Nessun issuer, approvazione o esecuzione collegati.**

## Cosa fa

`v13_original_portfolio.py` legge il contratto e lo schema candidati con hash
fissi; verifica forma, identità, vettore completo di 18 asset, encoding numerico,
hash e ordine causale dei timestamp. Il parser respinge chiavi duplicate, NaN,
Infinity e overflow numerico. I target mancanti sono espansi a zero soltanto
dalla mappa sparse research nell'universo congelato, mai da una proposta parziale.

`v13_original_verify.py` funziona come programma separato: verifica prima i
16 file congelati e gli input originali tramite il loader esistente, legge il
prefisso raw/daily e journal fino alla barra scelta e ricalcola il percorso
Trend originale. Non esegue Cointegration, non trasferisce curve equity né
usa il peso Trend del combinato 50/50. Confronta esattamente tutti i vettori
del prefisso, non soltanto quello finale. Nessun download o modifica agli input.

I valori daily devono riprodursi dai byte raw per tutti i 18 asset consumati.
Il funding storico mostra due encoding riproducibili della somma: sequenziale
binary64 e somma del runtime corrente. È richiesto un confronto esatto con
uno dei due, senza tolleranza o arrotondamento; la ricevuta espone le occorrenze.
I valori originali restano invariati e sono quelli usati dal calcolo congelato.
Questa compatibilità diagnostica non approva un nuovo profilo operativo:
runtime, dependency bundle e normalizzazione richiedono pinning/review nel
futuro binding dell'issuer.

## Ricevuta e limiti della prova

La ricevuta contiene hash della sorgente e del prefisso, hash dell'input causale
normalizzato, byte raw referenziati, riferimenti scientifici originali, versioni
e hash dei due nuovi moduli, tutti i target e tempo di verifica. Il programma
usa il tempo reale di completamento; un clock fornito alla funzione di test
è esplicitamente marcato `supplied_diagnostic_clock`.

`derivation_status=VERIFIED` dimostra soltanto che quei target si ricostruiscono
da quegli input. `availability_status=UNRESOLVED` segnala che mancano ricevute
indipendenti di pubblicazione completa e disponibilità delle dipendenze.
I timestamp legacy di acquisizione non sono reinterpretati come disponibilità.
Restano `research_only=true`, `execution_approved=false`, `issuable=false` e
`independent_custody_verified=false`. Il contratto operativo è ancora DRAFT,
binding/epoch/confine non approvati; nessun record storico è promosso.

La funzione di verifica di una proposta candidata richiede digest di ricevute
provenienti separatamente dal custode, verifica binding fra i contenuti e i
tempi, e restituisce sempre un risultato privo di autorità di esecuzione.
Ricevute sintetiche negli unit test non sono evidenza di custodia reale.
Il futuro issuer deve verificare ownership, root pin, confine, epoch, replay,
freshness, policy e contratto di ammissibilità; questo modulo non lo sostituisce.

## Uso isolato

Il programma può essere eseguito tramite `python3 -m
octobot.ai_strategy_lab.v13_original_verify`, con argomenti espliciti
`--repo-root`, `--research-root`, `--archive-root`, `--implementation-lock`
e `--source-bar-date`. Di default stampa solo la ricevuta. `--output-dir`
pubblica un nuovo artefatto diagnostico identificato dal digest, con creazione
esclusiva e fsync; non sovrascrive file preesistenti diversi. Guasti di storage
restano errori anche se un tentativo precedente ha lasciato byte identici.
È vietato scrivere dentro gli input o in `octobot-local`.

Eseguire con rete assente, repository/research/archive/lock montati read-only,
UID senza privilegi e sola directory di output candidata scrivibile. Conservare
le location originali necessarie ai manifest congelati, senza modificarli.
Non montare approvals, execution ledger, registry/gate o credenziali. I comandi
di riproduzione e le prove sono conservati nelle evidenze della scheda.

## Prossimo passaggio

Issuer portfolio `work-card-71bc1c35-d049-48d2-825c-de2f5f479a67`, executor
`work-card-9be311a0-d1b3-4350-8931-639d8240eb4f` e prove E2E
`work-card-898bdd9a-0108-4558-8d4e-0d07687f9f6a` restano lavori separati.
Prima dell'attivazione servono decisioni sul contratto/HLD, policy e confine
futuro, custodia reale della derivazione, migrazione riconciliata del conto
e review indipendente. I minimi KuCoin restano UNKNOWN: questa implementazione
non prova l'ammissibilità degli ordini e non modifica P0-03.
