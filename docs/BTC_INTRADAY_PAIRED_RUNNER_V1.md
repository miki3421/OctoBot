# BTC intraday — runner appaiato SHORT / LONG+SHORT

21 ottobre 2026 · **Candidato tecnicamente qualificato, non attivato.**
Implementa il [protocollo candidato](BTC_INTRADAY_LONG_SHORT_COMPARISON_CANDIDATE_V1.md)
senza modificare alcun conto o servizio esistente. Non esiste un nuovo giorno
forward ufficiale; i test sintetici non dimostrano redditività o ammissibilità KuCoin.

## Stato e provenienza

Il package `octobot/ai_strategy_lab/intraday_pair/` contiene runner, motore,
lettori causali, worker con gate manuale, probe e valutatore. Usa soltanto
la libreria standard Python. Non importa i moduli del runtime attivo e non
ha un client exchange, credenziali, rete o issuer.

Il motore deriva dal runner SHORT fissato per SHA-256
`52e2d6843527c3ef1bdffc32ffef982a0e06adf7eea7fe8f1335f0480282e555`.
Sono state estratte in un namespace nuovo le sole utility causali necessarie:
le loro definizioni AST corrispondono agli originali fissati per hash.
Una copia completa del riferimento è conservata come fixture di test;
non viene eseguito il suo CLI né aperto il conto originale.

Il runner conserva l'aritmetica float del riferimento per rendimento e
contabilità, e Decimal per size/pricing, così il confronto non aggiunge una
modifica numerica al controllo SHORT. Il precedente kernel puro Decimal
rimane conservato come preparazione: non è il motore contabile eseguito.
Le tracce economiche SHORT e i confini ±1% sono verificati contro il riferimento.
Gli ID del nuovo esperimento non ereditano autorità, PnL o approvazioni precedenti.

## Quattro ledger e input comuni

| Braccio | Identità del conto | Stato persistente |
| --- | --- | --- |
| Controllo SHORT | `btc-intraday-short-control-v1` | `control-primary.sqlite` |
| Candidata LONG+SHORT | `btc-intraday-long-short-v1` | `candidate-primary.sqlite` |
| Stress controllo | Stesso conto, scenario distinto | `control-stress.sqlite` |
| Stress candidata | Stesso conto, scenario distinto | `candidate-stress.sqlite` |

Tutti partono flat a 10.000 USDT con stesso T0/T1; non si copia lo storico
del conto attuale. Un solo processo possiede i writer nella nuova directory
privata; lock esclusivi impediscono due writer. Non si rivendica una
separazione per tabella SQLite: tutte le tabelle del singolo file appartengono
al medesimo runner. Nessun DB dei conti esistenti è aperto.

Il witness conserva disponibilità e persistenza, quindi `input.sqlite` registra
un envelope append-only con hash e sequenza. Ogni braccio consuma esattamente
quell'input e registra il proprio cursore **nella transazione che cambia stato**.
Un arresto dopo un solo commit lascia una consegna parziale visibile:
al riavvio si completano i bracci mancanti senza ripetere quelli già committati.
I retry usano l'ora corrente; non recuperano ingressi storici scaduti.

File assenti, identità/bundle cambiati, symlink, chain corrotta e guasti dello
storage bloccano il processo; nessun reset del conto. Un crash dopo un fill
committato ma non confermato conserva posizione/fill e attiva l'integrity halt.
I quattro bracci possono divergere per esposizione, rischio, latenza e mancati
fill: non si forza artificialmente un trade comune.

## Direzione, protezioni e funding

LONG compra ask e vende bid; SHORT vende bid e compra ask. Entrambi rispettano
gli stessi limiti, costi, warm-up, cutoff e latenza congelati. La quantità
intenzionata può solo diminuire. Lo stress segue le opportunità ammesse dal
proprio primario, ma usa posizione, prezzi, rischio, stop e scadenze propri.

