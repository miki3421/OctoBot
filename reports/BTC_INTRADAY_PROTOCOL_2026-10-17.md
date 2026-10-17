# BTC intraday — protocollo candidato consegnato

17 ottobre 2026. Stato **CANDIDATE_NOT_APPROVED_NOT_ACTIVATED**.
La richiesta autorizza la definizione del protocollo; nessun avvio o rischio operativo configurato.

| Elemento | Proposta per il solo nuovo conto |
|---|---|
| Identità | `btc-intraday-m1-l5-paper-v1`; nuovo seed 10.000 USDT, conto flat |
| Segnale | Ogni 5 minuti: BTC a −1% o meno nell'ora, almeno 12/18 simboli in calo; solo SHORT BTC |
| Quantità | Minore tra 10% equity, budget stimato di stop e 10 unità native; massimo teorico 0,010 BTC nel contratto sintetico |
| Esecuzione | Slot successivo, latenza 500 ms; profondità completa per ingresso, nessun fill retrodatato |
| Frequenza | Un'opportunità ammessa per giorno UTC, inclusi tentativi poi respinti/mancati; cooldown sei ore |
| Uscite | Stop 1%, take profit 2%, sei ore dal fill; riduzioni protettive su book nuovi, residui sempre visibili |
| Rischio | Perdita giornaliera 2%, drawdown 10%, cap totale/BTC 10%; nessun reset al riavvio |
| Costi | Fee ipotizzata 6 bps + 1 bps avverso per fill, oltre VWAP/tick; stress esplicito separato |
| Funding | Tassi finali firmati, calendario osservato e mark causale precedente entro 60s; stima dichiarata, pending non zero |
| Verifica futura | T0 non impostato; 90 giorni, almeno 20 episodi/20 giorni/8 settimane, criteri congiuntivi e nessuna promozione automatica |

I numeri sono scelte di progetto candidate, non valori ottimizzati sulla redditività né approvazioni ereditate.
Il contratto sintetico assume 0,001 BTC per unità grezza, minimo quantità 0,001 BTC,
minimo nozionale 1 USDT e tick 0,1 USDT: è una simulazione, non evidenza di validità
KuCoin. I minimi reali restano **UNKNOWN**. La size viene sempre arrotondata verso zero.
L'osservazione puntuale dei metadata del 25 settembre non certifica le unità dell'intero archivio.

Il [tutorial funding KuCoin](https://www.kucoin.com/support/26695933047705) descrive il
mark al settlement effettivo; il nostro mark precedente è una stima esplicita.
Il candidato conserva l'incertezza ai confini temporali e usa il caso meno favorevole
per un'uscita vicina al settlement. Nessun credito o costo mancante viene inventato.

Conto nuovo non creato. Originale, FAST, HALF, M1 paper e osservazione M1 invariati.
Le vecchie famiglie L5 respinte non vengono riattivate. Un utile contro la cassa
non dimostrerebbe, da solo, abilità predittiva di M1 rispetto al mercato ribassista.

## Verifiche svolte

JSON, lineage e pin di provenienza verificati; 24 combinazioni sintetiche di equity/prezzo,
tre esempi di size e tre casi di segno funding coerenti. Non sono test del simulatore,
qualifica delle fonti future o validazione scientifica. Nessun nuovo outcome economico letto.
Nove container esistenti healthy, nessun avvio o riavvio impartito in questo incarico.

## Attività residue, tutte To-do

| Schedina | Lavoro | Dipendenza |
|---|---|---|
| `work-card-4cd8e105-25ad-418a-9d5e-41d86bfb9ff7` | Qualificare join causale 18 simboli + L5 + funding/mark | Protocollo consegnato |
| `work-card-f20d8837-a539-4394-859b-ba75b94ed3a8` | Implementare simulatore/account isolato e inerte | Qualifica fonti |
| `work-card-b8a049f7-cefc-4ef8-b393-07bb5ff45f70` | Prove su replay, riavvio, storage e casi avversi | Simulatore |
| `work-card-312947f2-47cd-44da-b475-b185e71c70a6` | Bundle esatto di riesame, monitoraggio/UI e decisione di eventuale avvio paper | QA e successiva autorizzazione specifica |

Protocollo dettagliato: `docs/BTC_INTRADAY_M1_L5_PROTOCOL_CANDIDATE_V1.md`.
Contratto: `docs/research-protocols/btc-intraday-m1-l5-paper-candidate-v1.json`.
Verifica documentale: `reports/BTC_INTRADAY_PROTOCOL_REVIEW_2026-10-17.json`.

Lineage del candidato: `8e407437e98bb464f9265f0bb7bf42a44b258716abe339e8b40fcfd91b78de04`.
SHA-256 file JSON: `b0374dfd26f4d556e22781d37113a78aea52dc84a1f7878d7e995b82a4ef933d`.
