# BTC intraday — adapter causale e benchmark dei costi

17 ottobre 2026. **Preparazione tecnica completata; conto nuovo non creato.**

La scansione dei 74.116.396 book della copia qualificata ha mantenuto 74.089.965 eventi e scartato 26.431 catture oltre un secondo. Ha ricostruito 297 segmenti: 175 inizi di sessione e 122 reset per buchi fra book accettati. Non sono né trade né episodi scientifici.

Le query causali usano ricezione e freschezza; interrompono le finestre ai buchi/cambi sessione. Il fingerprint delle feature dipende solo dagli input consumati. I dati futuri non cambiano gli input passati nelle fixture. Ricostruiti su richiesta 8.252 campioni dei dieci secondi precedenti gli slot; 8.232 completi e 20 incompleti, esplicitamente marcati.

La griglia fissata prima dei risultati ha generato **264.064 intenti ipotetici**: entrambi i lati, quattro quantità native e quattro latenze ogni 15 minuti. 221.749 misurabili, 41.715 senza profondità L5 sufficiente, 544 senza riferimento fresco, 56 senza arrivo fresco. Nessun tentativo è omesso. Queste righe non sono ordini del laboratorio.

## Costi a 500 ms

Costi per singolo fill in punti base (1 bps = 0,01%). Le quantità sono **unità native grezze del book**, non BTC o USDT certificati e non minimi contrattuali. Le medie si riferiscono soltanto ai casi misurabili. BUY e SELL sono intenti di costo simmetrici, senza posizioni aperte o previsione.

| Quantità nativa | Lato | Misurabili / 8.252 | Profondità insufficiente | Costo medio bps | P95 bps |
|---:|:---|---:|---:|---:|---:|
| 1 | BUY | 8233 | 0 | 7.0076 | 7.6888 |
| 1 | SELL | 8233 | 0 | 7.0071 | 7.6752 |
| 10 | BUY | 8227 | 6 | 7.0228 | 7.7911 |
| 10 | SELL | 8230 | 3 | 7.0197 | 7.7816 |
| 100 | BUY | 8044 | 189 | 7.0454 | 7.8989 |
| 100 | SELL | 8056 | 177 | 7.0424 | 7.9171 |
| 1000 | BUY | 3099 | 5134 | 6.9779 | 7.5244 |
| 1000 | SELL | 3276 | 4957 | 6.9801 | 7.5676 |

In ogni gruppo a 500 ms mancano anche 19 casi per dati freschi indisponibili. Per la size 1 il mezzo spread medio è circa 0,0074 bps, mentre commissione e slippage aggiuntivo assunti valgono circa 7 bps per fill. Il costo medio vicino a 7 bps è dunque soprattutto una conseguenza di queste ipotesi: non è una scoperta di alpha. Un ingresso e una successiva uscita devono entrambi sostenere i propri costi; il riferimento di ricerca è circa 14 bps prima degli ulteriori effetti di spread, profondità, attesa e funding.

La size 1.000 non è completamente rappresentata nei cinque livelli per oltre il 60% dei tentativi a 500 ms. La media sui soli casi misurabili non la rende conveniente e non autorizza estrapolazione o fill parziali. Serve un limite di size nel futuro contratto del simulatore.

La latenza richiesta di 500 ms produce un arrivo osservato medio di 552,64 ms, massimo 1.154,03 ms, perché si attende il primo aggiornamento valido successivo. Il caso 0 ms ha comunque attesa media di 52,58 ms. Sono scenari di replay, non misure della latenza di un ordine. Il movimento del prezzo durante l’attesa è separato dal costo di liquidità e può essere favorevole: non è profitto della strategia. Le altre latenze e lo stress aritmetico sono nel report JSON; nessuna è stata selezionata come vincente.

## Evidenze e verifiche

- Snapshot SHA-256 `1141375eb2945a09c261e9f1d7b64972d532e2debd4e8543121734d9b739e678`.
- Contratto congelato prima del run, hash originale `b1b60ee870592f2d009f1d1e79589f27c3b441aadbb2fddf290ab2d2c6f65273`; la copia JSON normalizzata ha hash diverso, stesso contenuto.
- Tool eseguito SHA-256 `1d384c96d359cf485e05118020fb7c1b48fcd15f3ee4ef0a43e051eb6058bcfd`.
- Evidenze complete fuori Git: alias `scalping-costs-20261017-v1`, ricevuta finale con hash di ogni file; sorgente qualificata conservata.
- 21 test nuovi più 13 test di qualifica/cronologia superati. Verificati tutti i timestamp di riferimento/arrivo, chiusure causali dei campioni, denominatori, hash e `integrity_check` del solo indice derivato offline.
- Nove container preesistenti healthy, con identità, orario di avvio e restart count invariati. Nessun riavvio, download, modifica di policy, grant o ledger operativo.

## Passo successivo per il conto BTC separato

Fissare il protocollo candidato: driver indipendente, dati causali necessari, quantità, ingresso/uscita, orizzonte, rischio e funding. Il book BTC non contiene la breadth dei 18 simboli richiesta da M1. Le vecchie famiglie direzionali L5 respinte restano respinte.

Il moltiplicatore 0,001 è documentato da una risposta pubblica del 25 settembre; manca evidenza applicabile a tutto il periodo luglio–ottobre e il binding storico delle quantità del feed. La conversione BTC/USDT rimane non qualificata; `min_quantity` e `min_notional` reali restano **UNKNOWN**. Questo non impedisce una successiva simulazione di ricerca con contratto sintetico esplicito: l’ammissibilità fedele a KuCoin resta distinta e bloccata.

Il nuovo conto avrà namespace e journal propri. Non erediterà autorizzazioni o validità scientifica. Originale, FAST, HALF, M1 paper e osservazione M1 rimangono invariati. La schedina del protocollo/conto `ee52019c` resta To-do, con queste dipendenze esplicite.

Schedine consegna: `0cef3daa`, `c9187254`, `0211c696`, `d3eaae8f`, `26bdb4f5`. Dettagli tecnici: `docs/SCALPING_CAUSAL_COSTS_V1.md`; aggregati e provenienza nel report JSON omonimo.
