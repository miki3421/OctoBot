# BTC intraday — ricevute prospettiche, 17 ottobre 2026

Milestone tecnica completata; non prova di redditività o ammissibilità KuCoin.
La richiesta è stata poi estesa dall'utente fino al conto paper attivo e in UI:
questa milestone non conclude l'incarico operativo.

Osservazione limitata di 90 secondi, senza nuovo collector periodico o conto:
89 batch, **901 righe L5**, un pacchetto iniziale bootstrap e **un nuovo pacchetto
mercato verificato**. Query book massima 0,882ms. Disponibilità osservata dopo
46–1221ms dalla ricezione, mediana 558ms, percentile 95 circa 1046ms.
**78 righe superavano 1000ms** alla visibilità confermata: non vanno usate come
quote fresche d'ingresso. Non equivale a 78 opportunità perse, né misura la
copertura di un conto futuro. Nessun fill o PnL calcolato in questa prova.

Ricevute su disco dati, alias `btc-intraday-availability-20261017-v1`, file
sigillati e `integrity_check=ok`. Database 7.155.712 byte, SHA-256
`707661d4e9ba0717d71b3d1663c54ef7f84211bc5b1c6e9a9cfd654091e8bf13`.
Catena finale `4e97aaf55eeb506851fde88e861f03833accba64a33592ddef25086c9abebeff`.
La completion receipt vincola anche il riepilogo e gli hash. Non è stata
ricostruita alcuna prova di commit del passato.

23 test interni superati: crash reali dopo ciascuno dei tre commit, restart
senza completamento retroattivo, duplicati, deadline, clock/boot, catena
alterata, SQLite pieno e read-only, dati futuri, book incrociato, backlog,
transazioni sorgente non committate invisibili e assenza di backfill iniziale.
Questa verifica interna non viene presentata come review indipendente.

Protocollo v2 preservato. Minimi reali UNKNOWN. Schedine: 1a999de7,
5c75e0d0, 0437e0c4, a655a24c. Il simulatore separato f20d8837 è in lavorazione
per l'estensione autorizzata; nessuna modifica alle regole delle strategie attuali.
