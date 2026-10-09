# Qwen — capacità verificata e arresto dello shadow BTC

9 ottobre 2026. Il proprietario ha chiesto di riprendere la verifica Qwen
rimandata e spegnere il componente se non funzionante. Nessun nuovo
esperimento sulle uscite V13 viene avviato; l'analisi BTC/veto resta materiale
per future review.

Schede:
- `work-card-be726a89-5841-4655-86c8-07d5ab71eb86`: capacità e diagnosi;
- `work-card-81a4e765-5f70-4fd1-99ee-dad330451888`: arresto autorizzato dello shadow.

## Esito e scelta operativa

Il backend Qwen funziona, ma lo shadow con limite congelato di 35 secondi
non ha margine affidabile. Fermati soltanto i quattro timer collect, decide,
recover, mature di Qwen BTC shadow e i rispettivi servizi. Disabilitati anche
per i successivi boot. Non ci sono nuovi tentativi di inferenza pianificati
da questo esperimento.

Il modello condiviso rimane attivo: l'analisi giornaliera V13 delle 08:01
italiane è ready, completata in circa 60 secondi. Il suo timer resta attivo.
La componente BTC 30/120 indipendente non è stata modificata. I sette
container paper/collector sono estranei all'arresto. Il publisher shadow
rimane attivo e la UI espone «Programmazione non attiva», scheduler false,
phase ATTENTION. Non si lascia apparire la schedulazione come funzionante.

## Evidenza operativa, senza risultati scientifici

Sette slot shadow registrati: cinque risposte valide, due MISSING al limite
di 35 secondi (7 e 9 ottobre). La registrazione MISSING è corretta, ma non è
una risposta riuscita del modello. Il journal ha integrità ok, zero conflitti;
nessuna performance o outcome scientifico è stato consultato.

Per il 9 ottobre la diagnosi rimane CLIENT_TIMEOUT_LIKELY / INFERRED:
task cancellato intorno a 35 secondi e runner a 35,044s. Il client scientifico
non conserva il codice curl; non si trasforma questa inferenza in una prova
di trasporto. L'8 ottobre il prompt richiedeva 31,25s per 3.173 token e la
risposta totale 33,592s.

Configurazione osservata: zero layer GPU, otto thread e otto thread batch,
un solo slot, context 32.768; host con 16 CPU logiche. Nessun restart del backend.
Non sono stati cambiati thread, modello, prompt, cache, deadline o sampling.

## Prova sintetica isolata

Tre richieste su 121 chiusure artificiali, identità e date fittizie,
scope SYNTHETIC_CAPACITY_ONLY. Sampling e schema uguali al contratto per
misurare la capacità; prefisso esplicito di prova, nessun dato forward o
record del journal. Slot condiviso controllato libero prima di ogni richiesta.
Nessun download, nuovo modello o servizio installato.

| Prova | Budget | Durata | Esito | CPU media del modello |
| --- | ---: | ---: | --- | ---: |
| 1 | 35s | 35,01s | curl 28, timeout osservato | 6,70 core |
| 2 | 35s | 31,66s | JSON valido, risposta completa | 7,38 core |
| 3 | 60s | 31,03s | JSON valido, risposta completa | 7,43 core |

Nelle risposte completate: 3.101 token di prompt, elaborazione 29,45/28,75s,
29 token generati in circa 2s. Il test da 60s riguarda solo la prova, non
modifica il timeout scientifico. Mostra che il modello può completare una
richiesta di questa taglia; non garantisce il limite di 35s.

Nel primo tentativo RSS passa da 17,77 a 26,30 GiB; nei successivi arriva
a 27,67 GiB. È compatibile con un costo di riscaldamento dei dati del modello
e mostra che la latenza non dipende soltanto dal numero di thread. Non prova
la causa dei timeout storici. Lo swap host resta quasi pieno; il monitor aveva
mostrato attività corrente modesta. Non è dimostrato thrashing continuo.

I dati di risorse storici agli slot delle 02:12 non erano stati raccolti:
questo limita l'attribuzione retroattiva. Il verdetto riguarda l'affidabilità
nel contratto temporale attuale, non la qualità predittiva.

## Preservazione e seguito

I 21 pin del bundle scientifico sono validi; hash di manifest, files.sha256
e journal prima/dopo l'arresto coincidono. Sette coppie conservate, performance
ancora sigillata, nessuna riscrittura, retry, backfill o promozione. Il calendario
rimane congelato, ma la raccolta è deliberatamente interrotta: non può essere
descritta come un forward continuativo completato. Le future caselle senza
record non vanno riempite artificialmente.

Per riprendere servirebbero decisione esplicita e trattamento scientifico
dell'interruzione; un cambio di timeout, input, runtime vincolato o modello
va esaminato rispetto al contratto congelato, non introdotto di nascosto.
Non è stato avviato alcun percorso di ripresa.

Evidenze fuori da Git: `audit-evidence/qwen-capacity-recheck-20261009/` nella
radice del workspace. Diagnosi recenti, piano/risultati sintetici, campioni
risorse e ricevuta di arresto. Quattordici test del diagnostico passano;
API dashboard verificata con scheduler inactive e analisi V13 ancora ready.
Sono verifiche dell'autore, non una review scientifica indipendente.
