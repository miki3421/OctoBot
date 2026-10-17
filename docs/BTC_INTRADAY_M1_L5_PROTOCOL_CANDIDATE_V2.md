# Conto intraday BTC — protocollo candidato M1 + L5 v2

17 ottobre 2026 · **CANDIDATO, NON APPROVATO, NON ATTIVATO.**
Esperimento e conto proposti: `btc-intraday-m1-l5-paper-v1`.
Revisione frequenza `34617df1`; coerenza `e4c2388d`; consegna `5bd4e669`.
Il contratto numerico è `research-protocols/btc-intraday-m1-l5-paper-candidate-v2.json`.
Nessuna directory conto, policy operativa, autorizzazione o schedulazione creata.

Questa revisione rimuove su richiesta utente la quota giornaliera e il cooldown.
La versione v1 è conservata. Restano i limiti di esposizione, perdita e drawdown,
le uscite protettive, il requisito di dati validi e una sola posizione alla volta.
`null` nei massimi giornalieri significa nessun cap; `0` nel cooldown significa nessuna attesa.

## Obiettivo e identità

Verificare su soli dati futuri se il filtro cross-asset M1 possa sostenere SHORT
BTC al netto di esecuzione, uscite e funding. Il book L5 serve a rappresentare
liquidità e costi, non a riscoprire un segnale direzionale nei modelli già respinti.
M1 viene riutilizzato come definizione di un'ipotesi: non è dimostrata indipendenza
statistica dal book, né superiorità rispetto al M1 multiasset esistente.

Il nuovo conto parte **flat con 10.000 USDT virtuali**. Non clona equity, posizioni,
PnL o approvazioni della V13: quelle copie appartengono alle precedenti biforcazioni.
Originale, FAST, HALF, M1 paper e osservazione scientifica M1 restano invariati.
Lo storico scalping qualificato rimane evidenza tecnica riutilizzata; non diventa
performance forward del nuovo conto. Nessun LLM o addestramento necessario.

## 1. Segnale e disponibilità causale

Ogni cinque minuti UTC, per i 18 simboli originali fissati nel JSON:

`r_s(t) = prezzo_s(t) / prezzo_s(t − 1 ora) − 1`.

M1 è vero se **BTC perde almeno l'1% nell'ora e almeno 12 dei 18 simboli sono
in calo**. Il confronto di breadth è strettamente negativo, include BTC e mantiene
il denominatore 18 anche quando i dati mancano: un dato mancante invalida lo slot.
Nessuna nuova selezione di monete, soglie o direzione LONG.

Servono 289 punti contigui sulla griglia di cinque minuti, con tutte le 18 quote
ricevute entro il rispettivo punto e vecchie al massimo 120 secondi. La storia
prima dell'avvio serve solo al warm-up. Non si riempiono retroattivamente buchi.
La decisione deve essere persistita entro 30 secondi dallo slot.

Il join causale delle fonti pubbliche dei 18 simboli, L5 e funding/mark è **ancora
da implementare e qualificare** per questo conto. Non basta leggere prezzi o
performance dalle pagine degli altri esperimenti. I consumer saranno in sola lettura.

Per L5 valgono i limiti fissati nell'adapter: cattura, età dalla ricezione ed età
dalla sorgente entro un secondo; reset per cambio sessione o gap oltre cinque
secondi. Decisione e ingresso richiedono dieci secondi completati e validi nel
segmento. Una chiusura protettiva richiede invece solo un nuovo book fresco,
senza attendere il warm-up. Clock regressivo o identità incoerente bloccano nuovi rischi.

## 2. Ingresso, quantità e contratto della simulazione

**Nessun massimo giornaliero e nessun cooldown**, nemmeno dopo un tentativo
respinto o mancato. Ogni nuovo slot M1 valido può produrre un ingresso se il conto
è flat e non esistono ingressi o uscite pendenti al cutoff dello slot. Dopo una
chiusura si usa il primo slot valido strettamente successivo, anche se M1 è rimasto
vero. I segnali durante una posizione o intent pendenti sono registrati e soppressi.
Ogni slot ha un solo esito durevole e un intent univoco: retry dello stesso slot,
riavvio o riuso dello stesso book non generano ingressi duplicati.
Ingresso previsto allo slot successivo, cinque minuti dopo; attesa di esecuzione
500 ms e primo book fresco successivo entro un secondo aggiuntivo. Anche la
ricevuta del fill deve rispettare la scadenza: leggere più tardi un vecchio book
non permette di attribuirsi il fill. Nessun ingresso tardivo ricostruito.

Con equity completa `E` e mid BTC fresco `P`, il nozionale candidato è:

`N = min(10% × E, 0,25% × E / (1% + 0,28%), 10 × 0,001 × P)`.

