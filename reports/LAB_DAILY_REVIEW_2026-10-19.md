# Trading AI Lab — controllo e analisi del 19 ottobre 2026

Rilevazioni principali 08:20–08:25 UTC, 10:20–10:25 italiane. Solo letture,
copie SQLite coerenti e analisi; nessuna modifica a strategie, servizi, policy,
ledger o scheduler. Esecuzione SINGLE_AGENT, senza review indipendente.

**Esito: conti aggiornati e dieci container attivi healthy, ma monitor automatico
fermo e due ribilanciamenti M1 paper mancati.** La riduzione del rischio ha
contenuto le perdite; non emerge un vantaggio di FAST rispetto a HALF. BTC
intraday è pronto a osservare opportunità, ma non ne ha ancora ammesse.

## 1. Conti paper e confronto corretto

Valori virtuali della proiezione comparativa, circa 08:20 UTC. Il confronto di
Originale/FAST/HALF parte dalla copia comune del 13 ottobre, 14:55:36 UTC,
con 9.964,760357 USDT. M1 è stato copiato il 17 ottobre, 09:09:06 UTC, con
9.907,300220 USDT. BTC intraday è indipendente, senza storico ereditato.

| Conto | Equity USDT | Variazione dalla propria copia/avvio | Fill nuovi | Esposizione lorda attuale |
| --- | ---: | ---: | ---: | ---: |
| V13 originale | 9.905,12 | −59,64 (−0,598%) | 49 | 20,22% |
| FAST | 9.931,84 | −32,92 (−0,330%) | 53 | 6,58% |
| HALF | 9.936,36 | −28,41 (−0,285%) | 72 | 7,24% |
| V13 + M1 SHORT | 9.904,22 | −3,08 (−0,031%) | 0 | 19,98% |
| BTC intraday | 10.000,00 | 0,00 (0,000%) | 0 | 0,00% |

I fill ereditati sono 164 per FAST/HALF e 199 per M1: non sono nuovi trade
delle varianti. La differente data iniziale di M1 impedisce di confrontare
direttamente le variazioni della terza colonna con quelle del 13 ottobre.

Nella finestra comune dei quattro V13 dal 17 ottobre, 09:15 UTC, le variazioni
descritte dalla proiezione sono: Originale −0,029%, FAST −0,044%, HALF −0,018%,
M1 −0,038%. Non è un confronto a rischio costante né una prova statistica.
Le valorizzazioni hanno clock distinti: nell'ultimo giorno la proiezione
dell'Originale usa osservazioni da circa 19 secondi successive a circa 89
secondi precedenti al timestamp della griglia comparativa. Le differenze
minime non vanno interpretate come vantaggi del segnale.

**FAST/HALF.** Dalla copia, FAST contiene la perdita di circa 26,72 USDT e HALF
di 31,23 rispetto all'Originale; HALF precede FAST di 4,51 USDT. Drawdown
osservato dalla copia: Originale 1,772%, FAST 0,786%, HALF 0,781%.
Le commissioni nuove sono rispettivamente 0,46 / 0,96 / 0,95 USDT; funding
stimato −1,57 / −0,65 / −0,75. Il vantaggio osservato delle due varianti è
compatibile con la minore esposizione, non dimostra capacità di anticipazione.

I sei ribilanciamenti FAST/HALF sono tutti EXECUTED, ma tre superano la
tolleranza del 2% sullo scarto relativo di volatilità dell'allocazione dopo
gli arrotondamenti: 15 ottobre 7,38%, 16 ottobre 2,78%, 18 ottobre 6,33%.
Il 19 ottobre lo scarto è 1,80%, entro tolleranza. Non sono punti percentuali
di perdita. Prima di conclusioni sul filtro serve qualificare questo limite
del controllo di rischio appaiato; non alzare la tolleranza per farlo passare.

## 2. V13 originale: recupero giornaliero, settimana ancora negativa

Snapshot analitico autonomo delle 08:21:42 UTC: equity **9.905,32 USDT**,
risultato dall'attivazione **−94,68 USDT (−0,947%)**. La differenza di 0,19 USDT
rispetto alla tabella dipende dal diverso istante di valorizzazione.

| Periodo | Variazione netta | Rendimento | Drawdown osservato |
| --- | ---: | ---: | ---: |
| Ultime 24 ore | +25,15 USDT | +0,255% | 0,962% |
| Ultimi 7 giorni | −148,38 USDT | −1,476% | 2,592% |
| Storico disponibile dal 21 settembre | −94,68 USDT | −0,947% | 3,887% |

