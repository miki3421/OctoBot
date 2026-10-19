# BTC intraday: diagnosi del messaggio sul book

19 ottobre 2026 — verifica completata e presentazione UI corretta.

## Causa e impatto verificato

Il motore riceve e accetta book freschi, ma il campo `state.reason` può
conservare `PRICE_MISSING` da un controllo precedente. Nella coda di `tick`,
quando non esistono posizione o intenti, `veto or s['reason']` mantiene il
vecchio motivo se il nuovo controllo non restituisce un veto. L’età mostrata
riguarda l’ultimo book accettato, mentre il motivo può essere precedente.

Una copia SQLite coerente offline dimostra 727 aggiornamenti del book
accettato, in 1.200 eventi recenti, con il motivo ancora PRICE_MISSING; esempi
con età 0,055–0,116 secondi. Non è soltanto una deduzione dall’età mostrata:
`last_book_ns` cambia nel ramo eseguito soltanto quando `fresh` è soddisfatto.
Entrambi i ledger offline superano `PRAGMA integrity_check`.

Nello snapshot risultano 378 slot post-T0: 205 di warm-up/input incompleto e
173 con finestra completa, tutti `NO_SIGNAL`. Nessuno dei 173 ha insieme BTC
≤ −1% nell’ora e almeno 12/18 simboli in calo. Zero fill e saldo 10.000 USDT
sono coerenti con questi esiti; non emergono opportunità ammesse e ignorate
in tali slot. Il controllo non ricostruisce retroattivamente segnali durante
il warm-up e non prova redditività futura o che ogni eventuale ingresso
supererebbe gli altri gate.

## Correzione e limite

Modificati soltanto template e JavaScript della pagina `/btc_intraday`.
L’attività e l’orario dell’ultimo slot sono distinti dal motivo memorizzato,
conservato nei dettagli diagnostici. Un book vecchio o non verificabile,
proiezione scaduta, rischio, pending o SHORT aperto restano espliciti.
Una sola età recente non viene presentata come autorizzazione di ingresso.

Il runner congelato mantiene il proprio campo diagnostico originale: non è
stato modificato, aggiornato o riavviato. Protocollo, ricevute, ledger, policy,
soglie di un secondo, condizioni M1 e minimi contrattuali restano invariati.
Il limite diagnostico del campo reason resta documentato; l’UI non lo tratta
più automaticamente come una descrizione esclusiva dello stato corrente.

## Consegna

16 gruppi browser in anteprima e smoke live desktop/mobile superati, senza
errori JavaScript o overflow. Verifiche interne dell’autore, non QA indipendente.
Asset HTTP 200, MIME JavaScript e digest verificati su localhost e 127.0.0.1.
Container intraday healthy con identità, avvio e contatore restart invariati.
Candidato UI `760f76c7be58c84efa5fed1cb680a95dafbc0ad2`.
JavaScript SHA-256
`4742805d395183e1a9564fd3fc08ebc2a677eb06a90d6d064b3db8ab143946fd`.
Nessun collector, grant, credenziale exchange o ordine reale coinvolto.

Evidenze e copie SQLite conservate in
`audit-evidence/intraday-book-check-20261019/` alla radice del laboratorio.
Rollback ai due asset del commit `b1480e07b5c136568e34f806b83c5a6e105e6546`.

Schedine Development:

- Diagnosi: `work-card-08d52224-b45f-4248-a96f-75c53568f508`.
- UI: `work-card-dedbb563-b43c-4004-9c87-cf87f6adbd77`.
- Test: `work-card-85c7c526-1edc-4fa9-af2d-884bdae36f0e`.
- Consegna: `work-card-76c0ed85-758c-488a-a954-8d175b82988c`.

SINGLE_AGENT, MMTech baseline, stream esclusivo Development. Tempo attivo
non riportato perché non misurato separatamente dalle attese. Nessuna
ricostruzione temporale inventata; nessuna attività residua per la verifica
richiesta e la correzione della presentazione.
