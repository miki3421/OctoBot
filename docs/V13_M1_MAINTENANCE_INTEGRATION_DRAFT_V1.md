# M1 — preparazione della manutenzione sul conto esistente

Stato: **bozza non attiva**, 23 ottobre 2026. Scheda
`work-card-026c44e2-f248-41ac-aa1f-da68db8f1e98`.
Il runner, il ledger e la policy M1 non sono modificati. L'Originale resta il
riferimento. Nessun nuovo conto, universo o servizio viene attivato.

## Decisione da rendere operativa in una fase successiva

La fotografia del 23 ottobre propone AAVE LONG da 2,61 a 1,30 e LTC LONG
da 8,20 a 4,10. Sono quantità di ricerca da rivalutare all'attivazione,
non istruzioni di vendita correnti. I profitti SHORT osservati sui due
simboli rendono impropria la loro eliminazione indistinta.

Il contratto candidato separa due controlli sul solo conto M1:

1. **Tetto LONG persistente**, espresso in quantità del sottostante. Il
   target ordinario è il minimo fra baseline causale e tetto. Se la baseline
   scende ancora, il tetto scende con essa. Un successivo rialzo del target
   non riacquista la quota rimossa. Il tetto può risalire soltanto con una
   nuova decisione di manutenzione, registrata e versionata. Un tetto sceso
   a zero resta zero fino alla revisione: è una scelta candidata da approvare.
2. **Budget SHORT indipendente dal LONG ridotto**. Per i soli simboli oggetto
   della manutenzione si conserva un massimo di quantità SHORT distinto,
   fissato e verificato all'inizio dell'epoca. Nella prima proposta i valori
   indicativi sono 2,61 AAVE e 8,20 LTC. L'ingresso SHORT è limitato anche
   dalla baseline causale disponibile: una baseline che scende a 0,5 AAVE
   non autorizza 2,61 AAVE SHORT. Nessuna crescita automatica del budget.

Un passaggio da +1,30 AAVE a -2,61 AAVE richiederebbe un SELL di 3,91 AAVE:
1,30 chiude il LONG, 2,61 apre lo SHORT. Non deve essere scambiato per uno
SHORT di 3,91 o una semplice vendita del LONG. Il funding e le commissioni
devono restare attribuiti alle due parti. Il rientro dopo M1 riporta al
massimo al LONG consentito dal tetto, non alla baseline non mantenuta.

Il capitale liberato rimane cash e non aumenta altri simboli. Conservare un
budget SHORT non garantisce che venga utilizzato: quantità, mark, book,
funding, limiti di rischio e disponibilità degli input possono ridurre o
negare l'ingresso. Nessun nuovo accesso a leva o capacità oltre i limiti M1.

## Collegamenti da implementare prima dell'attivazione

- Identità dell'epoca: account M1, hash del ledger al boundary, fotografia
  approvata, configurazione e codice esatti. All'attivazione verificare che
  posizione e quantità siano ancora coerenti; non eseguire il vecchio report.
- Persistenza nello stesso `account.sqlite`, sotto la transazione già usata
  per stato, intent e fill: tetti correnti, budget SHORT, decisione e versione,
  evento d'attivazione. Migrazione con backup verificato e rollback senza replay.
- DAILY e REENTRY derivano i target attraverso il tetto. M1_ENTRY usa il
  budget separato invece della sola quantità LONG attualmente detenuta.
  EXIT e le riduzioni protettive continuano a chiudere le esposizioni effettive;
  non modificano o ricaricano i budget. Non ratchettare un tetto LONG da una
  quantità SHORT transitoria dell'overlay.
- Scadenza delle revisioni: nessuna riapertura o rimozione automatica del
  tetto. Una revisione mancante deve essere visibile; dati o policy mancanti
  negano nuovi aumenti e conservano le riduzioni protettive.
- Limiti M1 invariati: perdita giornaliera 2%, drawdown 10%, 31,5% per asset,
  90% totale, massimo un episodio M1 al giorno, tenuta 6 ore e cooldown 6 ore,
  massimo tre aumenti di rischio al giorno e 22 ore fra ribilanciamenti ordinari.
  Il limite va applicato all'esposizione finale, distinguendo chiusura LONG
  e nuova esposizione SHORT. Nessun reset al riavvio.
- Pubblicare stato dell'epoca e decisioni nella proiezione M1. La UI deve
  distinguere proposta, approvata, eseguita, ridotta o rifiutata con motivazione.
  Questa pagina di sola lettura non crea approvazioni.

## Prototipo verificabile, separato dall'esecuzione

`octobot/ai_strategy_lab/v13_m1_maintenance_preview.py` contiene una funzione
pura che mostra i target candidati per NORMAL, REENTRY e M1_ENTRY. Non è
importata da alcun runner, non legge/scrive file, non gestisce uscite né
dispone di interfacce d'ordine. Restituisce sempre `active=false` e
`execution_authorized=false`. Non simula che il gate di rischio sia già passato.

I test della funzione coprono mantenimento dei tetti, target successivi più
alti o più bassi, budget SHORT preservato dopo riduzione, rientro limitato,
baseline deteriorata, zero persistente, isolamento degli altri simboli e
input non validi. Non sono prove del runner integrato o di restart reale.

La successiva integrazione richiede test di transazione e riavvio, crash fra
intent e commit, replay/idempotenza, policy o epoca alterata, scadenze,
esecuzione parziale e gap di mercato/funding. Va verificato che un nuovo DAILY
non ricompri la quota e che il budget SHORT resti verificabile attraverso
due episodi e un riavvio. Questi controlli restano nella scheda test operativi
`work-card-967ffe12-bdb1-4636-a422-20b5ff81e075`.

La preparazione non decide se le riduzioni migliorino il rendimento: il
campione è ancora breve e condizionato dai DAILY mancati del 18–19 ottobre.
I minimi reali KuCoin rimangono UNKNOWN. Nessuna modifica a P0-03, alla
quarantena, a grant o alle strategie Originale, FAST, HALF e osservazione M1.
