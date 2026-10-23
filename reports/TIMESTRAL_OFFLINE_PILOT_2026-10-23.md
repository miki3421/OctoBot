# Timestral-5M: risultati della prova offline

Stato: **prova completata, senza promozione del modello**. Timestral-5M è eseguibile su questa CPU con risorse contenute, ma nella configurazione e nel periodo fissati non supera la previsione semplice del prezzo invariato. Non consiglio di collegarlo ora alle strategie attive. Conti e strategie restano invariati.

Schede Control Plane:

- Ricerca e protocollo: `work-card-00bd0cb1-c7c2-4f5e-a2ae-4eb79eedef95`.
- Adapter e valutatore: `work-card-54f64f8b-68bc-4183-892b-eb73d03165fa`.
- Esecuzione e risultati: `work-card-1e1f028d-adbc-4dc6-aadf-6aa7700b8408`.

## Risultati effettivi

3.740 previsioni effettive; 3.663 hanno un esito futuro osservabile entro il periodo. Le altre 77 hanno un esito mancante o oltre il termine e restano escluse dalle metriche, con denominatore esplicito. L'orizzonte è di sei ore e cinque minuti dallo slot.

| Metrica di previsione, stesso campione | Timestral-5M | Persistenza del prezzo |
| --- | ---: | ---: |
| Errore assoluto medio, bps di log-rendimento | 58,72 | 55,95 |
| Radice dell'errore quadratico medio, bps | 83,11 | 79,82 |
| Giorni con errore assoluto medio inferiore al riferimento | 3 su 14 | — |

L'errore assoluto di Timestral è **4,94% superiore** al riferimento. Il suo intervallo nominale all'80% copre il 75,24% degli esiti; ampiezza media 166,42 bps. Le finestre sono sovrapposte: non sono 3.663 osservazioni indipendenti e non viene dichiarata significatività statistica.

| Segnale sullo stesso sottoconto BTC ipotetico | Segnali grezzi | Episodi completati | Netto base USDT | Netto stress USDT |
| --- | ---: | ---: | ---: | ---: |
| Timestral, mediana prevista ≤ −1% | 0 | 0 | 0,00, nessuna operazione | 0,00, nessuna operazione |
| M1: BTC in calo e almeno 12/18 asset in calo | 46 | 6 | +5,27 | −3,82 |
| Semplice: solo BTC in calo dell'1% nell'ora | 46 | 6 | +5,27 | −3,82 |

M1 e la baseline semplice hanno vettori di segnale identici in questo campione. Quaranta segnali per metodo sono assorbiti dall'attesa fra episodi. Tutti i sei episodi ammessi hanno ingresso, uscita e funding verificabili; nessun episodio ammesso è censurato. Due dei sei sono positivi. Commissioni complessive: 6,82 USDT; funding ricevuto: 0,28 USDT. Il risultato netto diventa negativo con costi raddoppiati e non dimostra un vantaggio robusto.

La previsione mediana Timestral più negativa è −0,9691%, quindi non attraversa la soglia congelata del −1%. Lo zero economico significa assenza di operazioni, non una strategia vincente. La soglia rimane quella fissata prima della prova. Il confronto è uno studio di episodi a nozionale fisso, non il rendimento dei conti attivi.

## Confronto fissato prima dei risultati

Il protocollo `docs/research-protocols/timestral-btc-offline-pilot-v1.json`, identificato da `a7776028076c2a4838dcb0b5e14970abb7b12396763507ebfbd6c27ca4f92c81`, confronta tre segnali SHORT sullo stesso sottoconto BTC ipotetico: Timestral, il filtro M1 invariato e il semplice calo BTC dell'1% nell'ultima ora. La persistenza del prezzo è il riferimento per l'accuratezza delle previsioni.

Periodo fisso: 1–14 ottobre 2026 UTC, prima dell'osservazione prospettica M1. Sono usate finestre di 289 punti a cinque minuti, su BTC e sulla quota dei 18 asset in calo nell'ultima ora. Nessun dato successivo allo slot entra nelle caratteristiche. L'inferenza riceverà soltanto le caratteristiche, senza il file degli esiti futuri. Non è stato aperto il journal dell'osservazione M1 sigillata.

L'esecuzione ipotetica usa un nozionale fisso di 1.000 USDT, ritardo di cinque minuti, durata di sei ore, sei ore successive di attesa e al massimo un ingresso al giorno. Book L5 osservato, commissioni di 6 bps e slippage avverso di 2 bps per esecuzione; stress con costi raddoppiati. Funding e dati mancanti restano espliciti. Queste sono condizioni comuni dello studio, non cambiamenti ai conti intraday esistenti.

La conversione delle quantità del book è un contratto sintetico dichiarato: la corrispondenza storica con i contratti reali non è qualificata. I minimi reali restano UNKNOWN. Il confronto riguarda il segnale su BTC, non il rendimento del conto multiasset M1 attivo.

## Dati preparati e controlli

