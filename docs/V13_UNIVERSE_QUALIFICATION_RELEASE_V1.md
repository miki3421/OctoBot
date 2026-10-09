# Qualifica V13 18/29 · pacchetto candidato per decisione

30 settembre 2026. **Preparato e verificato offline; nessuna installazione o raccolta attiva.**
Preparazione `work-card-885f311c-8046-4d56-9f86-6e225dff139c`;
valutatore `work-card-32019ba9-bcfa-49ad-b3e2-9e9e49f9f4f8`;
prove `work-card-3f26b1bd-c893-4116-9b8f-cc23506fbae2`;
UI/consegna `work-card-7158ce11-05c0-40ac-a3bc-eb68e11319fc`.

## Decisione proposta

Autorizzare l'installazione locale del solo collector orderless e la raccolta
pubblica del paniere confermato di 29 simboli **dal 2 ottobre 2026 00:00 UTC
al 16 ottobre 2026 00:00 UTC escluso**, cioè dalle 02:00 del 2 ottobre
alle 02:00 del 16 ottobre in Italia. Sono 14 giorni, senza rinnovo automatico.
Se la decisione arriva dopo l'inizio proposto, non avviare né retrodatare:
preparare una nuova finestra futura e aggiornare gli artefatti di rilascio.

| Sorgente pubblica | Dati e frequenza | Richieste previste |
| --- | --- | ---: |
| KuCoin Futures | Depth20 per i 29 simboli ogni 15 minuti | 38.976 |
| Binance Futures | Una candela daily chiusa del giorno precedente per simbolo, alle 00:10 UTC | 406 |
| KuCoin Futures | Funding pubblicato del giorno precedente per simbolo, alle 00:10 UTC | 406 |
| Entrambe le venue | Catalogo contratti una volta al giorno | 28 |
| Totale | Sole GET, nessuna credenziale | **39.816** |

Limiti: massimo 42.000 tentativi, 512 MiB di raw compressi incluse le riserve
incerte, nessun retry automatico. Errori persistenti, rate limit, clock arretrato,
storage non affidabile o budget esaurito arrestano le acquisizioni conservando
le evidenze. Il timer contiene solo le date 2–15 ottobre; nessuna scadenza
successiva e nessuna acquisizione per i 180 giorni del futuro confronto.

Identità candidata: `v13-universe-capture`, UID/GID **30930**, senza login e
senza gruppi aggiuntivi. Entrambi gli ID risultano liberi alla preparazione;
**l'identità non è stata creata**. Verificare di nuovo prima dell'installazione:
se occupati, fermarsi, non riutilizzare un'identità altrui.

Destinazioni proposte:

- codice e manifest root-owned in `/opt/v13-universe-qualification-v1`, sola lettura;
- archivio privato 0700 in `/srv/v13-universe-qualification-v1`, scritto solo dal collector;
- ricevuta owner root-owned in `/etc/v13-universe-qualification/activation.json`;
- solo le unità `v13-universe-qualification.service` e `.timer`.

Non sono creati conti A/B, issuer, grant operativi o percorsi d'ordine.
V13 paper, BTC 30/120 e Qwen shadow proseguono con i propri artefatti invariati.
I minimi reali KuCoin restano UNKNOWN; questa raccolta non li risolve.

## Isolamento e risorse

Il servizio candidato usa il nuovo UID, nessuna capability, filesystem di
sistema protetto, home non accessibili, dispositivi privati, nessun privilegio
aggiuntivo. I contenuti host di `/opt` e `/srv` sono nascosti: sono montati
soltanto codice in lettura e archivio dedicato in scrittura. Le directory BTC
in `/var/lib` e le configurazioni degli altri esperimenti sono inaccessibili.
Non riceve credenziali o mount del workspace operativo.

Limiti: 256 MiB RAM, 8 task, 50% di una CPU, priorità ridotta, timeout 70 secondi,
nessun restart automatico. Il timer sveglia il processo ogni minuto solo nella
finestra; il piano immutabile decide se esiste una richiesta dovuta. Un tick
senza job non fa rete. Le risposte lente possono lasciare buchi: non è promessa
una copertura reale del 95% in base ai test sintetici.

Il client fissa host/path HTTPS pubblici, rifiuta redirect e proxy ambientali.
Il filtro degli endpoint è applicativo: non si afferma una allowlist DNS/IP
nel firewall del kernel. L'isolamento esclude i dati degli altri esperimenti.

Il cap 512 MiB riguarda raw e riserve, non l'intero DB. Richiedere almeno
**4 GiB liberi** nel filesystem di destinazione prima dell'installazione:
SQLite, indici, rollback journal e spazio temporaneo hanno costi aggiuntivi.
Alla preparazione risultano circa 28 GiB liberi. Nessun volume viene ripulito
per recuperare spazio; i controlli di scrittura continuano a fallire chiusi.

## Convenzioni del valutatore, fissate prima della raccolta

