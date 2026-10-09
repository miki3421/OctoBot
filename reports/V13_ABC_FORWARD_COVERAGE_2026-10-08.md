# V13 A/B/C — consegna del verificatore funding e archivio forward

8 ottobre 2026. **Codice offline collaudato; confronto operativo ancora BLOCKED.**
Questo aggiornamento integra la consegna precedente, senza sostituire le sue evidenze.

## Completato

- Verificatore della copertura funding su calendario esplicito dei regolamenti per tutti i 29 simboli, con intervallo, hash esterno e riferimenti alle evidenze. Non ricava periodicità dalle rate osservate. Un calendario alterato, un regolamento mancante o un mark non disponibile causano rifiuto.
- Archivio forward SQLite separato, indipendente dalla durata della qualifica. Riceve byte HTTP e tempi da un collector autorizzato: verifica endpoint, finestra temporale, metadata precedenti, hash, schema e replay. Il lettore ricontrolla le ricevute. Non effettua download e non installa un collector.
- Collegamento delle due dipendenze nel consumer. Senza configurazione verificabile resta il diniego; nessuna approvazione operativa è stata creata. Il primo intervallo parte da conti nuovi e piatti, senza debiti anteriori ereditati.
- Dashboard aggiornata con stato reale e distinzione tra implementazione, evidenze e attivazione.

## Verifica

**93 test passati: 73 del confronto e 20 del valutatore di qualifica.**
Suite eseguita nel runtime locale esistente, rete disabilitata, sorgenti in sola lettura.
Le nuove prove usano ricevute e calendari sintetici dichiarati: verificano copertura esatta, dinieghi, hash, persistenza, riapertura e dati 30 giorni dopo l’inizio della qualifica. Nei test del calendario la custodia filesystem è mockata perché il file sintetico risiede in /tmp; il codice reale mantiene il controllo root-owned.
Il test positivo del consumer continua a simulare le autorità: **nessun E2E positivo con funding reale o ordine KuCoin viene dichiarato**.

Evidenze: `audit-evidence/v13-forward-coverage-20261008/` alla radice del laboratorio.
Comando riproducibile: `python3 -B scripts/verify_v13_abc_offline.py` dal fork nel runtime esistente.

## Ciò che rimane davvero

| Condizione/lavoro | Stato e criterio di chiusura |
| --- | --- |
| Evidenza funding | Manca il calendario autorevole applicabile ai 29 contratti, revisionato e fissato esternamente. Gli hash dei riferimenti non costituiscono da soli verifica documentale. Nessun calendario reale è stato inventato. |
| Raccolta forward | Archivio e reader pronti; manca il processo periodico autorizzato che alimenti l’archivio. Il calendario di acquisizione riusato pubblica funding del giorno precedente: un regolamento più recente assente resta bloccante. |
| Integrazione del servizio | Restano ciclo di osservazioni equity, validità operativa degli intenti, riduzioni protettive e ownership/release del servizio finale. Non sono sostituiti da flag di readiness. |
| Qualifica | Valutazione finale dal 16 ottobre 2026 alle 00:00 UTC / 02:00 italiane; la data da sola non implica PASS. |
| Avvio | Bundle candidato da verificare e attivazione distinta; il controllo di ammissione continua a negare l’esecuzione. |

Schede: funding `work-card-507f0fdb-521e-48bc-a9bb-60d17ceeee9d`; forward/servizio `work-card-56a72d4d-956c-47f1-b7b5-47bbc74546a1`; QA `work-card-dba701d5-25ec-4873-bfa5-697024eed97b`.
Le schede ampie non sono Done: il codice verificato non soddisfa ancora i criteri operativi.

Nessun riavvio, nuovo download, grant, avvio A/B/C, modifica al conto V13 o cancellazione dati. Minimi reali KuCoin ancora UNKNOWN. Bundle v2 separato, senza riscrivere il contratto approvato o il bundle precedente. Nessun commit/push indiscriminato del workspace con modifiche pregresse.