Le finestre 24h/7d sono complete secondo il monitor delle osservazioni;
lo storico intero conserva un'interruzione di circa 7,34 giorni. Il drawdown
storico è quindi quello osservato, non la garanzia del massimo effettivo.
Massimo registrato 10.198,41 USDT il 29 settembre; minimo 9.802,03 il
18 ottobre. Dal massimo il conto ha restituito circa 293,10 USDT al momento
dello snapshot. Un giorno positivo non prova l'inversione del regime.

Riconciliazione: **+76,94 realizzato −156,33 aperto −4,29 commissioni −10,99
funding stimato = −94,68 USDT**. Il realizzato positivo non protegge dalle
perdite delle posizioni ancora aperte. Importi esposti arrotondati;
riconciliazione verificata prima dell'arrotondamento. Prima di commissioni/funding il prezzo
contribuisce −79,40 USDT: i costi incidono per 15,29 USDT, circa il 16% della
perdita netta, e non ne spiegano la parte principale. Lo slippage è già nei
prezzi dei fill; non si sottrae una seconda volta.

| Contributi positivi netti dall'attivazione | USDT | Contributi negativi principali | USDT |
| --- | ---: | --- | ---: |
| NEAR | +39,30 | HBAR | −54,45 |
| LINK | +23,80 | LTC | −23,39 |
| AAVE | +18,42 | ZEC | −21,24 |
| XLM | +12,23 | ETH | −18,15 |
| ATOM | +5,61 | XRP | −15,20 |

Cinque simboli positivi generano +99,36 USDT; tredici negativi −194,04.
HBAR/LTC/ZEC spiegano circa il 51% dei contributi negativi lordi. Questi sono
contributi in USDT, non rendimenti normalizzati per capitale investito o
tempo di esposizione: non bastano per dichiarare una coin inadatta in ogni
regime o sostituirla retroattivamente con una vincente.

**Riacquisti.** Dal 12 ottobre: 53 BUY per 435,48 USDT e 18 SELL per 471,80.
Su HBAR i quattro riacquisti del 13/14/15/17 ottobre ammontano a soli
23,38 USDT; il 18 ottobre è avvenuta una riduzione di 30 HBAR. Il fenomeno
esiste, ma il risultato negativo dell'intera posizione non si può attribuire
interamente a questi piccoli ribilanciamenti: pesa anche l'esposizione
precedente. SELL non implica SHORT; tutte le posizioni attuali dei quattro
conti V13 sono long o flat.

La perdita dal massimo osservata rimane sotto il limite di drawdown del 10%:
non ci si deve aspettare che quel limite emergenziale realizzi automaticamente
i profitti o cambi direzione. Le protezioni veloci e gli SHORT sono ipotesi
distinte già in osservazione, non una funzione che manca al semplice calcolo
del P/L.

## 3. M1 paper e BTC intraday: due diagnosi diverse

**V13 + M1 SHORT:** zero episodi e zero fill dopo la copia. I 566 slot M1
registrati nel conto risultano NO_SIGNAL: l'assenza di SHORT non dimostra un
errore del filtro. Esiste però un errore operativo distinto: i DAILY del
18 e 19 ottobre sono entrambi MISSED, motivo `execution_window_expired`.
La baseline scientifica è disponibile fino al 18 ottobre e il runner continua
a valorizzare le posizioni; healthy/OBSERVING non dimostra che ribilanci.

L'esame del codice mostra che l'intento deve attendere un'acquisizione
iniziata dopo la propria creazione e completare entro 120 secondi dallo slot.
La combinazione fra cadenza, derivazione e deadline è una pista da riprodurre,
non una causa definitivamente isolata da questo check. Non sono conservati
qui tutti gli istanti intermedi dell'intento ormai scaduto. Nessun recupero
retroattivo, allargamento della finestra o modifica della causalità eseguiti.
Finché il problema non è corretto, la differenza rispetto all'Originale non
misura soltanto l'effetto degli SHORT e va qualificata nel confronto.

**BTC intraday:** primario e stress indipendente a 10.000 USDT, flat, zero
commissioni/funding/operazioni; contabilità corrente completa, nessun halt
di integrità o rischio. Proiezione fresca, book accettato circa 0,17 secondi
prima dello snapshot e mark circa 19 secondi prima. La freshness riportata
non sostituisce la verifica al momento di un futuro ingresso.

