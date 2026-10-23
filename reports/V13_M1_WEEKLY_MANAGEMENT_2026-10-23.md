# M1 — selezione settimanale collegata: candidato pronto, attivazione pendente

23 ottobre 2026. SINGLE_AGENT; lenti Supervisor, Developer e QA applicate in sequenza, senza rivendicare revisione indipendente. Skills: `mmtech-company-baseline`, `software-house-project-manager` per pianificazione/stato. Progetto `project-tranding-ai-lab`, roster approved, nessun cambiamento al roster o alla policy aziendale.

## Risultato concreto

Implementati selettore settimanale, collector pubblico separato, broker autenticato delle approvazioni, continuazione del runner M1 sul medesimo ledger, esclusioni LONG persistenti, budget SHORT indipendenti e UI con approvazione/rifiuto, costi, scadenze e risultato dell'esecuzione. Proposta, intenzione e fill sono collegati. I nuovi simboli sono pubblicati nei grafici solo dai prezzi osservati dopo l'ammissione.

Pagina destinataria: `/v13_variants/m1/review`. Il codice è pronto ma **non caricato sui servizi operativi in questa consegna**. La UI pubblicata in precedenza continua a mostrare le metriche storiche; non dichiarare già applicata la selezione. Nessuna proposta reale approvata dall'agente.

Specifica: `docs/V13_M1_WEEKLY_MANAGEMENT_V1.md`. Candidato Compose: `docker-compose.v13-m1-managed.yml`. Preparatore ripetibile che rifiuta la sovrascrittura e non avvia servizi: `scripts/prepare_m1_weekly_release.py`.

## Evidenza verificata

| Verifica | Esito |
| --- | --- |
| Test mirati runner legacy, gestione, autorizzazione, route, selector e grafici | **68 test passati** nell'immagine Python effettiva già locale, rete disabilitata |
| Browser desktop/mobile, codice reale delle route e token CSRF | Passati su preview isolata, nessun errore JavaScript o richiesta esterna |
| Password errata, conferma assente, origine differente e CSRF assente | Decisione negata, nessun ordine |
| Approvazione da browser, broker Unix UID 30945, runner UID 30943 | Decisione consumata dal processo distinto; cinque riduzioni effettive sulla copia privata |
| Nuove ammissioni | PUMP e QNT a posizione zero; test DAILY separato verifica il successivo ingresso con fill |
| Storico prima della prova | 286 righe orders e 87 fill M1 preservati come prefisso identico; dopo la prova 291 e 92 |
| Metadati dei cinque nuovi fill | Revisione, hash proposta, decisione approvante e codice presenti |
| Riavvio del runner gestito | Revisione 1 conservata; nessun riacquisto dei LONG esclusi |
| Crash durante commit | Policy, consumo approvazione e stato annullati insieme; retry senza duplicazione |
| Funding mancante / policy alterata / approvazione scaduta o conflittuale | Nuovi ingressi negati; nessuna inferenza dei dati mancanti |
| Integrità SQLite | `ok` sulle copie offline coerenti; copia Originale byte-identica prima/dopo |
| Compose e separazione | Configurazione valida; UID distinti, ledger separati, nessun mount di verificatore nel runner, Originale RO, broker e runner senza rete |
| Healthcheck broker | Eseguito realmente sul servizio Unix isolato: passato |
| Servizi operativi alla fine delle prove | Undici container `octobot-*`, tutti healthy; M1 e UI non riavviati in questa attività |

Il primo tentativo di includere la vecchia suite del selettore richiedeva il suo percorso di import aggiuntivo; il comando finale con PYTHONPATH appropriato ha passato tutti i 68 test. Nessuna dipendenza installata. Browser reale usato anche per verificare il JavaScript; Node non è installato sull'host.

Evidenze private fuori Git: `audit-evidence/m1-weekly-integration-20261023/`, con snapshot iniziali, ricevute pubbliche, runtime usato nella prova, copia privata finale, `browser/browser-result.json`, screenshot desktop/mobile, `accounting-verification.json` e `operational-containers-final.json`. I quattro container fixture sono stati fermati al termine; dati e risultati preservati.

