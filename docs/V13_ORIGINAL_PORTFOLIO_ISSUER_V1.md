# V13 originale — issuer portfolio isolato v1

28 settembre 2026. Schede: implementazione `work-card-71bc1c35-d049-48d2-825c-de2f5f479a67`; prove interne `work-card-69a717fd-b2e7-488b-aef6-6e9bbf58c6a5`. Stato del rilascio: **BLOCKED**. Queste prove non costituiscono una review indipendente o un’autorizzazione operativa.

## Risultato e perimetro

`octobot.ai_strategy_lab.v13_original_issuer` implementa un issuer separato per il vettore completo della V13 originale: 18 asset, conto candidato `v13-paper-v2`, componente `risk_budgeted_bear_regime_v13`. Riutilizza parser, schema e controlli del verifier originale senza modificarli. Il producer e l’issuer BTC 30/120 rimangono separati. Nessuna previsione viene certificata come profittevole.

Sono ammessi soltanto due profili locali, entrambi entro un sandbox esplicitamente marcato:

| Profilo | Esito ammesso | Significato |
| --- | --- | --- |
| `diagnostic_only` | `DENY` persistito, oppure errore senza autorizzazione | Verifica una ricevuta reale copiata; nessun binding operativo approvato |
| `architecture_fixture` | `APPROVE`, `DUPLICATE` o `DENY` | Stesso codice issuer, con contratto, policy, disponibilità e custodia dichiaratamente sintetici |

Ogni ricevuta positiva reca `scope=SYNTHETIC_ARCHITECTURE_ONLY`, `operational_approval=false`, `scientific_certified=false` e `kucoin_order_admissibility_proven=false`. Non esiste un profilo operativo attivabile in questa versione. Il sandbox non può stare in `octobot-local`; nessun executor, ledger, grant, ordine o configurazione Compose è collegato.

## Verifiche e ricevute

La configurazione è root-owned, non scrivibile dagli altri ruoli, e richiede un digest esplicito proveniente dal chiamante fidato. Vengono verificati di nuovo a ogni richiesta configurazione, marker del sandbox e hash di adapter, verifier e issuer. Le ricevute hanno proprietario, digest del file e digest del contenuto vincolati dalla configurazione: questi riferimenti non arrivano dalla proposta della strategia. File simbolici, hard link, genitori scrivibili da altri e cambiamenti durante la lettura sono rifiutati.

Il positivo architetturale verifica schema e hash canonici, identità conto/lineage/universo, tutti i 18 target, corrispondenza esatta alla derivazione, dipendenze raw, ricevuta di pubblicazione e ordine causale dei tempi. Verifica inoltre epoch e binding sintetico, confine futuro, esclusione dello slot baseline, freshness, policy completa e contratto di ammissibilità sintetico pinnati. Questi ultimi verificano il controllo di emissione; non dimostrano l’ammissibilità di un ordine sull’exchange né applicano già il controllo del rischio al futuro fill.

La ricevuta lega l’intera proposta, il suo hash, il bundle dei componenti, binding, contratto candidato e schema, versione/hash della policy e del contratto sintetico. Contiene un ID generato dall’issuer, timestamp e scadenza. La durata della fixture non è una configurazione operativa. La CLI usa l’ora corrente; l’iniezione dell’ora nell’interfaccia Python serve alle sole prove isolate.

## Persistenza, proprietà e restart

`approvals.sqlite` contiene metadata del namespace, approvazioni e audit dell’issuer. Usa SQLite `journal_mode=DELETE`, `synchronous=FULL`, controllo di integrità e schema esatto. La creazione è esplicita ed esclusiva; il normale utilizzo non ricrea un database mancante. L’inizializzazione sincronizza anche la directory.

L’issuer è l’unico writer del file e della directory. Il gruppo reader ha accesso in sola lettura; strategia ed executor delle prove non possono modificarlo. I permessi filesystem riguardano **l’intero SQLite**, non singole tabelle. Non esistono API di claim, consumo o ledger in questo issuer. Il futuro executor dovrà consumare le autorizzazioni in un distinto `execution.sqlite`, di cui sarà l’unico writer, senza accesso in scrittura ad approvals.

Le unicità sono per proposal ID e per `(account, epoch, binding, source_record_hash)` e `(account, epoch, binding, source_bar_date)`. Sotto transazione `BEGIN IMMEDIATE`, una richiesta identica restituisce la stessa ricevuta e la stessa scadenza; cambiare timestamp o ID non riemette lo slot. Un conflitto è negato durevolmente. Uno slot precedente a quello già approvato è negato. Ricevuta e audit positivo vengono salvati nello stesso commit.

Un crash prima del commit non lascia approvazioni; dopo il commit un retry restituisce la ricevuta già salvata. Corruzione, modalità WAL inattesa, schema/namespace errati, storage non scrivibile o commit fallito non producono una risposta autorizzante. Se l’audit non è persistibile, la CLI restituisce errore con `persisted=false`; non dichiara un rifiuto durevole inesistente. Un consumer futuro dovrà rileggere e verificare scadenza, stato e consumo dall’evidenza persistita: `DUPLICATE` non concede una nuova autorizzazione.

## Evidenza raccolta e limiti

Evidenze: `audit-evidence/v13-original-issuer-20260928T113705Z/`. **95 test interni PASS**: 39 casi issuer e 56 regressioni adapter/verifier. Coprono positivo sintetico, conflitto dello slot, target incompleti/alterati, account/epoch/binding errati, causalità/freshness, pin e proprietari errati, symlink, policy/contratto incompleti, UID separati, concorrenza, corruzione/schema/WAL e guasti/crash intorno al commit. Tre processi CLI verificano inoltre l’errore esplicito `persisted=false` con storage mancante, corrotto o non scrivibile. Il primo run fallito per un gruppo di lettura errato nella fixture è conservato; sono stati corretti soltanto i permessi del sandbox di test.

La ricevuta reale del 27 settembre è stata copiata senza alterazioni e letta da due nuovi processi CLI con UID issuer non-root: **zero approvazioni, due `DENY: binding_unapproved` persistiti**. Sono riportati anche `source_availability_unresolved` e `source_custody_unresolved`. Separare i processi di questa prova non dimostra la custodia indipendente della precedente acquisizione. Gli UID/GID 30010/30020/30030/30040 sono fixture effimere; non sono utenti host, roster o topologia di deployment approvati.

Restano da implementare executor portfolio, consumo durevole e transazione economica atomica, test integrati e migrazione sul conto copiato. Rimangono necessari binding/confine/epoch approvati, ricevute realmente causali sotto custodia distinta, policy e review indipendente. Il contratto candidato già documentato resta `DRAFT` e inattivo; non è stato aggiornato retroattivamente.

`min_quantity` e `min_notional` KuCoin restano **UNKNOWN**. `daily_loss`, `drawdown`, `order_frequency` e `cooldown` operativi restano **non configurati**. I numeri presenti nelle fixture non sono raccomandazioni né valori approvati. Nessun deploy, riavvio, nuova acquisizione pubblica o modifica alla quarantena è incluso.
