# V13 A/B/C — kit di preparazione tecnica completato

8 ottobre 2026. Scheda work-card-7566d242-4c8e-45c0-9b21-3bc248b362ab.

Consegnati piano inattivo e tre configurazioni candidate, validatore read-only del bundle e dei binding, prova riproducibile dei permessi Unix/SQLite, procedura di rilascio e rollback. Le bozze sono rifiutate dai CLI operativi: nessun grant o conto creato. Percorsi candidati sul disco capiente; UID, partenza, lineage e pin ancora non definiti restano esplicitamente null. L’autorizzazione ai download pubblici già ricevuta viene conservata.

## Correzioni verificate

1. Il controllo della custodia ora distingue directory dello scrittore e antenati root-owned. Il vecchio controllo richiedeva root anche per la directory dove SQLite deve creare il journal e avrebbe rifiutato la configurazione prevista. File non regolari, symlink, proprietario diverso e scrittura di gruppo/altri restano rifiutati. Nessuna modifica al collector di qualifica o al suo contratto.
2. Un intento nuovo scaduto non interrompe più le osservazioni del conto esistente: resta non eseguibile e l’equity può continuare ad aggiornarsi con i controlli consueti.

## Evidenze

- 114 test della suite offline superati nel runtime locale esistente, senza rete.
- Tre identità sintetiche in container: ciascuna scrive soltanto il proprio DB. Producer legge il collector ma non il ledger executor. Executor legge gli input e scrive solo il proprio archivio. Nessun utente o gruppo host creato.
- Preflight controlla hash, separazione di UID/directory/store, timing, pin e valori da assegnare. technical_checks_passed non significa execution_ready: quest’ultimo resta false.
- Bundlev5 separato dagli snapshot precedenti. Le evidenze sono in audit-evidence/v13-technical-preparation-20261008/ alla radice del laboratorio.

## Uso della consegna

La procedura completa è docs/deployment/V13_ABC_RELEASE_RUNBOOK.md; il piano è docs/deployment/v13-abc-inactive-plan-v1.json. I frammenti per collector, producer ed executor sono nello stesso percorso. Il piano documenta la proposta e non applica configurazioni all’host.

La preparazione del kit è conclusa. Restano fuori dalla sua accettazione: esito della qualifica dal16ottobre02:00italiane, copertura funding e sua revisione, binding definitivi e autorizzazione/verifica del rilascio effettivo. Il gate di ammissione attuale continua a rifiutare l’attivazione e non viene aperto automaticamente da una data o da un booleano nel piano.

Nessun nuovo servizio o riavvio; osservatore funding esistente ancora attivo. Conti paper esistenti, minimi KuCoin UNKNOWN, journal e prove storiche preservati. Nessun push indiscriminato delle modifiche locali pregresse.
