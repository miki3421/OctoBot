# BTC intraday LONG + SHORT — runner e qualifica tecnica

**21 ottobre 2026 · TECHNICALLY QUALIFIED CANDIDATE, NOT ACTIVATED.**
Il runner bidirezionale e il confronto appaiato richiesti sono implementati
e verificati. Nessuna attivazione ufficiale, schedulazione, pagina UI nuova,
credenziale, grant o modifica ai conti/collector esistenti. T0/T1 operativi
restano null; la validità scientifica rimane UNASSESSED.

## Consegna

- Package isolato `octobot/ai_strategy_lab/intraday_pair/`, con controllo
  SHORT, candidata LONG+SHORT e due ledger stress indipendenti. Stesso capitale
  iniziale, input, calendario, regole di rischio e costi; nessun risultato ereditato.
- Esecuzione firmata: LONG BUY ask / SELL bid, SHORT SELL bid / BUY ask;
  stop e TP sul lato di uscita. Quote e rischio vengono rivalidati al fill;
  le quantità possono solo diminuire. Uscite latched e riduzioni parziali
  conservano il residuo senza inversione o aumento.
- Riconciliazione funding LONG-aware: include SELL protettivi al confine,
  usa il cashflow meno favorevole e conserva pending per rate discordanti
  o mark non disponibili. La chiusura amministrativa valida conto, scenario,
  position ID/generazione, quantità, nonce e TTL tramite file locale custodito.
- Fanout durevole: la stessa ricevuta alimenta tutti i bracci e ciascun
  cursore è salvato nella transazione di stato. Ripresa di consegne parziali
  senza duplicare fill; identità o stato mancanti non causano un reset.
- Valutazioni comuni al cutoff con stato già confermato e prezzi già
  disponibili; niente interpolazione, retrodatazione o riscrittura dei buchi.
  Export di fill, fee, funding, realizzato, posizioni e motivi degli slot.
- Valutatore dei criteri congelati: finestra di 90 giorni, attività minima,
  copertura, bootstrap settimanale appaiato e controllo di esposizione/funding
  irrisolti. Review reale prima di T1 negata; le fixture restano esplicitamente tali.
- Worker e gate manuale pronti: l'avvio richiede ricevuta root-owned esterna,
  T0 futuro e hash completi. Il runner non crea la propria approvazione.
  Il template consegnato contiene autorizzazione **false** e nessun T0/namespace.

Il [runbook tecnico](../docs/BTC_INTRADAY_PAIRED_RUNNER_V1.md) descrive
confini, ripresa e condizioni del successivo avvio. Il protocollo precedente
rimane immutabile; il nuovo bundle registra l'implementazione separatamente.

## Prove eseguite

**103 test passati**, tutti su fixture e namespace temporanei:

| Suite | Test |
| --- | ---: |
| Nuovo runner, fanout, valutatore e gate | 37 |
| Kernel candidato precedente | 19 |
| Conto SHORT di riferimento | 33 |
| Stress di riferimento | 10 |
| Continuazione di riferimento | 4 |

Il round trip E2E sintetico passa da 289 slot causali alla proposta LONG,
ingresso primario, ingresso stress ritardato e uscite separate. Il controllo
SHORT resta flat nell'episodio di rialzo. Nessun profitto della fixture
viene presentato come risultato scientifico o performance del nuovo conto.

Verificati anche:

- parità economica delle tracce SHORT sui casi di stop/TP e dei segnali
  ai confini numerici; utility ricevute/sorgenti identiche per AST al riferimento;
- guasto del journal input prima del fanout, arresto dopo il solo primo braccio,
  replay, conto mancante, identità mutata e blocco delle scritture dopo un guasto;
- crash reale di processo dopo commit di un LONG e prima dell'ack: posizione
  e fill conservati, integrity halt al riavvio, nessuna falsa posizione flat;
- quote mancanti, stop latched, chiusure parziali, funding firmato, confini
  prima/dopo settlement, rate discordanti e mark tardivi;
