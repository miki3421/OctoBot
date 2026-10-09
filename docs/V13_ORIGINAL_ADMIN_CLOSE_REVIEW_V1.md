# V13 originale — chiusura amministrativa su copia

**Candidato inattivo del 28 settembre 2026. Readiness BLOCKED.**
Implementazione `work-card-72a59034-fdee-494d-9d06-f996c5803088`;
test interni `work-card-0954a079-fe50-4c48-95cb-83115521bfac`.
Nessuna installazione, grant, avvio, nuova acquisizione o modifica del conto operativo.

## Confine e identità

`v13_original_admin_close_review.py` aggiunge una libreria di revisione, priva
di entrypoint operativo. Usa solo un sandbox privato e un bundle di migrazione
verificato con SHA-256 del manifest fornito da fuori del bundle. Non modifica
l'executor originale, che continua a negare l'ammissione di baseline reali;
non modifica issuer, strategia, P0-03, collector, policy o quarantena.

La configurazione candidata è un file root-owned 0444, fissato da hash esterno,
con hash dei componenti, account `v13-paper-v2`, epoch candidato, UID/GID
dell'executor, UID/GID dell'amministratore, UID distinto della strategia e nome
del canale. Queste identità sono **proposte effimere di prova**, non utenti
operativi approvati. `runtime_admission=false` e `operational_apply=false`
sono obbligatori. La custodia dei riferimenti esterni e la topologia operative
restano da approvare e installare separatamente.

Il canale di prova è un socket Unix locale che accetta una sola richiesta e
viene rimosso al termine. La directory è 0750, executor-owned, nel gruppo
primario candidato dell'amministratore; il socket è 0660. Il ricevente legge
**SO_PEERCRED dal kernel** e confronta UID e GID; un campo UID nel payload non
autentica nessuno ed è respinto dallo schema. Non serve né viene invocato un
modello, producer, verifier di strategia o issuer. Non si tratta di stop/horizon
automatici e non è un servizio avviato nel progetto.

## Comando e riduzione

Il comando contiene schema, nonce SHA-256 monouso, account, epoch candidato,
simbolo, position ID, generazione, emissione/scadenza UTC e quantità massima
positiva da ridurre. TTL massimo cinque minuti **di fixture**, da approvare
per l'eventuale canale operativo. Schema esatto, valori non finiti, timestamp
futuri/scaduti e identità discordanti sono negati. La validità viene ricontrollata
prima della riserva e prima del commit economico.

L'executor legge le quantità correnti sotto lock esclusivo. Il comando non
contiene side o target: il segno opposto deriva dalla posizione corrente.
Una quantità superiore a quella detenuta viene negata; il comando non viene
adattato silenziosamente. Per una riduzione parziale occorre il passo positivo
osservato e la quantità deve esserne multipla. Una chiusura intera usa la
quantità effettivamente detenuta, come nel ramo protettivo P0-03 esistente.
La verifica dopo il fill vieta crescita, inversione e riduzione oltre il limite.

Le identità derivano dalla migrazione: generazione 1 assegnata al checkpoint
candidato, **non** ricostruita come prima apertura storica. Una chiusura conserva
il tombstone e non abilita riaperture o riuso della generazione. Un futuro
percorso di apertura dovrà gestire esplicitamente la nuova generazione/epoch;
non è implementato qui.

## Prezzi, funding e persistenza

Questo candidato ammette **solo mercato SYNTHETIC_ARCHITECTURE_ONLY** con pin
dei byte fornito dall'executor. Richiede book, profondità in quantità base,
mark, timestamp di mark/metadata e fee dichiarata. Richiama direttamente
`structure_and_time` e `preflight(..., protective=True)` P0-03, poi il VWAP
e lo slippage avverso del simulatore esistente. Book crossed, futuro, stale,
profondità insufficiente o dati mancanti negano il fill. Prezzi/profondità e
osservazioni complete restano nella ricevuta. Non si usano i prezzi storici
del conto come book corrente. `min_quantity` e `min_notional` restano null,
ossia **UNKNOWN**; il ramo nuove aperture P0-03 continua a negarli.

`admin-review.sqlite` è un nuovo registro di revisione privato 0600, scritto
dal solo executor: stato candidato, claim e eventi. Le copie di migrazione,
tabelle storiche, ordini, equity e funding originali restano intatti. Strategia
e amministratore non possono accedere al DB; l'amministratore usa il socket.
Questo è isolamento **per file/directory**, mai per tabella SQLite.
`approvals.sqlite` non viene creato, letto o scritto dalla chiusura.

La riserva del nonce viene committata e sincronizzata prima del fill. Il fill,
stato e claim COMMITTED vengono scritti in una seconda transazione SQLite
DELETE/FULL. Replay negato; una riserva incerta impedisce anche altri comandi
fino a riconciliazione. Guasti prima del commit economico lasciano la posizione
invariata. Morte o errore di sync **dopo** il commit possono lasciare il fill
di revisione già persistito, senza risposta positiva: non si dichiara rollback
inesistente, non si riprova e occorre riconciliare claim, stato ed evidenza.
Il clock non è qualificato per l'operatività; i test usano un clock sintetico.

La catena di eventi deve coincidere con il riferimento head fornito da fuori
del DB; il ripristino coerente di un DB vecchio è negato con il riferimento
successivo. Riavvolgere anche il riferimento esterno vanifica questa difesa:
il candidato non dispone di un witness operativo monotono già installato.

Il funding mancante non viene azzerato, stimato o aggiunto; il cursore storico
di funding/mark non avanza. La ricevuta dichiara copertura `UNRESOLVED` e non
pubblica un'equity corrente del portafoglio con marks misti. Un fill di revisione
su quantità reali copiate e prezzi sintetici prova la meccanica di chiusura,
**non** l'ammissibilità KuCoin o il risultato economico del conto operativo.

## Prima dell'abilitazione

Completare catture contemporanee e custodia/clock, decisione sulla riconciliazione
funding, binding/epoch/topologia e policy, integrazione E2E e review indipendente.
Approvare amministratore, canale, TTL e custodia anti-rollback; integrare il solo
writer nel cutover senza affiancarlo al runner legacy. Richiedere poi autorizzazione
esplicita per l'attivazione paper. I minimi UNKNOWN bloccano le nuove aperture
KuCoin-faithful; non impediscono queste prove architetturali di riduzione.
