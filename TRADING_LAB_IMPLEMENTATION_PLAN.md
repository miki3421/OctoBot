# Trading Lab — Piano di implementazione

- Versione del documento: 1.0
- Data: 5 settembre 2026
- Stato: pianificato; questo documento non attesta l'esecuzione delle fasi.
- Origine: audit del laboratorio e piano discusso con l'utente.
- Ambito di questa consegna: salvataggio e versionamento del piano, non avvio
  dell'implementazione.

## Obiettivo

Portare V13 + Cointegration in paper con profitti e perdite calcolati dalle
proprie esecuzioni, non copiati dalla curva di ricerca. Usare poi lo stesso
motore contabile per verificare lo storico e decidere se la candidata merita
di proseguire.

Il criterio di progresso non è il numero di trade o di esperimenti: è poter
ricostruire ogni USDT di risultato, misurare il rischio e stabilire se la
combinazione aggiunge valore rispetto a una soluzione più semplice. Nessun
rendimento futuro è garantito.

## Vincoli trasversali

- Solo paper trading; nessuna credenziale di trading reale, ordine reale,
  deposito, prelievo o promozione automatica.
- Il profilo legacy KuCoin e gli esperimenti di ricerca restano distinti.
- Nessuna cancellazione di journal, dataset, log, risultati o volumi.
- Nessuna riscrittura silenziosa di protocolli, gate, lock o curve congelate.
- Conservare le modifiche locali esistenti e distinguere il codice effettivo
  di ogni esecuzione.
- Riutilizzare i dati disponibili. Nessun nuovo collector senza un consumatore,
  una domanda precisa e una data di revisione.
- Ogni fase richiede verifiche prima del passaggio alla successiva. Registrare
  avanzamento, evidenze e variazioni di ambito in successive revisioni Git.

## Fase 1 — Proteggere e rendere riconoscibile lo stato attuale

### Interventi

- Registrare versione del codice, modifiche locali, configurazioni, protocolli
  e servizi attivi.
- Eseguire snapshot coerenti dei journal attivi, includendo Diversified paper,
  forward, Breadth ed Execution.
- Provare il ripristino dei piccoli database in una directory separata.
- Distinguere nella dashboard il mirror teorico attuale dal futuro paper
  basato su esecuzioni.
- Correggere le discrepanze documentali individuate: costi 2×/3×,
  autorizzazioni del solo paper manuale e istruzioni di avvio obsolete.

Gli esperimenti congelati restano intatti. Non cancellare risultati, azzerare
perdite o cambiare il significato di una curva già iniziata. Le rettifiche
documentali devono essere riconoscibili e non riscrivere gli artefatti
scientifici originali.

### Criterio di completamento

Stato iniziale riproducibile e ripristino verificato. La protezione dal guasto
del disco richiede anche una destinazione di backup indipendente, da
individuare senza presumere servizi cloud. Un backup sullo stesso volume non
deve essere presentato come protezione dal guasto fisico.

## Fase 2 — Costruire la contabilità economica corretta

### Architettura

```text
Segnali → Ordini desiderati → Fill simulati → Contabilità → Equity e report
                                 ↑
                      Prezzi e funding osservati
```

Aggiungere nel laboratorio un motore separato dalla logica dei segnali.

### Responsabilità del motore

- Quantità e moltiplicatori dei contratti, non soltanto pesi percentuali.
- Saldo del conto, P/L realizzato e non realizzato.
- Commissioni separate dallo slippage.
- Funding applicato alle quantità detenute al momento del settlement.
- Precisioni, dimensioni minime e limiti di esposizione.
- Attribuzione per strategia e posizione complessiva per strumento.

Per i futures, la valorizzazione deve seguire la contabilità del contratto:
non usare impropriamente la formula di un portafoglio spot. Eventuali
esposizioni opposte delle due componenti richiedono una regola esplicita,
evitando ordini o commissioni fittizi.

I rendimenti upstream non possono entrare nel calcolo del P/L.

### Test obbligatori

