# Trading AI Lab — root e migrazione Docker, 19 ottobre 2026

**Verifica completata; nessuna cancellazione, migrazione o interruzione.**
La root è sotto il 15% libero. Docker e containerd occupano insieme circa
66,71 GiB: trasferire entrambi gli store è la soluzione strutturale proposta.
I dati del laboratorio sono già sul filesystem capiente e restano al loro
posto. Questa verifica non autorizza un fermo globale del runtime.

## Misure e causa dell'alert

Campione `df -B1` delle 10:26 UTC; GiB = 2^30 byte. Le misure cambiano mentre
i servizi scrivono. `du -x` misura spazio allocato senza attraversare gli
altri filesystem; le righe annidate non si sommano ai loro genitori.

| Filesystem | Capacità | Disponibile | Utilizzo mostrato da df |
| --- | ---: | ---: | ---: |
| Root, `/dev/md2` | 117,49 GiB | 17,11 GiB | 85% |
| `/var/lib/libvirt`, `/dev/md3` | 810,48 GiB | 436,80 GiB | 44% |

Disponibile root: 18.373.132.288 byte, circa **14,56% della capacità**.
L'alert sotto il 15% è quindi corretto, anche se `df` arrotonda l'utilizzo.
Capacità meno usato meno disponibile include lo spazio riservato ext4:
non è una directory da eliminare. Non propongo di ridurre tale riserva.
Il valore disponibile precedente nella stessa verifica era 18.392.064.000
byte: differenza circa 18 MiB, insufficiente per estrapolare una crescita
giornaliera affidabile. Occorrono campioni omogenei più distanziati.

I due filesystem sono partizioni diverse della **stessa coppia di NVMe in
RAID1**, non dischi fisici indipendenti. Gli array risultano `[UU]`.
La migrazione risolve la pressione sulla partizione root, non aggiunge
ridondanza o isolamento fisico.

| Occupante root | Spazio allocato | Classificazione |
| --- | ---: | --- |
| containerd | 43,60 GiB | 33,97 GiB snapshot overlay, 9,59 GiB contenuti, metadati |
| Docker | 23,11 GiB | soprattutto volumi, non soltanto immagini |
| Dentro Docker: volumi | 22,15 GiB | protetti, anche quelli di altri progetti |
| Dentro Docker: container | 0,96 GiB | include log e filesystem; preservare |
| Versioni distribuite Codex | 8,15 GiB | potenziale pulizia selettiva, separata dalla cronologia |
| Versioni server VS Code | 3,19 GiB | cinque versioni, nessun processo rilevato; conservare finché non definita la retention |
| Log di sistema | 2,80 GiB | inclusi 1,42 GiB di journal; nessuna cancellazione proposta |
| Cache pip | 205,9 MiB | download ricreabili; verificare installazioni attive prima di pulire |
| Cache APT | 128,7 MiB | circa 11,8 MiB di pacchetti e 116,8 MiB di indici binari ricreabili |

Ci sono inoltre circa 4,49 GiB di workspace di un altro progetto: esclusi
dalla pulizia. Sessioni, allegati, stato applicativo, credenziali, dataset,
journal, log e bundle di rollback non sono cache eliminabili.

## Cosa possiamo eliminare e cosa preservare

1. **Prima scelta limitata:** cache download pip e pacchetti/indici APT,
   complessivamente circa 0,33 GiB. Una verifica di processi/installazioni
   va ripetuta immediatamente prima della pulizia. Non disinstallare pacchetti.
   Questo recupero è modesto e non risolve la crescita del runtime.
2. **Versioni Codex:** presenti 22 release. `current`, eseguibili, file aperti
   e mappe dei processi osservati puntano alla 0.163.0. Escludendo questa e
   la 0.162.1 come riserva, le altre 20 occupano **7,33 GiB**. Sono candidate
   a retention/pulizia selettiva con nuovo controllo dei riferimenti e del
   gestore delle versioni; non sono state rimosse. Nessuna pulizia di sessioni
   o cronologia. Le cinque versioni VS Code richiedono una scelta analoga,
   senza sommare tutto il loro spazio a un recupero già garantito.
3. **Immagini senza container:** non sono automaticamente eliminabili.
   `59661c770f78` risulta senza container, con 9,56 GB visualizzati da
   `docker system df -v`, dei quali 7,972 GB indicati come unici;
   `8260ed629891` mostra 2,64 GB e 1,045 GB unici. La provenienza/versione
   approvata non è sufficientemente attribuita: nessuna allowlist di
   rimozione autorizzata deriva dal solo conteggio dei container.
   Le dimensioni di `image inspect` e quelle di `system df` differiscono:
   non sommare immagini/layer condivisi né trattare i valori come recupero
   fisico garantito. Le immagini OPS recenti, il browser, gli strumenti
   di test e il digest attivo V13 restano protetti.
4. **Volumi:** `ops-rc3-docker-data` occupa circa 19,88 GiB allocati ed è
   associato a un container di test fermo. Altri volumi OPS occupano circa
   1,12 e 1,13 GiB. Sono dati di un altro progetto, non rifiuti. Nessun volume
   viene eliminato. Build cache Docker dichiarata: **0 B**; nessun beneficio
   atteso da una pulizia della build cache.

Nessun `prune`, vacuum dei log o intervento sui dataset. Recupero effettivo
di questa attività: **0 byte**, essendo una verifica.

