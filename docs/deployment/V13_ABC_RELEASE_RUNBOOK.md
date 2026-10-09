# V13 A/B/C — preparazione e rilascio controllato

Scheda work-card-7566d242-4c8e-45c0-9b21-3bc248b362ab. Preparazione offline, nessuna autorizzazione di avvio.

## Artefatti consegnati

- `v13-abc-inactive-plan-v1.json`: percorsi candidati sul disco capiente, tre scrittori distinti, slot/start non ancora fissato. Poll5s e validità intento60s sono valori candidati da verificare nel rilascio, non configurazioni applicate.
- `scripts/check_v13_abc_preparation.py`: ricontrolla hash, percorsi, UID distinti, finestra UTC e campi ancora da assegnare. Produce tre frammenti esplicitamente DRAFT_NOT_RUNTIME_CONFIGURATION: i CLI operativi li rifiutano.
- `scripts/verify_v13_abc_permissions.py`: prova reale Unix/SQLite con UID sintetici in container senza rete. Non crea utenti host. Scrittura solo sul proprio DB, letture minime, producer senza accesso al ledger executor.
- Bundle candidato e manifestv5: snapshot separato dai bundle precedenti e dall’osservatore funding già rilasciato.

L’autorizzazione alla raccolta pubblica è già acquisita e non va richiesta nuovamente per lo stesso ambito. Le bozze restano inutilizzabili dai CLI operativi per scope/UID; non sono grant di trading.

## Controlli riproducibili

Dal fork, nel runtime esistente Python/NumPy:

```bash
python3 -B scripts/verify_v13_abc_offline.py
python3 -B scripts/check_v13_abc_preparation.py --repo . --plan docs/deployment/v13-abc-inactive-plan-v1.json --bundle docs/contracts/v13-abc-implementation-bundle-2026-10-08-v5.json
```

Il secondo comando può terminare con codice0 e restituire `execution_ready:false`: il codice0 significa soltanto controllo strutturale positivo. I binding mancanti e i gate restano obbligatori. Non è una verifica della firma/approvazione del manifest né dell’ambiente installato.

La prova dei permessi richiede root solo per attribuire UID ai file sintetici e un percorso NUOVO esplicito; usa esclusivamente l’immagine locale `octobot-local:dev`. Le identità11001/11002/11003 e i relativi gruppi sono fixture, non assegnazioni operative.

## Sequenza del rilascio successivo

1. Dopo il16ottobre00:00UTC (02:00italiane), eseguire il valutatore della qualifica sul medesimo archivio e activation receipt originali. Non modificare orologio, cutoff o risultato. Proseguire solo con esito QUALIFIED effettivo.
2. Verificare osservazioni funding, eventuali gap, cambi intervallo e riconciliazione degli eventi. OBSERVATIONS_COMPLETE non equivale a copertura certificata dei regolamenti. Congelare la prova e il relativo calendario revisionato; nessun minimo exchange inventato.
3. Fissare una partenza COMUNE futura alle00:15UTC, lineage, UID reali, permessi e pin del warm-up/calendario. Assegnare identità nonroot distinte dopo verifica disponibilità; non riutilizzare implicitamente i conti V13 esistenti.
4. Preparare copia immutabile del bundle verificato, configurazioni CLI COMPLETE e pin esterni. Non passare direttamente il piano DRAFT ai CLI. Mantenere codice/configurazioni root-owned; directory DB del relativo writer, antenati root-owned e non scrivibili dagli altri ruoli. Gli input del consumer sono read-only; solo executor scrive ledger/status. Per SQLite la separazione è tra file e directory, mai per tabella.
5. Creare una sola volta store VUOTI nuovi (forward, intenti e contabilità) nelle directory assegnate, usando le rispettive classi create=True. Non usare create=True al riavvio, non cancellare né importare ledger precedenti. Verificare proprietà, gruppi e accessi con le identità definitive.
6. Conservare snapshot preavvio e rollback. Verificare in un ambiente isolato il ciclo con le identità/configurazioni effettive, senza importare fixture nei conti definitivi. Qualunque diniego deve lasciare invariati saldi e consumo intenti.
7. Eseguire il rilascio solo dopo decisione sul bundle e partenza. **Il modulo di ammissione attuale mantiene intenzionalmente comparison_activation_not_authorized: la preparazione non lo rimuove e un cambio di data/configurazione non lo sblocca.** L’integrazione della futura autorizzazione operativa dovrà essere verificata come parte di quel rilascio; non consiste nel sostituire un booleano.
8. Confermare processi reali, avanzamento ricevute, intenti sigillati, ledger coerente, equity e funding. Solo allora aggiornare la dashboard a “conti attivi”. Gli ordini reali restano fuori scope.

## Ripartenza e guasti

- Controllare processo e stato del servizio, non file `.lock`.
- L’intento non acquisisce una nuova scadenza al riavvio; quello già consumato non genera nuovi fill.
- Un nuovo intento scaduto non interrompe le osservazioni del conto precedente; nessuna operazione nuova viene autorizzata.
- Storage indisponibile o transazione fallita: nessun successo dichiarato, nessuna sostituzione del DB con uno nuovo.
- Prima di una chiusura amministrativa, rileggere stato/quantità, comando root-owned, pin, conto e scadenza. Riutilizzo o generazione cambiata vengono rifiutati. Funding incompleto mantiene debito pendente ed equity netta sconosciuta; non viene azzerato.
- Rollback: fermare soltanto i componenti ABC interessati, conservare DB, journal, ricevute e configurazioni. Non cancellare volumi e non toccare il paper V13 esistente o la qualifica.

## Limite della consegna

Il kit tecnico è pronto alla revisione, non all’esecuzione automatica. UID, start e pin non disponibili restano null anziché essere inventati. La raccolta funding pubblica continua col rilascio esistente; nessun servizio ABC o grant è creato da questo kit.
