# V13 — panoramica con un grafico per ogni simbolo

10 ottobre 2026. Scheda `work-card-51c6a68a-c556-4e42-bd1c-745ee5e306b5`.
Pagina consegnata: `/v13_paper/charts`, vista predefinita «Tutti i simboli».

La griglia mostra i 18 simboli originali del conto V13, due per riga su desktop
e uno su telefono. I grafici usano lo stesso periodo e asse temporale, con
prezzi osservati e tutti i marker BUY/SELL del periodo. Posizione e quantità
indicate sono quelle attuali. I marker restano fill del simulatore, non nuove
previsioni. Il passaggio sui marker mostra l'effetto sulla posizione; un click
o «Apri dettaglio» porta al grafico completo, alla tabella e all'impatto equity.

Restano disponibili 24 ore, 7 giorni e tutto lo storico, aggiornamento ogni
30 secondi e link diretto `?symbol=BTCUSDT` o altro simbolo ammesso. I grafici
non riempiono buchi né inventano quotazioni precedenti alla prima acquisizione.

Un endpoint protetto come il precedente legge un'unica transazione SQLite in
sola lettura. Riconcilia numero di fill, quantità e contabilità, poi compatta
solo i punti di prezzo della panoramica a massimo 800 per simbolo. Minimi,
massimi ed estremi temporali sono preservati; ogni intervallo contenente un
buco viene disegnato senza collegamento. Nessun fill è scartato o alterato.
Il dettaglio conserva la lettura precedente fino a 20.000 prezzi per simbolo
e tutto lo storico dei fill; eventuale limitazione resta dichiarata.

Misura locale iniziale: 18 grafici, 134 fill, risposta circa 1,30 MB,
circa 0,95 secondi. Evita 18 richieste indipendenti e relativi snapshot diversi.
È una misura su questo archivio e host, non una garanzia di latenza futura.

Verifiche: 12 test su transizioni long/short, contabilità, scope, lettura
parametrizzata/immutabile, extrema e gap. Browser reale in preview e dopo
rilascio: 18 canvas disegnati, dettaglio BTC e impatto equity accessibili,
filtri temporali, telefono a colonna unica senza overflow, link diretto AAVE;
zero errori JavaScript e richieste esterne. Screenshot e ricevute nella radice
workspace: `audit-evidence/v13-charts-overview-20261010/`.

Codice UI candidate commit `990358257bd3460820c546ed7dddd13416f7426c`, pubblicato
sulla branch di consegna separata. Aggiornato soltanto il container interfaccia
`octobot-local`, poi healthy. I quattro servizi del paper continuano e il conto
conserva 18 posizioni, 134 fill, scope RESEARCH_SIMULATION_ONLY. I file cambiati
non appartengono ai pin del trading attivo né al manifest A/B/C congelato.
Nessuna modifica a ledger, collector, grant, policy, modello o strategia.
Preview locale temporanea chiusa dopo la verifica.