## Migrazione proposta, concretamente applicabile

Docker Engine 29.1.3 usa `overlayfs` con snapshotter containerd.
`DockerRootDir=/var/lib/docker`; il demone si connette al servizio containerd
indipendente, la cui configurazione effettiva indica
`root=/var/lib/containerd`, `state=/run/containerd`. Namespace osservato:
solo `moby`; nessun servizio host Kubernetes/k3s attivo rilevato.
`LiveRestoreEnabled=false`. **Cambiare soltanto Docker data-root lascerebbe
circa 43,60 GiB di containerd sulla root.** Queste conclusioni derivano dalla
configurazione e dai comandi dei programmi installati, senza nuove installazioni.

Destinazioni proposte, oggi inesistenti:

```text
/var/lib/libvirt/container-runtime/docker
/var/lib/libvirt/container-runtime/containerd
```

Raccomando bind mount persistenti sui due percorsi canonici attuali, per
conservare anche i riferimenti ai volumi. È una proposta non applicata.
Entrambi i servizi e i mount devono dipendere esplicitamente dal filesystem
capiente: se non è montato, il runtime deve restare fermo, senza inizializzare
uno store vuoto sulla root. Non basta un collegamento simbolico o nascondere
la vecchia directory con un mount: i byte sottostanti resterebbero occupati.

Ordine esecutivo subordinato alla manutenzione autorizzata:

1. Registrare immagini, container attivi/fermi, mount, volumi, namespace,
   configurazioni, health e stato contabile. Verificare che nessun altro
   progetto stia costruendo immagini o usando il runtime. Tutti i dieci
   container attualmente attivi appartengono al lab e sono healthy; ci sono
   anche sedici container fermi, da lasciare fermi.
2. Preparare spazio e destinazioni. Un eventuale pre-copia a caldo è solo
   staging: non è un backup coerente dei metadati del runtime.
3. Scegliere il fermo lontano dagli slot giornalieri/funding e verificare
   eventuali episodi SHORT in corso. Arrestare in modo ordinato i container
   interessati, poi Docker/socket e containerd; verificare task/shim e
   scrittori realmente fermi prima della copia definitiva. Il fermo coinvolge
   UI, collector ed esecutori dei conti paper, non solo le immagini.
4. Copiare entrambi gli store a freddo preservando proprietari numerici,
   permessi, hard link, ACL e attributi estesi; confrontare contenuti e
   metadati. Predisporre i mount persistenti e le dipendenze di avvio.
5. Riavviare i demoni e **soltanto i container prima attivi**. Verificare
   namespace, digest, mount/volumi, health, UI, continuità di equity,
   posizioni e operazioni; verificare integrità SQLite su copie coerenti
   dei journal interessati. Non riscrivere storico o ricevute causali:
   eventuali buchi della raccolta restano espliciti.
6. Conservare una copia coerente di rollback sul filesystem capiente.
   Rimuovere dalla root soltanto i duplicati verificati, dopo il collaudo
   e nell'ambito autorizzato. Solo allora si recupera spazio sulla root.

Capienza: i circa 66,71 GiB attuali entrano nei 436,80 GiB disponibili.
Anche due copie di pari dimensione lascerebbero circa 303 GiB, prima della
crescita durante l'operazione. Il recupero stimato sulla root è circa
66,7 GiB, portando il disponibile intorno a **84 GiB**; non è un risultato
già ottenuto. Durata del fermo da misurare con il pre-copia e le verifiche,
senza promettere una durata non provata.

Rollback: prima di nuove scritture, ripristinare mount/configurazione e
store salvato. Dopo la ripresa delle scritture, non riattivare una copia
obsoleta: fermare di nuovo, verificare capienza root e riportare lo stato
corrente preservando i dati anche degli altri progetti. L'archivio lab e
i suoi bind mount restano nella posizione attuale durante tutta l'operazione.

## Tracciamento e verifiche

| Attività | Schedina | Esito |
| --- | --- | --- |
| Analisi root | `work-card-b0fec86e-aeca-4f3c-9f12-c9dbf4917275` | completata |
| Fattibilità Docker/containerd | `work-card-76d769a1-1549-4d98-8aee-cc65d2a61fa5` | completata |
| Consegna documentale | `work-card-d411450f-739c-4288-a2b7-d6d53a0f7b28` | report verificato |
| Pulizia mirata | `work-card-f17ea2fd-16c1-4199-92ba-620a57d52e59` | To-do, allowlist finale da verificare |
| Migrazione effettiva | `work-card-0ecefc67-a704-4868-9a06-ff07451c9cf4` | To-do, fermo condiviso da autorizzare |

Evidenze private conservate: misure filesystem/allocazione, inventari
sanitizzati, configurazione effettiva, RAID, riferimenti ai runtime gestiti.
Manifest SHA-256:
`54ca5af4496a38d87c2292fe19ab2ec7c0f8179b6a6f1f0dc1c43b7accc6e4f0`.
Nessuna credenziale o payload operativo grezzo incluso nel report.
Verifica SINGLE_AGENT dell'autore, non indipendente. Consegna solo
documentale: controllo aritmetico, integrità delle evidenze e diff Git;
nessun test del codice applicativo necessario. Policy, grant, quarantena,
strategie e minimi reali KuCoin restano invariati.
