# V13 originale — ricevute contemporanee, candidato offline

28 settembre 2026. **SYNTHETIC_ARCHITECTURE_ONLY, inattivo, readiness BLOCKED.**
Implementazione `work-card-dec1a7e6-6650-416a-9a02-290af7af0272`;
test interni `work-card-9cd8bbf3-98ce-4ac4-9b7c-37023da105a3`.

## Cosa è implementato

`v13_capture_receipt_review.py` è una libreria di prova della ricezione in
streaming e della conferma durevole. **Non ha client HTTP o entrypoint runtime**:
consuma esclusivamente stream, status HTTP e clock dichiarati sintetici.
Nessuna GET reale, nuova acquisizione, collector installato, credenziale,
issuer, approval store, ledger, grant o modifica di policy è inclusa.

Il custode campiona il proprio clock prima del consumo, al ricevimento dei
chunk e dopo la fine dello stream. I tempi non arrivano dal JSON del payload.
Conserva tutti i byte, lunghezza/SHA-256, metodo/URL del catalogo pinnato,
status HTTP di fixture, inizio/primo byte/completamento, identità del custode,
epoch/nonce, clock evidence e hash dei componenti. Il body deve completarsi con
la lunghezza dichiarata; timeout, stream corto/lungo, dati oltre il limite o
clock regressivo lasciano staging diagnostico senza ricevuta completa.

Ogni nonce identifica un tentativo di acquisizione, **non uno snapshot o una
decisione scientifica**. La cattura non può sovrascrivere il tentativo esistente.
Il witness nega anche il riuso del nonce su un'altra richiesta. Una nuova
osservazione richiede un nuovo nonce; non si rilegge un vecchio file chiamandolo
nuova ricezione. Il modulo non calcola target o causal hash della strategia.

## Persistenza e tempi

Il custode scrive raw e manifest esclusivi, fsync dei file/directory, poi
restituisce il pin. `receipt_committed_at` nel manifest resta **null**: il
manifest non può attestare il proprio fsync futuro. Il witness separato legge
RO, controlla pin/hash/lunghezza/namespace e riconferma la persistenza dei file.
Poi committa un evento sequenziale/hash-chained in SQLite DELETE/FULL e solo
successivamente campiona il clock per un ACK separato.

L'ACK lega manifest e evento già persistiti. Il suo tempo è una **osservazione
post-commit**, non il tempo del proprio futuro fsync (`own_ack_commit_time_known=false`).
Il pin dell'ACK viene restituito solo dopo fsync del file e della directory.
Il verifier RO richiede config pin, capture pin, ACK pin e head esterno,
verifica appartenenza alla chain e nega un controllo precedente alla conferma.
La conferma della singola risposta non è la disponibilità della strategia:
pubblicazione degli input e derivazione originale hanno ricevute distinte,
ancora da integrare prima di definire un descriptor futuro completo.

Clock evidence, errore zero, epoch e tempi sono **fixture**. Monotonic_ns prova
l'ordine soltanto nei campioni del custode; non viene confrontato tra ruoli o
host. La comparazione UTC del witness è ammessa solo nel modello sintetico
con errore zero dichiarato. Bound clock, freshness, skew, custodia e confine
temporale operativi restano **non approvati e non configurati**.

Crash prima di una ricevuta completa non crea ACK. Una cattura completa può
essere riconfermata esplicitamente dal witness dopo la morte del custode.
Disco pieno o fsync fallito non restituiscono un ACK utilizzabile. Se il witness
muore dopo il commit e prima della risposta, l'head vecchio viene negato: occorre
riconciliare esplicitamente il pin, senza retry automatico che ignori l'incertezza.
Il replay byte-identico dell'ACK conserva la prima osservazione. Un DB vecchio
coerente è negato con l'head successivo conservato fuori dal restore; riavvolgere
anche quel riferimento rende il rollback indistinguibile. Nessun witness
monotono operativo è installato dal candidato.

## Identità, sorgenti e UNKNOWN

Il bootstrap di fixture è root-owned e richiede un nuovo sandbox. Configurazione
0444, marker, hash di libreria/helper e contratto originale sono pinnati. Quattro
directory distinte appartengono a strategia, custode, witness e verifier;
si possono usare UID numerici effimeri nel container, senza utenti host.
Solo il custode scrive raw/manifest, solo il witness scrive l'intero witness.sqlite;
strategia e verifier hanno lettura, nessuna scrittura fidata. I permessi separano
file e directory, **non tabelle SQLite**. Bootstrap, identità e separazione nei
test non equivalgono a roster operativo o approvazione della custodia.

Sono mantenuti conto `v13-paper-v2`, lineage originale e tutti i 18 mapping
del contratto congelato, incluso BTC → XBTUSDTM. Il catalogo di fixture separa
36 richieste scientifiche Binance (daily e funding), 18 book KuCoin Futures e
una risposta contracts/active. Gli URL provengono dai percorsi già dichiarati
localmente; non sono stati interrogati o riqualificati qui. Limit=2 è soltanto
un campione di prova, non un piano completo di acquisizione/paginazione.
Questi endpoint non sono scambiabili e non attestano autenticità dell'exchange.

Risposte HTTP/applicative fallite o JSON duplicato/non finito/invalido possono
essere conservate come byte ricevuti e confermate per forensic; il verifier le
marca `response_framing_valid_fixture=false`. Una risposta HTTP/JSON valida
prova soltanto il framing, non correttezza semantica, causalità o ammissibilità.

La vista diagnostica di contratto/book verifica i riferimenti, purpose, simbolo
e valuta; conserva il campo raw markPrice e il timestamp proprio del book.
**Il timestamp di misura del mark resta null/UNKNOWN** per contracts/active;
non è ricavato dal book, dalla ricezione o da una data di pubblicazione.
Il risultato resta `DENY_MARK_TIMESTAMP_UNKNOWN`: non è un adapter esecutivo,
non normalizza quantità/profondità né sostituisce i dati richiesti da P0-03.
`min_quantity` e `min_notional` restano null/UNKNOWN, senza reinterpretare
lotSize, multiplier, minRiskLimit o regole spot. Le quattro policy operative
restano UNCONFIGURED. I test non dimostrano ammissibilità KuCoin.

Gli archivi legacy e le loro ricevute restano immutati: disponibilità storica
UNRESOLVED e ricevute di acquisizione MISSING. Il candidato sintetico non
implementa l'autorità FUTURE_CAUSAL_CAPTURE, non promuove la bozza JSON,
non rende issuable la sorgente research-only e non certifica profitto.

## Passo successivo

Revisionare libreria/envelope e integrare le dipendenze del publisher/verifier
su fixture isolate. Prima della cattura reale futura occorrono una decisione
su identità/componenti e clock/custodia, un adapter HTTP approvato con tempi
misurati effettivi, copertura/paginazione e controlli semantici dei singoli dati,
più autorizzazione alla nuova acquisizione. Nessun requisito è sostituito
dalle prove sintetiche. Restano funding, binding/epoch/policy, E2E/review e
autorizzazione esplicita al cutover/avvio paper.
