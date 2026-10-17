# Confronto UI: BTC intraday e quattro versioni V13

17 ottobre 2026 — consegna completata, solo visualizzazione paper.

La pagina `/v13_variants` include BTC intraday come quinto conto accanto a
Originale, FAST, HALF e M1 SHORT. Mostra equity, stato della raccolta iniziale,
numero di fill, data di avvio, costi e collegamento alla pagina `/btc_intraday`.
L’intraday parte da 10.000 USDT virtuali e non eredita lo storico V13.

Il grafico predefinito indicizza le cinque equity a 10.000 punti dalla prima
finestra condivisa disponibile nelle viste pubbliche. I riferimenti e gli
estremi finali appartengono agli stessi intervalli di cinque minuti; non sono
interpolati. Nessun riferimento precede l’attivazione intraday. La finestra può
avanzare quando cambiano le porzioni di storico esposte: è un confronto
descrittivo, non un nuovo benchmark scientifico fissato o a parità di rischio.
I pulsanti consentono anche la precedente finestra V13 e lo storico assoluto,
con capitali e date distinti espliciti. Il drawdown intraday non esposto dalla
vista è lasciato sconosciuto, senza ricostruzioni parziali.

Dati mancanti, identità errata, ritardi o contabilità incompleta sospendono il
confronto comune; le altre quattro versioni restano consultabili. I punti
intraday incompleti e i buchi oltre 30 minuti interrompono la linea.

## Verifica e consegna

- 13 gruppi di controlli browser in anteprima, comprese fixture con capitali
  differenti: rendimenti esatti +10%, -10%, 0%, +20% e +1%.
- Prove negative su assenza, scadenza, identità, contabilità, funding V13,
  finestre disgiunte e intervalli temporali non corrispondenti.
- Verifica live desktop/mobile: cinque schede e righe, tre modalità del
  grafico, quattro pagine V13 di dettaglio conservate, nessun errore JavaScript
  o overflow orizzontale. Verifiche eseguite dall’autore, non QA indipendente.
- Asset JavaScript HTTP 200 e MIME corretto su localhost e 127.0.0.1, SHA-256
  `a3ad5010d186f2c819cac23c38f9721a4b82bd78b419769b533acb7a10911477`.
- Candidato applicativo `d5a21169a86013b3e0fafe689324a69c0650b255`.
  Pubblicati soltanto il template e il JavaScript tramite asset già montati;
  nessun riavvio. Dieci container healthy con identità, avvii e contatori
  restart invariati rispetto alla rilevazione prima del lavoro.
- Conto intraday alla verifica: ACTIVE_WARMUP, equity 10.000 USDT, zero fill,
  25/289 osservazioni iniziali. Le osservazioni proseguono automaticamente;
  nessuna operazione è stata forzata per la consegna.
- Nessuna modifica a strategie, servizi, policy, grant, ledger o collector.
  Ordini reali assenti; minimi contrattuali KuCoin ancora UNKNOWN.

Evidenze locali conservate in `audit-evidence/intraday-comparison-20261017/`
alla radice del laboratorio: manifest degli asset e backup precedenti,
risultati browser, screenshot desktop/mobile e confronti runtime. Il ripristino
consiste nei due asset precedenti, equivalenti al commit
`4004dc1b774163fc385770d5ee1cf4e18785136d`, senza operazioni sui conti.

Schedine Development:

- UI: `work-card-950837e9-7cb2-4704-9d34-a87535fe104e`.
- Verifica: `work-card-f5806af2-cd61-451e-8fcf-2bec9bc53c57`.
- Consegna: `work-card-3bf4c78f-4b68-4067-ad53-f66067f6804b`.

Esecuzione SINGLE_AGENT; procedure MMTech baseline e tracciamento PM.
Stream esclusivo Development. Minuti attivi non riportati: non è stata
raccolta una misurazione affidabile separata dai tempi di attesa, né viene
inventata una ricostruzione retroattiva. Nessuna attività residua per questa
richiesta UI; restano le osservazioni scientifiche già pianificate.
