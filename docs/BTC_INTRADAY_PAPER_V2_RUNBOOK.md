# BTC intraday v2 — conto sintetico separato

Autorizzazione dell'utente nel presente incarico: completare il conto attivo e
in dashboard. Include l'implementazione del protocollo v2 già discusso, con
frequenza senza quota/cooldown come richiesto, e l'avvio del solo simulatore
locale isolato. Non è un'approvazione scientifica, un'autorizzazione a fondi
reali, credenziali exchange o deployment di trading reale.

L'artefatto candidato storico v2 resta immutato, compresi i suoi precedenti flag
non approvati. L'effetto attuale è registrato da una ricevuta di attivazione
separata root-owned, con hash del protocollo e dei file effettivamente eseguiti,
identità conto e T0/T1. T0 è la mezzanotte UTC successiva all'attivazione; la
raccolta prospettica comincia subito. Nessun risultato precedente è ereditato.

Il conto nasce flat con 10.000 USDT virtuali. La prima finestra richiede 289
punti causali contigui di cinque minuti, circa 24 ore, e può richiedere più tempo
in presenza di buchi. Il conto può essere attivo in warm-up senza aprire trade.
La pagina `/btc_intraday`, raggiungibile dal confronto V13, mostra questo stato
esplicitamente. Nessuna operazione viene forzata per rendere positivo il test.

## Confini

Il servizio `octobot-btc-intraday-paper` usa un'immagine già presente e fissata per
digest, filesystem immutabile, rete disabilitata, capability rimosse e limiti di
risorse. Riusiamo l'identità numerica di runtime già presente 30943:30910;
non viene inventato né approvato un nuovo roster o utente del sistema. Questa
scelta non costituisce isolamento tra UID: la separazione concreta è data dai
mount del container. Nessun altro conto o approval store viene montato.
I quattro volumi impliciti dell’immagine sono sovrascritti da directory vuote RO,
così non costituiscono ulteriori aree persistenti scrivibili.
Fonti raw e scalping sono RO; soltanto stato proprio e proiezione pubblica sono RW.

Unico writer del nuovo ledger e delle ricevute è il runner deterministico. Non
esiste issuer collegato né grant operativo. Questo è un simulatore di ricerca
con contratto sintetico, senza accesso all'executor fidato degli altri esperimenti.
SQLite non offre permessi per tabella: nel nuovo file le tabelle sono tutte
responsabilità del medesimo runner. La strategia non riceve accesso ai ledger o
alle approvazioni degli esperimenti esistenti.

I mark M1 devono essere ricevuti e realmente visibili entro ciascun cutoff; nessun
backfill successivo di uno slot. Decisione entro +30s; ingresso sul primo book
fresco dopo +300s+500ms, persistito entro un ulteriore secondo. Dieci secondi
completi richiesti all'ingresso, non alla chiusura protettiva. Le ricevute tardive
non diventano ingressi storici. Ogni slot è unico e persistente; al riavvio un
file conto mancante o identità modificata causa errore, mai un conto nuovo.

Size e costi seguono il contratto sintetico v2. Il rischio viene ricontrollato al
fill inclusi i costi; la quantità può solo diminuire. Una posizione alla volta,
stop 1%, TP 2%, sei ore, perdita giornaliera 2%, drawdown 10%. Nessuna quota di
ingressi al giorno o attesa dopo il flat. Dati mancanti negano ingressi; un'uscita
pendente rimane tale e non si inventa flat o fill senza profondità fresca.
I commit tardivi sono incidenti di integrità e non risultati validi di ingresso.

## Funding e dati incompleti

Calendario effettivamente annunciato, nessun intervallo fisso inventato. Rate
finale firmato e mark exchange ricevuto strettamente prima dell'evento, età
massima 60s; nessun book mid sostitutivo. Attesa minima di riconciliazione fino
alla chiusura della finestra ±60s per includere le eventuali uscite protettive e
usare il cashflow meno favorevole tra le quantità ai confini. Non si ritarda
un'uscita per evitare funding. Rate mancanti o discordanti restano pending;
oltre 15 minuti chiedono uscita e bloccano nuovi ingressi. Nessuno zero sostitutivo.
Le curve già pubblicate non vengono riscritte con informazioni tardive.

Lo scenario stress riceve soltanto le opportunità effettivamente ammesse dal
primario e le stesse quantità intenzionali congelate. Usa un ledger separato,
latenza 1000ms, propri book/freshness, posizioni, rischio e uscite, fee/slippage
raddoppiati, debit funding doppi e crediti nulli. Una posizione stress ancora
aperta sopprime l'opportunità; mancate entrate e divergenze restano registrate.
Le quantità possono solo ridursi per i suoi cap, non crescere o essere riselezionate.
Il futuro riesame scientifico resta separato. La precedente sola stima dei costi
resta conservata nel ledger primario come diagnostica, ma non viene mostrata
come scenario stress v2.

La correzione è stata completata prima di T0 e con zero fill primari. Una
ricevuta root-owned di continuazione lega vecchia attivazione, nuovo codice,
protocollo invariato e prova zero-fill; l'identità contabile primaria resta
quella iniziale. Non si cambiano saldo, storico o confine temporale della
valutazione. Il nuovo stress parte flat prima di T0, senza risultati ereditati.

## Chiusura locale, stop e recupero

`btc_intraday_admin.py` consente soltanto a root locale di scrivere una richiesta
nel control directory root-owned: account, position ID/generazione, quantità
massima, nonce monouso e TTL 60s. Il runner verifica il file, confronta quantità
e generazione correnti e consuma il nonce nella stessa transazione dell'intento.
L'uscita usa nuovi prezzi e profondità dopo 500ms; può essere parziale e non
inverte mai la posizione. Se lo storage fallisce, nessun claim o fill è finto.
Non esiste un pulsante o endpoint UI che invia ordini.

Per fermare, arrestare soltanto il servizio `btc-intraday-paper` del suo Compose,
con il project name dedicato `btc-intraday`; non usare il progetto Compose degli
altri servizi.
Conservare stato, ricevute, configurazione e proiezioni; mai rimuovere volumi o
inizializzare una seconda volta il ledger. Un riavvio verifica le identità e la
catena, conserva high-water, halt, posizione e pending; intenti d'ingresso senza
commit confermato vengono cancellati. Le uscite protettive restano abilitate.
La health Docker e la freschezza della proiezione mostrano lo stato effettivo.

La pagina usa le stesse protezioni di login/profilo delle altre pagine, solo GET,
con cache disabilitata. Si aggiorna soltanto il servizio web per caricare le
route nuove; gli esecutori/collector e le regole degli altri conti restano invariati.
Nessuna pulizia o cancellazione delle evidenze precedenti.
