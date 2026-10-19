# Trading AI Lab — migrazione storage runtime, 19 ottobre 2026

Manutenzione autorizzata dall'utente: trasferire Docker/containerd sul
filesystem capiente, accettando il fermo e riavviando i servizi precedentemente
attivi; rimuovere le venti vecchie release Codex identificate nella verifica.
Nessuna modifica ai segnali, alla contabilità o alle autorizzazioni di trading.
Esecuzione e verifica dell'autore, SINGLE_AGENT; non è una review indipendente.
Effetto governato: configurazione live e migrazione dello storage host,
eseguite nel contesto canonico autorizzato, senza nuove dipendenze o download.

## Pulizia e destinazione

Rimosse esclusivamente 20 release Codex, **7,326 GiB allocati**. Conservate
0.163.0 in uso e 0.162.1 di riserva: verificati collegamento `current`,
eseguibili, file aperti e mappe dei processi prima della rimozione.
Sessioni, stato, allegati, cache pip/APT e server VS Code non toccati.
Disponibile root passato da circa 17,09 a 24,42 GiB durante questa fase.

Gli store completi, inclusi volumi e metadati, sono trasferiti a:

```text
/var/lib/libvirt/container-runtime/docker
/var/lib/libvirt/container-runtime/containerd
```

Bind mount persistenti conservano i percorsi canonici `/var/lib/docker` e
`/var/lib/containerd`. Entrambi risultano sul filesystem ext4 `/dev/md3`.
L'archivio lab e i relativi bind mount sono rimasti nella posizione precedente.
Il disco capiente è un'altra partizione dello stesso RAID1, non un diverso
dominio fisico di guasto. Nessun volume o immagine eliminato.

## Configurazione applicata

Artefatti tracciati in `docker/host-storage/`, identici ai file host:

- `var-lib-docker.mount` e `var-lib-containerd.mount`, abilitati all'avvio;
- `docker.service.d/30-lab-storage.conf` e
  `containerd.service.d/30-lab-storage.conf`.

Ogni servizio richiede i mount del proprio store e del filesystem capiente,
con dipendenze `RequiresMountsFor`, `BindsTo`, ordinamento `After` e verifiche
`mountpoint` prima dell'avvio. Non viene introdotto un fallback a uno store
vuoto sulla root. `fstab`, configurazione del daemon e image digest invariati.

`systemd-analyze verify` superato includendo esplicitamente il mount del
filesystem già generato da fstab. La verifica iniziale senza quel file non
risolveva la dipendenza; non era un guasto del mount attivo. Rimane un avviso
preesistente sul servizio browser di un altro progetto, non modificato.
Nessun reboot host o smontaggio forzato del filesystem è stato eseguito:
la persistenza è verificata su file, enablement e grafo delle dipendenze,
non mediante un test distruttivo di indisponibilità del disco.

## Continuità e controlli

Inventario iniziale: 26 container, 10 attivi e 16 fermi. Tutti i dieci attivi
erano del laboratorio. Registrati immagini, volumi, policy di riavvio e mount.
I servizi host di altri progetti sono rimasti attivi.

Pre-copia a caldo, arresto ordinato, verifica dell'assenza di task/shim,
sincronizzazione definitiva a freddo e confronto completo con checksum,
permessi, hard link, ACL e attributi estesi: entrambi gli store senza differenze.
Durante il fermo il runtime è stato mascherato solo temporaneamente per
impedire avvii accidentali; tutte le maschere sono state rimosse.

Tempi UTC:

- inizio arresto: **10:50:54**;
- scrittori/containerd completamente fermi: **10:51:55**;
- mount nuovi attivi e journal ancora invariati: **10:56:32**;
- tutti i dieci container riavviati: **10:57:19**;
- BTC intraday tornato `ACTIVE_PAPER` dopo la verifica della propria catena
  di ricevute all'avvio, senza modificare i controlli di integrità;
- conferma registrata dei **dieci healthy**: **11:02:53**.

L'intervallo tra richiesta di arresto e completamento dei riavvii è circa
6 minuti e 25 secondi; disponibilità dati e health possono richiedere ulteriore
tempo all'avvio. Eventuali buchi della raccolta restano visibili: nessun fill
o dato causale ricostruito retroattivamente per nascondere il fermo.

Verifiche di continuità effettuate:

- stessi 26 container e image digest, nessuna ricreazione; soltanto i dieci
  prima attivi riavviati, sedici precedentemente fermi lasciati fermi;
- stessi nomi dei volumi, policy di restart e mount;
- otto journal contabili/autorizzativi copiati coerentemente a freddo,
  `PRAGMA integrity_check` tutti `ok`, hash originali e WAL invariati prima
  della ripartenza;
- anche il journal delle ricevute di disponibilità intraday supera
  `PRAGMA integrity_check`, eseguito in sola lettura dopo la ripartenza;
