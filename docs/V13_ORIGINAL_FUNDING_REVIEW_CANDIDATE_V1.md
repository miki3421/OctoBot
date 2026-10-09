# V13 originale — riconciliatore funding candidato solo su copie

28 settembre 2026. **IMPLEMENTATO, INATTIVO, metodo/qualità NON APPROVATI;
readiness BLOCKED.** Scheda `work-card-edc2e575-f692-4997-807f-352a1b3c8ba0`;
test interni `work-card-5111d6c5-47ed-4414-8fd0-f227d0a1c23b`.

Il modulo `octobot/ai_strategy_lab/v13_original_funding_review.py` prepara una
**simulazione retrospettiva esplicita** sul backup del conto `v13-paper-v2`, usando
il metodo candidato `UNAPPROVED_LEGACY_PREVIOUS_DECLARED_MARK_ESTIMATE_V1`.
L'istruzione di procedere autorizza costruzione e prova del candidato su copie;
non viene registrata come accettazione operativa del metodo o dei dati.
Non è un writer runtime e non viene importato dal collector, issuer o executor.
Nessuna modalità operativa, ordine, credenziale, rete, grant, policy configurata,
installazione, avvio o cambio quarantena.

## Risultato riproducibile sul backup congelato

| Evidenza | Risultato |
| --- | --- |
| Backup di partenza SHA-256 | `af77dae4a05006f6dd25c9f1c2697da2dc4ad4ca72e55c881760cd2a1381774d` |
| Archivio | Prefisso congelato di 693 record, fino al 28 settembre 13:30:31 UTC |
| Eventi candidati | 168 distinti, su 8 asset detenuti; 161 addebiti e 7 crediti |
| Funding stimato totale | **−3,7732603484000005 USDT** |
| Equity candidata ai vecchi marks del 21 settembre | 10.021,821761813528 USDT; non equity corrente |
| Tabelle originali della copia | Identiche: 8 ordini, 14 equity storiche, 0 funding legacy |
| Nuove tabelle di revisione | 168 eventi, 1 ricevuta/stato candidato, 1 punto di rettifica |
| Replay | `ALREADY_REVIEWED`, stessa ricevuta, nessuna duplicazione |

Questi importi sono stime locali da revisionare, non costi exchange certificati,
performance forward o ammissibilità KuCoin. Il conto operativo conserva zero
funding contabilizzato; **nessuna rettifica gli è stata applicata**.

## Input e metodo

Sono richiesti selezione esplicita del metodo candidato e pin SHA-256 esterni per
backup, gzip e prefisso decompresso. Il contratto portfolio originale è letto
contro il pin già esistente; universo e mapping candidati dei 18 simboli sono
controllati in tutti i record. Asset extra del raw non entrano nel portafoglio.
Si verifica la chain completa, JSON senza duplicati/non finiti, invarianti
observation-only e contiguità dei bucket/tempi dichiarati. Si deve ritrovare
esattamente il record già presente nel cursore del conto.

Il backup è controllato con `inspect_legacy`: ordini filled, quantità/prezzo medio,
fee/realizzato, funding precedente, marks, cursore ed equity devono coincidere.
Questo candidato ammette solo il caso conservativo in cui tutti i fill storici
precedono il cursore di partenza e sono cronologici. Per ciascun settlement,
la quantità in unità base viene ricostruita dai fill precedenti e confrontata
con quella del conto; non si presume continuità dalla sola posizione corrente.
Fill al tempo del settlement, fill successivi al cursore, pending e incoerenze
sono rifiutati; una futura migrazione di casi diversi richiederà lavoro separato.

Usa esclusivamente `settled_last_24h`, conserva il segno, deduplica per
account/simbolo/settlement e rifiuta rate discordanti o duplicati nella stessa
lista. `current_rate` e `predicted_rate` sono ignorati. Un evento mancante resta
mancante; uno zero **effettivamente osservato come rate** può essere usato.
Questo non autorizza zero per minimi contrattuali UNKNOWN.

Il riferimento è l'ultimo mark di un record dichiarato completamente ricevuto
**prima** del settlement; non il primo record che contiene la rate dopo il
settlement. Formula candidata: `−quantità base detenuta × mark precedente × rate
regolata`. Ogni evento conserva contratto, quantità/unità, segno, rate, hash delle
fonti rate/mark e i relativi tempi dichiarati.

Il controllo degli intervalli funding è quello dichiarato dal collector:
nessun buco interno, primo evento entro un intervallo dal cursore e tail prima
del prossimo intervallo dichiarato. Non certifica il calendario dell'exchange.
Il cut-off è congelato: non inventa il settlement successivo e non completa
il costo fino a un'eventuale ripresa futura.

