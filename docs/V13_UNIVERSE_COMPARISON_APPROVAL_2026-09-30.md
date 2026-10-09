# Protocollo confronto V13 · conferma owner

Il 30 settembre 2026 l'owner ha confermato il protocollo del confronto
18 contro 29 asset. La decisione è registrata in una
[ricevuta separata](contracts/v13-universe-comparison-owner-approval-v1.json),
vincolata all'hash della proposta revisionata:
`09f855a5af1b3945bf6bb9e9bca4a1676599d6c0c633da66387af650c460e49d`.

La proposta e il suo manifest originali restano intatti come evidenza di ciò
che è stato approvato; i loro vecchi flag DRAFT descrivono lo stato alla
presentazione. Per lo stato corrente leggere la ricevuta successiva.

Sono confermati il disegno A=18/B=29, PEPE sospeso senza sostituti, la
qualifica dati di 14 giorni e il successivo disegno forward di 180 giorni,
con criteri e controlli descritti nel protocollo. Questa decisione approva
il protocollo, non certifica un risultato scientifico né abilita un servizio.

**Stato corrente:** protocollo approvato; qualifica non avviata; data iniziale
non fissata. I conti di confronto non sono stati creati. Il conto V13 esistente
continua invariato.

Il [piano tecnico offline](contracts/v13-universe-qualification-plan-v1.json)
esplicita 29 simboli, cinque classi di GET, 39.816 richieste nominali, massimo
42.000 tentativi e 512 MiB raw compressi in 14 giorni. Book ogni 15 minuti;
daily chiuse Binance, funding KuCoin e metadata giornalieri. Il mapping va
riverificato sulle fonti al momento della futura raccolta. Nessuna richiesta
di questo piano è stata eseguita.

La verifica offline espande il calendario nominale, controlla unicità e
conteggio dei job, esclusione PEPE, coorti, hash e limiti. Non è il collaudo
di un collector: restano da implementare e testare isolamento, persistenza
dei tentativi prima della rete, prenotazione dello spazio, arresto al limite,
ripartenza e pubblicazione dello stato. La relativa scheda resta To-do.

Prima della raccolta periodica occorre l'autorizzazione specifica ai download,
distinta dalla conferma del protocollo, come richiesto dalla regola aziendale
MMTech. L'autorizzazione una tantum del checkpoint precedente è già stata usata.
Avvio della qualifica e della fase forward richiedono inoltre i rispettivi
componenti pronti, testati e un momento di attivazione esplicito.

La UI ora mostra «Protocollo approvato · qualifica non avviata». Nessun
riavvio, nuovo download, grant, ordine o modifica al paper in questa iterazione.
