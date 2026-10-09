# V13 A/B/C — consegna offline e blocchi reali

8 ottobre 2026. **Consegna offline collaudata; lavoro operativo NON terminato. Stato BLOCKED.**
Il conto paper V13 esistente prosegue separatamente. Nessun conto A/B/C operativo,
riavvio, nuovo download, grant o deroga alla qualifica è stato eseguito.

## Implementazione consegnata

- Selettore settimanale A18/B29/C massimo18, derivazione causale e target V13.
- Reader con verifica delle ricevute, precisione quantità/prezzi, fee pubbliche,
  intenti persistiti e book successivi al commit, disponibili e recenti entro60s.
- Motore contabile comune: VWAP entro profondità, slippage avverso2bps,
  arrotondamento avverso ai tick e commissioni per simbolo almeno6bps.
- Cassa, posizioni, commissioni, funding e consumo monouso persistiti insieme;
  importi non determinabili restano null, riconciliazione tardiva senza doppio addebito.
- Consumer protetto: verifiche del contratto e della qualifica prima di aprire
  un ledger, costruzione del pacchetto tramite intent store, ricontrollo book
  dopo il lock di scrittura, commit atomico e replay.
- Correzione del binding archivio dopo la migrazione al disco più capiente.
- Dashboard pulita che distingue collaudo offline, dati osservati e ostacoli all’avvio.

Il consumer **non è pronto all’attivazione**. `_funding_available` e
`_verified_funding` rifiutano esplicitamente perché non esiste ancora il
verificatore autorevole della copertura: non sono implementazioni positive.
Il reader attuale serve la finestra di qualifica, non è una sorgente forward
perpetua. Ciclo di osservazioni equity, validità degli intenti e riduzioni
protettive richiedono integrazione nel servizio finale. Queste parti non
vengono nascoste dietro un generico “manca solo l’approvazione”.

## Prove e limiti

**89 test passati:69 del confronto e20 del valutatore della qualifica.**
Il nuovo test del controller collega intento, book, fee per simbolo e ledger;
le autorità di qualifica e funding sono esplicitamente mockate. È una prova
architetturale con fixture, non una prova positiva su dati reali né di
ammissibilità KuCoin. Verificati rifiuto senza creazione del ledger,
rollback dopo il calcolo, replay, checksum del pacchetto e parità contabile.

Il controllo reale corrente ritorna contratto approvato, qualifica
IN_PROGRESS e diniego. Non crea un intento né un ledger. Il fingerprint
usato nella diagnosi locale non è una firma di deployment. Gli hash nel
contratto approvato restano lo snapshot storico; il nuovo manifest è un
**bundle candidato non approvato**, non aggiorna automaticamente quei pin.

UI: desktop e mobile HTTP200, tre bracci, nessun overflow né errore JavaScript.
Container esistenti osservati healthy; nessun riavvio effettuato. Tre ledger
V13 controllati in sola lettura: integrity_check=ok. Test e risultati in
`audit-evidence/v13-abc-delivery-20261008/` alla radice del laboratorio.

## Cosa impedisce di terminare l’avvio

| Lavoro residuo | Motivo | Scheda |
| --- | --- | --- |
| Copertura funding | Le203ricevute e735rate osservate non certificano tutti i regolamenti dovuti. Occorre evidenza e poi un verificatore; nessun costo zero implicito. | work-card-507f0fdb-521e-48bc-a9bb-60d17ceeee9d |
| Sorgente forward e integrazione operativa | La qualifica finisce il16ottobre. Serve il feed29 successivo e il ciclo operativo completo, con ownership, protezioni e bundle verificato. | work-card-56a72d4d-956c-47f1-b7b5-47bbc74546a1 |
| Qualifica finale | Cutoff16ottobre00:00UTC,02:00Europe/Rome. Raggiungere la data non implica PASS. | work-card-23902a16-23d0-4275-9a71-e4d413319f96 |

Le due nuove schede sono To-do e conservano lavoro effettivamente non svolto.
L’implementazione generale resta bloccata/incompleta; non viene chiusa Done.
Le regole di simulazione già approvate non richiedono una nuova approvazione
per il solo fatto che il codice è avanzato. L’attivazione operativa e le
relative identità/store non sono state autorizzate da questa consegna.

## Riprodurre il collaudo

Nel runtime Python/NumPy esistente del laboratorio, da `octobot-source`:

```bash
python3 -B scripts/verify_v13_abc_offline.py
```

Ambiente del collaudo: immagine locale octobot-local:dev, Python3.13.14,
NumPy2.4.2, rete disabilitata, checkout in sola lettura e /tmp temporaneo.
Nessuna dipendenza installata. Il manifest elenca hash delle sorgenti e
contratti del candidato; l’archivio è uno snapshot da applicare al checkout
esistente, non un installer o un rilascio approvato.

Non è stato effettuato commit/push: il workspace contiene molte modifiche
pregresse non correlate e questa consegna le conserva. Non sono cancellati
archivi, journal o evidenze storiche. Nessuna promozione scientifica.
