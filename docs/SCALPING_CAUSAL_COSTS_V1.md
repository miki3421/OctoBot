# BTC L5: adapter causale e diagnostica dei costi v1

Schedine: `0cef3daa` adapter, `c9187254` costi, `0211c696` verifiche,
`d3eaae8f` esecuzione offline, `26bdb4f5` consegna.

Questi strumenti preparano la ricerca intraday su un conto BTC separato.
Non creano un conto, un segnale, autorizzazioni o ordini. Originale, FAST,
HALF, M1 paper e l'osservazione scientifica M1 rimangono invariati.
La copia tecnica qualificata non diventa un freeze scientifico.

## Contratto e sorgente

Il contratto `research-protocols/scalping-causal-costs-v1.json` fissa prima dei
risultati il limite di cattura di 1 secondo, la freschezza di 1 secondo sia
rispetto alla ricezione sia rispetto al timestamp exchange, il reset al cambio
sessione e ai buchi oltre 5 secondi. Gli orologi non sono calibrati per misurare
la latenza di un ordine.

La sola sorgente ammessa dalla CLI è una copia sigillata, non scrivibile,
con hash corrispondente al contratto e ai risultati della qualifica. Si controllano
anche integrità e cronologia precedentemente verificate. Non si interroga il
journal del collector attivo. Nessuna dipendenza aggiuntiva o rete.

## Adapter

`scalping_causal_costs.py` ricostruisce un indice compatto di segmenti dai raw.
`CausalAdapter.quote` effettua una lettura as-of o restituisce il primo book
accettato dopo il tempo di arrivo richiesto, entro un secondo. Nessuna
interpolazione o estensione oltre i cinque livelli osservati.

`frame` ricostruisce sul momento secondi completati, senza usare gli aggregati
storici `second_buckets`. La chiusura del secondo deve essere già disponibile
alla decisione. I book contribuenti devono essere freschi anche a quella chiusura;
`book_count` si riferisce a questi book, non al totale grezzo del secondo.
Le operazioni sono assegnate secondo la ricezione, filtrate per ritardo e sessione.
Un secondo privo di book valido rimane mancante. Una finestra incompleta è
esplicitamente segnalata e non può essere scambiata per warm-up completo.

Il fingerprint causale comprende soltanto dati consumati, slot, segmento e
regole pertinenti. L'hash dell'intera acquisizione è provenienza separata:
aggiungere eventi futuri non deve cambiare la finestra già calcolata.
La classe accetta connessioni per fixture isolate; per dati reali si usa la CLI
validante e si verificano gli hash della ricevuta di completamento. Non è un
adapter del runtime operativo.

## Benchmark

Ogni quarto d'ora UTC genera entrambi i lati e tutte le quantità native
1, 10, 100, 1000, con latenze ipotizzate di 0, 250, 500, 1000 ms.
Anche il caso a latenza zero attende un book ricevuto al tempo richiesto o dopo:
non rappresenta una garanzia di esecuzione istantanea.
Si salvano le finestre di feature dei dieci secondi precedenti questi slot;
non viene materializzato un nuovo archivio di tutti i secondi.

L'esecuzione ipotetica consuma la profondità visibile, richiede quantità completa
e separa movimento del mid durante l'attesa, mezzo spread, impatto della profondità,
commissione assunta di 6 bps e slippage avverso aggiuntivo assunto di 1 bps.
I valori negativi del movimento durante la latenza indicano miglioramento del
prezzo in questa simulazione; non sono profitto della strategia.
Lo stress raddoppia le componenti di liquidità e i costi assunti, mantenendo il
movimento misurato durante la latenza. È una sensibilità aritmetica, non un modello
certificato di mercato stressato. Nessun holding return, markout o funding PnL.

Tutti i tentativi, anche senza quote o profondità, restano nei denominatori.
Le statistiche dei costi si riferiscono solo ai tentativi misurabili, con la quota
corrispondente sempre esplicita. Per dati/size non eseguibili non si inventa un fill.
Nessuna selezione di giornate, lato o size dopo averne letto i risultati.
Tutto lo storico viene riusato per questa diagnostica tecnica; nessun holdout
scientifico nuovo, né riapertura delle famiglie direzionali L5 già respinte.

## Conservazione e riavvio

Ogni esecuzione richiede una directory nuova sul disco dati, copia contratto e
hash dei prerequisiti. Scrive la ricevuta di completamento solo dopo tutti gli
output e li rende non scrivibili. Un errore lascia gli artefatti incompleti:
non sono un risultato valido e non vengono sovrascritti automaticamente.
Il consumer deve verificare ricevuta e hash, non dedurre il successo dai file presenti.
Il journal SQLite dell'indice è un derivato locale, distinto da approvals e ledger.

Per eseguire senza importare le dipendenze del laboratorio:

```text
python3 octobot/ai_strategy_lab/scalping_causal_costs.py \
  --source ARCHIVIO_SIGILLATO/snapshot.sqlite \
  --qualification-dir ARCHIVIO_SIGILLATO \
  --contract docs/research-protocols/scalping-causal-costs-v1.json \
  --destination NUOVA_DIRECTORY_SU_DISCO_DATI
```

## Cosa manca prima del conto BTC

Le quantità rimangono native: nessuna conversione storica certificata in BTC o
USDT. L'osservazione KuCoin del 25 settembre espone moltiplicatore 0,001,
ma non dimostra l'invarianza nel periodo luglio–ottobre né sostituisce il binding
delle unità del feed. `min_quantity` e `min_notional` reali restano `UNKNOWN`.
Questa incertezza non impedisce il benchmark né un futuro simulatore con contratto
sintetico separato; non dimostra ammissibilità KuCoin.

Il passo successivo è fissare un protocollo candidato con input direzionale
indipendente, quantità, orizzonte, uscite, limiti di rischio, fee e funding,
contratto del simulatore e valutazione futura. L5 da solo non fornisce la breadth
M1 dei 18 simboli. Il conto avrà identità e journal propri, senza ereditare
approvazioni o validità scientifica dagli altri esperimenti. L'avvio resta distinto
dalla presente consegna.
