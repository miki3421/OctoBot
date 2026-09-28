# Trading AI Lab — contratto candidato portfolio V13 originale

28 settembre 2026 · v1 · **DRAFT, NON APPROVATO E NON ATTIVO**.
Progetto `project-tranding-ai-lab`; conto esistente `v13-paper-v2`.
Scheda `work-card-2d179f9f-dc76-49cd-aebd-8ca9ecaf6f64`.
Verifica dichiarativa `work-card-c4ced497-5634-4969-b980-bf523a688410`.

Questo documento completa la specifica dell’adattatore; non implementa un issuer/executor, non modifica HLD/spec approvati né autorizza nuovi fill. La scelta del conto esistente è già acquisita. Il file JSON associato è **dichiarativo e inattivo**, non configurazione runtime. Restano BLOCKED attivazione, nuove aperture KuCoin-faithful e ogni emissione finché i parametri di approvazione sono mancanti.

## 1. Identità preservata e risultato atteso

Si conserva il conto V13 V2, le sue quantità e i suoi 8 fill; nessun capitale o rendimento del legacy V1, del combinato 50/50 o del BTC 30/120 viene accreditato. Strategia: `risk_budgeted_bear_regime_v13`; stessi parametri, 18 asset e codice congelato. La componente Cointegration serve al contesto dell’archivio originale, non ai target del conto V13 standalone.

Il contratto operativo candidato si chiama `v13-original-portfolio-adapter-candidate-v1`. Non crea una nuova strategia scientifica: il suo digest operativo è distinto dal riferimento agli artefatti scientifici originali. La verifica della lineage non è una promozione scientifica né eredita autorizzazioni. Il nuovo BTC `v13-btc-paper-new-v1` e il suo issuer rimangono separati e non vengono modificati.

| Pin originale | SHA-256 verificato |
|---|---|
| Protocollo forward, file | `4b46004584f352230339afccfc8c2c950d72ddbd5b126a82fe159483830cb616` |
| Protocollo forward, contenuto | `c2d1abbc716a4775d6cdac15774613f657009adab55984189bf2f2b1dc42e010` |
| Implementation lock, contenuto | `9b3bda6f2771d55aa1d66b1c9148eec3feb222d50f70d7d47678eba7e7279de4` |
| Selected model, file | `c191d1122d1c9031354aa55a0b5cb2fbf242efe7484e6265ca11681dbfb5fac2` |
| Trend, sorgente | `ec07dc6c6fb74a9763a3251cb4b9c5753b3625566f8fb2d63fa41361c43a57f9` |

I 16 file congelati, manifest, universo e hash file/contenuto sono enumerati nel [JSON dichiarativo](contracts/v13-original-portfolio-adapter-candidate-v1.json). `scientific_lineage_ref` è il digest della mappa di questi riferimenti, **non** un nuovo lock o una nuova lineage scientifica approvata. I runtime dichiarati nel vecchio lock restano evidenza; non si aggiunge una nuova regola di uguaglianza runtime per aggirare o irrigidire il loader originale. Gli artefatti storici devono riprodursi esattamente secondo i controlli già esistenti.

## 2. Origine della futura proposta e causalità

La sorgente research ufficiale resta read-only e `research_only=true`. Nessun token o approvazione viene aggiunto al journal; nessun record corrente diventa issuable. Il futuro adattatore produrrà **una proposta separata**, da una nuova derivazione verificata del componente congelato per un nuovo slot dopo il confine approvato. Può referenziare la corrispondente osservazione research come provenance; quella referenza non è l’autorità di esecuzione. L’issuer necessita anche del contratto umano e della verifica indipendente.

Sono obbligatori prima di qualunque emissione: binding root-pinned approvato, confine futuro e baseline sorgente, modalità di ammissibilità, epoch della migrazione, hash dei nuovi componenti/dependency bundle e identità del verifier. Oggi sono **null/UNAPPROVED**. Si respinge ogni record nel prefisso già esistente, incluso il catch-up del 28 settembre, e ogni slot precedente al confine. Si conserva la storia per audit, senza approvazioni retroattive.

Il solo selettore economico è `decision_payload.research_targets.trend_component_weights`, verificato tramite ricalcolo indipendente del componente congelato. Sono esclusi `trend_effective_portfolio_weights`, Cointegration, rendimenti e curve equity research. Nessun refit, scaling, ottimizzazione o nuova alpha.