- comando root, replay, generazione/conto/scenario errati e documenti insicuri;
- prezzi/stato successivi al cutoff esclusi dalla valutazione passata;
- valutatore deterministico con casi positivi, negativi, insufficienti e review anticipata negata.

Durante la costruzione due fixture hanno richiesto correzione: una quotazione
oltre il limite di freschezza e un calendario funding diventato vecchio prima
dell'ingresso. Il runner li ha rifiutati; sono stati aggiornati gli input del
test, **non le soglie**. I log intermedi sono conservati con quelli finali.

## Prova tecnica sulle fonti pubbliche già raccolte

Eseguito probe locale di **15 secondi**, senza nuove GET o collector. I file
market e SQLite scalping sono stati aperti in sola lettura; soltanto un nuovo
namespace privato di evidenze ha ricevuto scritture. T0 futuro e gate prestart
impediscono che questa prova diventi un conto operativo.

L'ultima prova ha persistito **73 input** (1 market, 15 batch book e 57 heartbeat)
con gli stessi cursori/hash in tutti i quattro bracci, **zero fill e posizioni flat**.
Tra 151 righe book, 134 erano disponibili entro un secondo; 17 oltre tale
limite. Latenza di disponibilità osservata: 47,998–1250,743 ms. Non tutte le
righe catturate sono quindi utilizzabili come nuovo fill tempestivo: i gate
restano stretti. Una prima prova separata è anch'essa conservata nelle evidenze.

I sei SQLite privati della prova (quattro ledger, input e witness) hanno dato
`integrity_check = ok` **dopo la chiusura**, senza scansioni sui journal live.
Questa verifica prova compatibilità e fanout nel periodo osservato, non
copertura futura per 90 giorni, readiness dopo il warm-up completo o efficacia
predittiva. Il confronto reale dovrà registrare anche rifiuti e dati mancanti.

## Immutabilità e impatti

Il [bundle del runner](../docs/research-protocols/btc-intraday-paired-runner-bundle-v1.json)
fissa codice, protocollo e prove. SHA-256:
`92a5b4d1c23e2373ce7ce3e858e01c8646a3c3797d7021e4bdd409da3f38dc31`.
Il [template di attivazione](../docs/research-protocols/btc-intraday-pair-activation-template-v1.json)
è inerte e non è stato installato in un percorso operativo.

Base `22a99eb5d5d09da4ac3e14ec6d9595f4446f8159`, branch
`codex/btc-intraday-paired-runner-20261021`, repository canonico unico.
Nessun worktree aggiuntivo o merge a main. Il lavoro locale estraneo è preservato.
Hash del runtime attuale, Compose e precedente candidato invariati;
dieci container healthy con ID, immagini, avvii e contatori di riavvio identici.
Il percorso KuCoin-faithful resta bloccato: `min_quantity` e `min_notional`
UNKNOWN; nessun indebolimento di P0-03 o uso di zero.

Evidenze: `audit-evidence/btc-intraday-ls-runner-20261021/` nel workspace,
incluse prove intermedie, log finali, copie private e confronto runtime.
Sono verifiche dell'autore SINGLE_AGENT, non QA indipendente.

## Schedine e seguito

| Lavoro | Scheda | Stato |
| --- | --- | --- |
| Runner bidirezionale | `work-card-ef8cf6f2-4590-4d0a-b1b0-3fa5aeb1feb5` | Test, candidato consegnato |
| Qualifica appaiata | `work-card-02a20e84-2032-4edb-8cab-a1d1f5e3814d` | Test, evidenze disponibili |
| Prove di guasto e parità | `work-card-dd7f7332-15fb-4972-a573-957d82732948` | Verificate |
| Bundle e consegna | `work-card-2edc53af-5218-4191-99e4-826bb929beac` | Documentata |
| Avvio e UI | `work-card-8fd80afc-9599-40ca-abf9-68d2d2d082a9` | To-do |

Il seguito è la consegna operativa separata: approvare e custodire la ricevuta
esatta, predisporre soltanto il nuovo namespace e servizio, inizializzare i
due conti con stesso T0, collegare proiezioni, UI e monitoraggio e verificare
l'avvio. Nessun esperimento esistente deve essere modificato o riazzerato.
