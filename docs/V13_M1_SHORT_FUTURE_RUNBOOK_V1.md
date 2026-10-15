# Procedura M1 SHORT futuro — preparazione v1

Stato della consegna del 15 ottobre 2026: PREPARED_NOT_STARTED. Nessun servizio installato o avviato. Eseguire i comandi di avvio soltanto nell'ambito di una successiva attivazione osservativa esplicita. Non crea ordini o autorizzazioni.

## Identità e dati

Usare il bundle `docs/research-protocols/v13-m1-short-preparation-bundle-v1.json` per verificare protocollo, registratore, valutatore e dipendenze. Il commit di confronto `ef45ce6f` è la sorgente storica della proposta; i file del nuovo bundle identificano la preparazione corrente. Il protocollo espone una lineage propria e validità UNASSESSED. Nessuna eredità di risultati o approvazioni.

Sorgenti locali già esistenti: ledger originale `octobot-local/v13-paper/research/execution/execution.sqlite`, writer UID 30914; archivi pubblici `octobot-local/v13-paper/research/source/market`, writer UID 30911. Lettura con `mode=ro` e `query_only`. Nessuna credenziale exchange o accesso ai database approvals. L'output fisso è esclusivamente `octobot-local/v13-m1-short-future-v1/`, sotto la radice workspace canonica. Nessun nuovo UID o ACL è stato creato.

Le finestre del segnale provengono dalle quotazioni originali già registrate e ricevute entro lo slot. Servono 289 punti contigui su griglia 5 minuti, con tutti i 18 simboli e quotazioni vecchie al massimo 120 secondi. Una storia pre-T0 può servire da warm-up; non fornisce outcome forward. Le catture d'ingresso/uscita conservano il database completo, poi il valutatore ricostruisce lo stato economico al tempo del book: non usa la riga `state` più recente per retrodatare posizioni.

## Controllo, avvio esplicito e raccolta

Dalla directory del fork, con l'interprete delle dipendenze già disponibili:

```bash
python3 scripts/v13_m1_future_observer.py check
python3 scripts/v13_m1_future_observer.py status
```

`check` convalida il bundle; `status` distingue preparazione e attivazione senza creare un conto. Lo stato corrente deve essere PREPARED_NOT_STARTED e activation=null.

Nel successivo incarico autorizzato di attivazione:

```bash
python3 scripts/v13_m1_future_observer.py start
```

Genera una sola ricevuta durevole. T0 è la mezzanotte UTC successiva; T1=T0+90 giorni. Richiamare `start` non sposta la frontiera. Un journal esistente o parziale non viene reinizializzato. Prima di T0, `tick` restituisce WAITING_FOR_FUTURE_T0.

```bash
python3 scripts/v13_m1_future_observer.py tick
python3 scripts/v13_m1_future_observer.py status
```

L'incarico di attivazione dovrà predisporre l'esecuzione di `tick` ogni minuto, con un solo writer, avvio al boot e verifica delle dipendenze. Questa preparazione non installa timer, servizi o loop. Il lock è un mutex di processo, non una prova di servizio attivo.

Ogni slot è fissato al primo input letto. SCHEDULED indica soltanto una futura cattura di ricerca, mai un ordine. Il book d'ingresso appartiene al campione successivo e deve precedere il suo slot, essere fresco e rispettare il ritardo minimo di 60 secondi dal segnale. Anche la ricevuta deve essere entro 120 secondi dallo slot. Il medesimo vincolo si applica all'uscita sei ore dopo.

Alla cattura vengono copiati ledger originale e book in `episodes/<id>/entry.*` e `exit.*`, con controllo integrità SQLite e hash. Nessuna variante paper viene scritta. Un secondo passaggio non deve cambiare una cattura già acquisita.

## Guasti e conservazione

- Slot non osservato: MISSED, senza ricostruzione di un segnale successivamente favorevole.
- Cattura ingresso/uscita scaduta: ENTRY_MISSED / EXIT_MISSED; non riempire in seguito il buco.
- Dato insufficiente: INSUFFICIENT_INPUT, nessun episodio. Nessun prezzo o funding mancante reinterpretato come zero.
- Errore storage o identità: processo in errore, nessuna decisione riuscita dichiarata. Conservare file e journal; risolvere il guasto e riprendere con la stessa identità.
- Copia presente senza ricevuta: pausa e review. Non cancellare o sovrascrivere l'evidenza per far passare il controllo.
- Durante un episodio o il suo cooldown non si arruolano altri episodi; un ingresso mancato mantiene il cooldown conservativo previsto.

Per un riavvio usare il journal già esistente. Non rimuovere file per ripartire con equity o contatori azzerati. Un cambiamento semantico richiede nuovo protocollo/versione/frontiera e conserva il vecchio periodo.

## Chiusura e valutazione

Il primo `tick` dopo T1 sigilla l'orizzonte e marca gli slot finali persi. Prima di T1 il valutatore rifiuta la valutazione finale.

```bash
python3 scripts/v13_m1_future_observer.py evaluate
```

Il valutatore controlla hash e input consumati, ricalcola M1, ricostruisce i tre casi dai ledger e dai book, include funding, costi e ripristino delle quantità comuni. I punti usati dal segnale devono essere presenti nel database d'ingresso con stessi prezzi e tempi. Una modifica retrospettiva del prefisso contabile, incluso funding tardivo che cambi lo stato iniziale, rende il caso irrisolto.

Sono conservati tutti gli episodi ammessi; dati mancanti non autorizzano una selezione dei soli casi favorevoli. Se l'originale non ha alcun long all'ingresso, NO_LONG_NO_INTERVENTION resta esplicito e non diventa un trade fittizio. Le somme per episodio non sono la curva di un portafoglio continuo.

I criteri candidati sono nel protocollo: 90 giorni, almeno 20 casi completi su 10 giorni e 8 settimane, 95% di slot validi, nessun episodio irrisolto, vantaggio paired e profitto short positivi anche con costi stressati. L'intervallo per blocchi settimanali è descrittivo; non trasforma episodi correlati in osservazioni indipendenti. Una classificazione positiva è soltanto CANDIDATE_FOR_FURTHER_REVIEW_ONLY e operational_approval resta false.

Controlli settimanali: stato, clock, copertura, catture, spazio, integrità e versioni. Nessuna selezione di nuove soglie dai PnL intermedi. Nessuna promozione automatica, chiamata all'issuer, modifica della quarantena o deroga ai gate. Minimi KuCoin reali UNKNOWN; il contratto di simulazione separato non è prova di ammissibilità exchange.
