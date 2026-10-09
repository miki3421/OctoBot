# V13 originale — contratto candidato di provenienza e disponibilità multiasset

28 settembre 2026. **DRAFT, inattivo, readiness BLOCKED.** Conto esistente
`v13-paper-v2`, portafoglio `trend-v13-original-standalone`, strategia
`risk_budgeted_bear_regime_v13`. Non cambia il modello originale, non adotta il
producer BTC 30/120 e non eredita la ripartizione trend/cointegration 50/50.

Scheda di design: `work-card-58b6b012-473e-45dc-b4e7-b04f287fcbd3`.
Verifica interna: `work-card-b8855526-73c2-4572-afad-0f4b5de4c084`.
La [descrizione dichiarativa](contracts/v13-original-multiasset-provenance-candidate-v1.json)
è un contratto da revisionare, **non uno schema di validazione eseguibile né
una configurazione runtime**. Nessun componente lo importa. Le classi e i campi
proposti non sono autorizzazioni; il codice di enforcement resta da implementare.

## 1. Evidenza esistente e impiego consentito

| Classe | Cosa dimostra | Limite e impiego candidato |
| --- | --- | --- |
| `LEGACY_ARCHIVE_REVIEW` | Identità dei byte conservati, chain e corrispondenza degli archivi normalizzati | Disponibilità storica indipendente UNRESOLVED. Solo ricerca e possibile stima funding retrospettiva su copie, subordinata a criterio e qualità accettati. |
| `FUTURE_CAUSAL_CAPTURE` | Contratto proposto per ricevute indipendenti e input causalmente disponibili | Non implementato. Neppure una futura verifica positiva conferisce autorità di emissione o attesta qualità predittiva. |
| `SYNTHETIC_ARCHITECTURE_ONLY` | Fixture isolate per prove della pipeline di controllo | Nessuna ammissibilità KuCoin, nessuna sostituzione di metadata o authority operativi. |

L'inventario funding congelato contiene **693 record**, **168 settlement distinti**
per gli otto asset detenuti e **168 riferimenti a mark precedenti**. Gli otto asset
non rappresentano l'universo completo del modello. I record sono normalizzazioni
schema 1: mancano byte raw delle singole risposte REST, tempi di ricezione per
richiesta, timestamp di misura dei mark e custodia indipendente contemporanea.
L'assenza è documentata in questo archivio; non è una dichiarazione di assenza
in tutto il repository. Chain e SHA-256 non sono firme dell'exchange.

Il prefisso journal ha SHA-256
`59d48ca654438e407dc28074b8f1e318bc871bcc65e289194580500e17c14ceb`,
congelato il `2026-09-28T13:34:20.018791+00:00` secondo la ricevuta locale
`audit-evidence/v13-funding-reconciliation-20260928T133115Z/capture.json`.
Questo tempo documenta il congelamento dichiarato oggi, non la disponibilità
attestata il 21 settembre. `observed_at_end` resta una dichiarazione del collector;
`recorded_at` non diventa un tempo di pubblicazione. Un mark precedente al
settlement secondo questi campi resta una **stima candidata**, non un prezzo
con misura exchange attestata. Nessun importo funding è calcolato in questo lavoro.

La derivazione research originale rimane verificabile con i suoi artefatti raw
quando presenti; le ricevute diagnostiche correnti mantengono
`availability_status=UNRESOLVED`, `research_only=true`, `issuable=false`.
Nessuna nuova ricevuta conferisce retroattivamente autorità a quei record.

## 2. Identità completa e sorgenti

Il JSON riprende esattamente i **18 simboli**, mapping candidati e hash universo
`15ef730f7484b7bd0563399015725b8e018f251660e9baef98ce88bb33238108`
dal contratto portfolio precedente, senza modificarne hash o binding. BTC usa
`XBTUSDTM`; gli altri mapping sono quelli già osservati, non stringhe dedotte
automaticamente. Prima dell'uso futuro il custode confronta ogni mapping con la
risposta contrattuale conservata: prodotto Futures, quote/settlement USDT,
identità del contratto, multiplier e unità dichiarate. Un mapping cambiato richiede
review/versione; il valore spot non prova la semantica Futures.

L'archivio può contenere altri asset, fra cui PEPE. Si conserva l'intero payload
raw e si seleziona esplicitamente il sottoinsieme di 18. Un extra **nel payload**
non viene promosso nel portafoglio; un extra nel vettore selezionato o un asset
obbligatorio mancante rifiuta il batch completo. Nessuna applicazione parziale.