Le chiusure sono latched: il residuo rimane EXIT_PENDING fino a un nuovo book
valido. Le riduzioni parziali non aumentano né invertono la posizione. Il
funding è firmato; la riconciliazione ai confini considera entrambe le direzioni
dei fill `EXIT`, inclusi i SELL che chiudono LONG. Tassi discordanti, mark tardivi
o mancanti restano pending; nessuno zero inventato. I costi stress restano avversi.

Il canale amministrativo accetta solo un file regolare root-owned, non
scrivibile da gruppo/altri, aperto senza seguire symlink e di dimensione limitata.
Il comando fissa conto, scenario primario/stress, position ID, generazione,
quantità massima corrente, nonce monouso e TTL 60 secondi. Consumo e intento
di chiusura sono atomici nel ledger. Non esiste un pulsante UI di trading o
uno scrittore di approvazioni; il modulo non genera decisioni dell'operatore.

## Valutazioni e review

`observe_grid()` ricostruisce la stessa griglia UTC per tutti i bracci usando
soltanto stato con commit già confermato e book con ricevuta di disponibilità
entro il cutoff. Un fill, prezzo o accredito arrivato dopo non entra nel punto
passato. Quote non fresche, funding provvisorio o stato non attestato rendono
il punto incompleto; non vengono interpolati né riscritti.

L'export include fill firmati, prezzi, fee, realizzato, funding, posizioni,
copertura e conteggi degli esiti degli slot. Il valutatore impone T1 dopo
90 giorni, quattro bracci, stesso seed e nessuna esposizione/funding irrisolti.
Verifica i minimi di attività e copertura e applica il bootstrap settimanale
appaiato a 10.000 repliche, seed 20261021 e quinto percentile nearest-rank.
Settimane parziali e senza trade restano incluse. La review reale prima di T1
è negata. L'override sintetico è accettato solo su export dichiarati test-only.

Il confronto rigetta griglie incomplete anziché riempire o cancellare buchi;
il solo superamento del minimo di copertura slot del 95% non basta se manca
la serie appaiata necessaria alla valutazione. Un esito sintetico positivo
prova il comportamento del classificatore, non la validità della strategia.
Nessuna classificazione abilita automaticamente un conto o il trading reale.

## Worker e confine dell'attivazione

`service.py` fornisce il worker locale e il gate, senza registrare servizi.
Per inizializzare richiede configurazione e ricevuta root-owned, T0 futuro
alla mezzanotte UTC, T1 esattamente 90 giorni dopo, identità dei due conti,
namespace distinto dalle fonti, riferimento all'accettazione dell'operatore
e hash completi del runtime. La ricevuta deve autorizzare esplicitamente
il solo paper sintetico e negare ordini reali, credenziali e grant operativi.
Un template o la promozione del classificatore non costituiscono tale ricevuta.
L'opzione di inizializzazione rifiuta una directory già esistente.

Senza autorizzazione il probe usa soltanto modalità prestart con T0 futuro:
al raggiungimento di T0 si ferma; non può convertirsi in conto attivo.
La prova pubblica legge i file già raccolti in RO e scrive soltanto un nuovo
namespace di evidenze, senza avviare collector o effettuare GET Internet.
Il worker autorizzato produce la proiezione nel proprio namespace; nessuna
route, pagina, unità systemd o configurazione Compose esistente è modificata.

Per la futura consegna in UI resta la scheda di avvio separata: scelta del
namespace operativo, ricevuta esatta approvata, packaging/mount dei soli nuovi
stati, inizializzazione comune, schedulazione, pagina e monitoraggio. Il T0
resta non impostato per l'esperimento ufficiale. Il warm-up di 289 slot dovrà
essere osservato realmente, senza trasformare i dati dei test in storia forward.

I minimi KuCoin rimangono UNKNOWN. Il contratto sintetico non modifica P0-03;
la presente qualifica non autorizza il percorso exchange-faithful.
