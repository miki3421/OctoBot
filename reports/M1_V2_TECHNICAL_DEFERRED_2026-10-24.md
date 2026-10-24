# M1 v2: passaggio tecnico autorizzato, attesa fine episodio

**24 ottobre 2026.** L'operatore ha autorizzato esclusivamente il passaggio tecnico del pacchetto già verificato, non il ribilanciamento. Manifest invariato `b454f2d0763b349c103dde0baa1a3a83586de34b8c79f45a48192ef8099baa6d`, proposta `1772f2efa446fa66888a35b803ffc234fa46e667a86ae9714ce0d49e5fffe6c0`.

Il controllo preliminare ha rifiutato di proseguire prima di fermare alcun servizio: il conto aveva appena pianificato un episodio M1, segnale alle **17:10 CEST**, ingresso previsto alle **17:15** e uscita prevista alle **23:15 del 24 ottobre**. Alla successiva lettura l'episodio è ACTIVE. Non è stata rimossa o aggirata la condizione del pacchetto: il passaggio richiede fase NORMAL e nessun intent pendente.

## Continuazione unica del lavoro autorizzato

`scripts/wait_m1_transition_deploy.py` attende in sola lettura sul medesimo conto. È un processo temporaneo di manutenzione, non un collector o una strategia, senza ricorrenza o autostart dopo reboot. Controlla la fase ogni trenta secondi; procede una sola volta, soltanto quando la condizione del pacchetto è soddisfatta.

Prima di eseguire il pacchetto risincronizza il Control Plane, verifica che regole/skill/capacità siano ancora quelle lette e che il checkpoint del progetto non sia stato sostituito da altro lavoro. Un cambiamento interrompe l'operazione per review. I pin del pacchetto, l'immagine, la scadenza e l'assenza di policy/decisioni vengono ricontrollati dal preparatore già approvato. Non si modifica alcun timer di trading, non si chiude uno SHORT e non si forza un REENTRY.

La finestra di attesa è limitata a quattordici ore e termina comunque almeno quindici minuti prima della scadenza della proposta. Se NORMAL non viene raggiunta, la procedura si ferma senza applicare il pacchetto. Se il passaggio tecnico fallisce, non vengono fatti tentativi ciechi dopo un possibile stop parziale: backup e stato restano disponibili per il controllo.

Dopo un passaggio riuscito, la procedura esegue il collaudo browser su `/v13_variants/m1/review` e sulle pagine collegate. Usa solo una password deliberatamente non valida, controlla CSRF/origine, versione e budget SHORT, salva screenshot desktop/mobile e verifica che la proposta resti PROPOSED e la policy assente. La password reale dell'operatore non viene letta. Le schede tornano in Test per l'accettazione tecnica; la scelta economica in UI resta separata.

Sei test mirati verificano che l'episodio attivo, un intent pendente, la scadenza o un cambiamento del checkpoint impediscano il deploy, e che un errore durante il passaggio non causi tentativi automatici ulteriori. La modalità `--check-only` non scrive stato né chiama il deploy.

## Visibilità

- Unità temporanea: `trading-lab-m1-v2-technical-once-20261024.service`.
- Stato privato: `audit-evidence/m1-v2-ui-20261024/deferred-technical-deploy/status.json`.
- Esiti possibili: `WAITING_NORMAL`, `DEPLOYING_AUTHORIZED_PACKAGE`, `COMPLETED_TECHNICAL_ONLY`, `STOPPED_REVIEW_REQUIRED`, `CANCELLED_NO_FURTHER_ACTION`.
- Scheda di consegna: `work-card-b49ae44b-40dc-4a83-bdda-982690151c9b`; collaudo: `work-card-cfaeff44-00a6-4fa0-8c1a-d4ed4d94b7b3`.

L'ora delle 23:15 è l'uscita prevista dell'episodio, non una promessa di pubblicazione: anche REENTRY, dati e guardie devono permettere il ritorno a NORMAL. Non occorre una nuova autorizzazione per lo stesso passaggio tecnico già approvato. Originale, altri conti e collector rimangono invariati; nessuna strategia viene fermata e nessuna proposta viene approvata dalla procedura.