- Prezzo `100 → 110 → 100`, quantità ferme: risultato da prezzo zero.
- Nessun fill: nessuna variazione di quantità.
- Nessun movimento, costo o funding: equity invariata.
- Apertura, chiusura parziale, inversione e funding: confronto con esempi
  calcolati indipendentemente.
- Riavvio o evento duplicato: nessun doppio addebito o doppio ordine.
- Riconciliazione del conto entro una tolleranza numerica esplicita.

### Criterio di completamento

Ogni variazione dell'equity è spiegabile con eventi contabili verificabili.
La copertura del codice non basta: i risultati attesi devono provenire anche
da calcoli indipendenti, non soltanto dalla stessa formula da verificare.

## Fase 3 — Collegare un simulatore di esecuzione paper

### Ambito iniziale

La prima versione simula esecuzioni taker. Rimandare ordini maker e
modellazione della coda: aggiungono complessità non necessaria a risolvere il
problema principale.

Ogni fill registra almeno:

- Decisione e strategia di origine.
- Momento in cui il segnale diventa disponibile.
- Momento dell'ordine e dell'esecuzione simulata.
- Quantità, prezzo, commissione e riferimento alla quotazione.
- Eventuale mancata esecuzione e relativa motivazione.

### Regole di causalità ed esecuzione

- Mai attribuire rendimenti precedenti al fill.
- Quotazioni o segnali troppo vecchi impediscono nuovi ingressi.
- Il recupero di decisioni arretrate non genera fill retroattivi presentati
  come forward.
- Le posizioni aperte restano visibili anche quando mancano dati aggiornati.
- Simboli e prezzi appartengono alla stessa borsa e agli stessi contratti
  della simulazione.

Riutilizzare i dati disponibili. Se mancano quotazioni adeguate per uno
strumento, dichiararlo senza inventare prezzi. Un'eventuale lettura pubblica
mirata deve alimentare direttamente le esecuzioni, non diventare un collector
senza obiettivo.

Il conto parte con un nuovo identificativo e un boundary esplicito, senza
ereditare guadagni o posizioni del mirror. L'attivazione forward avviene solo
dopo i controlli tecnici e il riesame storico della fase 4.

### Criterio di completamento

Replay deterministico e test di riavvio superati; ogni fill è ricostruibile.
Nessun accesso a ordini reali o credenziali di trading.

## Fase 4 — Ricalcolare la candidata e confrontarla con alternative semplici

### Due verifiche distinte

1. Replay degli stessi target già prodotti: isolare quanto cambia correggendo
   contabilità ed esecuzione.
2. Riesecuzione della strategia con parametri congelati: verificare il
   comportamento completo, comprese eventuali dipendenze dal capitale e dal
   rischio.

Non modificare i parametri per recuperare un risultato peggiorato.

### Confronti

| Candidata o controllo | Domanda |
| --- | --- |
| V13 + Cointegration 50/50 | La combinazione resta interessante dopo le correzioni? |
| V13 50% + cash 50% | La cointegration aggiunge qualcosa rispetto a ridurre l'esposizione? |
| V13 a rischio comparabile | Il miglioramento rimane a parità di rischio? |
| Cointegration separata | Quali profitti, rischi e costi apporta davvero? |

Il report separa prezzo, funding, commissioni, slippage e ritardo di
esecuzione. Include concentrazione per asset, periodi negativi, turnover,
disponibilità degli strumenti e limiti dell'universo storico.

Definire le soglie di valutazione prima di leggere i nuovi risultati. Lo
storico già utilizzato resta diagnostico: non torna vergine grazie al nuovo
motore.

### Criterio di completamento

Report delle differenze rispetto ai risultati precedenti e verdetto motivato:
proseguire, ridimensionare o respingere. Un risultato negativo non avvia
automaticamente un'altra ricerca di parametri. Un eventuale ridimensionamento
che modifica la strategia richiede una versione e una valutazione distinte.

## Fase 5 — Rendere dashboard e operatività affidabili

### Dashboard

Tre aree principali:

- Conto paper: equity, P/L realizzato/non realizzato, costi, funding, posizioni,
  ultima valorizzazione e prossimo evento previsto.
