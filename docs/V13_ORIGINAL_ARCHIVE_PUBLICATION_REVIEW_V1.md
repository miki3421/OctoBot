# V13 originale — integrazione offline archivio, pubblicazione e derivazione

Scheda `work-card-824a3cd4-3dc8-437f-abbf-6a233b0ce0a5`.
Test: `work-card-a8e4020b-5b68-40a0-9fda-cd51c64634b4`.
Componente: `octobot/ai_strategy_lab/v13_original_publication_review.py`.
**Candidato inattivo, LEGACY_ARCHIVE_REVIEW, readiness BLOCKED.**

## Consegna

Il componente collega i byte originali già conservati al verificatore originale
congelato e alle ricevute di pubblicazione persistenti. Non usa il normalizzatore
sintetico come derivazione della strategia. Riutilizza soltanto gli helper di
filesystem, fsync, SQLite e hash-chain del candidato precedente, anch'essi
pinnati; mantiene una nuova versione e un marker/configurazione separati.
Non modifica moduli scientifici, vecchio verifier, helper portfolio o issuer.

Percorso offline:

`archivio originale RO → inventario delle dipendenze selezionate → copia
persistente del custode → manifest del publisher → ACK post-commit witness
→ reconstruct originale → ricevuta derivazione persistente → ACK post-commit
witness → verifica RO dei pin esterni`

L'inventario conserva il prefisso journal in byte originali fino allo slot,
le daily compresse e le risposte raw referenziate dal sottoinsieme scientifico
di 18 asset. Ogni file ha path relativo, lunghezza e SHA-256; i raw mantengono
hash della risposta decompressa, metodo e URL già conservati. Le dipendenze
scientifiche e il contesto iniziale restano quelli validati dall'implementation
lock e dalla lineage del loader originale: non sono sostituiti da prezzi o da
una strategia diversa. La selezione resta la V13 standalone originale, senza
ripartizione 50/50, senza BTC 30/120 e senza ereditarne autorizzazioni.

La ricerca originale usa gli endpoint Binance Futures congelati nei suoi raw;
questo non li trasforma in metadata o prezzi esecutivi KuCoin. Il futuro mercato
esecutivo del conto è un'altra dipendenza, ancora da qualificare separatamente.
Per i record raw legacy i campi request/response/receipt storici e clock evidence
restano null, con `historical_capture_receipt_status=MISSING`.
La copia fatta oggi non crea ricevute di acquisizioni passate.

## Ricalcolo e verifica

Il verifier legge la copia persistente e invoca davvero
`v13_original_verify.reconstruct`, che controlla raw/normalizzazioni, prefisso
daily, prefisso dei target e parametri/codice originali congelati. Confronta tutti
i target del prefisso, non soltanto il segnale finale. Il wrapper controlla hash,
identità, universo, source record e prefix, numero dei record, raw response hash,
versione/codice verifier e vettore canonico completo di 18 asset.
Conflitti tra duplicati funding raw nel periodo consumato vengono rifiutati prima
della copia: il comportamento last-wins del parser storico non li nasconde.
Il nuovo snapshot lega causal hash, slot, lineage, universo e versione; non
riinterpreta l'identità dei journal storici. Byte futuri non consumati rimangono
fuori dal prefisso selezionato. Nessuna validità predittiva viene certificata.

Il replay ricalcola nuovamente e confronta tutti i campi sostanziali; conserva
la prima ricevuta, incluso il suo tempo di completamento, invece di sostituirla
con una nuova lettura del clock. Target o input discordanti rifiutano il replay.
La ricevuta originale mantiene research-only, availability UNRESOLVED e
issuable false. Cambiare questi campi e ricalcolare gli hash non la promuove.

## Persistenza, clock e custodia

File esclusivi senza sovrascrittura, fsync di file/directory e riconferma
indipendente precedono le attestazioni. Il witness committa l'evento in SQLite
DELETE/FULL, poi campiona l'orologio locale e pubblica un ACK separato. Il tempo
attesta un'osservazione successiva al commit referenziato, non il fsync futuro
dell'ACK stesso. Nessun pin viene restituito da un ACK con persistenza fallita.
Un evento committato senza ACK resta recuperabile, senza availability pubblicata.
Staging, SQLite FULL, fsync fallito e morte del processo non creano autorizzazioni.

`current_review_available_at` descrive solo il bundle di revisione persistito
oggi, dopo il completamento della derivazione. Non è `source_available_at`:
quest'ultimo resta null, con `historical_availability_status=UNRESOLVED`.
Il clock non può retrodatare la revisione prima del bootstrap pinnato; i clock
forniti ai test sono diagnostici, non orologi operativi approvati. Clock policy,
limiti di errore/freshness/skew e custodia operativa restano non approvati.

Il bootstrap crea directory di sandbox per strategy/custodian/publisher/verifier/
witness, senza installare utenti. Nei test gli UID sono effettivamente distinti;
la strategia non può scrivere copie fidate, manifest, derivazioni, configurazione
o witness, né invocare i writer. Gli altri ruoli leggono il witness RO, il solo
witness scrive l'intero file SQLite e la directory. I permessi non separano
singole tabelle. Approvals ed execution non vengono aperti da questo componente.
Il probe reale archiviato usa un solo UID: non certifica custodia indipendente.

Pin esterni di configurazione, inventario, ACK e head sono obbligatori.
Resta il limite già documentato: se un restore riavvolge anche i pin esterni,
la coerenza locale non dimostra assenza di rollback. Nessun custode monotono
operativo viene installato o approvato dal candidato.

## Limiti e seguito

Il collegamento offline è implementato; la scheda di integrazione resta in
**Test** per revisione della versione e delle dipendenze reali ancora mancanti.
Non è completato un percorso di acquisizione futura con ricevute contemporanee,
identità approvate e orologio qualificato. Non si converte retroattivamente
l'archivio legacy in FUTURE_CAUSAL_CAPTURE. L'issuer reale continua a negare
binding non approvato / fonte research-only.

Restano separati: ricevute di nuove acquisizioni, custodie/clock, binding/epoch,
metodo/qualità funding, risk policy, close amministrativo originale, E2E del
conto e cutover. daily_loss, drawdown, order_frequency e cooldown restano non
configurati. min_quantity e min_notional restano UNKNOWN e bloccano soltanto
nuove aperture KuCoin-faithful. Questa integrazione non dimostra ammissibilità
KuCoin, risultati scientifici o readiness per il deployment.
