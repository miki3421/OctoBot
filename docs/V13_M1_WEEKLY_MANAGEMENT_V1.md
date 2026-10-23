# Manutenzione settimanale approvata del conto M1

23 ottobre 2026. Scheda principale `work-card-026c44e2-f248-41ac-aa1f-da68db8f1e98`.

## Perimetro e identità

Continuazione del conto `v13-m1-short-paper-v1-5e761f0cedac`, nello stesso `account.sqlite`: equity, posizioni, storico, high-water e contatori conservati. Nessun nuovo conto, reset o riutilizzo delle vecchie autorizzazioni copiate. Originale, FAST, HALF, osservazione M1, confronti A/B/C e conti intraday non cambiano. L'intervento distingue una nuova epoca di gestione nel journal; il rendimento successivo non misura soltanto il filtro SHORT originario.

È solo paper di ricerca, con validità scientifica UNASSESSED. Prezzi, precisione e funding provengono da acquisizioni pubbliche autorizzate; minimi di simulazione separati: un incremento di quantità e 1 USDT di nozionale. `min_quantity` e `min_notional` reali KuCoin restano UNKNOWN. Nessuna credenziale exchange, operazione reale, grant operativo, modifica P0 o disattivazione della quarantena.

## Selezione e tempi

Pool congelato di 29 simboli, già autorizzato per le acquisizioni pubbliche. Una proposta immutabile per settimana, ancorata al lunedì 00:15 UTC; prima proposta al primo ciclo con dati sufficienti. Non viene rigenerata dopo un rifiuto o osservando prezzi successivi. Scade dopo 48 ore; la successiva revisione ordinaria sarà nella settimana seguente. Il limite di rischio della revisione vale fino al mercoledì successivo all'ancora settimanale: nove giorni, inclusi due giorni per decidere sulla proposta seguente. Scadenza e mancanza di dati bloccano nuovi rischi; le riduzioni restano possibili.

La selezione riusa il kernel deterministico del confronto settimanale: momentum coerente 30/120 su 121 daily chiuse, punteggio rapportato alla volatilità, SHORT ordinari subordinati al regime BTC, massimo 18 selezionati e due nuovi ingressi/sostituzioni per settimana. Una sostituzione richiede punteggio superiore del 20% al più debole. Le uscite per perdita del segnale possono superare due: il vincolo non impone di mantenere esposizioni senza segnale. La V13 calcola i pesi con covarianza annualizzata e li limita ai budget approvati.

Gli input devono essere contigui, già ricevuti alla pubblicazione, chiusi e con lag minimo di dieci minuti; gli hash identificano snapshot, proposta e codice. Storia mancante su un incumbent blocca la proposta: un guasto non diventa un segnale di uscita. Su un nuovo candidato produce inammissibilità. Book attuale, spread, mark, profondità sui due lati e copertura funding determinano la proposta. Questo esame puntuale non sostituisce la qualifica storica A/B/C né prova ammissibilità KuCoin.

## LONG, SHORT e riacquisti

Ogni proposta espone separatamente tetto LONG e budget SHORT per tutti i simboli. I budget SHORT esistenti non sono ridistribuiti o eliminati automaticamente da un'uscita LONG. L'operatore può escludere anche lo SHORT di ciascun simbolo con budget positivo nella conferma. Un'esclusione completa comporta tetto zero su entrambi i lati. BUY che copre uno SHORT è una riduzione protettiva, non un riacquisto LONG.

Il tetto LONG vale in DAILY e REENTRY e diventa anche un limite persistente alla quantità: dopo una riduzione non si riacquista la quota tolta al calare del prezzo. La quantità massima può diminuire fino alla nuova approvazione. La liquidità liberata non viene riallocata automaticamente. I nuovi simboli sono ammessi a posizione zero e ricevono eventuali primi fill solo su dati futuri.

Il filtro M1 continua a usare BTC e l'universo originario fisso di 18 simboli: BTC nell'ora a -1% o meno e almeno 12 simboli in calo, senza cambiare soglie, frequenza, tenuta o cooldown. Quando scatta, usa i budget SHORT approvati, anche da FLAT o con LONG escluso, anziché ricavare lo SHORT dal LONG residuo. Gli SHORT ordinari già presenti non vengono attribuiti all'overlay. Gli altri controlli rimangono: perdita giornaliera 2%, drawdown 10%, 31,5% per asset, 90% lordo, massimo un episodio M1 e tre aumenti di rischio al giorno, un aumento ordinario e 22 ore fra aumenti ordinari.