Le acquisizioni pubbliche reali hanno ottenuto daily e quotazioni dei 29 simboli il 23 ottobre, con ricevute archiviate. Nel test end-to-end gli orari dei book sono stati resi sintetici e i prezzi fissati, con etichetta **CONTROL_FIXTURE_ONLY**. Il test dimostra il controllo e la contabilità, **non l'ammissibilità KuCoin né un vantaggio economico**. Le quotazioni iniziali non vengono riutilizzate come prove di eseguibilità al momento del deploy.

## Candidato operativo preparato

Runtime root-owned `/opt/v13-m1-paper-runtime-v3`, 368 file con SHA-256 nel manifest esterno `octobot-local/v13-m1-management-v1/release-manifest.json`. Stessi file di gestione usati nelle prove; il manifest verifica anche le dipendenze già presenti nel vecchio runtime. Immagine locale immutabile `sha256:7e825796375e06e3cfb6ea46b5b7202bdba4c0bb998bdffea5e02b8bd9d67575`; nessun download d'immagini.

Configurazioni e directory preparate separatamente dal runtime attivo. Nessun verificatore operatore o file autorizzante `runtime-upgrade.json` creato in questa fase. Il template di upgrade non è autorità. Il candidato non può partire come continuazione autorizzata finché questi passaggi non vengono completati.

Il codice della nuova funzionalità viene consegnato separando le modifiche locali preesistenti del controller. Il repository contiene ancora molte dipendenze e modifiche storiche non consolidate: non si dichiara che un clone pulito del solo commit ricostruisca l'intero laboratorio. Per questo rilascio il runtime completo root-owned e il suo manifest sono l'artefatto operativo identificabile.

## Passaggi residui precisi

1. Password dedicata alle sole approvazioni scelta dall'operatore. Input locale `~/.ops/m1-ui-approval.credential`, una riga di almeno 12 caratteri, mai in chat. Generare il verificatore con `scripts/configure_m1_approval_password.py` nel percorso privato configurato; nessuna password predefinita o riutilizzo di credenziali CP/exchange.
2. Conferma manuale del passaggio operativo secondo la regola aziendale “The operator performs the manual deploy and acceptance”: sostituire il solo M1 sullo stesso ledger, avviare i due servizi dedicati e ricaricare la sola UI. Non è autorizzazione a una proposta specifica o a trading reale.
3. A M1 fermo, creare backup fresco e verificarlo offline. Compilare l'upgrade root-owned con identità iniziale, identità del candidato, hash del backup, riferimento reale all'autorizzazione e ora. Non riscrivere l'identità iniziale né le righe storiche. Avviare prima broker/collector, quindi la continuazione senza `--initialize`. La configurazione v2 e il vecchio container devono restare recuperabili e non concorrenti.
4. Copiare nella directory runtime della UI il controller già verificato, ricaricare `octobot-local`, verificare percorso utente, stato canale, nuove ricevute, conto/rischio/storico e salute degli altri servizi. Test negativo delle decisioni senza password sul runtime pubblicato; la prima approvazione reale resta all'operatore.
5. L'operatore approva una selezione specifica in UI. Osservare nel ledger le riduzioni sul primo book successivo utile; gli aumenti aspettano DAILY 00:15 UTC o un segnale M1 valido e tutti i controlli. Solo allora si potrà dichiarare il primo ribilanciamento operativo verificato. Accettazione finale e chiusura delle schede dopo questo riscontro.

Originale invariata, nessun ordine reale, grant, cambio quarantena o variazione delle altre strategie. Minimi reali KuCoin **UNKNOWN**; readiness exchange-faithful **BLOCKED**.

## Schede

| Ambito | ID | Stato della consegna |
| --- | --- | --- |
| Integrazione conto esistente | `work-card-026c44e2-f248-41ac-aa1f-da68db8f1e98` | Test locale passato; verifica operativa pendente |
| Disegno e custodia | `work-card-778887ed-6380-440b-a6c0-22df7d664e98` | Artefatto verificabile, in Test |
| UI approvazione | `work-card-bd1f0a85-5dac-4029-8d07-9e929e429caf` | Browser isolato passato; caricamento operativo pendente |
| Prove | `work-card-77ca0963-6d54-4788-8e84-669cf7d19408` | Prove locali concluse; E2E operativo pendente |
| Consegna e cutover | `work-card-8f398480-1842-4f8e-88d1-947756d0916c` | Preparata; password e conferma operatore richieste |
