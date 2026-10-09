# V13 A/B/C — preparazione prima del cutoff

8 ottobre 2026. Schede: work-card-ad198a58-f077-4c6a-871c-e734ec5d32e0 (funding),
work-card-4967bd0a-2ecf-4e1d-a276-b6021450c904 (binding),
work-card-2bbccd2a-2d67-4f98-b07b-fa5d30863aab (warm-up),
work-card-4983b3a1-948b-4e67-a863-4f0f7cf23d51 (verifiche/consegna).

## Assetto predisposto

Piano `v13-abc-inactive-plan-v2.json`, distinto dalla bozza v1. Identità locali
senza login: collector 30931, producer 30932, executor 30933. Gruppi di sola
lettura: forward 30934, intenti 30935. Nessuna appartenenza a gruppi privilegiati.
Le directory degli scrittori sono distinte, con antenati root-owned. I due
archivi di input sono stati creati UNA volta e sono vuoti: non ricrearli al
riavvio. Il ledger non è stato creato e non ci sono conti A/B/C.

La lineage è fissata in `v13-abc-lineage-v1.json` sul medesimo esperimento,
contratto e bracci A/B/C. Non eredita performance da conti precedenti. Non è
un'approvazione scientifica o un'autorizzazione di avvio.

Warm-up separato e root-owned: 121 daily chiuse su 29 simboli, 2 giugno–30
settembre. Byte, ricevute e hash verificati; tutti i timestamp di ricezione
sono quelli effettivi dell'8 ottobre. Non è un backfill del forward. La qualifica
fornirà il seguito solo dopo il suo cutoff, tramite copia coerente verificata.

`v13-abc-container-bindings-v1.json` contiene i comandi concreti con immagine
locale fissata per SHA-256. Producer/executor hanno rete disabilitata, input
montati read-only e soltanto il proprio archivio scrivibile. Il collector ha
accesso alla rete per le sole richieste pubbliche previste dal codice.
Le tre unità `.service` sono artefatti non installati, senza sezione Install.
Le configurazioni restano DRAFT e vengono rifiutate dai CLI. Non creare il
file di attivazione indicato nelle unità per tentare di superare i controlli.

L'archivio originale della qualifica non ha cambiato permessi. Il montaggio
futuro previsto espone una copia read-only al percorso `/srv` presente nella
ricevuta originale: questo evita di alterare la ricevuta o il binding del
valutatore. La copia non esiste ancora e non è stata anticipata.

## Funding: prova disponibile e prova ancora mancante

Nella finestra chiusa 14:10–14:50 UTC dell'8 ottobre: 232/232 ricevute verificate,
nessun gap, 29 simboli. Sono osservati intervalli di 8 ore per 23 contratti e
4 ore per 6; non vengono estesi nel futuro come calendario garantito.
Il primo regolamento annunciato successivo all'avvio è alle 16:00 UTC.

Lo storico pubblico acquisito separatamente per questa finestra restituisce
`data:null` su tutti i 29 contratti. Il report mantiene la disponibilità
sconosciuta; non converte null in lista vuota o costo zero. Non ci sono ancora
regolamenti maturati nella finestra per una verifica positiva di riconciliazione.

Sono pronti due comandi: `review_v13_funding_observations.py` verifica raw,
continuità, finestre e cambi; `capture_v13_funding_history.py` acquisisce storia
pubblica per una finestra chiusa di massimo un giorno, in una NUOVA directory.
Passare la directory al primo comando tramite `--history` per confrontare
annunci e regolamenti. La riconciliazione resta diagnostica: non produce il
calendario `REVIEWED_EXPLICIT_FUNDING_CALENDAR_V1` e non certifica il proxy mark.
Le finestre di più giorni vanno suddivise senza perdere o duplicare i confini.

## Chiusura dopo il cutoff

1. Non prima del 16 ottobre 00:00 UTC: valutare l'archivio originale con il
   valutatore e la ricevuta congelati. Solo un effettivo QUALIFIED permette
   di proseguire. Nessuna modifica di soglie, calendario o clock.
2. Pubblicare una copia SQLite coerente verificata dopo il cutoff, nella
   directory host prevista `qualification_snapshot_host`, mantenendo UID
   proprietario 30930 e gruppo read-only 30934. Confrontare binding e contenuti;
   non allargare l'accesso all'archivio operativo originale.
3. Riconciliare gli annunci con lo storico pubblico e verificare i book
   precedenti ai regolamenti. Fissare il calendario revisionato e il suo hash
   SOLO per l'intervallo dimostrato. Nessuna copertura futura inventata.
4. Fissare una partenza futura comune alle 00:15 UTC, dopo aver accertato che
   il collector possa acquisire metadata, daily e book nelle rispettive finestre.
   Una finestra già persa non si recupera retroattivamente.
5. Finalizzare l'autorizzazione e l'integrazione di rilascio. Il modulo attuale
   conserva `comparison_activation_not_authorized`: la consegna pre-cutoff non
   modifica questo controllo. La ricevuta di accettazione del contratto non
   è una ricevuta di attivazione. Nessun semplice cambio di scope o booleano
   sostituisce questa fase e i relativi test.
6. Rigenerare configurazioni e pin della release autorizzata, ripetere le prove
   con quei binding, quindi installare/avviare esclusivamente i componenti
   autorizzati. Verificare primo ciclo e persistenza prima di mostrare conti attivi.

Il kit è pronto per questo completamento condizionato. Non promette che il
16 ottobre tutti i dati supereranno la qualifica o che l'avvio sarà automatico.
Nel frattempo rimangono attivi soltanto i servizi già autorizzati.
