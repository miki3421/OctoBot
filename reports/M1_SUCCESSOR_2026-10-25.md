# M1: sostituzione della versione precedente con gestione graduale LONG + SHORT

25 ottobre 2026. Richiesta dell'operatore: una sola nuova versione sul conto M1 esistente, ritiro della precedente, nessun altro conto di confronto. Confermata la sequenza **50% / 25% / 25%** della quantità iniziale. SINGLE_AGENT: sviluppo, verifica e integrazione svolti come responsabilità distinte dell'autore; nessuna accettazione dell'operatore presunta dai test.

## Proposta concreta

La strategia `m1-gradual-long-short-v3`, mostrata come **M1 · gestione graduale + SHORT**, conserva equity, posizioni residue, storico, funding, costi, contatori di rischio e high-water dello stesso account `v13-m1-short-paper-v1-5e761f0cedac`. Il capitale non viene riportato a 10.000. La versione precedente termina al cambio e viene conservata come periodo storico del conto.

| Simbolo | Quantità iniziale | Residuo dopo la prima tappa | Residuo dopo la seconda | Residuo dopo la terza |
| --- | ---: | ---: | ---: | ---: |
| AAVE | 2,74 | 1,37 | 0,68 | 0 |
| BCH | 1,10 | 0,55 | 0,27 | 0 |
| BTC | 0,010 | 0,005 | 0,002 | 0 |
| DOT | 306 | 153 | 76 | 0 |
| LTC | 8,3 | 4,1 | 2,0 | 0 |
| NEAR | 48,4 | 24,2 | 12,1 | 0 |

I residui sono arrotondati verso il basso ai passi del simulatore, perciò i tagli non corrispondono sempre al 50% o 25% esatto. Alla fotografia della proposta, il lordo LONG passa da **25,34% a 12,64%** alla prima tappa. Turnover indicativo 1.237,42 USDT; costo immediato stimato 1,28 USDT. I fill effettivi richiedono un book successivo all'intento e hanno prezzi/costi propri.

Il budget SHORT è conservato **per ciascun simbolo**, oltre che nel totale **25,5458333431%** dell'equity. Ridurre un LONG non elimina lo SHORT, non ne raddoppia la capacità e non distribuisce la liquidità sugli altri asset. Nessuna nuova coin inclusa.

## Regole fissate

1. La prima riduzione porta i sei LONG a circa metà delle quantità iniziali. Avviene solo su book fresco dopo l'intento persistito. Un fill parziale mantiene lo stesso target e viene completato protettivamente; il riavvio non dimezza una seconda volta.
2. La seconda tappa può iniziare **almeno 24 ore dopo l'effettivo completamento della prima per il simbolo**; la terza almeno 24 ore dopo la seconda. Richiedono un nuovo giorno chiuso, dati disponibili e conferma che il segnale dual momentum non sia positivo. Lo stato e i tempi sopravvivono ai riavvii.
3. Se il segnale torna positivo, la riduzione successiva si ferma. Se i dati sono insufficienti, il tetto resta e la verifica attende; la mancanza di dati non diventa una vendita. Per riprendere una riduzione servono condizioni nuovamente verificabili.
4. **Nessun riacquisto automatico LONG.** Quantità e tetti possono soltanto diminuire. Anche il rientro dopo un episodio SHORT non ricostituisce il LONG chiuso. Riattivazioni, nuovi simboli e aumenti richiedono una revisione esplicita. Un BUY che copre uno SHORT resta consentito come riduzione di esposizione negativa.
5. Il filtro M1 resta BTC a −1% o meno nell'ora e almeno 12 dei 18 simboli in calo; tenuta SHORT sei ore, cooldown sei ore, un episodio al giorno e guardie esistenti invariati. Il primo slot della nuova versione è strettamente successivo all'attivazione; nessun segnale storico viene riprodotto. La capacità SHORT resta operativa anche con tutti i LONG FLAT.
6. Restano i veti ai nuovi rischi al 2% giornaliero e 10% dal massimo, cap 31,5% per asset, 90% totale e tre aumenti di rischio al giorno. Non sono presentati come liquidazioni automatiche garantite. La revisione di nuovi rischi ha validità sette giorni; riduzioni protettive e storico restano disponibili.

Questa modifica affronta il mantenimento e il ripristino dei LONG deteriorati. Non introduce uscite adattive degli SHORT né pretende di risolverne il rischio di rimbalzo. La validità scientifica della nuova versione rimane **UNASSESSED**; il ritiro della precedente è una decisione operativa dell'utente, non un nuovo verdetto statistico.

