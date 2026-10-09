# V13 originale — pubblicazione causale candidata, solo fixture

Schede: `work-card-2a3f3bb2-0af0-4957-88d8-26d739083829` (implementazione) e
`work-card-781b1be7-dab1-4695-b323-5b3db9d5fe67` (prove).

Questo componente inattivo dimostra la pubblicazione e la verifica degli **input
normalizzati** di un portafoglio di 18 asset, usando soltanto dati sintetici.
Non acquisisce dati di mercato, non ricalcola i target scientifici della V13,
non produce proposte accettabili dall'issuer e non viene collegato al runtime.
La readiness resta **BLOCKED**. La disponibilità della sorgente legacy resta
`UNRESOLVED`; quella operativa non viene valorizzata da queste ricevute.

## Confini e identità

`v13_causal_publication_fixture.py` carica il contratto originale già congelato:
account `v13-paper-v2`, lineage scientifica e mapping completo dei 18 simboli.
Mantiene tale identità come riferimento; non assegna una nuova autorità alla
strategia né eredita autorizzazioni dalla ricerca. Configurazione e componente
sono vincolati tramite SHA-256 esterno. L'epoch, l'orologio e le soglie di età
600 secondi / skew 60 secondi sono **fixture**, non scelte operative approvate.
Il massimo errore dell'orologio pari a zero descrive solo il tempo simulato.

Il file raw conserva integralmente i byte. Il verifier rilegge quei byte con
rifiuto delle chiavi JSON duplicate e dei numeri non finiti, applica il cutoff,
ricostruisce l'input causale e confronta manifest e ricevuta. Controlla identità,
unità, mapping, completezza, prezzi, profondità, tempi di osservazione e
ricezione, conflitti di duplicati funding e skew tra asset. Eventi e barre
successivi al cutoff restano nel raw ma non entrano nell'identità causale.
Due rappresentazioni dello stesso timestamp vengono normalizzate prima del
controllo dei duplicati delle barre. Una modifica non consumata cambia l'hash
raw e l'ID della pubblicazione, ma mantiene l'hash causale e lo snapshot passato.
Un secondo payload nello stesso slot già attestato viene rifiutato: cambiare
provenienza non consente di sostituire silenziosamente una pubblicazione.

`min_quantity` e `min_notional` restano `null`/UNKNOWN, compresi i dati sintetici
di questa prova. Valori inventati, anche zero, vengono rifiutati. Nessun test
certifica l'ammissibilità degli ordini KuCoin; P0-03 resta invariato.

## Persistenza e disponibilità nella simulazione

Percorso candidato:

`raw fixture → bundle persistito → attestazione publication → verifica input
→ ricevuta derivazione persistita → attestazione derivation → verifica RO`

Il publisher scrive file esclusivi senza sovrascrittura, effettua fsync di file
e directory e consente solo il completamento di staging byte-identico.
Il witness controlla nuovamente bundle e persistenza prima di registrare
l'evento in SQLite (`DELETE`, `synchronous=FULL`, transazione atomica).
Per la derivazione controlla anche la ricevuta persistita del verifier.
Il witness campiona un orologio **simulato dopo il commit dell'evento** e scrive
un ACK separato. Questo timestamp attesta un'osservazione successiva al commit
referenziato, non il completamento futuro del fsync dello stesso ACK.
Il pin dell'ACK viene restituito solo dopo persistenza confermata; gli errori
non restituiscono una ricevuta utilizzabile. Un crash tra commit e ACK lascia
un evento recuperabile, senza rendere disponibile la sorgente. Un retry non
crea un secondo evento e completa la ricevuta mancante.

Il controllo finale richiede file completi, ACK confrontati con eventi
realmente committati, pin esterni di configurazione e ACK e head del witness.
`source_available_at_fixture` è il massimo tra ricezione raw e osservazioni
post-commit di pubblicazione/derivazione; il tempo di verifica deve essere
successivo. `source_available_at_operational` resta `null`.
Le fault injection dimostrano il comportamento del software e il recupero
SQLite; non certificano hardware, perdita di alimentazione o un orologio reale.

## Custodia e replay

Il bootstrap crea esclusivamente directory di sandbox; non installa utenti.
Publisher, verifier e witness scrivono nelle rispettive directory; la strategia
scrive solo gli input non fidati. I test con UID numerici effettivamente distinti
avvengono in un container isolato, senza rete, con filesystem di progetto RO.
Configurazione e artefatti sono leggibili ma non scrivibili dalla strategia.
Il witness è l'unico writer di `witness.sqlite`; gli altri ruoli possono leggerlo
in modalità RO. I permessi proteggono il **file e la directory**, non singole
tabelle SQLite. Questo witness non è approvals.sqlite né execution.sqlite e
non sostituisce l'assetto issuer/executor già separato.

La catena controlla ordine, identità, hash, slot e oggetti attestati. Un restore
coerente più vecchio è rilevato solo se il pin dell'head corrente rimane fuori
dal rollback. Se anche quel pin viene riportato indietro, il rollback coerente
non è distinguibile: il test documenta questo limite. Nessun custode monotono
operativo è installato o dichiarato verificato.

## Cosa resta prima di usare una sorgente reale

Occorrono ancora il publisher di acquisizioni reali con ricevute temporali per
ogni dipendenza, interfaccia versionata con il ricalcolo dei target originali,
revisione delle custodie e dell'orologio/soglie, binding ed epoch approvati.
Questi criteri non vengono dedotti dal successo della fixture. Restano inoltre
la revisione del metodo funding candidato, la policy di rischio, il close
amministrativo originale, l'E2E del conto e la decisione di cutover.
L'issuer reale e i contratti scientifici congelati non sono modificati.
Non sono creati grant operativi, ordini, cambi di quarantena o servizi.
