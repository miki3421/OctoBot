# BTC intraday — conto attivo e dashboard consegnata

17 ottobre 2026. **Consegna operativa paper completata**, stato `ACTIVE_WARMUP`.
Dashboard: `http://localhost:5001/btc_intraday`, collegata dal confronto V13.
Conto `btc-intraday-m1-l5-paper-v1`: **10.000 USDT virtuali, flat, zero fill**.
Non è una previsione di profitto, un conto exchange o trading reale.

## Cosa funziona

- Ricevute prospettiche di disponibilità e persistenza, hash e clock distinti
  dalla ricezione originale; nessuna ricostruzione retroattiva di un ingresso.
- Simulatore isolato con M1 sui 18 mark, SHORT solo BTC, size e costi sintetici,
  book L5 osservato, pending persistenti, stop/TP/scadenza e funding riconciliato.
- Nessuna quota giornaliera né cooldown: restano limiti di perdita/esposizione,
  una posizione alla volta e un tentativo per slot distinto.
- Chiusura protettiva locale root-only, nonce monouso, scadenza e generazione;
  nessun pulsante d'ordine o credenziale exchange nella UI.
- Scenario stress v2 con le stesse opportunità primarie e quantità intenzionali,
  ma latenza 1000ms, rischio, profondità, posizioni e uscite indipendenti;
  debit funding doppi, crediti nulli, fee/slippage raddoppiati.
- Dashboard con equity, stato della raccolta, operazioni, segnali e motivi di
  attesa; verifica desktop/mobile senza errori JavaScript. Asset verificato
  per contenuto e MIME, dati con `no-store`.
- Health e freschezza del nuovo container incluse nel monitor già configurato;
  nessuna mail manuale o modifica a credenziali SMTP.

## Attivazione, continuità e isolamento

L'utente ha richiesto esplicitamente di terminare soltanto con conto attivo e
in dashboard; ha poi approvato specificamente il riavvio di `octobot-local`.
Solo il servizio web condiviso è stato riavviato per caricare le route.
Gli altri **otto container preesistenti di collector/strategie** hanno mantenuto
ID, avvio e restart count; **dieci container totali healthy** alla consegna.
Originale, FAST, HALF, M1 paper e osservazione M1 non sono stati modificati.

La correzione dello stress è stata completata **prima di T0**, con zero fill
primari e una ricevuta esplicita di continuazione che vincola snapshot flat,
attivazione iniziale, nuovo codice e protocollo immutato. Il ledger primario,
il saldo e la sua identità iniziale sono conservati. Il vecchio diagnostico
che variava solo i costi resta nelle evidenze; non è presentato come stress v2.
Il nuovo ledger stress nasce flat prima della valutazione, senza risultati ereditati.

Immagine cached fissata per digest, rete `none`, root filesystem RO e nessuna
capability. I volumi impliciti dell'immagine sono montati vuoti RO; soltanto
`/state` e `/projection` sono persistenti RW. Nessun altro conto, grant o
credenziale exchange è montato. I problemi di ricreazione del legacy Compose
sono stati risolti rimuovendo solo la definizione del container nuovo fermato,
**senza rimuovere volumi, dataset, journal o storico**.

## Prove ed evidenze

**119 test interni superati**: 23 ricevute; 33 primario; 10 stress;
4 continuazione; 3 proiezione; 4 route; 21 fonti; 21 adapter L5.
Crash reali, SQLite pieno/read-only, replay, clock/boot, deadline, prezzi futuri,
book insufficienti, chiusure parziali, funding tardivo/discordante e confini UTC.
Il riavvio reale del nuovo conto ha conservato equity, posizione e storico.
La verifica interna non viene dichiarata review indipendente.

Le copie finali di entrambi i ledger sono state controllate offline con
`integrity_check=ok`; hash, identità e dimensioni sono nel JSON compagno.
Prova ricevute di 90s e copie storiche qualificate restano conservate.
Evidenze sul disco dati, alias `btc-intraday-activation-20261017-v1`, comprese
ricevute precedenti, continuazione, snapshot e screenshot browser delle due fasi.
Codice runtime fissato nel commit `315471fe148624268116e24aaeaf01fec40a7abf`.
Protocollo v2 SHA-256 `bbc19094ac23b8b13a0d82919802f2ede3787add5eda2e13f0f2d8489861493b` invariato.

## Cosa resta futuro

Il conto raccoglie da subito. Servono **289 punti contigui di cinque minuti**,
circa 24 ore, prima della prima opportunità ammissibile; i buchi possono
prolungare l'attesa. Il conto non forza operazioni per produrre un risultato.
T0 **18 ottobre 2026, 00:00 UTC**; T1 **16 gennaio 2027, 00:00 UTC**.
La valutazione resta `UNASSESSED`: niente promozione prima dei criteri congelati
su giorni, episodi, settimane, copertura, drawdown e rendimento netto/stress.
Il riesame scientifico resta una schedina futura To-do, distinto da questa consegna.

Minimi reali KuCoin **UNKNOWN**; il conto usa esclusivamente il proprio
contratto sintetico. Il percorso KuCoin-faithful e il trading reale non sono
abilitati o certificati da queste prove.

Esecuzione SINGLE_AGENT con procedure MMTech e tracking PM; stream Development.
I minuti attivi non sono stati misurati separatamente dalle attese e dai nuovi
indirizzi dell'utente: non viene inventato un consuntivo temporale.
Schedine di riferimento: 1a999de7, f20d8837, b8a049f7, 312947f2,
5c75e0d0, 0437e0c4, a655a24c, a966e5da, a8a086fc, 10bec2ef, 21414709.

Riesame futuro visibile To-do: `work-card-3d0610f3-0313-4788-8ea9-9585d99d1c28`.