Il verifier opera in un processo distinto senza accesso ad approvals/ledger/control; esegue soltanto codice e dipendenze pinnati, senza rete. La sua ricevuta lega input causali, hash raw/daily e journal, sorgenti originali, vettore ricalcolato, tempi reali di disponibilità, versione e risultato. Il processo strategia non può scriverla; l’issuer ne verifica ownership e contenuto su un mount RO, non importa codice dalla strategia. Il pinning/custodia locale non è una firma exchange.

`source_available_at` è il massimo dei tempi **reali** di ricezione delle dipendenze, pubblicazione completa/fsync della sorgente e disponibilità della ricevuta di derivazione. Il `recorded_at` legacy, che può essere l’inizio dell’acquisizione, non basta. Mancano receipt sufficienti → `source_not_available`, senza inventare tempi. Deve valere:

`chiusura barra + lag originale ≤ disponibilità input ≤ source_available_at ≤ decision_timestamp ≤ proposal_timestamp ≤ issuer_checked_at`.

Un nuovo book deve essere disponibile dopo l’intento. I limiti di età del P0-03 e la scadenza dell’approvazione restano controlli ulteriori. Nessuna osservazione futura entra in una proposta passata.

## 3. Proposta completa e identità del batch

Lo [schema candidato](contracts/v13-original-portfolio-proposal.schema.json) richiede account/portfolio/epoch, reference scientifico e binding operativo, hash sorgente/publication receipt/derivation receipt, slot, timestamp causali, hash universo e **tutti i 18 target**. Non ammette campi extra: niente token, grant, equity, quantità, prezzo, fee, leva, kill o soglie.

Universo completo:

`AAVEUSDT, ADAUSDT, ATOMUSDT, AVAXUSDT, BCHUSDT, BTCUSDT, DOGEUSDT, DOTUSDT, ETHUSDT, HBARUSDT, LINKUSDT, LTCUSDT, NEARUSDT, SOLUSDT, UNIUSDT, XLMUSDT, XRPUSDT, ZECUSDT`.

I quattro asset eventualmente assenti dalla mappa research sparse sono espansi a peso zero soltanto dopo confronto con l’universo congelato. **Un asset mancante nella proposta completa è un rifiuto**, non una chiusura implicita. Lo zero del target significa flat; non ha relazione con i minimi contrattuali, che restano UNKNOWN. Posizione detenuta fuori universo → `unexpected_held_symbol`, nessuna liquidazione automatica. Mapping exchange candidato esplicito a 18 contratti, ricavato dalle osservazioni esistenti; non costituisce approvazione dei metadata o nuovo accesso API.

I pesi sono valori binary64 finiti della derivazione congelata, serializzati come stringhe decimali nella rappresentazione shortest round-trip, senza arrotondamenti; zero canonico `"0"`, nessun `-0`, NaN, Infinity o booleano. Per i nonzero la stringa deve coincidere con `repr(float(value))` nell’encoding specificato. Il verifier confronta il vettore completo esattamente; le sole tolleranze di esposizione restano quelle esistenti P0-02. La forma JSON non verifica da sola i limiti o la derivazione.

Canonical JSON UTF-8: chiavi ordinate, separators `,`/`:`, `ensure_ascii=false`, `allow_nan=false`, parser senza chiavi duplicate. `proposal_id = SHA256(canonical({domain: "v13-original-portfolio-proposal-v1", proposal: payload_senza_proposal_id}))`. Tutti i campi, il vettore e i tempi sono vincolati. La ricevuta issuer contiene anche hash esatto del payload canonico.

Unicità issuer: `(account, epoch, binding, source_record_hash)` **e** `(account, epoch, binding, source_bar_date)`. Cambiare il timestamp/intent ID non crea una seconda autorizzazione per lo stesso slot. Duplicato identico restituisce la stessa ricevuta senza nuova emissione; stesso slot con proposta diversa → `source_slot_conflict`. L’intento consumer può contenere soltanto riferimento esatto alla proposta/approval e tempo effettivo di persistenza; l’executor rilegge i target dall’approvazione, mai da valori forniti dal modello.

Vettore identico all’ultimo realmente applicato → marks/funding e ricevuta `NO_CHANGE`; nessun rebalance dovuto soltanto a deriva delle quantità teoriche/equity, nessun consumo di token o contatore di nuovo rischio. Sono preservate le regole di cambiamento target del conto originale. Una proposta rifiutata non aggiorna il vettore applicato.

## 4. Issuer: ammissibilità e persistenza, non profitto

L’issuer indipendente verifica binding approvato, epoch/confine futuro, proprietà dei file, hash/chain senza riscritture, slot unico, schema, account e universo, causalità e receipt indipendente, derivazione originale esatta e contratto di ammissibilità esplicito. Flag `approved` della strategia o health non hanno autorità. Policy non configurata o verifier assente → DENY durevole, mai un’approvazione implicita.