## Approvazione ed esecuzione

Pagina `/v13_variants/m1/review`: nuova sezione settimanale sopra la fotografia storica del 23 ottobre. Mostra ingressi, esclusioni, ragioni, pesi per lato, quantità e costi indicativi, scadenza, revisioni e risultato effettivo del runner. I prezzi e le quantità eseguibili vengono verificati di nuovo. Il pulsante registra un'approvazione, non un fill.

La dashboard corrente non richiede login. Le sole nuove decisioni richiedono una password dedicata, conferma della proposta esatta, token CSRF di sessione e origine coincidente. Nessuna password predefinita; senza verificatore il canale rimane non approvabile. La password non entra nei log, journal, Git o risposte. Il browser non conserva la password. La configurazione conserva un verificatore scrypt con sale casuale.

Separazione effettiva:

| Processo | UID | Scritture consentite | Rete |
| --- | --- | --- | --- |
| Collector dedicato | 30944 | Acquisizioni, ricevute e pubblicazioni proprie | Sole GET pubbliche autorizzate |
| Broker approvazioni | 30945 | `approvals.sqlite` proprio e socket locale | Nessuna |
| Runner M1 | 30943 | Ledger M1 esistente e proiezioni proprie | Nessuna |
| Web esistente | 0 nel container corrente | Nessun mount scrivibile dei due ledger; invia richieste al socket | UI esistente |

Il broker verifica UID del peer locale e password; il client verifica anche l'UID del server ottenuto dal kernel prima di inviare la password. L'approvazione è vincolata a conto, hash proposta, revisione precedente, azione, scelte SHORT e scadenza. Replay identico è idempotente; azione conflittuale o proposta diversa è respinta. Nessun approvatore automatico o collegamento all'issuer operativo.

Il runner consuma l'approvazione solo in fase NORMAL senza vecchi intent pendenti, con dati sufficienti e senza debito funding. Ammissioni, policy, consumo e state sono transazionali. Le riduzioni sono pianificate su book acquisito dopo l'intent. Nuovi ingressi attendono DAILY 00:15 UTC e i gate di rischio, oppure un futuro segnale M1 per lo SHORT. Una policy approvata non annulla un veto di rischio. Fill parziali e attese sono visibili; intento e fill includono proposta/revisione/codice. Eventi di gestione formano una catena di hash. Nuovi grafici conservano solo prezzi realmente osservati dopo l'ammissione.

## Consegna e rollback

Il runtime candidato e le configurazioni sono preparati separatamente dai servizi attivi. Manifest con SHA-256, immagine già locale, configurazioni root-owned, scritture separate e healthcheck per ruolo. Il file di upgrade autorizzante non viene creato durante la sola preparazione: l'avvio prematuro deve fallire.

Il passaggio operativo richiede conferma manuale dell'operatore secondo la regola aziendale di deploy. Sequenza: fermare il solo M1; backup coerente del ledger e verifica offline; registrare identità/stato/contatori e hash del backup; compilare il record root-owned di upgrade; sostituire il solo runner sulla stessa directory state; avviare collector e broker dedicati; copiare il controller nella directory runtime della UI e riavviare solo `octobot-local`. Nessun avvio globale di Compose. Confrontare identità dei container e stato degli altri conti prima/dopo. Nessuna proposta reale viene approvata dall'agente nei test.

Prima della prima approvazione il rollback può ripristinare runtime/configurazione v2 sul ledger conservato. Dopo un'ammissione o un ribilanciamento gestito, non riavviare il vecchio codice su un ledger esteso: fermare nuovi aumenti, conservare il ledger e correggere in avanti nel runtime gestito. Ripristinare un backup cancellerebbe l'attività successiva e richiede una decisione esplicita, non è rollback automatico.

## Accettazione

Prova reale della pipeline su copia privata completa del conto: browser, token CSRF, password esclusivamente fixture, peer Unix con UID distinti, `approvals.sqlite` separato, consumo nel runner, ammissioni a zero, cinque riduzioni con fill e metadati verificabili. Prove avversariali e di restart verificano mancata approvazione, conflitti, scadenza, crash transazionale, riacquisti esclusi, nuovi ingressi al DAILY e budget SHORT ancora utilizzabile. I book con orari sintetici sono esplicitamente CONTROL_FIXTURE_ONLY: dimostrano il controllo, non l'ammissibilità di ordini reali né la redditività futura.
