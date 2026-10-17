# BTC intraday v2 — qualifica delle fonti causali

17 ottobre 2026. **Input ricevuti verificati sul prefisso ispezionato; conto non pronto all'avvio.**
Protocollo v2 invariato, SHA-256 `bbc19094ac23b8b13a0d82919802f2ede3787add5eda2e13f0f2d8489861493b`.

Finestra tecnica: **16 ottobre 13:00–17 ottobre 13:00 UTC**, 288 slot di cinque minuti,
preceduti da 24 ore di warm-up e 120 secondi di storia per il bordo iniziale.
Il periodo è stato fissato prima della misura. Non è una prova forward, un conto
paper o una valutazione di redditività. Nessun PnL o fill calcolato.

| Componente | Evidenza nel prefisso | Esito e limite |
|---|---|---|
| M1, 18 mark originali | 288/288 punti e finestre da 289 righe validi | Causalità sui tempi dichiarati, età entro 120s; un segnale ricostruito, nessun episodio economico valutato |
| L5 BTC | 288/288 finestre decisionali, arrivi e finestre d'ingresso validi | Tempi di ricezione conformi, limiti di freshness invariati |
| Calendario funding | 288/288 slot con annuncio osservato e fresco | Intervalli letti dai contratti, nessuna assunzione di otto ore fisse |
| Funding regolato | 3/3 eventi annunciati con tasso finale e mark precedente validi | Input per la stima di ricerca; non pagamento exchange certificato |
| Disponibilità/persistenza | Nessun timestamp storico di commit per evento/batch L5 | **Non dimostrata la scadenza di disponibilità richiesta dal futuro esecutore** |

## Copie, integrità e provenienza

La copia tecnica conserva **2.721 pacchetti**, 48.978 ricevute mark, 2.721 ricevute
contratti e 2.721 ricevute BTC di funding storico, con i raw e gli hash verificati.
Gli endpoint non necessari non sono stati qualificati. SQLite offline da 516.874.240
byte, `integrity_check=ok`; nessuno scan sul journal scalping live.
Hash database: `443c479689ddb48e8f3bb52fa14ffc29d4ff794275af0ace132f9107a6ebaa6e`.

L5 deriva dalla copia già qualificata `1141375eb294…`; indice segmenti e database
verificati per hash. Le evidenze complete restano sul disco dati, alias
`btc-intraday-source-qualification-20261017-v2-complete-prefix`, con ricevuta finale
che vincola tutti gli output. Anche la prima estrazione e il suo esito conservativo
sono preservati; il solo bordo del warm-up è stato completato senza cambiare
soglie o finestra. Non sono stati eliminati dati o journal.

## Il caso funding vicino al cambio d'ora

Alle 16:00 UTC del 16 ottobre il mark valido era stato ricevuto alle
15:59:58,996713, timestamp exchange 15:59:58. Il pacchetto multiasset si è concluso
alle 16:00:01,317142. Il mark è quindi precedente, ma il pacchetto completo no:
la distinzione è conservata. Quel dato può sostenere una riconciliazione successiva,
non una pubblicazione retrodatata. Gli altri due mark precedenti hanno età di 45 e
6 secondi, tutti entro il limite già fissato di 60 secondi.

I tre tassi finali sono stati osservati nei pacchetti circa 64,68, 21,68 e 61,41
secondi dopo l'evento nominale. Prima di allora restano pending: nessuno zero o
`current/predicted` sostitutivo. Le quantità del nuovo conto non esistono ancora,
quindi non è stato calcolato alcun cashflow funding.

## Cosa resta da fare

I raw permettono di verificare hash e coerenza dei tempi dichiarati dal custodian,
non di ricostruire il commit storico. Il collector L5 esegue commit periodici, ma
non registra quando ciascun batch diventa persistito/visibile: il secondo nominale
di commit e l'mtime non provano il deadline di ogni input.

Serve quindi una ricevuta **prospettica del consumer**: dati visibili/lettura
completata, identità del prefisso, clock e conferma di persistenza distinti dalla
ricezione exchange. Se tardiva o assente, il futuro simulatore non deve attribuirsi
un ingresso storico. Non occorre cambiare soglie o inventare prove per il passato.

Schedina To-do: `work-card-1a999de7-c39e-42ad-9929-e8bfda7fa708`. Il simulatore può essere preparato inerte usando
questi input; eventuale avvio richiede poi ricevute di disponibilità, prove del
simulatore e riesame del bundle esatto. Nessuna approvazione scientifica o operativa
è ereditata. I minimi reali KuCoin restano **UNKNOWN**, il mapping sintetico resta
esplicito; non è una prova di ammissibilità degli ordini.

## Verifiche e conservazione delle strategie

**42 prove interne superate:** 21 nuove e 21 dell'adapter L5 usato. Coprono futuro,
stale, hash alterati, duplicati JSON, warm-up incompleto, calendario mancante,
funding tardivo/discordante, distinzione fra ricezione e pacchetto, conservazione
degli output e stabilità dell'identità causale dopo append futuri.
Hash e tutti i confini temporali dei risultati ricontrollati su copie.
Nove container healthy con ID, avvio e restart count invariati. Nessun download,
installazione, riavvio, grant, nuovo conto o cambiamento a Originale, FAST, HALF,
M1 paper o osservazione M1.

Strumento: `octobot/ai_strategy_lab/btc_intraday_source_qualification.py`.
Metodo: `docs/BTC_INTRADAY_SOURCE_QUALIFICATION_V2.md`.
Schedine: `4cd8e105`, `efd1e408`, `e1d0fe15`, `7faade8a`.