## Transazione, storico e ricevuta

Il target è una nuova copia privata, con marker del sandbox di migration review,
root 0700 e file posseduti dall'identità locale senza accesso group/world.
Il modulo rifiuta percorsi `octobot-local`, escape, symlink, hardlink, input con
WAL/journal non vuoto e uso del file sorgente come target. Il lock locale
non bloccante serializza la revisione: **non è il lease operativo P0-04**.
File incompleto dopo un guasto di backup non viene silenziosamente sovrascritto.

Le tabelle originali **non vengono mutate**, neppure sulla copia. Le nuove
`funding_review_events`, `funding_review_batches` e `funding_review_equity`
registrano eventi, stato candidato/ricevuta e punto esplicito di rettifica,
insieme in un'unica transazione SQLite DELETE/FULL. Il punto ha il tempo reale
`accounted_at` della revisione e tipo `RETROSPECTIVE_ESTIMATE_AT_REVIEW_TIME`;
non viene aggiunto retroattivamente all'equity storica.

La ricevuta lega hash di backup/stato/archivio/eventi/codice, metodo, cutoff,
risultati prima/dopo, stato candidato e dati di rischio storici. Mantiene:
`method_approved=false`, `data_quality_approved=false`,
`historical_availability=UNRESOLVED`, `mark_measurement_timestamp=null`,
`operational_approval=false`, `issuable=false`, `gap_operationally_closed=false`.
La fine di un record è una dichiarazione legacy, non receipt indipendente.
Questi hash sono integrità locale, non firma exchange o autorizzazione.

Il replay confronta nuovamente input, schema, tabelle legacy, chiavi SQL, eventi,
intera ricevuta ricalcolata, stato candidato e punto di revisione. Una ricevuta
alterata e risigillata per attribuire un'approvazione viene rifiutata. Un bundle
successivo richiede una nuova copia, non un append implicito a questa revisione.
Gli input vengono ricontrollati dopo la derivazione; la namespace privata è
un requisito per evitare writer concorrenti non coordinati.

Crash pre-commit o SQLite FULL → rollback, senza stato candidato parziale.
Crash post-commit → restart con `ALREADY_REVIEWED`, senza raddoppiare eventi.
La prova di guasto mediante eccezione è distinta da un test fisico del disco/fsync:
nessun guasto hardware è simulato come certificazione di persistenza fisica.
I test di morte reale del processo verificano il recovery del rollback journal.

Non si aggiorna `last_mark_at`/`last_market_at`, non si azzera un contatore,
non si ricostruiscono approval/claim storiche e non si supera il guard di 20 ore.
Il vecchio bundle di migrazione resta conservato. Il candidate state qui prodotto
non è un database migrabile/operativo già approvato: il futuro writer dovrà
applicare una rettifica accettata e creare un **nuovo** bundle/epoch, dopo review
e definizione del cutover, preservando tutto lo storico. Un rollback coerente
non è rilevabile con questi soli file se vengono riavvolti insieme: serve ancora
un witness esterno approvato per il futuro percorso operativo.

## Verifiche e seguito

**124 test interni passati:** 41 del candidato e 83 regressioni paper/decoder
mercato. Coprono segni long/short, zero osservato, rate previste ignorate,
conflitti/assenze/futuro, mapping completo, quantità incoerenti, tampering,
replay fra processi, morte pre/post-commit, SQLite FULL e limiti dei percorsi.
Non sono review indipendente QA/Security né prova di ordini KuCoin ammissibili.
Il probe separato confronta ciascuno dei 168 eventi con l'inventario congelato,
ricostruisce le quantità dai fill e verifica digest di tutte le tabelle originali.

Evidenze e comandi riproducibili:
`audit-evidence/v13-funding-reconciler-20260928T140804Z/`, in particolare
`unit-tests-final-command.json`, `unit-tests-final-output.txt`,
`probe-command.json`, `probe-result.json`, `candidate-receipt.json` e
`candidate-events.json`. I comandi usano solo l'immagine già in cache, senza
pull/rete, con fork RO; il probe scrive soltanto nella propria directory di evidenza.

Prossimo lavoro candidato: publisher/ricevute causali offline e test dedicati,
poi protective close sul writer unico e integrazione. Per applicare il funding
servono accettazione del metodo/qualità, quantità riconfermate sotto il writer
appropriato e cutoff aggiornato. Binding, identità/custodia, epoch, semantica
paper e quattro valori policy restano da decidere prima dell'attivazione.
`min_quantity` e `min_notional` restano **UNKNOWN** e bloccano soltanto nuove
aperture KuCoin-faithful. Nessuna soglia o criterio operativo mancante è attivato.