## Continuità e autorità

La sostituzione manuale è autorizzata dalla richiesta diretta dell'operatore del 25 ottobre e dalla successiva conferma delle tre tappe. Il passaggio registra un file root-owned, legato a proposta, account e backup a servizi fermi, con provenienza `direct_operator_instruction`. **Non viene letta la password dell'operatore, simulato un click in UI o inserita una falsa decisione autenticata nel database delle approvazioni.** Le protezioni del broker web rimangono e le vecchie proposte non sono consumabili come consenso alla nuova versione.

Viene usato lo stesso ledger e conservato un backup freddo completo prima del passaggio. Il vecchio container M1 e il broker sono conservati spenti, con restart disabilitato, prima di caricare i sostituti. Il solo servizio condiviso dashboard viene riavviato per pubblicare le viste. Originale, FAST, HALF, coppia intraday, osservazione M1 e collector restano fuori dal batch, incluso il market observer. Nessuna VM OPS viene toccata.

La UI mantiene la perdita del conto dalla copia e mostra separatamente il risultato dalla nuova versione, con equity ereditata e data del cambio. La curva conserva lo storico e una linea verticale segnala il confine. La precedente M1 compare come versione ritirata; non viene aggiunta una strategia parallela. Il monitor passivo continua a seguire lo stesso container/account attraverso lo schema di proiezione conservato.

## Identità del candidato

- Proposta: `99a8e06e92ea76b9cfb358b56e2bb07a3dcca295c89e34e71350eea60004915d`.
- Runtime: `/opt/v13-m1-successor-runtime-v6`.
- Pacchetto: `octobot-local/v13-m1-successor-v6`.
- Manifest SHA-256: `981b71a9ca2ae927d37f64d38765e25dcb48e54fc72ef4a654531477ae739187`.
- Protocollo leggibile: `docs/research-protocols/m1-gradual-long-short-v3.json`.
- Preparatore `scripts/prepare_m1_successor.py`; passaggio manuale `scripts/activate_m1_successor.py`. Quest'ultimo verifica soltanto, senza gli argomenti manuali e l'identificatore esatto della proposta.

## Verifiche e stato

Il candidato è provato con test unitari mirati e con il runner reale su **una copia completa dei 313 ordini esistenti**. Le future giornate della prova sono fixture controllate, non risultati economici o un nuovo confronto: eseguono le tre tappe, un riavvio, un ingresso SHORT da FLAT e il BUY che lo copre; non producono una pretesa di rendimento. Seed e Originale restano immutati e l'integrità SQLite viene verificata. La prova ha individuato e corretto il conteggio del tempo dal completamento effettivo del fill.

Evidenze private in `audit-evidence/m1-successor-20261025/`: copie, proposta, manifest, test, browser e ricevuta del passaggio. Le versioni preparatorie precedenti sono conservate; il candidato finale è soltanto quello identificato sopra.

**Attiva dal 25 ottobre alle 12:27:40 CET.** Prima riduzione completata sui sei LONG alle 12:28:38 CET: 6 fill, costo immediato effettivo 1,574570 USDT, incluse fee 0,741120. Tutti i 313 ordini precedenti conservati, ora 319. Budget SHORT e contatori di rischio invariati; contabilità indipendente riconciliata e integrity_check `ok` sulla copia successiva. Seconda tappa non prima del 26 ottobre alle 12:28:38 CET, solo con nuovi dati e deterioramento confermato.

**78 test mirati passati**, prova completa su copia e browser fixture/live desktop e mobile passati. Sei conti attivi in UI, vecchia M1 come versione ritirata, nessun altro conto di confronto. Monitor passivo successivo: M1 healthy, zero issue e zero alert complessivi. Altri container con ID, avvio e restart count conservati. Evidenze operative: `manual-20261025T112639Z/result.json`, `operational-readback.json`, `v6/browser-live/result.json`. Il browser già aperto può conservare la vecchia pagina: una ricarica carica i nuovi riferimenti degli asset. Accettazione dell'operatore ancora distinta dalle verifiche dell'autore.

Richieste successive dell'operatore: aggiunta alle regole del progetto della revisione settimanale delle tecnologie open source; approvazione automatica ponderata M1 da implementare con evidenze e controlli espliciti. Quest'ultima non è inclusa nel manifest di sostituzione sopra identificato.
