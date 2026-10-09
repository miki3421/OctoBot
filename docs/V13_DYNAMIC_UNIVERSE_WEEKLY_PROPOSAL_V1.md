# V13 selezione settimanale dinamica — proposta v1

8 ottobre 2026. Stato: **proposta pronta per revisione, non attivata**.
Scheda `work-card-1b971587-4470-459a-8410-ae638b397fe7`.
Identità candidata: `v13-dynamic-universe-weekly-research-v1`.

Obiettivo: verificare se selezionare settimanalmente un sottoinsieme dei 29
asset già individuati migliora il risultato netto della V13. Le soglie sotto
sono scelte progettuali proposte, non parametri ottimizzati né approvati.
La richiesta autorizza la preparazione; questo documento non attiva conti,
collector o autorizzazioni. La V13 attuale conserva conto e storico.

## Riuso e confronto

Riutilizzare mapping, ricevute e rosa di Candidate V13, storico acquisito e
qualifica 2–16 ottobre. La shortlist esistente ordina per turnover mediano:
non è un ranking di rendimento. Non modificare il protocollo fisso 18/29,
la sua ricevuta di approvazione o il valutatore della qualifica.

Proposta di estensione: aggiungere il braccio C ai due conti A/B pianificati,
prima del loro avvio. A = V13 sui 18 originali; B = V13 sui 29 fissi;
C = selezione dinamica fra gli stessi 29, massimo 18 simboli con segnale.
PEPE resta fuori; nessuna ricerca automatica di ulteriori coin.

Confronto primario **C meno B**: isola il valore della selezione rispetto allo
stesso insieme disponibile. C meno A è secondario e combina ampliamento e
selezione. Tutti partono flat con 10.000 USDT nello stesso futuro slot;
non confrontare il loro cumulato con quello del conto V13 oggi attivo.
Se A/B partissero prima di C, servirebbe un controllo B sincronizzato nuovo:
nessun riallineamento retroattivo dei risultati.

## Input e calendario causale

Una decisione ogni 7 giorni, con fase identica per tutti i bracci e ancorata
al futuro `start_utc`, ancora non fissato. Slot alle 00:10 UTC; il giorno D
usa solo barre daily fino a D−1, chiuse alle 00:00 UTC. Snapshot e ricevute
devono essere disponibili entro lo slot. Uno slot perso resta perso, senza
ricalcolo retroattivo. Una proposta valida si esegue solo su book successivo
all'intento persistito, con le stesse scadenze del contratto paper dei bracci.

Servono almeno 121 close positivi, finiti, contigui, con mapping verificato,
per tutti i 29 e BTC come indicatore di regime, anche quando BTC non è scelto.
Nessuna interpolazione. Byte raw e hash causale sono distinti: aggiungere
barre future non deve cambiare identità e risultato dello slot passato.

La qualifica completa deve superare i criteri già fissati prima dei fill;
il 16 ottobre è un cutoff, non un PASS garantito. Durante il confronto,
input comuni assenti, mapping invalido o mercato sospeso bloccano nuovo rischio
in tutti i bracci; non favorire C scartando soltanto il simbolo problematico.
Gestione protettiva delle posizioni già presenti separata e registrata.

## Punteggio e selezione deterministica

1. Calcolare il segnale originale V13 30/120, incluso il filtro BTC che
   consente short soltanto nel regime bearish previsto dal codice originale.
   Segnale zero esclude dall'allocazione della settimana. Non invertire un
   long in short perché il suo P/L è negativo.
2. Con `r30 = close[d]/close[d−30]−1`, `r120` analogo e `sigma60` deviazione
   standard campionaria (`ddof=1`) degli ultimi 60 rendimenti semplici daily,
   definire:
   `score = min(abs(r30)/sqrt(30), abs(r120)/sqrt(120)) / sigma60`.
   Sigma nulla/non finita rende il simbolo non selezionabile; se l'input è
   mancante o invalido si applica invece lo stop comune descritto sopra.
   Il punteggio misura persistenza normalizzata, non profitto previsto.
3. Ordinare per score decrescente; parità esatta risolta con simbolo canonico
   crescente. Congelare precisione numerica e librerie nel bundle prima del
   forward. Selezione iniziale: primi 18 con segnale, oppure tutti se meno.
4. Agli slot successivi conservare gli incumbent che hanno ancora segnale.
   Segnale zero comporta uscita obbligatoria dal set. Prima coprire i posti
   vuoti con i migliori esterni, poi confrontare miglior esterno e peggior
   incumbent. Sostituire soltanto se `score_esterno > 1.20 * score_incumbent`.
   Massimo **due ammissioni nuove per settimana**, comprendendo posti vuoti
   e sostituzioni. La prima selezione è esente; le uscite obbligatorie non
   sono limitate. Se il margine non basta, fermare le sostituzioni.
5. Un cambio di segno ammissibile sullo stesso simbolo non è una nuova
   ammissione. È comunque un'inversione economica: contabilizzare chiusura
   e riapertura, costo totale e gate di nuovo rischio, senza compensare i fill.

