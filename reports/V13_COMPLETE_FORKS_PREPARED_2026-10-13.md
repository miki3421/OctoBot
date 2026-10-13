# V13 — copia completa e due biforcazioni preparate

13 ottobre 2026. Richiesta: clonare il conto esistente e conservare lo storico; applicare le varianti solo dopo la biforcazione. V13 originale invariata.

## Copia consegnata

Snapshot economico coerente: **13 ottobre 2026, 16:55:36 Europe/Rome** (14:55:36 UTC).

| Stato iniziale comune | Valore |
|---|---:|
| Equity virtuale | 9.964,760357 USDT |
| P/L realizzato | +102,738110 USDT |
| P/L aperto | -124,719580 USDT |
| Fee cumulative | 3,836385 USDT |
| Funding cumulativo stimato | -9,421788 USDT |
| Posizioni aperte | 18 |
| Fill nello storico | 164 |
| Punti equity | 19.979 |
| Mark registrati | 359.474 |
| Eventi funding | 889 |

Conservate tutte le 11 tabelle, incluso stato completo, ingressi medi, quantità, generazioni delle posizioni, cursori funding, claim storici, migrazione, intenti ed eventi research. Lo storico precedente è comune e consultabile; non sarà attribuito come performance delle varianti.

Tre file indipendenti e identici byte per byte: snapshot genitore, copia FAST e copia HALF. SHA-256 comune:
`ca4acd534434c32fadfff3c548c6cb8bfab796ad091ec7b2a5612b54ca644bbc`.

Directory: `octobot-local/v13-prospective-forks/clone-v2-20261013/`.
- `parent-snapshot.sqlite`: copia genitore sigillata, da conservare.
- `fast/execution.sqlite`: storico e conto completi per protezione rapida.
- `half/execution.sqlite`: storico e conto completi per esposizione ridotta.
- `fast/branch.json` e `half/branch.json`: identità distinte, enabled=false, nessun collegamento all'executor o grant operativo.
- `fork-manifest.json`: timestamp, identità, conteggi e hash logici di tutte le tabelle.

Audit autorizzazioni conservato separatamente come documento, con backup SQLite e hash. È acquisito in un secondo istante, non fa parte dell'istantanea economica multi-database e non costituisce autorità riutilizzabile. I dataset raw esterni restano negli archivi originali, non duplicati integralmente: la copia completa riguarda il conto e tutte le tabelle del suo ledger, non l'intero laboratorio.

## Protezioni e biforcazione

High-water ereditato: 10.198,414846 USDT; daily_start 9.923,876507, un ingresso giornaliero già consumato, ultimo aumento 13 ottobre 00:12:05 UTC. Tutti i valori sono identici nelle copie: nessun reset dei limiti.

Le identità storiche delle posizioni restano conservate. Prima di future scritture, il runner dovrà usare il namespace specifico della biforcazione; non potrà utilizzare claim storici come autorizzazioni. Nessuna modifica ai database sigillati è stata necessaria per assegnare le identità esterne dei due conti.

Protocollo **v2**: sostituisce l'inizializzazione flat della v1, che rimane conservata. Inizio economico al punto della copia; finestra fissa di 90 giorni fino all'11 gennaio 2027 ore 14:55:36 UTC. Il primo slot operativo della variante rimane da qualificare e sigillare nel futuro. Nessuna operazione retrodatata: fino ad allora le quantità clonate restano detenute e il runner dovrà contabilizzare movimenti mark e funding successivi alla copia. Gli slot non elaborati saranno mancanti, non riempiti con decisioni inventate.

Il primo adeguamento ai target FAST/HALF paga i normali costi simulati e rispetta i limiti ereditati. Regole di protezione e pareggiamento del rischio della versione precedente invariate.

## Verifiche e stato

Backup online tramite connessione SQLite read-only e singola transazione coerente; nessuna copia grezza di database live e WAL. Hash logici e conteggi sorgente/snapshot confrontati nella stessa lettura. Integrity_check su genitore e due copie: OK. Posizioni riconciliate con tutti i fill; equity ricostruita da capitale, realizzi, mark, fee e funding coincide con l'ultimo punto storico entro 0,000001 USDT. Intero payload state identico nelle tre copie; inode distinti, nessun hard link.

Test sintetico: originali invariati, copia integrale dello storico e risk state, file indipendenti e rifiuto di sovrascrivere una destinazione esistente. I sette container del laboratorio risultano healthy, con uptime preesistente; nessun riavvio.

**Stato: copie complete e biforcazioni preparate, non in esecuzione.** Nessun nuovo servizio o simulatore attivato. Per raccogliere performance dopo la copia manca il runner isolato e il collaudo già nelle schedine To-do, aggiornati alla v2. La V13 originale continua normalmente.

Schede: copia `work-card-6c3d36d8-0f82-42f5-af08-e23eee49dc41`; protocollo `work-card-5fb8e181-a915-4189-b91b-1f0d81fe8a94`; verifica `work-card-af85df3f-1489-41a8-8b80-a598e4b31dfb`. Evidenze: `audit-evidence/v13-forks-v2-20261013/`. Nessuna qualifica scientifica o approvazione al trading reale.