Dal ledger copiato: 83 slot di riscaldamento pre-avvio; dopo il T0 del
18 ottobre, 00:00 UTC, 205 WARMUP_OR_MISSING_INPUT e **184 NO_SIGNAL validi**.
La prima finestra completa è del 18 ottobre, 17:05 UTC; ultima analizzata
19 ottobre, 08:20 UTC. In quelle 184 finestre BTC nell'ora varia fra
**−0,505% e +0,827%**: zero raggiungimenti di −1%. La condizione di ampiezza
(almeno 12/18 simboli in calo) compare 51 volte, ma mai insieme alla soglia BTC.
Zero segnali congiunti, quindi zero opportunità di ingresso ammesse.

Il vecchio campo interno `PRICE_MISSING` è ancora presente pur dopo book
freschi; la precedente diagnosi e la UI già distinguono questo motivo
conservato dall'ultimo esito dello slot. Non è evidenza che tutti i 184 slot
siano stati bloccati dal book. Zero fill significa anche **esecuzione reale
del primo episodio non ancora osservata**, non strategia già validata.
Non abbassare la soglia per ottenere artificialmente attività.

## 4. Resto del laboratorio, dati e risorse

- **Runtime:** dieci container attivi healthy, nessun OOM registrato. Intraday
  conserva un riavvio nel contatore e avvio del 18 ottobre, 02:53 UTC; nessun
  riavvio eseguito oggi. I quattro container legacy exited non sono outage
  nuovi e non sono stati riattivati.
- **Persistenza:** integrity_check OK su sei backup SQLite coerenti: Originale,
  approvals, journal appaiato FAST/HALF, M1 paper, intraday primario e stress.
  È una verifica strutturale, non un audit completo delle catene crittografiche.
  Nessuna scansione profonda del grande database scalping operativo.
- **Funding:** nessun debito o gap corrente nelle varianti. Restano tre
  osservazioni storiche incomplete FAST/HALF e una M1 con funding AAVE
  temporaneamente incompleto. Non cancellate né trasformate in costo zero.
- **Market observer:** 19 simboli, 2.687 record archiviati, ultimo successo
  08:15:59 UTC, coerente con la cadenza di 15 minuti. Scalping connesso,
  circa 28,14 GB decimali di database, book/trade freschi e latenza intorno
  a 129/125 ms. Nessun ordine o credenziale exchange nei collector.
- **BTC 30/120:** 19/19 slot, zero missing/conflitti, 19 LONG; integrità OK,
  timer attivi. I 18 outcome maturi restano sigillati. Review preregistrata
  31 marzo 2027, 00:10 UTC: non è un conto paper operativo.
- **Osservazione M1:** 964/964 slot dovuti validi, nessuna issue; un episodio
  del 16 ottobre con entrambe le catture conservate. Precede l'avvio del
  conto M1 paper e non deve comparirvi come trade retroattivo. Performance
  sigillata; termine osservazione 14 gennaio 2027, 00:00 UTC.
- **Qwen BTC shadow:** sospeso intenzionalmente dal 9 ottobre, scheduler
  disabilitato; 7 coppie conservate su 17 slot di calendario ormai dovuti.
  ATTENTION e giorni mancanti sono coerenti con la sospensione. Non riavviato,
  non confuso con il diverso rapporto descrittivo V13 giornaliero.
- **Qwen analista V13:** rapporto odierno accettato alle 06:01 UTC, circa
  61 secondi di elaborazione. Problema qualitativo: il testo dice che NEAR e
  LINK sono gli «unici contributi positivi netti», mentre le sue stesse
  evidenze riportano cinque simboli positivi. Accettazione tecnica del testo
  non equivale a correttezza di tutte le conclusioni. Nessuna nuova inferenza.
- **A/B/C selezione settimanale:** conti ancora non avviati. Cutoff del
  16 ottobre superato: il journal di raccolta contiene 406 daily e 406 funding
  validi; 38.918 book validi e 58 mancanti. Il controllo di raccolta ha zero
  failure ma non contiene un PASS finale. L'osservatore funding separato
  prosegue: 89.899 ricevute valid, una invalid storica, 29 simboli, nessun
  controllo di blocco. Questi conteggi non certificano la copertura di tutti
  i settlement/mark. La pagina A/B/C è ancora un checkpoint statico dell'8
  ottobre: va aggiornata dopo la valutazione, non interpretata come monitor live.
- **Dischi:** root circa 18 GiB liberi, 85% occupato; disco laboratorio circa
  439 GiB liberi, 43% occupato. Non è imminente l'esaurimento del disco del
  lab, ma la root richiede sorveglianza. Nessuna cancellazione effettuata.