Se restano meno di 18 simboli, non riempire con segnali nulli. Se nessuno è
selezionabile, target zero. Il budget di rischio non va necessariamente tutto
investito; la stessa funzione V13 può però riallocarlo sui pochi simboli
rimasti entro i limiti originali. Nessuna garanzia che meno simboli significhi
meno esposizione o minore rischio.

## Pesi, rischio e costi

Calcolare segnali e covarianza sul pannello completo causale. In C azzerare
solo i segnali fuori selezione e passare la maschera alla funzione originale
`_target_weights`; non azzerare righe della covarianza. Conservare algoritmo,
lookback e gestione del regime V13. Target volatilità annua 13,5%, lordo
massimo 90%, massimo 31,5% per asset. La covarianza influenza il dimensionamento;
non aggiungere in v1 un ulteriore filtro di correlazione o un parametro per coin.

Riproporre simmetricamente le condizioni del confronto: stop nuovo rischio
a perdita giornaliera 2% o drawdown 10%, massimo un aumento al giorno UTC,
cooldown 22 ore, stato persistente ai riavvii. La loro configurazione sui
conti nuovi resta da approvare nel pacchetto di attivazione.

Simulare ogni gamba sul book osservato, VWAP entro profondità disponibile,
2 bps avversi e fee almeno 6 bps o taker pubblica se maggiore; funding firmato
esplicitamente stimato. Minimi del contratto di simulazione: un incremento
di quantità e 1 USDT; i minimi reali KuCoin restano UNKNOWN.
Quantità, fill parziali, ritardi e arrotondamenti si registrano senza fill
inventati. La lista selezionata è distinta dalle posizioni effettive.

Il limite di due ingressi e il margine del 20% riducono la rotazione, ma non
provano che i costi siano coperti. Nessuna conversione arbitraria di score in
USDT per dichiarare conveniente uno scambio. Riportare costi effettivi, turnover
e scenario diagnostico con fee/slippage tripli, senza usarlo per scegliere
nuovi parametri durante il forward.

## Valutazione e visibilità

Proposta: 180 giorni comuni, almeno 95% degli slot dati validi e almeno 20
decisioni settimanali comuni; altrimenti INCONCLUSIVE, senza estendere il
periodo per inseguire un risultato. Primaria: differenza di rendimento netto
C−B. Secondarie: C−A, drawdown, esposizione, concentrazione, costi, turnover,
funding e contributi per simbolo. Posizioni/fill non sono campioni indipendenti.

C merita ulteriore ricerca se C−B è positivo, C è positivo e il suo drawdown
non supera B di oltre 2 punti percentuali; non equivale a validità dimostrata.
Riportare intervallo bootstrap appaiato a blocchi di 7 giorni, 10.000 repliche,
seed 13029, percentile 95%, come nel disegno esistente. Dichiarare che questa
è un'ulteriore ipotesi nella famiglia V13: nessuna pretesa di significatività
globale o promozione automatica. La visione dei P/L attuali ha motivato l'idea;
non è evidenza fuori campione a suo favore. Storico disponibile = sviluppo.

UI: tre curve con origine comune, graduatoria settimanale, score, segnale,
incumbent/candidato, motivo di mantenimento/esclusione, posti vacanti,
selezione teorica versus fill, costi, timestamp e prossima decisione.
Monitoraggio operativo quotidiano; risultati intermedi descrittivi senza
ritoccare soglie o decretare in anticipo il vincitore.

## Accettazione e sequenza di implementazione

Esempi da collaudare su fixture: incumbent score 1,00 ed esterno 1,19 non
cambiano; 1,21 consente sostituzione se resta budget; 1,20 esatto non basta.
Tre incumbent senza segnale escono tutti ma entrano al massimo due nuovi.
Uno short forte senza regime BTC ammesso è escluso. In input identici,
ordine delle righe e riavvio non cambiano selezione o duplicano il fill.

| Passo | Criterio di consegna |
| --- | --- |
| Regola candidata (questa scheda) | Algoritmo, limiti, confronto e decisioni espliciti; controllo documentale, nessun risultato economico calcolato |
| Adapter e selettore offline | Parità A/B con V13 quando la maschera non restringe; snapshot causali, stato delle selezioni e nuova lineage versionati |
| Test | Future data invariance, warm-up, gap, regime short, pareggi, limite cambi, costi/inversioni, restart e storage failure |
| Dashboard e attivazione | Qualifica verificata, conti isolati, bundle congelato, fonte autorizzata, policy e piano acquisizioni definiti, data comune fissata |

Prima dell'attivazione l'owner decide sulla regola candidata (18 posti,
score, 20%, due ammissioni), sull'aggiunta C al confronto A/B e sulle condizioni
simmetriche dei tre conti. Si può intanto implementare e testare il candidato
offline senza trasformare queste proposte in configurazione operativa.

Riferimenti: `V13_UNIVERSE_COMPARISON_PROPOSAL_V1.md`, relativa ricevuta owner
e `contracts/v13-universe-qualification-activation-20260930.json`;
`v13_candidate_shortlist.py`, `v13_universe_view.py`, `trend.py` e
`diversified_trend_cointegration_forward_runner.py` nel laboratorio.