La ricevuta APPROVE lega proposal ID/hash, **intero vettore**, account/epoch/portfolio, scientific reference, binding e component bundle, sorgente/slot, receipt/tempi, risk policy versione/hash e admissibility contract versione/hash. Include approval ID generato solo dall’issuer, timestamp effettivo e scadenza. Durata candidata massima 30 minuti dall’emissione, da approvare con il contratto; nessun backdating, estensione automatica o reissue dopo crash. Una modifica della policy non riutilizza vecchie approval.

Una APPROVE indica soltanto ammissibilità della proposta nel pilota/versione scelti; non certifica profitto, scientific validity o ammissibilità del book KuCoin al futuro fill. Il forward ufficiale del combinato, incluso `required_before_shadow_or_paper`, resta immutato e non dichiarato superato. Il separato pilota originale richiede una decisione esplicita sul suo contratto: questo DRAFT non la sostituisce.

## 5. Esecutore: claim durevole e commit dell’intero portafoglio

Sotto lock esclusivo dell’account, l’executor verifica approval RO, epoch corrente, slot non superato e stato riconciliato. Un batch più recente finalizzato rende il precedente non eseguibile. Fonte o approvazione stale, quantità ignote, gap funding o cursore incoerente negano il batch.

Per nuovo rischio, il lease P0-04 ha `entry_id=proposal_id` deterministico, non un intent ID riscrivibile. Il callback P0-01 registra una **riserva consumata durevole in execution.sqlite prima della transazione economica**, con unicità su approval/proposal/source-slot/account/epoch. Nessuna scrittura in approvals.sqlite. Il lease copre pianificazione, P0-03, P0-02, risk policy, fill simulati e commit. Riduzioni da strategia richiedono comunque un’approvazione portfolio valida; l’eccezione P0-04 per riduzioni certe non autorizza un intento BTC parziale o misto.

Tutte le quote per asset detenuti e target richiesti devono essere verificate insieme. Serve un adapter multiasset che provi provenienza di mark/metadata per ciascun contratto: non si allarga silenziosamente lo schema 2 BTC e non si spaccia schema 1 per metadata completi. L’assenza di un solo requisito P0-03 blocca **tutte** le gambe; min_quantity/min_notional UNKNOWN non diventano zero o fixture operative. Si preservano book/VWAP/slippage/fee, arrotondamenti conservativi e cap P0-02 0,315/0,90. Le verifiche di tutti gli stati intermedi precedono ogni fill.

Pianificazione e una sola transazione economica: ordini/fill, state e vettore applicato, funding, marks, equity, market evidence, risk outcome e ricevuta finale di batch. **Nessuna esecuzione parziale** se una gamba è invalida; nessun retry del sottoinsieme. Il contatore di frequenza futuro deve identificare il batch, secondo policy da approvare. Il codice BTC resta invariato; il nuovo adattatore deve mantenere le garanzie del suo controllo, non copiarne il filtro di scope o il modello a singolo target.

| Punto di guasto | Esito richiesto nel futuro executor |
|---|---|
| Prima della claim P0-04/P0-01 | Nessun effetto; eventuale ripetizione richiede ancora approval valida e ordine degli slot |
| P0-04 consumata prima di P0-01 | Batch bruciato, zero fill; nuovo intent ID non lo riapre |
| P0-01 riservata prima del commit | Claim resta consumata, zero fill; classificare ABORTED/UNKNOWN con audit, senza rigenerare token |
| Errore durante fill/commit SQLite | Rollback di **tutte** le gambe; claim durevole resta consumata. Marks/funding eventualmente salvati separatamente devono avere un evento contabile distinto e verificato |
| Commit riuscito, risposta persa | Leggere ricevuta COMMITTED; restituire risultato, mai rieseguire |
| Errore audit, disco pieno, storage read-only | DENY e zero fill; impossibilità di persistere il DENY dichiarata come errore, senza fallback in memoria |

La riserva durevole evita che il rollback dell’economia riabiliti una approval. Frequenza/cooldown e history si basano su stato persistito; non si azzerano al restart. Restore deve comprendere claim, ledger, P0-04 audit e epoch coerenti, non soltanto il saldo.

## 6. Proprietà di SQLite, writer e chiusura amministrativa

