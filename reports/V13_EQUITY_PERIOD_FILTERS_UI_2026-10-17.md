# Filtri temporali del confronto equity

17 ottobre 2026 — consegna UI completata.

La pagina `/v13_variants` offre **24 ore**, **7 giorni** e **Tutto lo storico**.
Il filtro ritaglia le sole osservazioni disponibili, senza normalizzare o
ricalcolare i saldi USDT. Le finestre recenti terminano all’ora corrente e
includono il punto esatto del cutoff; lo storico mostra tutti i punti esposti
dalle API. Il conto intraday più recente non viene esteso artificialmente.

Il periodo è indipendente dalla modalità equity/percentuale e rimane
selezionato durante refresh automatici e cambi di modalità. Le percentuali
mantengono il proprio riferimento: il filtro modifica solo la porzione visibile.
Schede e tabella non cambiano a seguito del filtro. Nei periodi senza dati il
canvas e il tooltip vengono puliti, con un messaggio esplicito, senza saldi
zero inventati. I buchi nello storico restano visibili.

Verifiche dell’autore: 19 gruppi browser in anteprima, comprendenti cutoff
inclusivi a 24 ore e 7 giorni, importi USDT intatti, refresh, copertura breve,
periodi vuoti e ripristino dello storico; tre gruppi smoke live desktop/mobile,
quattro pagine V13 di dettaglio preservate, nessun errore JavaScript o overflow.
`git diff --check` superato. Verifica interna, non QA indipendente.

Candidato applicativo `8448607c22e6d8da3028e9ea89fc475027f8a910`.
JavaScript SHA-256
`c35d32012546dce755aad8393bb386f9266305869682f1ea345a40078238200a`.
HTTP 200, MIME e contenuto confermati su localhost e 127.0.0.1.
Dieci container healthy e invariati, nessun riavvio; nessuna modifica a
strategie, collector, policy, grant o ledger, nessuna nuova acquisizione di
mercato o installazione. Backup, manifest e risultati conservati in
`audit-evidence/equity-period-20261017/` alla radice del laboratorio.
Rollback: i due asset UI del commit `6bd75272f5d6236137bfdc9a38e78dc36fa95421`.

Schedine Development:

- UI: `work-card-291ac049-48fb-48c4-8319-f865a8b6cd28`.
- Verifica: `work-card-68daa413-c733-4f01-b80e-01241b006c51`.
- Consegna: `work-card-7b70fba4-b7cf-4947-966b-e204142c141e`.

SINGLE_AGENT, MMTech baseline e tracciamento delle schedine. Stream esclusivo
Development; tempo attivo non riportato perché non misurato separatamente
dalle attese, nessuna ricostruzione inventata. Nessun residuo per questa UI.