- **Memoria:** circa 24 GiB disponibili; swap occupato circa 15 GiB su 24.
  Un campione breve mostra attività di swap-out, quello successivo di otto
  secondi zero swap-out e circa 115 KiB/s swap-in; PSI memoria medio zero.
  Non dimostrano thrashing sostenuto né garantiscono assenza di picchi.
  Le quattro VM controller/compute restano spente; altre due VM di laboratorio
  OPS sono accese, fuori dallo scope di modifica. Il backend Qwen conserva
  circa 20 GiB RSS. Nessuna variazione a VM, swap o modello.

## 5. Problema prioritario del monitor e backlog

Il monitor automatico fallisce **prima di avviare il programma** per mismatch
del checksum della configurazione. Ultimo status valido 17 ottobre,
17:05:06 UTC; primo fallimento documentato 17:10. Il codice del monitor
supera il checksum; la configurazione corrente non coincide con il manifest
del servizio. La configurazione include intraday ma non il container M1 paper.

Il notificatore mail continua ogni cinque minuti e rifiuta correttamente
lo status vecchio come `MONITOR_UNAVAILABLE_OR_STALE`; i log odierni mostrano
un alert deduplicato. Non è prova di check sani del laboratorio: il monitor
non produce campioni nuovi. Nessuna mail di prova inviata. Ripristinare un
bundle revisionato e coerente, non rimuovere il controllo di integrità.

| Priorità | Lavoro e criterio di miglioramento | Schedina / stato |
| --- | --- | --- |
| 1 | Ripristinare monitor e manifest verificati; coprire M1 e freshness intraday; verificare almeno due cicli naturali e dedup | `work-card-7346c1df-a816-400a-9552-aa347aa60340` · To-do |
| 2 | Riprodurre i DAILY M1 scaduti; preservare causalità e limite temporale; rendere visibile il degrado del confronto | `work-card-6394a348-5342-449f-9e60-26106ea3847a` · To-do |
| 3 | Qualificare gli scarti di rischio FAST/HALF dopo gli arrotondamenti, prima di attribuire valore al filtro | `work-card-ca705a4d-4a76-4eb0-979d-205efa95738a` · To-do aggiornato |
| 4 | Calcolare la qualifica finale A/B/C su copia e riconciliare calendario/mark/funding; aggiornare il checkpoint UI | `work-card-23902a16-23d0-4275-9a71-e4d413319f96` · To-do aggiornato; funding su `work-card-507f0fdb-521e-48bc-a9bb-60d17ceeee9d` |
| 5 | Verificare le affermazioni Qwen contro tutte le evidenze, incluse esclusive come «unici»; non indebolire il validatore | `work-card-229b2029-a9df-4977-99d3-3dee408f57c5` · To-do |
| 6 | Qualificare le osservazioni storiche di funding incompleto senza riscriverle | `work-card-d0d545bc-4053-4f61-94c6-be7422b597b5` · To-do esistente |
| 7 | Continuare intraday e registrare il primo vero episodio; separare input, segnale, veto, esecuzione e stress; riesame a scadenza | `work-card-3d0610f3-0313-4788-8ea9-9585d99d1c28` · To-do del riesame, raccolta già attiva |

Non propongo un altro esperimento o cambiamenti ai segnali oggi: prima
rendere affidabili monitoraggio e conti esistenti, poi accumulare osservazioni
con regole stabili. La lista dei simboli perdenti è una diagnosi del periodo,
non una nuova selezione approvata.

Evidenze private conservate in `audit-evidence/lab-daily-20261019/`, fuori
dal commit: snapshot completi delle API pubbliche, stato container/servizi,
backup coerenti e schemi, riconciliazioni e risultati derivati. Report su
schedine `work-card-51f7f35d-7399-4061-b3f8-24173f66a91c` (check),
`work-card-0d4eb8b8-284b-4ade-8f3b-b5ac9daf6378` (analisi),
`work-card-f1bbb8db-38be-4de6-af21-a0373255725e` (consegna).

Restano simulazioni di ricerca: ordini reali disabilitati, nessuna promozione
scientifica. L'autorizzazione paper delle sorgenti di ricerca è distinta dal
vecchio profilo in quarantena. I minimi KuCoin reali restano UNKNOWN e il
percorso exchange-faithful resta BLOCKED; i risultati non ne provano
l'ammissibilità.
