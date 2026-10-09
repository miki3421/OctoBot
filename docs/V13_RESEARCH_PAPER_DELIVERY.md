# V13 originale — paper di ricerca

Card contratto: work-card-395f2fc2-b628-4c87-a48a-e922687a2eed.
Card implementazione: work-card-77c03de2-8219-4ee0-8d56-a8651e760613.

Il proprietario ha autorizzato la consegna e l’attivazione del paper di ricerca, la policy numerica proposta e le acquisizioni pubbliche periodiche Binance/KuCoin. La successiva annotazione richiede esplicitamente minimi simulati. Questa versione applica il nuovo contratto `v13-research-paper-v1`; non promuove la ricerca storica, il BTC 30/120 o i vecchi issuer.

Il minimo simulato è un incremento di quantità e 1 USDT di nozionale, positivo, scelto per il simulatore. La precisione osservata è usata soltanto per rappresentare le quantità. Non costituisce prova di un minimo KuCoin. I minimi effettivi restano UNKNOWN e P0-03 per aperture exchange-faithful resta invariato e bloccato. I fill sono VWAP della profondità pubblica con 2bps avversi e fee conservativa: mai prezzi, volumi o liquidità inventati. Una gamba può essere ridotta alla profondità disponibile; quantità sotto il minimo sono saltate con motivazione.

La policy approvata limita nuovi aumenti di rischio dopo perdita giornaliera 2%, drawdown 10%, un ribilanciamento per giorno UTC o meno di 22 ore dall’ultimo. Limiti 31,5% per asset e 90% totale, verificati anche dopo fee e fill. Lo stato è persistente. Equity include PnL non realizzato, fee e funding stimato. Il primo punto completo del giorno è la baseline di perdita giornaliera; il massimo storico è conservato. Nessun reset al riavvio.

Il conto `v13-paper-v2` continua in `execution.sqlite` con copia verificata dei dati economici e nuova generazione delle posizioni. Il DB precedente resta conservato immutato. Il funding fra l’ultimo mark e la ripresa, e quello successivo, è una STIMA esplicita con rate pubblici regolati e il precedente mark osservato, come nel modello V2 originario: non è una ricostruzione degli addebiti exchange. Copertura mancante blocca nuovi ingressi.

Capture, producer, issuer ed executor usano UID distinti. La strategia scrive solo proposte; l’issuer ricalcola le funzioni originali e scrive approvals.sqlite; l’executor legge le approvazioni, registra il consumo monouso e scrive execution.sqlite. Filesystem e mount separano i file, non le tabelle. Un controllo amministrativo root-owned esclusivo per il nuovo scope consente solo V13 ricerca; il BTC resta in quarantena. La chiusura protettiva richiede peer UID amministratore locale, account, ID e generazione correnti, nonce e scadenza; non aumenta o inverte mai la posizione.

La UI distingue stato effettivo e freshness, simulazione e ammissibilità KuCoin. Nessuna certificazione scientifica o di profitto; verifiche dell’autore dichiarate interne. Rollback: arrestare esclusivamente i nuovi servizi e lasciare entrambi i ledger conservati, senza riattivare automaticamente il vecchio motore.

## Consegna e conduzione

La homepage del profilo locale apre `/v13_paper`. Il nuovo pannello usa solo asset locali, mostra equity, P/L, posizioni e ultimi fill e si aggiorna ogni 30 secondi. Il grafico interattivo conserva i buchi di osservazione; non interpola i sette giorni senza runtime. Il precedente laboratorio resta accessibile dall’archivio. La vista non legge o espone il socket amministrativo.

Da `octobot-source`, usando solo l’immagine già disponibile e il progetto Compose separato:

```bash
docker-compose -p v13-research -f docker-compose.v13-research.yml config -q
docker-compose -p v13-research -f docker-compose.v13-research.yml up -d --no-build
docker-compose -p v13-research -f docker-compose.v13-research.yml ps
```

Quattro UID non root, filesystem del container read-only, capability rimosse. Solo capture ha rete; producer, issuer ed executor non hanno rete. Approvals e execution sono file e mount separati. `control` è root-owned e leggibile dal GID 30910, directory 2750 e file 0640; una futura sostituzione amministrativa deve conservare questi proprietari e permessi. L’audit P0-04 è dell’executor. La riserva P0-01 viene committata prima dei fill: un crash successivo brucia la decisione e non ne permette il riuso. Il consumo usa l’identità causale stabile, distinta dall’hash dell’acquisizione completa.

La migrazione usa una copia SQLite sigillata, verificata per SHA e integrità, installata atomicamente prima di continuare il conto. Una copia SQLite può avere un hash fisico diverso dalla sorgente per i metadati di storage; la verifica confronta ogni riga di tutte le tabelle originali. La prima migrazione fallita e vuota è conservata separatamente come evidenza. I dati originali non vengono eliminati. Nuovi raw e archivi di mercato sono compressi senza cambiare i byte ricevuti o gli hash logici; i vecchi artefatti restano conservati.

Chiusura protettiva locale autenticata, da amministratore root; quantità omessa significa chiusura della quantità attualmente dichiarata:

```bash
python3 docker/v13-research-admin-close.py AAVEUSDT
python3 docker/v13-research-admin-close.py AAVEUSDT --quantity 0.1
```

Il comando usa un socket esterno ai mount della UI e identifica account, posizione, generazione, nonce e validità di 60 secondi. L’executor verifica quantità e book correnti, nega replay, scadenza, aumento, inversione e guasto di persistenza. Nessuna nuova previsione o automatismo stop/horizon. Questa consegna non chiude posizioni per dimostrare il percorso: i test positivi sono su copie, la prova amministrativa live è un comando scaduto correttamente negato.

Rollback del solo paper: `docker-compose -p v13-research -f docker-compose.v13-research.yml stop`. Non usare prune, eliminazioni di volumi, reset del ledger o riattivazione del vecchio executor. L’interfaccia passa a dati scaduti dopo il limite di freshness. Il riavvio conserva riserva, saldo, massimo storico, baseline giornaliera e cooldown.
