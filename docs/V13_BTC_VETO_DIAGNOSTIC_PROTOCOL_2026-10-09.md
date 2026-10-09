# Diagnostica BTC SELL/veto — piano prima del calcolo

Scheda `work-card-7d58d1a7-bcf5-4aa9-be63-edea482ac6a9`. Questo piano è fissato
prima del calcolo dei controfattuali, ma DOPO aver osservato il ribasso: è
ricerca esplorativa, non preregistrazione di validazione.

Input: copie SQLite coerenti del paper e delle approvazioni del 9 ottobre,
ricevute pubbliche già conservate, pesi originali, grafici e mark osservati.
Nessuna nuova acquisizione, ordine, grant, modifica al paper o outcome sigillato.

## Causa del SELL

Confrontare il ribilanciamento del 29 settembre con quello del 6 ottobre.
Riprodurre i pesi con la formula originale e la covarianza a 60 giorni; misurare
separatamente l'effetto dell'universo attivo e della covarianza. Separare i
target dalla quantità arrotondata: una vendita di un contratto può amplificare
visivamente una variazione molto inferiore del peso teorico.

## Trigger diagnostico e bracci

Il trigger è una diminuzione del target BTC positivo rispetto al precedente
target strategico positivo. Si usa il target contemporaneo dell'issuer, non
la posizione del marker nel grafico o il minimo successivo. Il primo evento
eseguibile è il batch con book successivo all'issuer, già presente nel ledger.
Non si cercano soglie percentuali che massimizzino questo episodio.

- Baseline: conto V13 effettivo.
- Veto ingressi: durante il veto scartare tutti gli aumenti long e le riaperture,
  lasciando le riduzioni previste dalla baseline, senza inversioni.
- Veto più uscita: al batch del trigger chiudere i long esistenti sul book
  pubblico conservato; poi mantenere il veto ingressi.
- Controllo logico: il veto basato sul momentum BTC negativo non si attiva
  se il momentum resta positivo. Non confonderlo con il trigger di allocazione.

Il veto resta valido fino al successivo ricalcolo strategico con nuovi pesi.
Prima della fine della copia non si assume quale sarà quel ricalcolo.
Le quantità degli ordini successivi sono quelle realmente osservate nella
baseline, limitate alla posizione residua. Si tratta di un esperimento a
ordini abbinati, non di un nuovo backtest con equity e target ricalcolati.

Usare gli stessi prezzi dei fill solo quando la quantità coincide; quantità
diverse e chiusure aggiuntive richiedono VWAP dal book conservato, slippage
avverso 2bps e arrotondamento al tick. Verificare capienza del book. I minimi
sono quelli dichiarati dal contratto di simulazione di ricerca; i minimi reali
KuCoin restano UNKNOWN. Non dichiarare ammissibilità exchange-faithful.

Funding: rate liquidate già registrate e medesimo mark precedente stimato,
applicate alle quantità controfattuali ai rispettivi regolamenti. Non introdurre
tassi zero quando una posizione è ancora aperta. Un braccio che resta flat ha
legittimamente funding nullo dopo la chiusura. Ogni posizione controfattuale
deve restare compresa tra zero e la posizione long della baseline.

Output: equity e drawdown osservati, differenze per simbolo, fee/funding,
operazioni scartate, errori di riconciliazione e limiti. Confrontare BTC con
gli altri asset già presenti: se tutti riducono il peso contemporaneamente,
il veto BTC non identifica necessariamente informazione specifica su BTC.

Nessun short simulato in questi bracci: convertire riduzioni in short richiede
un esperimento distinto con ingresso, size, uscita, durata e costi espliciti.
