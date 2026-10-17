# Ricevute prospettiche BTC intraday v1

Componente locale isolato, senza rete, ordini, approvazioni o collegamenti agli
esecutori esistenti. Schedine: 1a999de7, 5c75e0d0, 0437e0c4, a655a24c.
Protocollo v2 invariato: `bbc19094ac23b8b13a0d82919802f2ede3787add5eda2e13f0f2d8489861493b`.

Ogni lettura conserva identità e hash dell'input, timestamp exchange e ricevuto
originari, inizio/fine lettura del consumer, boot e clock monotono/UTC. I tempi
dichiarati dalle fonti restano distinti dalla disponibilità effettivamente
osservata. Non vengono dedotti commit dall'mtime o dalla cadenza del collector.
Il collegamento crittografico prova integrità locale, non autentica l'exchange.
Il payload websocket originale L5 non è archiviato dal collector: si conserva
l'hash dichiarato e si calcola un nuovo hash della riga realmente letta.

Il journal SQLite dedicato usa FULL synchronous, un solo writer con lock del
processo e una catena append-only. Tre transazioni separano dati, conferma del
ritorno del primo commit e attestazione del ritorno del commit di conferma.
Una transazione non attribuisce a sé stessa un timestamp di commit completato.
La disponibilità per un futuro consumer richiede inoltre una **lettura corrente
in sola lettura** della conferma completa, terminata entro la scadenza: non è
un token di ingresso, né permette un ingresso storico usando un'attestazione
letta dopo la scadenza. Il consumer deve ancora verificare tutti i gate v2.

Crash intermedi lasciano ricevute incomplete; un riavvio apre una nuova epoca e
non completa ricevute vecchie. Duplicati, catena alterata, clock regressivo o
salto del clock superiore a un secondo rispetto al monotono, cambio boot,
backlog oltre il limite della query, storage pieno/non scrivibile e dati futuri
negano disponibilità o fermano il witness. Il lock file da solo non prova attività.
FULL synchronous documenta il contratto SQLite/OS, non certifica l'hardware.

La prova limitata parte dal cursore corrente L5, usa query sul suffisso indicizzato
in brevi transazioni RO e non effettua scansioni sul journal live. Il primo
pacchetto mercato è bootstrap; non attesta disponibilità storica. I pacchetti
successivi vengono verificati da hash, raw e derivazioni delle sole fonti utili.
Le copie e ricevute storiche qualificate restano conservate.

Nessun limite di freshness o deadline viene cambiato: M1 120s, decisione +30s,
L5 1000ms, esecuzione dopo 500ms e attesa 1000ms. Il nuovo conto potrà osservare
molti dati ma dover rinunciare a un ingresso quando la persistenza è tardiva.
Minimi KuCoin UNKNOWN; minimi sintetici non sono evidenza di ammissibilità reale.