`v13_universe_qualification_evaluate.py` apre SQLite in `mode=ro`, con
`query_only` e una transazione coerente. Richiede binding dell'attivazione,
calendario completo identico al piano e integrità SQLite. Verifica hash e
compressione delle ricevute, orari, HTTP e schema; ricalcola le metriche dai
raw e le confronta con quelle archiviate. La metadata deve precedere ogni
campione e deve essere del medesimo giorno. Non legge dati degli esperimenti
BTC e non può scrivere nell'archivio di qualifica.

Prima del cutoff dei 14 giorni restituisce solo **IN_PROGRESS**, senza verdetto
finale. Al cutoff applica le soglie già approvate, con queste convenzioni:

| Misura | Denominatore / convenzione |
| --- | --- |
| Copertura book per simbolo | 1.344 slot attesi, anche se mancanti o invalidi |
| Copertura comune | Frazione dei 1.344 slot con tutti e 29 i book validi; non media delle coperture individuali |
| Buco comune | Massima sequenza di slot senza paniere completo × 15 minuti; comprende inizio e fine della finestra; 8 slot = 2 ore |
| p95 spread | Nearest rank: valore ordinato in posizione `ceil(0,95 × n)` sui soli campioni validi |
| Profondità | Almeno 3.150 USDT sia bid sia ask nello stesso campione, in ≥95% dei campioni validi; copertura book controllata separatamente |
| Daily e funding | Copertura di risposte valide per simbolo su 14 giorni; ≥95% richiede in pratica 14/14 |
| Metadata | Due cataloghi con identità verificabili, ≥95% dei 14 giorni, in pratica 14/14 |

Soglie inclusive: copertura ≥95%, buco ≤2 ore, p95 ≤20 bps. Nessuna esclusione
postuma dei simboli. Funding significa risposte e punti pubblicati osservati:
non si certifica che tutte le regolazioni economicamente dovute siano presenti.
Nessuna candela mancante o profondità insufficiente viene interpolata.

Un solo simbolo che fallisce produce **NOT_QUALIFIED** per l'intero paniere.
Un archivio non verificabile o un arresto tecnico irrisolto produce
**INCONCLUSIVE**, mai QUALIFIED. Un eventuale **QUALIFIED** riguarda la qualità
dati: ordini, paper del nuovo confronto e promozione automatica restano falsi.
Non è prova di profitto, né di ammissibilità degli ordini KuCoin.

## Prove già eseguite e limiti

- 30 prove del collector nella consegna precedente, incluso SIGKILL e guasti di storage.
- 20 nuove prove: archivio sintetico completo di 39.816 ricevute, replay senza
  scritture, cutoff, soglie, copertura comune, estremi della finestra, alterazioni
  di raw/metriche/calendario, binding errato e decompressione limitata.
- Verifica sintattica delle unità con `systemd-analyze verify`, senza installarle.
- Prova transitoria senza rete dello schema di isolamento: codice non scrivibile,
  accesso al solo archivio della fixture, home e directory degli altri esperimenti
  non visibili. Usato l'utente esistente `nobody` esclusivamente nella fixture;
  UID 30930 richiede prima la creazione approvata del proprio account. Il primo
  tentativo col numero non ancora registrato è stato negato da systemd (217/USER).

Le verifiche sono dell'autore, non una review indipendente. Non sono stati
scaricati dati o pacchetti, né avviato il collector candidato. Restano da
verificare nell'installazione autorizzata identità effettiva, permessi finali,
manifest staged, stato timer e archiviazione delle prime ricevute reali.

## Sequenza di installazione subordinata alla decisione owner

1. Verificare la decisione specifica per fonti, periodo, cap e attivazione.
   Verificare gli hash del pacchetto, clock sincronizzato, UID/GID liberi e spazio.
2. Creare esclusivamente il nuovo utente/gruppo senza login; installare i file
   immutabili e le due directory dedicate. Nessun mount di journal operativi.
3. Creare la ricevuta owner root-owned partendo da `activation-candidate.json`,
   solo dopo la decisione: registrare riferimento reale e autorizzazioni vere.
   Il candidato conserva oggi entrambi i flag falsi e non è utilizzabile per avviare.
4. Inizializzare l'archivio come il nuovo UID prima del 2 ottobre, usando il comando
   `initialize` e la ricevuta verificata. Non rigenerare un DB già presente.
5. Verificare manifest, ownership, profilo senza ordini; installare/abilitare solo
   il timer candidato. Nessun riavvio degli altri servizi. Verificare l'inizio futuro.
6. Dopo il primo tick dovuto controllare salute, ricevute, orari e contatori.
   In caso di errore fermare il solo timer candidato; conservare DB ed evidenze.
7. Dopo il 16 ottobre valutare l'archivio in sola lettura con il medesimo binding.
   Nessuna ripartenza, estensione o selezione opportunistica. Il confronto A/B
   di 180 giorni resta un incarico e un'autorizzazione distinti.
