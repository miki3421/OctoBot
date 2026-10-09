# V13 originale — executor portfolio isolato v1

28 settembre 2026. Implementazione: `work-card-9be311a0-d1b3-4350-8931-639d8240eb4f`; prove interne: `work-card-f914667b-fa10-4ca5-940f-0f48206da56f`. **Readiness BLOCKED**. Il codice aggiunge un componente candidato e non modifica il contratto DRAFT, HLD, producer, issuer o runtime operativo.

## Comportamento disponibile

`octobot.ai_strategy_lab.v13_original_executor` accetta soltanto `architecture_fixture` e `SYNTHETIC_ARCHITECTURE_ONLY`, entro un sandbox root-owned con marker esplicito. Nessun percorso operativo, daemon, rete, credenziale, writer di grant o collegamento Compose è presente. La CLI distingue inizializzazione esclusiva, ricezione dell’intento ed esecuzione di un intento già persistito; usa l’ora corrente. I test Python iniettano un orologio sintetico e non sono osservazioni forward.

L’intento contiene soltanto riferimenti a conto, epoch, binding, proposal ID, approval ID e receipt hash, oltre a versione e intent ID. Non contiene target, prezzo, quantità, leva, soglie o timestamp controllabili dalla strategia. L’executor salva payload/hash e **ora effettiva di ricezione** nel proprio database; una duplicazione identica non estende il tempo registrato. Il book deve essere successivo a questa persistenza, con raccolta iniziata non prima di essa.

I target provengono soltanto dall’approvazione e devono coprire l’universo completo dei 18 asset della V13 originale. Il reader RO controlla schema/namespace e integrità di approvals, owner, hash della ricevuta, campi denormalizzati, proposta canonica, epoch, binding, componenti, policy, contratto, scadenza e slot più recente. L’issuer BTC rimane separato e invariato.

Per nuovo rischio si attraversano il gate P0-04 e il consumo P0-01, quindi pianificazione P0-03/P0-02, controllo della policy fixture e commit simulato. Si riutilizzano direttamente i moduli P0 esistenti e la contabilità V13: profondità osservata/VWAP, slippage avverso, fee, arrotondamenti conservativi e limiti 0,315/0,90. Il lease P0-04 usa `entry_id=proposal_id` e resta aperto fino al commit, sotto lock esclusivo del conto.

Le riduzioni certe della strategia richiedono comunque un’approvazione portfolio valida e un consumo P0-01; mantengono l’eccezione esistente al grant di nuovo rischio. Non costituiscono una chiusura amministrativa indipendente dalla strategia, che resta un percorso separato. Un vettore esattamente uguale all’ultimo applicato produce `NO_CHANGE`, con soli marks/funding e ricevuta: niente rebalance per deriva dell’equity, nuova claim o incremento del contatore di rischio.

## Persistenza e guasti

| Archivio | Writer / verifiche |
| --- | --- |
| `approvals.sqlite` | Solo issuer; executor `mode=ro` e `query_only`. Nessun consumo in questo file |
| `execution.sqlite` | Solo executor: intenti ricevuti, tentativi, riserve, ordini/fill, funding, marks, equity, state, risk outcome e ricevute dei batch |
| Audit P0-04 separato | Solo executor; registry e gate amministrativi sono RO. Namespace e schema controllati insieme al ledger |

Nelle fixture, approvals è 0640 nella directory issuer 0750; execution e audit sono 0600 in directory executor 0700, con UID distinti. Questi UID/GID sono effimeri e non utenti host o topologia operativa approvati. I permessi riguardano l’intero file SQLite, **non singole tabelle**. Tutti gli archivi usano DELETE/FULL e non vengono ricreati dal normale percorso se mancanti.

Prima di entrare nel gate P0-04 viene persistito un tentativo non autorizzante, così il gap fra claim globale e callback P0-01 resta riconoscibile dopo un crash. Il candidato considera terminale anche un tentativo di nuovo rischio negato prima della claim globale: quella proposta non viene automaticamente riprovata. È una scelta conservativa delle fixture, da riesaminare nel contratto operativo. Il callback P0-01 salva una riserva `RESERVED` in una **transazione autonoma, precedente alla transazione economica**. L’unicità lega approval/proposal/intent e source-slot/account/epoch. Un nuovo intent ID non riapre una riserva consumata.

