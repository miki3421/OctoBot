# Host — correzione della riserva swap

9 ottobre 2026. Scheda `work-card-a26f1ef8-c617-4587-a05c-88dbd249d12b`.
Correzione richiesta dal proprietario dopo gli avvisi email del laboratorio.

## Risultato

Aggiunti 16 GiB di swap sul disco capiente del lab: totale circa 24 GiB,
circa 8 GiB occupati e 16 GiB disponibili alla verifica. Nuova riserva attiva
con priorità 100, partizione precedente preservata. `vm.swappiness` passa da
60 a 20; il valore riduce la preferenza relativa per lo swap rispetto al
reclaim delle pagine file, non impone una percentuale massima di swap.

Nessun reset forzato dello swap, arresto di VM o modifica alle loro allocazioni.
Nessun riavvio di Qwen, paper o collector; nessun nuovo grant. Tutti i sette
container del lab sono healthy, analisi V13 e backend condiviso disponibili.
L'allarme swap è rientrato e la mail «[Trading AI Lab] Recupero» è stata ricevuta
alle **14:19 italiane** del 9 ottobre.

## Diagnosi

Prima: circa 62 GiB RAM fisica, 10,3 GiB disponibili, 8 GiB swap praticamente
pieni. I campioni vmstat di un secondo non mostrano swap-in/out attivo e la
pressure stall memory è zero nei valori medi recenti. Lo swap pieno è una
riserva esaurita, non da solo prova di thrashing continuo.

Attribuzione iniziale usando SwapPss per evitare di sommare pagine condivise
due volte: controller circa 4,22 GiB, tre compute complessivamente circa
3,10 GiB, Qwen circa 0,58 GiB; il paper circa 11 MiB. Qwen occupa molta RAM
e contribuisce al budget del sistema, anche se la maggioranza delle pagine
in swap appartiene alle VM. Le statistiche guest inutilizzate sono vecchie:
non giustificano ridurre automaticamente la memoria delle VM.

Durante la verifica una VM esterna cambia ID da 6 a 7, per attività concorrente
non eseguita da questo intervento. La RAM disponibile sale temporaneamente
a circa 20 GiB: questo aumento non è attribuito all'aggiunta di swap.
La fix dà margine su disco e modifica una preferenza del kernel; non aggiunge
RAM fisica né risolve un eventuale futuro sovraccarico di working set attivi.

## Assetto persistente

- Nuovo file: `host-swap/reserve.swap` sul filesystem ext4 capiente del lab,
  16 GiB preallocati, root-owned, modalità 0600, directory 0700.
- Riga aggiuntiva fstab: swap con `nofail`, priorità 100; tutte le righe
  precedenti restano identiche e una copia è conservata fuori da Git.
- Sysctl dedicato `90-trading-lab-swap.conf`: solo `vm.swappiness = 20`.
- L'unità swap generata da systemd è loaded/active e dipende dal mount
  `var-lib-libvirt.mount`; non richiede un reboot per l'attivazione corrente.

La prima verifica completa fstab ha fermato la persistenza per un errore di
ordine `/boot/efi` prima di `/boot`, già presente nella versione originale.
Non sono stati cambiati mount di boot. Dopo review, la verifica delle sole
righe swap riporta zero errori; resta il warning generico per un file regolare,
che è qui atteso. Il kernel ha già accettato il file come swap effettivo.
Il comando di completamento rifiuta target o fstab diversi dal piano salvato.

## Verifiche e rollback

Controllati dimensione/permessi, capacità reale e priorità, valore sysctl
effettivo, dipendenza systemd dal disco, freschezza del monitor, servizi e mail.
Il monitor non espone più allarmi; i campioni dopo l'intervento non mostrano
swapping attivo. Il disco resta con circa 500 GiB disponibili dopo la riserva.
Non sono stati installati pacchetti o scaricate dipendenze.

Un rollback richiede rimuovere solo la riga aggiunta e il sysctl dedicato,
ripristinare il valore precedente 60 e disattivare solo la nuova riserva,
dopo aver verificato le pagine che nel frattempo contiene e il margine RAM.
La partizione swap originaria non va disattivata. Nessuna cancellazione del
file è stata eseguita; non esiste un cleanup automatico.

Script delimitato: `scripts/configure_lab_swap.py`. Evidenze private nella
radice del workspace: `audit-evidence/swap-fix-20261009-plan/` e
`audit-evidence/swap-fix-20261009-apply/`, con backup fstab, piano, verifiche
complete e mirate, ricevuta applicata e metriche successive.
Resta utile una review concordata del budget RAM fra VM e modello condiviso.
