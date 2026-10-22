# Coppia BTC intraday: continuazione I/O v2

Scheda principale `work-card-dd0a1084-730e-4e5c-9718-a9db566a3014`. Correzione autorizzata dall’utente il 22 ottobre 2026 per i tre riavvii automatici, conservando raccolta e strategie.

## Causa verificata

Alle 02:21:34, 06:15:43 e 06:53:44 UTC il processo interno del collector termina con `Level 5 book stale for 5.006 seconds`. Il suo supervisore riapre la connessione dopo cinque secondi. La chiusura dell’ultimo writer WAL elimina i file temporanei `-wal` e `-shm`; il database principale mantiene lo stesso inode. Il reader apre transazioni brevi in sola lettura, con UID differente e mount RO: nell’intervallo privo di sidecar SQLite non può creare l’indice condiviso e restituisce `SQLITE_CANTOPEN` (14). L’eccezione propagava fino al wrapper e Docker riavviava tutti i quattro bracci.

Riprodotto con SQLite 3.46.1 dell’immagine in uso, writer UID 1000 e reader UID 30943: stessa query e stesso errore quando il writer è chiuso; lettura corretta quando riapre. La prova completa del reader corretto, con sorgente montata RO, registra attesa e ripresa nello stesso processo, cursore da 1 a 2 e nessun avanzamento prima della consegna del batch. Il collector attivo non è stato modificato o interrotto per queste prove.

## Correzione circoscritta

Il nuovo adattatore esterno `btc_intraday_pair_io.py` riusa integralmente `intraday_pair.receipts.BookReader`. Gestisce esclusivamente errori SQLite di accesso/lock transitori CANTOPEN, BUSY e LOCKED, con un nuovo tentativo dopo 250 ms. Non dorme il runner: nel frattempo il fanout normale registra heartbeat, applica controlli e mantiene le eventuali uscite protettive. La ripresa conserva cursore e validazione; nessun backlog saltato durante l’attesa.

Restano bloccanti sostituzione del database, regressione di cursore o cronologia, backlog eccessivo, dati malformati, corruzione, I/O non classificato e guasti dello stato o delle ricevute. Nessun fallback `immutable`, accesso RW alla sorgente, aggiornamento artificiale dei timestamp o estensione dei limiti di freschezza. Un’interruzione lunga resta visibile nel monitor esistente. La prima identità del file viene conservata anche se l’apertura iniziale fallisce.

Gli episodi di attesa/ripresa vengono aggiunti a un file diagnostico privato distinto, `source-read-events.jsonl`, e lo stato I/O compare come campo supplementare della proiezione pubblica. Questo log non è una ricevuta causale e non autorizza operazioni. Non vengono cambiati monitor, notificatore o credenziali.

## Identità e attivazione

Il package qualificato `intraday_pair/`, incluso motore, reader originale, witness, protocollo e statistiche, resta identico per hash. Originale, FAST, HALF, M1 e intraday iniziale restano invariati.

La ricevuta di attivazione originale e il suo digest rimangono immutati nelle identità dei database esistenti. Il nuovo wrapper richiede una ricevuta root-owned di continuazione I/O separata, fissata al digest originale, al file di configurazione precedente e ai due nuovi file runtime. Verifica che percorsi, sorgenti e destinazioni siano gli stessi. Il comando initialize è vietato. Nuova ricevuta e codice non concedono ordini reali, credenziali exchange o grant operativi.

Il runtime v1 resta inalterato per rollback; la versione I/O viene installata in un percorso distinto. Si arresta soltanto il vecchio container della coppia, se ne conservano log e container fermo e si copia a freddo lo stato. Poi si avvia la nuova versione con gli stessi mount di stato e proiezione, senza inizializzazione. Tutti gli altri container continuano a operare. La copia fredda viene controllata separatamente: nessuna scansione di integrità dei database live di sorgente o conto.

## Verifica e rollback

14 test nuovi coprono ripresa, bootstrap, identità, errori non ammessi, preservazione di posizioni/cursori, heartbeat protettivi e vincoli della continuazione. Passano anche 10 regressioni di attivazione/proiezione e 37 del runner congelato. Le prove sono dell’autore; non costituiscono QA indipendente o validazione scientifica.

Dopo l’avvio: confrontare identità dei sei database, digest di attivazione, T0/T1, saldi, fill, griglia contigua, allineamento e avanzamento degli input; verificare UI e campione naturale del monitor. Il primo slot possibile rimane condizionato ai dati e al segnale; non recuperare slot mancati.

Per rollback arrestare soltanto la coppia I/O, conservarne container/log/configurazioni e rinominarla; ripristinare il nome e riavviare il precedente container fermo usando la ricevuta originale. I motori e i loro formati sono identici: non ripristinare i database dalla copia fredda e non perdere i record eventualmente aggiunti. Conservare il log diagnostico separato. Nessun riavvio degli altri servizi, reset, prune o cancellazione.