Tutte le gambe sono pianificate prima del commit. Una sola transazione salva l’intera economia, il vettore applicato, la ricevuta e lo stato `COMMITTED` della riserva/tentativo. Una gamba invalida o un veto non salva alcuna parte dell’economia; se possibile, il rifiuto terminale viene auditato mantenendo consumata la riserva. Le applicazioni matematiche dei fill nella funzione pura sono proiezioni temporanee: non sono ordini persistiti prima del controllo della policy.

Un crash con riserva pendente blocca il conto per riconciliazione; non rigenera un token. La perdita del solo audit P0-04 non lo ricrea, e una claim globale mancante rispetto al ledger impedisce nuovi batch. Un ripristino coerente ma più vecchio di entrambi gli archivi non è rilevabile solo da questi file: la procedura di restore/epoch e la sua autorità restano requisiti della futura migrazione, non certificati dalle fixture.

Dopo un commit riuscito con risposta persa, il restart legge `ALREADY_COMMITTED` con la ricevuta originale e zero nuove esecuzioni. Un errore intercettabile dopo il commit produce `COMMIT_CONFIRMED` soltanto dopo rilettura del risultato durevole; non dichiara falsamente zero fill. Se storage o audit non consentono questa verifica, la CLI restituisce errore con `persisted=false`, senza un’autorizzazione implicita.

## Policy e mercato sintetici

La sola policy fixture è root-pinned e completa. Per esercitare il meccanismo, loss e drawdown sono frazioni positive; la frequenza conta **batch di nuovo rischio committati nel giorno UTC** e il cooldown misura secondi dall’ultimo di tali batch. Equity history e batch persistiti sono riletti a ogni processo: il restart non azzera i limiti. Queste semantiche e questi numeri appartengono esclusivamente alla fixture e non configurano la futura policy operativa.

Il mercato dei test è un envelope sintetico root-owned con digest esplicito e snapshot enumerati. Per le prove matematiche usa il decoder multiasset schema 1 già esistente, con metadata **espressamente sintetici**; non allarga lo schema 2 BTC né prova provenance reali di mark/minimi per 18 contratti. P0-03 resta integro: un minimo UNKNOWN su una gamba di nuovo rischio nega l’intero batch. `min_quantity` e `min_notional` operativi restano **UNKNOWN**; `daily_loss`, `drawdown`, `order_frequency` e `cooldown` operativi restano **UNCONFIGURED**.

## Evidenza e prossimo lavoro

`audit-evidence/v13-original-executor-20260928T120425Z/`: **143 test interni PASS** (48 executor e 95 regressioni issuer/adapter). Coprono atomicità a 18 asset, minimi UNKNOWN, depth/spread/tempi, intenti alterati, slot superati, policy persistente, riduzioni/NO_CHANGE, UID, kill/revoca/grant assente, concorrenza, crash in quattro punti, commit fallito/risposta persa, lease al commit, storage e restore incoerente. Un limite SQLite di pagine genera realmente `SQLITE_FULL` nel database isolato: rollback dell’intera economia, riserva ancora consumata. Altri guasti/crash sono iniettati nei confini del commit. Non sono QA indipendente.

Il probe conserva approvals, execution, audit e ricevute dell’E2E sintetico: due fill, 18 marks, una riserva COMMITTED, approvazioni invariate e restart senza riesecuzione. Le proposte e le ricevute upstream del positivo sono fixture; **non è un E2E positivo del producer reale**, una validazione scientifica o una prova KuCoin.

Una copia consistente in sola lettura del conto originale conserva gli 8 ordini e lo stato esistente. L’inizializzazione del componente con quella baseline produce `real_account_migration_not_implemented` e non crea execution: nessuna riscrittura di history, generazioni o quantità. Rimangono da preparare migrazione/epoch/funding, adapter mercato con provenance multiasset reale, binding/confine e policy approvati, dati realmente disponibili sotto custodia indipendente, integrazione completa e review indipendente. Nessun deploy, riavvio, grant operativo, nuovo fill nel conto esistente o modifica della quarantena.