`q_BTC = floor((N / P) / 0,001) × 0,001`; la posizione aperta è `−q_BTC`.
Si usano decimali e arrotondamento della quantità verso zero. All'arrivo il rischio
viene ricontrollato: la quantità intenzionata può soltanto diminuire. Un ordine
sotto il passo/minimo simulato non viene aumentato artificialmente.

Esempio **sintetico**: con equity 10.000 e BTC a 80.000, il limite più stringente
è 800 USDT: SHORT da 0,010 BTC, 8% dell'equity. Stop teorico di prezzo 8 USDT,
più 2,24 USDT di riserva costi stressata: circa 10,24 USDT, prima degli ulteriori
effetti non coperti da questa convenzione. Non è una perdita massima garantita.

La quantità massima di dieci unità native evita la taglia 1.000, spesso priva di
profondità sufficiente nel benchmark. Non è una size ottimizzata sulla redditività.
L'ingresso richiede intera profondità osservata disponibile; nessun fill parziale
di apertura o estrapolazione oltre i cinque livelli.

| Elemento | Solo contratto sintetico candidato |
|---|---|
| Conversione assunta | 1 unità nativa grezza = 0,001 BTC |
| Passo e minimo quantità simulati | 0,001 BTC |
| Minimo nozionale simulato | 1 USDT |
| Tick prezzo simulato | 0,1 USDT |
| Margine | Esposizione virtuale coperta dalla cassa, nessuna leva |
| Minimi reali KuCoin | `min_quantity = UNKNOWN`, `min_notional = UNKNOWN` |

La conversione è un'**ipotesi dichiarata del simulatore**, non una qualificazione
delle unità storiche del feed. Il dato KuCoin puntuale del 25 settembre non prova
l'invarianza luglio–ottobre. Questo consente di progettare ricerca paper; non
certifica ammissibilità, minimo, margine o liquidazione KuCoin. Un futuro passaggio
a metadata applicabili richiederà contratto/versione espliciti, mai un fallback
silenzioso né un indebolimento di P0-03.

## 3. Rischio e uscite

Tutti i valori seguenti sono **proposte inerti per il nuovo conto**, non estensioni
delle precedenti approvazioni né configurazioni degli esperimenti attivi.

| Regola | Candidato |
|---|---|
| Cap BTC e totale | 10% dell'equity, nessun aumento della posizione aperta |
| Budget stimato per stop | 0,25% equity, subordinato anche agli altri cap |
| Perdita giornaliera | 2%: chiusura protettiva e stop ai nuovi ingressi |
| Drawdown dal massimo | 10%: chiusura protettiva e halt persistente da revisionare |
| Stop prezzo SHORT | Ask osservato almeno 1% sopra il VWAP effettivo di ingresso |
| Take profit SHORT | Ask osservato almeno 2% sotto quel VWAP |
| Scadenza | Sei ore dal fill effettivo, non dal segnale |
| Frequenza | Nessun cap giornaliero; un solo ingresso per nuovo slot valido e conto flat |
| Cooldown | Nessuna attesa dopo flat, veto o tentativo mancato |

Il trigger di stop non è il prezzo garantito del fill. La richiesta di chiusura
resta attiva; il simulatore deve acquistare sulla profondità di un nuovo book
successivo alla latenza, includendo costi e arrotondamento avverso. Sono consentite
riduzioni parziali protettive, conservando il residuo. Mai inversioni o nuovi LONG.
Priorità: comando amministrativo, guasto contabile/integrità, limite di rischio,
stop, scadenza, take profit. Un recupero di prezzo non annulla l'uscita già richiesta.

In un buco dati non si dichiara né stop eseguito né conto flat: stato `EXIT_PENDING`
e retry protettivo su book nuovi. Nessun riuso del medesimo book per moltiplicare
la liquidità disponibile. Il comando amministrativo locale richiederà identità
ammessa, account/position ID/generazione, ID monouso e scadenza; l'esecutore controllerà
quantità effettiva e replay. Non viene abilitato in questo incarico.

L'equity include commissioni, PnL aperto e funding del modello. Baseline giornaliera
alla mezzanotte UTC; se manca funding è provvisoria e impedisce nuovi ingressi.
Massimo storico, halt e deduplicazione degli slot persistono al riavvio. Non esistono
quota di frequenza o cooldown da applicare. Solo il limite di perdita
giornaliera segue naturalmente il nuovo giorno, con contabilità nuovamente valida.
Un funding pendente oltre 15 minuti richiede chiusura protettiva, senza inventare
il relativo importo.

## 4. Esecuzione e funding