- Valutazione: confronto con benchmark, attribuzione per componente,
  numerosità e maturità della prova.
- Problemi operativi: dati scaduti, gap rilevanti, esecuzioni mancate, backup
  incompleti e scadenze.

Ricerca teorica e legacy restano accessibili nell'archivio. Il grafico
principale mostra il conto paper dall'attivazione; i confronti teorici sono
espliciti e opzionali.

### Operatività

- Distinguere processo vivo, dati freschi e conto correttamente valorizzato.
- Eliminare il fallback SQLite non sicuro sul database vivo.
- Non calcolare gli overlay di ricerca quando non richiesti.
- Separare i servizi ritirati dall'avvio ordinario.
- Rendere identificabili codice e configurazione effettivamente in esecuzione.
- Restringere l'accesso gestionale conservando un percorso di accesso verificato.
- Completare copertura e verifiche dei backup.

### Criterio di completamento

Un dato vecchio non appare healthy; ogni riepilogo identifica il conto;
l'avvio standard non riattiva strategie ritirate.

## Fase 6 — Avviare la nuova prova forward con criteri di decisione

Superati i controlli tecnici e il riesame storico, attivare il nuovo paper con
parametri e regole riconoscibili.

Il protocollo precedente mantiene la propria storia e scadenza. La nuova
prova di esecuzione parte dalla sua effettiva attivazione: non eredita
automaticamente i giorni già trascorsi né una validazione al 28 febbraio 2027.

Controllare subito correttezza contabile, esecuzioni e freschezza. La
valutazione economica richiede tempo e osservazioni sufficienti: non decidere
sulla base di due trade o di una settimana favorevole.

Breadth resta un confronto separato. Execution completa la valutazione
prevista; ogni collector ha un consumatore e una data di revisione. TimesFM e
nuove famiglie di strategie non entrano nel percorso prioritario.

### Criterio di completamento

Nuovo conto forward attivato con baseline e versione verificabili, controlli
operativi funzionanti e protocollo di valutazione esplicito. L'avvio corretto
non equivale alla validazione economica della strategia.

## Ordine delle consegne e dipendenze

1. Baseline protetta e contabilità verificata: fasi 1–2.
2. Simulatore paper e report storico riconciliato: fasi 3–4.
3. Dashboard corretta, hardening operativo e nuova prova forward: fasi 5–6.

Gli interventi urgenti su backup, accesso e chiarezza delle etichette possono
essere anticipati senza alterare gli esperimenti. La fase 6 resta subordinata
alla correttezza tecnica e al verdetto della fase 4: se la candidata viene
respinta, consegnare il motore verificato e il report senza attivarla per
produrre volume artificiale.

## Stato delle consegne

- [ ] Fase 1: baseline protetta e ripristino verificato.
- [ ] Fase 2: contabilità autonoma e test economici indipendenti.
- [ ] Fase 3: simulazione taker causale, persistente e ricostruibile.
- [ ] Fase 4: ricalcolo diagnostico, benchmark e verdetto.
- [ ] Fase 5: dashboard e operatività affidabili.
- [ ] Fase 6: nuova prova forward, solo se soddisfatti i prerequisiti.

## Verifiche di rilascio

- `git diff --check` e test mirati delle parti modificate.
- Verifica del perimetro paper-only e delle autorizzazioni distinte per conto:
  observer di ricerca senza ordini; eventuali ordini paper autorizzati solo
  sul ledger dedicato; ordini reali sempre disabilitati.
- Integrità dei journal SQLite in sola lettura e verifica delle catene/hash
  pertinenti, senza riscrivere gli artefatti congelati.
- Dopo ogni eventuale avvio: stato reale dei container/processi, freschezza
  dei dati e directory di scrittura previste.
- Ritorno alla versione precedente documentato, senza cancellare gli eventi
  prodotti dalla nuova versione o riclassificarli come risultati del vecchio
  conto.

Il raggiungimento delle sei fasi non autorizza trading reale. Eventuali nuovi
ambiti, destinazioni esterne o cambi di autorizzazione richiedono una decisione
esplicita distinta.
