# BTC intraday LONG + SHORT — preparazione consegnata

**21 ottobre 2026 · PREPARED, NOT ACTIVATED.** Il conto SHORT attuale e tutti
gli altri esperimenti restano invariati. Nessun nuovo servizio, conto, grant,
download pubblico, osservazione ufficiale o ordine creato. T0/T1 restano null.
La validità scientifica della nuova ipotesi resta UNASSESSED.

## Risultato

Preparati [protocollo leggibile](../docs/BTC_INTRADAY_LONG_SHORT_COMPARISON_CANDIDATE_V1.md),
[contratto numerico](../docs/research-protocols/btc-intraday-long-short-comparison-candidate-v1.json),
kernel offline e fixture sintetiche. Il candidato aggiunge LONG quando BTC
sale almeno dell'1% nell'ora e almeno 12 dei 18 simboli sono in rialzo;
lo SHORT conserva la condizione speculare già definita. Questa è un'ipotesi
fissata prima di dati futuri, non una conclusione sulla sua redditività.

Sizing, limiti e tariffa dei costi sono comuni: massimo 10% equity e 0,010 BTC,
budget stop 0,25%, stop prezzo 1%, take profit 2%, durata sei ore, perdita
giornaliera 2%, drawdown 10%, una posizione alla volta, nessun cap giornaliero
né cooldown. Fee 6 bps e slippage avverso aggiuntivo 1 bps per fill; spread,
profondità e arrotondamento restano costi. Stress: latenza 1s e fee/slippage
doppi con ledger futuro indipendente per braccio. Tutti questi valori sono
**candidati inerti**, non policy installate sul nuovo conto.

Per il LONG: BUY ask, SELL bid, stop/TP sul bid. Il funding è firmato e non
diventa automaticamente un credito: con tasso positivo il LONG paga.
Il futuro adattamento deve includere SELL protettivi LONG nella riconciliazione
al settlement: l'attuale filtro sui fill positivi è specifico delle chiusure SHORT.

Confronto proposto su due bracci nuovi flat a 10.000 USDT, SHORT-control e
LONG+SHORT, con stesso T0 futuro e 90 giorni, stesse ricevute e costi, stato
indipendente. Il conto attuale è contesto leggibile sullo stesso intervallo;
non può diventare un controllo flat con la sola normalizzazione della curva.
Non si eredita PnL dal 17 ottobre né si cambia la scadenza dell'esperimento attuale.
La diversa esposizione e gli SHORT soppressi durante un LONG fanno parte del
confronto: non si promette parità di rischio realizzato.

## Prove e limiti

**66 test passati:** 19 sul nuovo candidato; 33 sul conto di riferimento,
10 sullo stress e 4 sulla continuazione. Le suite usano fixture/DB temporanei,
senza interrogare ledger live o outcome scientifici sigillati.

- Causalità, finestra completa, dati mancanti, tardivi, non finiti, deadline
  e identità stabile dopo aggiunta di dati futuri o modifiche non-feature.
- Otto casi di pricing BUY/SELL, stress, profondità insufficiente e uscita
  parziale confrontati con fixture generate dalle funzioni pure del runner
  attuale, fissato per hash; sei casi di sizing con lo stesso riferimento.
- Costi avversi su entrambi i lati, stop/tempo/TP, segno funding e pending.
- Confronto descrittivo con stessa griglia completa e seed: punti mancanti,
  duplicati o equity provvisoria causano rifiuto; nessuna interpolazione.

Il kernel non contiene I/O, ledger, writer, rete o issuer. Le primitive
prezzo/funding non validano la custodia delle ricevute né un intero episodio:
persistenza, stop latched, restart/storage, funding LONG-aware, stress completo
e amministrazione devono ancora essere implementati e qualificati nel runner.
Non è un E2E né una simulazione di redditività. Il controllo completo deve
dimostrare parità delle tracce SHORT, anche ai confini float/Decimal.

Il bootstrap e il classificatore di fine finestra sono definiti nel protocollo
ma non implementati. Le soglie numeriche sono proposte da congelare prima
del futuro T0; osservazioni correnti non sono un holdout nuovo.
Le vere quantità/nozionali minime KuCoin restano UNKNOWN, P0-03 invariato;
le fixture provano soltanto la preparazione della simulazione sintetica.
Verifiche dell'autore SINGLE_AGENT, non QA indipendente.

## Artefatti e custodia

Il [manifest del pacchetto](../docs/research-protocols/btc-intraday-long-short-preparation-bundle-v1.json)
fissa gli hash dei cinque artefatti e la base sorgente
`e0caa394ad76750f83949a04380b43b510f5104b`.
SHA-256 del manifest:
`6e68b7e0e4b5e532a904d9c9c575379916fa6be7afe0195b342a59d2152606df`.
Riferimento: protocollo v2 `bbc19094ac23b8b13a0d82919802f2ede3787add5eda2e13f0f2d8489861493b`,
runner installato e sorgente `52e2d6843527c3ef1bdffc32ffef982a0e06adf7eea7fe8f1335f0480282e555`.
Nessun file precedente incluso nel pacchetto è riscritto.

Log delle prove e confronto runtime conservati in
`audit-evidence/btc-intraday-ls-preparation-20261021/` del workspace.
Dieci container healthy con ID, immagini, avvii e riavvii identici prima/dopo;
hash del runner installato, protocollo attuale e Compose invariati.
Solo nuovi artefatti nel repository canonico, nessun worktree aggiuntivo
o modifica delle autorizzazioni operative. Branch:
`codex/btc-intraday-long-short-prep-20261021`; nessun merge a main.

## Schedine e seguito

| Lavoro | Scheda | Stato della consegna |
| --- | --- | --- |
| Ricerca dei contratti | `work-card-9a9725b9-2d9e-4a17-9439-2c6a6f800aba` | Conclusa |
| Protocollo candidato | `work-card-ad19a378-b46b-4a4b-8c2b-09a70194a693` | Preparato, da revisionare |
| Kernel e pacchetto | `work-card-0188dd29-8711-461f-9248-0d2e8631bce2` | Test, preparazione offline |
| Prove | `work-card-da39b55e-3a1e-42e2-bf39-b0c89891ead1` | Concluse |
| Consegna | `work-card-9a12f574-23e8-4cc5-af59-ae0f8caaaccc` | Documentata |
| Runner bidirezionale isolato | `work-card-ef8cf6f2-4590-4d0a-b1b0-3fa5aeb1feb5` | To-do |
| Qualifica prospettica appaiata | `work-card-02a20e84-2032-4edb-8cab-a1d1f5e3814d` | To-do, dopo runner |
| Avvio e UI autorizzati | `work-card-8fd80afc-9599-40ca-abf9-68d2d2d082a9` | To-do, dopo qualifica e autorizzazione |

La preparazione richiesta è completa. Il passo implementativo successivo è il
runner LONG-aware isolato; l'avvio dei due bracci e la UI restano un incarico
successivo, subordinato a bundle qualificato e autorizzazione esplicita.
