# V13 originale, FAST e HALF — consegna del 13 ottobre 2026

Consegnate una pagina comparativa `/v13_variants` e le pagine
`/v13_variants/original`, `/v13_variants/fast`, `/v13_variants/half`.
Il conto V13 attivo contiene il collegamento «Confronta le tre strategie».
Le pagine mostrano equity, variazione dalla copia, costi, funding, contributi dei
simboli, decisioni delle varianti e tutte le operazioni ereditate. Curve con
storico comune e risultati successivi distinti, orari di valorizzazione espliciti,
segnalazione di dati scaduti o incompleti. Nessuna azione di trading nella UI.

## Copia e continuazione

Il punto economico comune resta **2026-10-13 14:55:36.881469 UTC**:
equity **9964.760357221048 USDT**, 18 posizioni, 164 operazioni pregresse.
La copia integrale conserva tutte le tabelle, i prezzi medi, le generazioni,
le fee, il funding e i limiti di rischio. Parent sigillato SHA-256
`ca4acd534434c32fadfff3c548c6cb8bfab796ad091ec7b2a5612b54ca644bbc`.
Il prefisso immutabile resta conservato; le continuazioni FAST/HALF risiedono
in un nuovo journal appaiato, con namespace di conto distinti e transazione
unica per stati, funding, osservazioni, fill e consumo dello slot.

Il simulatore `octobot-v13-forks` è in osservazione. Primo slot futuro fissato
al **14 ottobre 2026, 00:15 UTC (02:15 in Italia)**. Nessuna operazione retrodatata.
Fino a quel momento le quantità copiate restano investite: mark e funding
successivi alla copia sono contabilizzati. La griglia passiva mancante durante
la preparazione viene ricostruita dai mark causali esistenti, senza trade.
Il termine scientifico resta l'11 gennaio 2027, 14:55:36.881469 UTC.

FAST applica il filtro giornaliero SMA10 e sospende gli aumenti long in regime
ridotto. HALF parte da metà dei target V13. Il rischio previsto viene allineato
solo verso il basso, su 60 rendimenti contigui e covarianza con shrinkage
congelato. Arrotondamenti, costi e limiti possono produrre scostamenti: vengono
registrati, senza scartare i risultati sfavorevoli. L'originale resta un
riferimento con le proprie regole e i propri orari; non è un terzo braccio
pareggiato per rischio.

## Verifiche

- 12 test del runner: ereditarietà e mancato reset, identità, rischio comune,
  rischio zero, blocchi condivisi per policy e mercato, causalità delle barre,
  dati alterati/scaduti, funding mancante e mark precedente, storage failure
  con rollback appaiato, replay e slot mancati.
- Un test della copia integrale: stessa storia, file distinti, originale
  invariato, rifiuto della sovrascrittura.
- Ricostruzione indipendente sui dati reali: 18 target originali e 61 chiusure
  contigue per simbolo verificati, senza rete e senza fill retroattivi.
- Prova di riavvio del simulatore: ricevuta, posizioni, costi e limiti conservati;
  nessun fill duplicato. SQLite `integrity_check = ok`.
- Quattro pagine desktop, confronto e FAST mobile verificati con Playwright:
  nessun errore JavaScript o overflow orizzontale; API senza cache;
  versione inesistente rifiutata. Screenshot conservati.
- `git diff --check`, compilazione Python e configurazione Compose verificati.

Prima del primo slot è stata completata la qualifica della build **v2.2**:
un veto di ingresso per spread o minimo simulato su un braccio sospende gli
aumenti in entrambi. La ricevuta preliminare v2.1 è conservata; il pin finale
è registrato separatamente, a zero fill e zero slot consumati, senza cambiare
conto, parametri scientifici, stato economico o prima decisione futura.

Le prove positive di esecuzione usano metadata sintetici esplicitamente nei
test: non dimostrano ammissibilità KuCoin. I minimi reali restano UNKNOWN,
e il percorso exchange-faithful resta bloccato. Il primo slot futuro reale
non è ancora avvenuto: nessun risultato scientifico è dichiarato.

## Isolamento e gestione

UID dedicato 30934, rete assente, filesystem del container in sola lettura,
capability rimosse. Sorgenti, proposte e ledger originale sono montati read-only.
Nessun mount di approval store, controlli amministrativi o credenziali exchange.
Le scritture sono limitate al nuovo journal e alla proiezione UI. La perdita del
journal o un'identità modificata impediscono l'avvio: nessun reset automatico.
Solo la UI è stata riavviata; capture, producer, issuer ed executor originali
conservano i rispettivi avvii precedenti e risultano healthy.

Gestione dalla radice del fork con `docker-compose -p v13-forks -f
 docker-compose.v13-forks.yml`: avvio del solo servizio `v13-forks`, oppure stop
del medesimo. Non reinizializzare il journal. Un rollback arresta soltanto il
nuovo simulatore e conserva copie, stato e prove; la V13 originale prosegue.
Per una revisione del protocollo dopo il primo slot serve una nuova versione
con confine futuro; la configurazione non promuove automaticamente la ricerca.

Evidenze locali: `audit-evidence/v13-fork-delivery-20261013` nel workspace del
laboratorio. Non vengono versionati DB, acquisizioni o credenziali.

Schedine: runner `work-card-4b2d8047-414b-4d19-b5fd-5fabe6a45d7a`;
qualifica `work-card-a3de24f6-9426-40f4-8f57-cbaed4434e04`;
UI `work-card-07e7a8cb-1a1e-4547-ba54-7d9f3fff2c1b`;
consegna `work-card-f0160160-e5be-4b92-9132-affa4901ae52`.
Esecuzione SINGLE_AGENT; verifica dell'autore, non review indipendente.