| Risorsa | Writer unico logico | Lettori fidati / esclusioni |
|---|---|---|
| Proposal journal/inbox | Processo strategia | Issuer/verifier RO; nessuna autorità di approval |
| Raw/daily originali | Custode/collector esistente | Verifier RO; strategia senza scrittura di evidenza fidata |
| Derivation receipt | Verifier isolato | Issuer RO; strategia senza scrittura |
| approvals.sqlite | Issuer | Executor RO, niente claims in questo file |
| execution.sqlite: claim + ledger | Executor | Strategia/issuer senza mount; UI legge snapshot pubblicato dall’executor |
| P0-04 registry/gate | Amministrazione già autorizzata | Executor RO; nessun writer modello |
| Consumer audit e export UI | Executor | UI/export RO; nessuna flag health equivale a grant |

UID e topologia devono essere configurati/approvati separatamente: i numeri usati nelle fixture BTC non sono roster o account host approvati. Codice e protocollo root-owned/RO, niente rete/credenziali nei processi strategy/verifier/issuer/executor; mount writable limitati e capacità rimosse. Sola lettura degli input non implica permesso di acquisire nuovi dati.

Lo stesso SQLite contiene più tabelle: ogni processo con write access al file può modificarle tutte. **Nessuna separazione per tabella attraverso chmod.** Per approvals condiviso tra issuer e reader executor, proposta minima: journal mode DELETE e synchronous FULL, file/directory scrivibili solo dall’issuer, gruppo executor RO; evitare i requisiti di scrittura SHM del WAL. Questa scelta è da provare con UID distinti. Execution resta del solo executor; la UI riceve backup consistente RO, con freshness/epoch esposti, senza richiedere scrittura nel suo SHM.

Chiusura protettiva futura: comando al socket amministrativo dello **stesso writer**, autenticato con identità locale del peer e canale approvati. Client amministrativo senza write mount ledger; account, simbolo, position ID/generazione, command ID monouso, issued/expires e quantità massima da ridurre vincolati. Executor rilegge quantità/book/provenienza/tempi; vietate inversione o aumento; replay e storage failure negano il comando. Nessuna nuova previsione richiesta. Migrazione dovrà attribuire ID/generazione con una ricevuta nuova, non fingere dati storici. Stop/horizon automatici restano un lavoro distinto e non sono introdotti.

## 7. Decisioni residue e prove per l’implementazione

Binding operativo inattivo; confine futuro, epoch e decisione owner non configurati. Daily loss/drawdown/frequency/cooldown sono **null**, anche se il report gate propone numeri per discussione. Il pilota, le semantiche delle policy, l’expiry candidata, la topologia, la custodia del verifier e il criterio di funding necessitano revisione prima di configurazione operativa. Nessun requisito KuCoin viene inferito o reinterpretato.

Le prove seguenti sono requisiti **futuri**, non PASS di software non scritto: sorgente/derivazione alterata; portfolio parziale; target equivalente ma non canonico; receipt mancante/posteriore; BTC single-target contro conto multiasset; doppia approval dello slot; replay con nuovo intent ID; stato/epoch cambiati; tick precedente all’intento; seconda gamba invalida; crash in tutti i punti della tabella; kill/revoca durante il lease; restore incoerente; UID separati e tentativi SQL della strategia; close con generazione/quantità mutate. Le fixture positive devono dichiarare metadata/policy sintetici e non provano KuCoin order admissibility.

Ordine del lavoro: (1) implementare parser/hash/adattatore e verifier offline, bloccati per default; (2) issuer e consumo durevole/executor portfolio con sole fixture isolate; (3) preparare migrazione sul conto copiato e metadata multiasset, senza inventare minimi; (4) review indipendente, decisioni esplicite e batch operativo. Nessun deploy o avvio incluso.

Schede successive: policy `work-card-cc961b2b-f28d-4d08-befc-0f6ae376e884` e migrazione `work-card-cae0c451-c40c-41f6-a0fb-9ecdf1d48008`, ancora To Do. [Matrice dei gate](../../audit-evidence/v13-existing-account-gates-20260928T094618Z/GATES_REPORT.md). Il recupero scientifico e la riconciliazione contabile precedenti sono evidenze distinte; il progetto resta **BLOCKED per attivazione**.

Implementazione tracciata To Do: adattatore/verifier `work-card-fe78a248-3d67-45fa-86b0-bbc5eed8e71e`; issuer `work-card-71bc1c35-d049-48d2-825c-de2f5f479a67`; executor `work-card-9be311a0-d1b3-4350-8931-639d8240eb4f`; prove isolate `work-card-898bdd9a-0108-4558-8d4e-0d07687f9f6a`. Nessuno di questi moduli e implementato da questo documento.
