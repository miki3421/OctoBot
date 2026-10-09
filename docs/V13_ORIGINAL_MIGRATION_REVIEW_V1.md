# V13 originale — migrazione candidata su copia, v1

28 settembre 2026. Scheda `work-card-cae0c451-c40c-41f6-a0fb-9ecdf1d48008`; prove interne `work-card-6b5c188a-bbcd-4349-a762-51c5a43ffd80`. **BLOCKED per applicazione e attivazione.** Questo componente prepara evidenze locali: non è un nuovo conto, un writer runtime o un'autorizzazione.

## Pacchetto disponibile

`octobot.ai_strategy_lab.v13_original_migration` accetta soltanto copie SQLite offline entro una directory privata con marker di revisione. Rifiuta percorsi `octobot-local`, link, traversali, WAL/journal non vuoti e destinazioni già esistenti. La CLI offre `prepare`, `verify` e `restore-review`; non offre apply, daemon, rete, grant o gestione dei servizi. Questi vincoli prevengono l'uso accidentale: il preparatore non sostituisce l'identità e l'isolamento del futuro executor.

Il bundle contiene:

| Artefatto | Contenuto |
|---|---|
| `original.sqlite` | Backup SQLite consistente del conto copiato, per confronto e rollback diagnostico |
| `execution-copy.sqlite` | Le stesse tabelle e righe storiche; una sola nuova tabella `migration_review` |
| `migration-receipt.json` | Nuova ricevuta, riconciliazione, identità candidate e prerequisiti irrisolti |
| `manifest.json` | Hash di ogni artefatto, scope inattivo, epoch candidato e hash della ricevuta |

La tabella storica `state` resta identica. Le nuove identità compaiono **soltanto nello stato candidato di revisione** e nella ricevuta. Ogni posizione attualmente aperta riceve un ID derivato da conto, epoch candidato e simbolo, con generazione 1 **a partire da questa migrazione candidata**; non è la prima apertura storica e non viene retrodatata. L'epoch dipende dal backup, dal checkpoint e da un nonce esplicito; rimane non approvato e non configurato. Nessun ordine, funding, prezzo, mark o punto equity viene aggiunto allo storico.

L'ispezione controlla integrità SQLite, versione e tabelle legacy, stato senza pending, numero ordini, replay della contabilità dei fill e coerenza di quantità/entry/fee/realizzato; confronta marks, funding già contabilizzato, cursori mercato ed equity conservata. Il confronto contabile ammette esclusivamente la regola di 8 ULP già usata dalla contabilità V13. Non prova autenticità exchange, validità scientifica, ammissibilità dei fill storici o copertura funding esterna al ledger.

## Riconciliazione e dati mancanti

La copia reale contiene 8 ordini, 8 posizioni, 14 punti equity, 104 marks e 13 market events, tutti del 21 settembre. I simboli aperti sono AAVE, ETH, LINK, NEAR, SOL, UNI, XLM e ZEC. Gli ultimi marks sono circa alle 12:00 UTC; `funding_events` è vuoto. Questo indica **zero righe contabilizzate**, non funding certamente nullo dopo quel momento.

Per ogni posizione la ricevuta conserva l'ultimo mark osservato e l'ultimo settlement presente nel ledger, oppure `null` se assente. L'intervallo successivo all'ultimo mark resta `UNKNOWN`; non si sposta il cursore al checkpoint. Il checkpoint del preparatore non è una nuova osservazione di mercato. Il gap attuale supera il limite esistente di 20 ore: nessun tick economico viene tentato.

La formula legacy usa rate KuCoin regolate e il mark precedente osservato come **stima dichiarata**, non il mark esatto del settlement. Prima della ripresa occorrono rate di settlement con segno, tempi e provenance verificabili per il periodo mancante, marks applicabili e decisione umana sul criterio di ricostruzione. Se i marks richiesti non esistono, va dichiarata tale assenza e definita una riconciliazione approvata; il codice non aggiunge settlement, non finge una scansione completa degli archivi e non azzera il costo.

Il massimo equity storico e l'ultimo fill restano documentati. Apertura giornaliera della nuova policy, conteggio dei batch e origine del cooldown non vengono inizializzati automaticamente: le semantiche di cutover richiedono decisione. `daily_loss`, `drawdown`, `order_frequency` e `cooldown` restano non configurati. `min_quantity` e `min_notional` restano **UNKNOWN**: bloccano le nuove aperture KuCoin-faithful, senza impedire questa preparazione architetturale.

## Autorizzazioni, writer e ripristino

Il conto legacy non contiene approvals, claim P0-01 o audit P0-04 del nuovo executor. La ricevuta li dichiara `UNINITIALIZED`; non produce approvazioni retroattive né interpreta gli 8 fill come nuove claim. Per questo il bundle reale **non è un ledger inizializzato per il nuovo executor**. L'executor isolato continua a rifiutare baseline reali e copie; issuer, contratto DRAFT e moduli P0 restano invariati.

Il cutover futuro deve escludere il vecchio runner come writer, mantenere un solo executor per execution/claim/audit e un issuer distinto per approvals. Strategia e issuer non avranno scrittura sul ledger; executor leggerà approvals RO. I permessi SQLite riguardano il file intero, mai una tabella. La topologia dei writer non viene installata da questo incarico.

`restore-review` verifica un digest del manifest fornito **da fuori del bundle**, poi crea una nuova directory diagnostica senza sostituire file esistenti. Tutti gli artefatti devono corrispondere; errori, storage failure e pubblicazione interrotta lasciano evidenze, senza bundle ammesso. Il manifest viene scritto per ultimo, dopo commit e sync. Il backup `original.sqlite` costituisce il rollback diagnostico; non autorizza il ritorno del vecchio runner né l'applicazione di un saldo vecchio.

Una funzione separata per fixture crea checkpoint coerenti di **approvals + execution/claim + audit P0-04**. Verifica namespace/epoch, approvazioni, claim globali, tentativi e batch; una riserva o un tentativo incerto richiedono riconciliazione. I test ripristinano tutti e tre gli archivi in una nuova directory e negano il backup precedente quando il digest esterno resta fissato al checkpoint successivo. Solo fixture `SYNTHETIC_ARCHITECTURE_ONLY`: non simulano authority sul conto reale.

Il digest esterno è un **witness candidato di revisione**, non un'autorità monotona già installata. Chi può riavvolgere anche quel riferimento può rendere indistinguibile un backup coerente vecchio: i soli file non risolvono il problema. Prima del restore operativo servono custodia separata del witness aggiornato, freeze degli scrittori, bundle completo sotto lock, decisione sull'epoch/invalidazione delle autorizzazioni precedenti e controllo del solo writer. Nessun restore operativo è implementato qui.

## Prossimo passaggio

Prima proseguire con il contratto di provenance/disponibilità dei dati multiasset già in To Do e con la chiusura amministrativa legata alle identità candidate; completare l'integrazione su copie/fixture e la review indipendente. Poi decidere binding, cutover/funding, epoch/topologia e policy. Solo un successivo batch esplicitamente autorizzato potrà applicare la migrazione e avviare il paper account. Nessun deploy, riavvio, grant operativo, nuova acquisizione dati o cambio quarantena è incluso.
