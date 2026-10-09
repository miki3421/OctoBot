# V13 A/B/C — osservazione funding attiva

8 ottobre 2026. L’owner ha autorizzato esplicitamente raccolta pubblica periodica per i29simboli e verifica ufficiale del funding. L’osservatore è installato e attivo, distinto dai conti e dal collector di qualifica.

## Consegna effettiva

- Servizio oneshot v13-abc-funding-observer.service e timer ogni5minuti. Primi due cicli (manuale e timer automatico):58risposte valide,29contratti per ciclo, SQLite integrity_check=ok. Prima finestra chiusa controllata:29campioni verificati senza gap; nessuna certificazione funding derivata.
- Codice rilasciato in directory separata sotto /opt, hash verificato prima di ogni esecuzione, configurazione root-owned fissata per hash; identità collector esistente30930, nessun nuovo privilegio o identità inventati.
- Filesystem del servizio in sola lettura salvo archivio dedicato sul disco capiente; home, segreti e archivio di qualifica inaccessibili. Nessuna scrittura a conti paper, intenti o approvazioni.
- Ricevute HTTP con URL, tempi, SHA-256 e byte compressi; esiti invalidi conservati, nessun retry della stessa coppia slot/simbolo. Limiti:64KiB per risposta,256MiB archivio,128MiB memoria,180s per ciclo. Rate-limit418/429 arresta le richieste e richiede revisione manuale anche dopo riavvio.
- Verificatore offline di continuità: finestre chiuse, identità, checksum e schema ricontrollati; gap e manomissioni restano visibili. Non trasforma la continuità dei campioni in certificazione dell’intero calendario di regolamento.

La frequenza osservata può variare, come documentato nell’annuncio KuCoin del17agosto2026 già citato nel rapporto precedente. Non si estrapola un calendario costante.

Collaudo:109test offline superati; i3test del collector sono passati anche su Python3.12.3 del server.

## Limiti che rimangono

Il confronto A/B/C **non è attivo**. La qualifica termina il16ottobre alle00:00UTC,02:00italiane, e il risultato potrebbe anche non essere PASS. Prima dell’avvio servono continuità del calendario e riconciliazione dei regolamenti, configurazione effettiva di producer/executor e verifica del rilascio con partenza comune. Il codice di ammissione conserva il diniego; non è stato creato un grant.

Il paper V13 esistente è healthy e non è stato riavviato o modificato. Minimi KuCoin ancora UNKNOWN.

Evidenze in audit-evidence/v13-funding-observer-20261008/ alla radice del laboratorio: test, configurazione del collector pubblico, unità/timer, hash del rilascio, prime ricevute verificate. L’archivio vive sul disco capiente separato dai journal operativi.

Schede: work-card-507f0fdb-521e-48bc-a9bb-60d17ceeee9d e work-card-56a72d4d-956c-47f1-b7b5-47bbc74546a1. Non chiuse Done perché i criteri di attivazione del confronto non sono ancora soddisfatti.

Rollback circoscritto: arrestare/disabilitare solo v13-abc-funding-observer.timer e arrestare il suo servizio; conservare archivio e configurazione. Nessuna rimozione dei dati.
