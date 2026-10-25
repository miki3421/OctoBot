# Revisione settimanale delle tecnologie open source del laboratorio

Regola richiesta dall'operatore il 25 ottobre 2026, richiamata dall'AGENTS.md
del workspace. Si applica almeno una volta ogni sette giorni, nel check
settimanale del lab. Consultare l'ultimo rapporto prima di ripetere la ricerca;
se manca o ha più di sette giorni, la revisione è da completare.

## Obiettivo e criteri

Verificare se le tecnologie attuali sono le più adatte all'obiettivo reale:
strategie robuste e profittevoli al netto di fee, spread, slippage e funding,
con rischio controllato, reazione al deterioramento e risultati riproducibili.
La notorietà, la novità o la dimensione di un modello non sono una prova di
utilità per questo laboratorio.

Esaminare soltanto le alternative pertinenti ai problemi osservati:

- segnali quantitativi, rilevamento del regime, modelli statistici e ML;
- selezione dei simboli, allocazione, sizing, uscite e gestione del rischio;
- raccolta e qualità causale dei dati, storage e adapter;
- simulazione di esecuzione, microstruttura e costi;
- validazione temporale, attribuzione, monitoraggio e spiegazione delle scelte.

Usare fonti primarie aggiornate: repository ufficiali, release, documentazione
dei progetti e articoli originali. Annotare versione/revisione e data della
consultazione. Distinguere licenza open source da soli pesi disponibili o
licenze source-available; verificare limiti di impiego commerciale quando
rilevanti. Rispettare le autorizzazioni vigenti per consultazioni e download.

Per ogni alternativa concreta valutare:

1. Quale difetto misurato del lab risolve e con quali evidenze.
2. Vantaggio rispetto alla tecnologia attuale sui nostri dati, inclusi costi,
   rischio, falsi segnali e capacità di reagire; separare ipotesi da benchmark.
3. Disponibilità causale degli input, rischio di leakage e riproducibilità.
4. CPU, RAM, eventuale GPU, latenza e spazio sull'hardware realmente disponibile.
5. Licenza, manutenzione, affidabilità, sicurezza e dipendenze.
6. Complessità d'integrazione, possibilità di rollback e vantaggio atteso
   rispetto all'effort. Considerare anche mantenere o semplificare l'esistente.

## Rapporto e conseguenze

Scrivere `reports/TECHNOLOGY_REVIEW_YYYY-MM-DD.md` nel fork. Il rapporto deve
contenere componenti esaminati, versioni/fonti, confronto sintetico, limiti
delle evidenze e decisione per ciascuna alternativa: mantenere, provare in modo
mirato, proporre sostituzione o scartare con motivo. Indicare la prossima
verifica entro sette giorni.

Quando emerge un miglioramento concreto, proporre un intervento piccolo e
verificabile sul problema prioritario, con risultato atteso e criterio di
successo. Il benchmark può usare copie offline e fixture tecniche; non aprire
un altro conto o confronto operativo senza richiesta dell'utente. Non
presentare un test riuscito come dimostrazione di profitto futuro.

Le autorizzazioni già date dall'operatore restano valide. La revisione non
conferisce nuove autorizzazioni a installare, scaricare, spendere, promuovere
modelli o modificare il runtime. Non crea da sola un job o servizio periodico:
definisce l'attività obbligatoria del check settimanale.