I percorsi GET pubblici già dichiarati dai collector costituiscono evidenza del
percorso configurato, non una nuova verifica delle API: klines per il segnale;
contracts/active, allTickers e level2/depth20 per mercato/contratto;
contract/funding-rates per settlement. L'eventuale endpoint di mark con timestamp
exchange deve essere individuato e verificato separatamente prima dell'uso.
Il valore `contracts/active.markPrice` e il timestamp del book non bastano a
costruire il timestamp di misura del mark. Nessuna chiamata o nuova acquisizione
è eseguita in questo checkpoint. Il nuovo envelope multiasset è separato dallo
schema 2 BTC: P0-03 e il collector operativo non sono estesi o indeboliti.

## 3. Tempi, causalità e disponibilità

Ogni acquisizione futura deve conservare byte raw completi, metodo/URL/query
esatti senza segreti, status HTTP e risultato transport, lunghezza/SHA-256,
identità e bundle del collector, inizio richiesta, fine ricezione effettiva e
ricevuta durevole del custode. JSON duplicato, numeri non finiti, timeout,
risposta parziale o codice applicativo non valido non producono dati ammissibili.

Per ciascun campo normalizzato si conservano riferimento raw, unità, posizione
nel payload e regola di trasformazione. Distinguere rigorosamente:

- **Misura exchange:** timestamp effettivo fornito per quel valore, con campo e
  unità della sorgente; se assente, `null`/`UNKNOWN`.
- **Ricezione:** intervallo reale richiesta/risposta, senza attribuirlo alla misura.
- **Persistenza/pubblicazione:** conferma durevole del custode/publisher.
- **Derivazione:** conclusione del ricalcolo indipendente e successiva ricevuta
  durevole del verifier. Un tempo di inizio non prova la conclusione.

UTC da host diversi richiede evidenza dell'orologio e limite d'errore approvato;
una sequenza monotona locale prova l'ordine su quel custode, non la sincronia
fra host. Errore orologio, limite di freshness e skew multiasset non sono
configurati qui. Nei confronti causali futuri si usano limiti conservativi che
includano l'incertezza; senza bound approvato non si certifica la disponibilità.
Timestamp futuro, intervallo invertito o dato oltre il limite autorizzato → DENY.

`raw_sha256` identifica l'acquisizione integrale. `causal_input_hash` identifica
solo il sottoinsieme effettivamente consumato: barre chiuse e ammissibili,
valori/unità, versione del contratto e universo. Un'aggiunta di barre future non
consumate può cambiare il raw hash, ma non il causal hash né lo snapshot dello
slot. L'identità dello snapshot lega lineage scientifica, data/slot, universo,
contratto e causal hash. La provenance resta separata con i raw hash: non si
cancella per stabilizzare l'identità. Gli ID/journal storici non si riscrivono.
L'eventuale mapping di questa identità nella futura proposta/binding è oggetto
di versione e review, non una modifica implicita di `source_record_hash`.

Proposta di protocollo futuro, ancora senza enforcement:

1. Custode approvato registra raw e ricevute durevoli indipendenti dalla strategia.
2. Publisher scrive bundle immutabile con input causali, manifest e dipendenze,
   verifica hash, esegue fsync di file e directory, pubblica senza sovrascrivere.
3. Una ricevuta di completamento attestata **dopo** la persistenza lega manifest,
   sequenza/epoch e hash delle ricevute delle dipendenze. File parziali sono staging.
4. Verifier separato legge RO, ricalcola il vettore originale e pubblica ricevuta
   di derivazione durevole. Non importa codice non pinnato dalla strategia.
5. Custode esterno conserva pin delle ricevute e descriptor finale di disponibilità:
   `source_available_at = max(completamento durevole delle dipendenze,
   pubblicazione durevole, ricevuta durevole della derivazione)`.

Nessun file può autoattestare il tempo del proprio fsync futuro: il completamento
è confermato da un ack/witness successivo, separato dal payload che attesta.
Non si inserisce il hash di una ricevuta dentro se stessa. Il descriptor finale
lega gli hash già conclusi; la propria pubblicazione ha a sua volta una ricevuta
esterna. L'issuer deve osservare la pubblicazione finale prima di emettere.
Il timestamp di decisione segue l'effettiva disponibilità degli input/derivazione;
il tempo della proposta segue la decisione. Nessuna retrodatazione.

L'helper portfolio attuale confronta `publication.completed_at` e
`derivation.verified_at`: questi campi non dimostrano da soli il commit durevole
di tutte le ricevute. La futura integrazione dovrà versionare esplicitamente
questa interfaccia e verificare gli ack; **l'helper e l'issuer non sono modificati**.
Ricevute create ora da una sola identità non soddisfano questo contratto.

## 4. Custodia, storage e fallimenti

| Oggetto | Writer proposto | Accesso della strategia |
| --- | --- | --- |
| Raw e capture receipt | Custode acquisizione approvato | RO |
| Manifest/publication e witness | Publisher/custode indipendente autorizzato | RO |
| Derivation receipt | Verifier isolato | RO |
| Proposta inbox research | Strategia | Scrittura non fidata |
| approvals.sqlite | Solo issuer | Nessuna scrittura/accesso fidato |
| execution.sqlite: claim, stato e ledger | Solo executor sotto lease P0-04 | Nessuna scrittura/accesso fidato |