Fee di ricerca **6 bps per fill**, più **1 bps avverso aggiuntivo** a spread,
VWAP e arrotondamento al tick. Sono ipotesi, non il fee tier dell'utente.
Il budget di 28 bps round-trip stressato non include ogni possibile effetto di
spread, profondità, attesa o funding. Lo stress usa latenza 1 secondo, fee 12 bps,
slippage 2 bps per fill, raddoppia i debiti funding e ignora i crediti.
Segue gli stessi segnali e quantità intenzionate, ma ricostruisce proprie
eseguibilità e uscite: non è un secondo conto operativo né una superiorità a
parità di esposizione. Mancati ingressi e divergenza di esposizione saranno visibili.

La [documentazione KuCoin sul funding](https://www.kucoin.com/support/26695933047705)
lega il pagamento al valore della posizione al mark di settlement e al tasso
firmato: con tasso positivo paga il long e riceve lo short; con tasso negativo
vale il contrario. Segnala inoltre possibili scostamenti temporali del pagamento.
Il nostro candidato usa invece un metodo **esplicitamente stimato**:

`cashflow = −quantità_BTC_firmata × mark_precedente × tasso_finale_firmato`.

Occorre un vero mark exchange già ricevuto prima del settlement nominale, vecchio
al massimo 60 secondi: non il mid del book e non il primo mark successivo.
Tasso finale da storia pubblica regolata; `current` e `predicted` non valgono come
prova di regolamento. Calendario e intervallo devono essere osservati per contratto:
non si presume che siano sempre otto ore. A ingresso, annuncio del prossimo evento
vecchio al massimo cinque minuti e nessun evento scaduto della posizione irrisolto.

Un nuovo ingresso entro ±60 secondi da un evento annunciato è respinto. Le uscite
protettive restano possibili: se vicine al settlement, si conservano entrambi gli
scenari di quantità prima/dopo e si usa il cashflow meno favorevole, marcandolo
`FUNDING_BOUNDARY_ESTIMATE`. Nel modello il settlement nominale precede fill con
identico timestamp; non è una certificazione dell'ordinamento exchange.

Ogni evento è unico per conto/contratto/timestamp. Importo mancante resta `PENDING`,
mai zero. Un tasso arrivato tardi genera una riconciliazione visibile, con tempo
economico e tempo di osservazione distinti; nessuna riscrittura dei punti passati
o delle decisioni. Zero esposizione è utilizzabile solo se ricostruita sull'intera
finestra possibile del settlement. La futura qualifica di calendario, tassi e mark
è ancora necessaria: non è stata ottenuta leggendo questa documentazione.

## 5. Verifica futura e avvio

T0 sarà la mezzanotte UTC successiva a ricevuta di attivazione autorizzata e bundle
implementativo qualificato; oggi è **non impostato**. Finestra di 90 giorni, nessuna
estensione scelta in base ai guadagni. Negli ultimi slot non si ammettono episodi
che non possano completare le sei ore più le attese modellate prima di T1.
Ogni residuo reale resta comunque da chiudere e da rendicontare.

Confronto primario: utile netto del nuovo conto contro cassa USDT flat da 10.000,
senza interesse. Non è un confronto di superiorità risk-matched con V13. Per una
classificazione positiva servono congiuntamente: almeno 20 episodi chiusi in
20 giorni e otto settimane ISO, almeno 95% degli slot validi, zero esposizioni o
funding irrisolti, utile primario e stressato positivi, drawdown entro 10% e limite
inferiore unilaterale al 95% della media settimanale sopra zero.

Bootstrap su somme delle settimane UTC, comprese settimane senza trade e parziali,
10.000 ricampionamenti, seed `20261017`, quinto percentile nearest-rank. Non si
trattano i milioni di book come trade indipendenti e non si annualizzano 90 giorni.
Il JSON fissa classificazioni `CANDIDATE_FOR_FURTHER_REVIEW_ONLY`,
`FAILED_FROZEN_CRITERIA`, `INCONCLUSIVE_NO_PROMOTION`. Dati/casi insufficienti
significano inconclusivo, non successo. Nessuna promozione automatica. Un utile rispetto alla cassa non isola la capacità
di timing di M1 da un mercato BTC genericamente ribassista: non prova alpha né
superiorità sulle strategie esistenti.

La UI futura potrà mostrare stato e PnL descrittivi; review tecniche giornaliere e
settimanali restano consentite, senza ritocchi delle soglie. Una modifica semantica
dopo T0 richiede nuova versione e frontiera futura, conservando il periodo consumato.

Prima dell'avvio restano: join causale qualificato delle fonti; simulatore isolato
con persistenza e prove negative/riavvio/storage; riesame del bundle esatto con
contratto sintetico e policy dedicati. Il produttore non scriverà approvazioni o
ledger fidati; issuer ed esecutore useranno store separati dove necessari, ledger
scritto dal solo esecutore. Nessun UID, permesso o grant viene inventato qui.

Questa consegna definisce il candidato richiesto, non ne autorizza l'attivazione.