| Controllo | Esito |
| --- | --- |
| Slot decisionali previsti | 4.032 |
| Finestre causali utilizzabili | 3.740, pari al 92,76% |
| Finestre escluse per copertura insufficiente | 292 |
| Book acquisiti per la griglia di valutazione | 4.033 punti, di cui 5 mancanti |
| Eventi funding disponibili nell'estrazione | 49; copertura delle singole operazioni da verificare nella valutazione |
| Copia coerente del ledger Originale | Sola lettura, integrity check `ok` |
| Archivio scalping | Riutilizzata la copia storica qualificata e sigillata; nessuna seconda copia da 27,6 GB |
| Test sintetici mirati | 12 superati; non sono risultati Timestral |

I test verificano causalità, ricevute stale o future, profondità insufficiente, costi stress, funding mancante, soglie M1 e blocco dell'accesso al modello senza conferma di idoneità alla licenza. Un'uscita non eseguibile non genera un profitto inventato e sospende gli ingressi successivi di quel metodo. L'errore di previsione e i saldi netti sono stati ricalcolati con una verifica separata. Le funzioni di riferimento M1 sono incluse in `timestral_m1_reference_v1.py` e risultano identiche all'originale mediante confronto della struttura del codice; la consegna non dipende dai vecchi file locali non versionati.

Il controllo del primo campione singolo contro il relativo elemento del batch è passato. Hash di dati, pesi e codice ufficiale verificati. Il contenitore di inferenza è terminato con codice zero, senza esaurimento memoria, con rete disabilitata e montaggi in sola lettura salvo la directory degli output. I 13 container del laboratorio erano healthy e senza riavvii o sostituzioni al controllo conclusivo.

Le evidenze complete, le copie e gli hash sono conservati fuori Git in `audit-evidence/timestral-offline-20261023/`. Pesi e dati grezzi non vengono aggiunti al repository.

## Modello, risorse e licenza

Download ufficiali autorizzati dall'operatore; nessuna installazione di pacchetti o immagine aggiuntiva.

- Modello: `mistralai/Timestral-5M`, revisione `bdd20cfc15a3fea0e4cb5ccef37f8d3ca7aa335f`, pesi 20.843.960 byte, SHA-256 `7ace108c4987e7f2a99a75a445240019d1d31c2117139d1bd05ffdfd25aca738`.
- Codice ufficiale: `mistralai/timestral`, commit `a534bdbd244d64f3d9d743f46c7bf6fc330ed4ff`.
- Ambiente CPU già presente: immagine `octobot-timesfm3-research:3.0.1-cpu`, ID `sha256:9740b81318ed12f8ddd67de2464797bf96c1e85708e58dbe771c89fe4fac6a99`.
- Esecuzione senza rete, filesystem di base in sola lettura, massimo quattro CPU e 4 GiB. **17,48 secondi** complessivi per 3.740 previsioni, incluso il caricamento; picco RSS **320,06 MiB**. Batch da 16: mediana 73 ms. Modello: 5.208.960 parametri. Qwen non è stato arrestato; nessun pacchetto o immagine aggiuntivi sono stati scaricati.

La [licenza dei pesi alla revisione fissata](https://huggingface.co/mistralai/Timestral-5M/blob/bdd20cfc15a3fea0e4cb5ccef37f8d3ca7aa335f/LICENSE) è Modified MIT con requisito sui ricavi mensili consolidati e alternativa commerciale. L'operatore ha confermato l'idoneità prima dell'inferenza. La ricevuta è conservata privatamente fuori Git; la pipeline l'ha verificata prima del caricamento dei pesi.

## Consegna e raccomandazione

La prova richiesta è conclusa. Aggregati, conteggi e hash degli output sono in `reports/TIMESTRAL_OFFLINE_PILOT_2026-10-23.json`; previsioni integrali, book, dataset e ricevute restano fuori Git.

La riproduzione usa il modulo `octobot.ai_strategy_lab.timestral_offline_v1` in tre fasi: `prepare`, `infer`, `evaluate`. L'ambiente CPU fissato riceve il repository in sola lettura. Durante `infer`, `/data` contiene soltanto `contexts.npz`, `inputs.json` e `dataset-manifest.json`; `/model` e il codice ufficiale sono in sola lettura, `/output` è l'unico montaggio scrivibile. Il protocollo e la ricevuta privata di idoneità sono file separati. Durante `evaluate` è montato anche `outcomes.json`. I parametri restano `--network none --read-only --memory 4g --cpus 4 --pids-limit 128`, con `HF_HUB_OFFLINE=1` e nessun download. I 12 test si eseguono con `python -B -m unittest tests.unit_tests.ai_strategy_lab.test_timestral_offline_v1` nello stesso ambiente locale.

Non raccomando una nuova integrazione operativa sulla base di questa prova. La fattibilità CPU è confermata, l'utilità di questo modello come segnale aggiuntivo no. Un eventuale seguito richiederebbe un protocollo futuro distinto, senza ricercare ora una soglia favorevole su questi stessi risultati. Non è stato avviato un altro esperimento o conto.

È uno studio storico esplorativo di soli 14 giorni. Il periodo precede la pubblicazione del modello e non conosciamo il suo cutoff di addestramento: non può dimostrare un vantaggio su prezzi estranei all'addestramento, né la capacità di prevedere futuri crolli. Nessun esito comporterà una promozione automatica o una modifica alle strategie attive.