Identità, path/mount, componenti e autorità witness devono essere approvati e
pinnati prima dell'installazione. Nessun UID reale è creato qui. L'issuer legge
ricevute RO e verifica pin esterni, ownership, schema e identità; una proprietà
`approved` scritta dalla strategia non ha autorità. I permessi filesystem
separano **file**, non tabelle SQLite. Un processo writer di un file può modificare
ogni tabella: mantenere separati approvals e execution, strategia esclusa da
entrambi. La semplice presenza di due file non prova la separazione runtime.

Crash, disco pieno, fsync fallito, hash discordante, manifest incompleto o witness
non raggiungibile non producono disponibilità verificata né effetti economici.
Bundle incompleto viene conservato fuori dalla namespace pubblicata per diagnosi,
mai completato con valori inventati. La ripresa controlla manifest e sequenza;
identità già pubblicata non si sovrascrive. Due payload diversi nello stesso slot,
receipt ripetuta incompatibile, contract mapping errato o rate duplicati discordanti
nel raw → DENY. Re-osservare lo stesso settlement non lo contabilizza due volte.

Un restore vecchio ma internamente coerente richiede un witness monotono esterno
alla copia ripristinata. Se si riavvolge anche il witness, il rollback non è rilevabile
con i soli hash locali. Nessun witness operativo esiste per questo nuovo contratto;
non dichiarare risolto il problema. Replay di publication e consumo one-shot
P0-01 sono due controlli distinti e restano necessari entrambi.

## 5. Handoff e decisioni ancora aperte

Il riconciliatore su copie riceverà capture/manifest originali e selezione
`LEGACY_ARCHIVE_REVIEW`, senza una finta receipt di disponibilità storica. Mantiene
zero approvazioni operative, otto ordini e quattordici punti equity storici;
registrerebbe la rettifica al tempo reale di contabilizzazione. Il metodo funding
candidato e i limiti qualitativi rimangono quelli del piano precedente, non
approvati da questa bozza. Fonte current/predicted non sostituisce settlement;
nessuna stima silenziosa, nessun grant, nessun ordine aggiunto.

| Decisione | Raccomandazione candidata | Cosa resta bloccato |
| --- | --- | --- |
| Qualità/metodo funding legacy | Stima esplicita su copie con rate settled e mark antecedente osservato; conservare UNKNOWN per misura mark | Applicazione economica al conto e nuovo checkpoint operativo |
| Custodi, bundle e witness | Separare strategia, publisher/verifier e writer; pin esterni conservati fuori dal restore | Availability fidata, issuer operativo e rollback detection |
| Tempi e copertura | Misure per campo, bound clock/freshness/skew approvati; full 18 senza leg parziali | Ammissibilità snapshot futuri e mercato esecutivo |
| Binding/epoch/confine futuro | Nuove proposte solo dopo confine approvato; ricerca storica preservata | Emissione di autorizzazioni operative |
| Modalità paper e risk policy | Rendere espliciti modello di simulazione e semantica contatori prima dei valori | Attivazione writer/controlli operativi |

`min_quantity` e `min_notional` rimangono **UNKNOWN**, codificati `null`; evidenza
contrattuale autorevole applicabile ancora mancante. Nessuna deduzione da lotSize,
minRiskLimit o regole spot e nessun valore zero. Questa mancanza blocca nuove
aperture **KuCoin-faithful**, non il design o test sintetici isolati. `daily_loss`,
`drawdown`, `order_frequency`, `cooldown` rimangono **UNCONFIGURED**.

Ordine minimo del seguito: (1) riconciliatore inattivo e test su copie con metodo
esplicito candidato, (2) publisher/verifier inattivi e fixture causalità/crash,
(3) review e decisioni sopra, (4) protective close amministrativo sul writer unico,
(5) E2E e restore/review indipendente, (6) preparazione cutover separata. Nessuna
raccomandazione è approvazione. Non avviare collector/servizi né cambiare quarantena.

## Riferimenti

Contratto portfolio e HLD v0.3 restano le bozze preesistenti: questo documento
precisa la dipendenza dati già dichiarata, non approva un nuovo confine fidato.
Fonti locali: `docs/V13_ORIGINAL_PORTFOLIO_ADAPTER_CONTRACT_DRAFT_V1.md`,
`docs/V13_ORIGINAL_FUNDING_RECONCILIATION_PLAN_V1.md`,
`audit-evidence/v13-funding-reconciliation-20260928T133115Z/REPORT.md`,
`audit-evidence/v13-original-offline-adapter-20260928T102548Z/REPORT.md` e
`octobot/ai_strategy_lab/{microstructure,v13_market,v13_original_portfolio}.py`.
