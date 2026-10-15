# Avvio osservativo M1 SHORT v1

Schede: `work-card-0ffe29e7-066d-4670-9b68-f23f7c651f94`,
`work-card-6e34a16c-52fb-4994-ade1-2abd126f13a9`,
`work-card-1e06b442-a685-4fad-a0bd-31ffe352ec2b`.

Autorizzazione utente del 15 ottobre 2026: avviare osservazione M1 e schedulazione,
lasciando Originale, FAST e HALF invariati. Effetto PRODUCTION limitato al runtime
di ricerca sul server; stream di consegna development. SINGLE_AGENT, nessuna
review indipendente dichiarata. Nessun ordine, issuer, grant o nuova acquisizione
Internet. I minimi KuCoin restano UNKNOWN.

Il bundle scientifico del commit `277a99731af53d81d462b16d51a3e100a20b544a`
rimane immutato. `new_service_activation=false` descrive la preparazione storica,
non un grant di esecuzione; questa attivazione osservativa ha una ricevuta distinta.
Il registratore usa soltanto libreria standard Python già installata.

Installare i 12 file del bundle, questi file di distribuzione e un manifesto
`files.sha256` sotto `/opt/v13-m1-short-observer-277a9973`, root-owned e in sola
lettura. L'esecuzione usa questa copia esatta; non dipende dalle modifiche locali
del checkout. La radice operativa canonica resta `/root/auto_trading_sys` sul
disco grande. L'unico nuovo spazio scrivibile persistente è
`octobot-local/v13-m1-short-future-v1`, UID numerico dedicato 30942, GID di
lettura 30910. L'identità locale di servizio ha password bloccata, nessuna home
e shell nologin; il gruppo dichiara il GID di lettura già presente sui dati.
Non creare accessi interattivi, credenziali exchange o nuovi grant.
Le directory sorgenti non cambiano proprietario o permessi.

Il namespace del processo maschera `/root` e vi espone solo ledger originale,
book e archivio del nuovo studio. Sorgenti e codice sono montati in sola
lettura; rete, socket Docker e credenziali non sono accessibili. La qualifica
usa lo stesso utente e lo stesso sandbox: verifica finestra causale, diniego
scrittura, rete e copia SQLite. Le copie `qualification/fixture-*` non sono
osservazioni future e non entrano nel journal scientifico.

Prima del primo avvio verificare l'assenza di uso precedente dell'UID 30942,
capacità disco, identità dei file, unità systemd e assenza di journal reale.
Eseguire la qualifica con ExecStart sovrascritto da drop-in temporaneo, rimuovere
il drop-in e ricontrollare la configurazione finale. Non toccare le altre unità.
Eseguire poi una sola volta `start` nello stesso sandbox con drop-in temporaneo,
conservare la ricevuta, ripristinare `tick` e abilitare il timer.

Il timer richiama `tick` ogni minuto al secondo 20 UTC. Le decisioni restano su
griglia 5 minuti. `Persistent=false` impedisce recuperi retroattivi al reboot;
il journal persistente marca gli slot mancati senza inventare segnali. Prima di
T0 il tick risponde WAITING_FOR_FUTURE_T0. T0 è la mezzanotte UTC successiva alla
ricevuta; T1 è T0+90 giorni. Un secondo `start` deve restituire la stessa ricevuta.

Non riavviare l'host per provare il recupero: verificare timer enabled, dipendenze
mount e nuovo processo sulla stessa ricevuta. La prova completa di un reboot
fisico resta distinta dal recupero di processo e non viene dichiarata eseguita.
I guasti falliscono senza ordini; systemd conserva errori e il tick successivo
mantiene il medesimo journal. Non cancellare journal o catture parziali.

Per un arresto reversibile: `systemctl disable --now v13-m1-short-observer.timer`
e `systemctl stop v13-m1-short-observer.service`. Conservare archivio, ricevuta,
release e unità; non resettare T0. Non cambiare il filtro dopo la partenza.

La schedulazione raccoglie input e book; i tre casi saranno ricalcolati soltanto
a fine orizzonte con il valutatore congelato. Non crea una quarta strategia
operativa e non modifica la dashboard o il monitoraggio delle strategie attuali.