- quantità, prezzi di carico, identità dei conti e conteggi fill invariati
  nel controllo prima/dopo; equity e mark possono cambiare con il mercato;
- episodio M1 SHORT, fase `ACTIVE` e uscita delle **16:40 UTC** conservati;
  BTC intraday FLAT con due fill e lo stesso saldo;
- risposte JSON del confronto, intraday e osservazione M1 valide; cinque
  pagine principali dashboard HTTP 200 HTML; configurazione Compose valida.

Il primo DAILY M1 corretto resta una verifica futura separata il 20 ottobre,
00:15 UTC. Nessun DAILY mancato è stato cancellato o recuperato artificialmente.

**Incidente di collaudo e limite operativo intraday:** il controllo di
integrità del journal delle ricevute, pur eseguito in sola lettura, ha
trattenuto un read lock abbastanza a lungo da far fallire un commit del
writer con `database is locked`. Il processo ha negato l'operatività ed è
ripartito tramite la policy esistente. Il controllo è terminato con `ok`;
la lettura è stata chiusa e non ripetuta. La verifica di futuri journal
live deve avvenire su copia coerente, evitando di trattenere il lock sul
writer. Nessuna modifica al codice o ai timeout per aggirare questo errore.

Dopo il fermo della raccolta la continuità della finestra causale intraday
non è più completa: il conto riprende `ACTIVE_WARMUP`, conserva saldo,
posizione e fill, ma attende 289 punti consecutivi di cinque minuti prima
di nuovi ingressi. Non è quindi corretto dichiararlo già pronto a entrare,
né recuperare artificialmente il buco. I tempi dipendono dalla continuità
della raccolta successiva. La dashboard mostra questo stato.

## Recupero root e rollback

Entrambe le copie di rollback sono completate e verificate con un secondo
confronto integrale dei checksum e dei metadati, senza differenze, in:
`/var/lib/libvirt/container-runtime/rollback-20261019/`.
Alle **11:07:16 UTC** si è conclusa la rimozione dei soli originali duplicati
sulla root, dopo aver verificato che non fossero mount o file ancora aperti,
e che tutti i container fossero healthy. Circa **66,707 GiB allocati**
trasferiti e ritirati dalla root; nessun percorso canonico montato o dato
lab eliminato. Questa rimozione è parte del trasferimento autorizzato,
non una pulizia indiscriminata delle immagini.

| Misura | Prima della pulizia/migrazione | Dopo |
| --- | ---: | ---: |
| Root disponibile | 17,09 GiB | **91,10 GiB** |
| Root utilizzo df | 85% | **19%** |
| Filesystem capiente disponibile | circa 436,8 GiB | **301,16 GiB** |

Incremento netto osservato del disponibile root circa **74 GiB**, inclusa
la pulizia Codex e al netto delle scritture intervenute. Il filesystem
capiente contiene lo store attivo, il rollback completo e le evidenze:
il suo maggiore utilizzo è previsto. Non è stato ridotto lo spazio riservato
ext4 e non sono stati alterati partizioni o RAID.

Monitor automatico e timer mail ripristinati; il monitor post-manutenzione
conclude con successo e non segnala più spazio root o container non healthy.
Il ciclo mail delle **11:07:45–11:07:47 UTC** è riuscito senza forzare una
mail di prova. Resta il solo avviso preesistente `PAPER_DAILY_NOT_EXECUTED:m1`,
relativo allo slot giornaliero già mancato prima della manutenzione.

Il rollback a freddo conserva lo stato pre-manutenzione. Dopo nuove scritture
non va riattivato alla cieca: fermare di nuovo i servizi, verificare capienza
e riportare alla root lo stato corrente completo, preservando i dati successivi.
Rimuovere/riordinare mount e drop-in soltanto in quella manutenzione; mai
avviare il runtime sopra directory vuote. I ledger lab non vengono riavvolti.

## Tracciamento

| Attività | Schedina |
| --- | --- |
| Rimozione release Codex | `work-card-f17ea2fd-16c1-4199-92ba-620a57d52e59` |
| Migrazione Docker/containerd | `work-card-0ecefc67-a704-4868-9a06-ff07451c9cf4` |
| Collaudo operativo | `work-card-31327f65-afb8-4b22-bb4e-a09a82ca0200` |
| Consegna | `work-card-3496ab62-0759-49ad-8e39-3d1b0712eb82` |

Ricevute, inventari sanitizzati, confronti, copie coerenti dei journal,
configurazione host e misure conservati nell'archivio privato delle evidenze.
Manifest di 65 file, SHA-256:
`dd7c5b5d4c0c29425f339476423bc0f7eb336271f94bdaf0607d5805f3b86b5d`.
Nessuna credenziale o payload grezzo pubblicato. Ricerca sigillata, grant,
quarantena e minimi reali KuCoin restano invariati.
