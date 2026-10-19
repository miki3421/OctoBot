# Navigazione laterale del Trading AI Lab

19 ottobre 2026 — consegna UI completata.

Sidebar comune su nove template standalone, per 15 percorsi del laboratorio.
Quattordici destinazioni sono organizzate in Conti paper, Confronti, Grafici
e Ricerca. La vista alternativa Originale viene riconosciuta come alias del
conto V13. La pagina corrente è evidenziata con `aria-current`.

Su desktop il menu resta a sinistra, con scorrimento indipendente. Sotto
1.100 px diventa un pannello richiamabile dal pulsante Menu: chiusura con
pulsante, sfondo o Esc, gestione del focus e contenuto retrostante inerte
soltanto durante l’apertura. Sono presenti un link per saltare al contenuto e
supporto alla preferenza di movimento ridotto. I collegamenti contestuali
esistenti restano disponibili. Il layout storico OctoBot/archivio mantiene
la propria interfaccia; la modifica riguarda le dashboard autonome del lab.

Implementazione condivisa: un partial Jinja, CSS e JavaScript locali, con
hash negli URL degli asset. Nessuna libreria, font o download aggiuntivo.
Nessuna modifica a route, login, profili, API, strategie, policy o ledger.

## Verifiche e consegna

- Browser in anteprima e live: 15 pagine HTTP 200, link e selezione attiva,
  alias Originale, desktop e mobile 390 px senza overflow orizzontale.
- Tastiera: focus iniziale nel pannello, ciclo Tab/Shift+Tab, Esc e ritorno al
  pulsante Menu; chiusura sullo sfondo e sul pulsante, navigazione effettiva
  al conto intraday e passaggio desktop/mobile verificati.
- Layout desktop aggiuntivi a 1.100 e 1.280 px. Valori e grafici delle viste
  paper caricati; screenshot desktop/mobile conservati.
- Regressioni UI: 19 gruppi del confronto equity e 16 dello stato intraday
  superati con i nuovi componenti condivisi. Nessun errore JavaScript.
- `git diff --check` superato. Verifica interna dell’autore, non QA indipendente.
- Tutte le 15 pagine e gli asset locali referenziati verificati su localhost
  e 127.0.0.1: HTTP 200, MIME corretto, byte uguali al candidato.
- Dieci container healthy con identità, avvio e contatori restart invariati.
  Nessun riavvio, nuovo servizio, collector o grant.

Candidato applicativo `db2f892904924473ac0feff42364e9d3346d1a9a`.
CSS SHA-256:
`e92793965d0b5300287b183fda846ea43903df3727a5a6037bb6a7aa91d7333a`.
JavaScript SHA-256:
`b8b8e68c7e6321cf1e61fef26c1ba9454b3e87380470a8cf4067d4e9331888c2`.

Pubblicati prima i nuovi asset e il partial, poi i nove template attraverso
i mount già presenti. Backup, manifest, risultati browser, screenshot e
confronti runtime conservati in `audit-evidence/lab-sidebar-20261019/` alla
radice del laboratorio. Rollback: ripristinare i nove template dal commit
`339a1aeb4b2eecdb880e1083e8ed49f6bc9e28b8`; gli asset non referenziati possono
restare disponibili senza modificare i dati.

Schedine Development:

- Mappa: `work-card-68fca313-708c-4521-8efe-1d28abe42bc4`.
- UI: `work-card-ce01f6ae-99ee-4367-8f79-f22cd193c596`.
- Test: `work-card-2e120fbc-176a-4afc-879c-307abe60f464`.
- Consegna: `work-card-dfba0863-6780-4a6d-96c5-5f16fb869504`.

SINGLE_AGENT, MMTech baseline e tracciamento delle schedine. Stream esclusivo
Development. Tempo attivo non riportato perché non misurato separatamente
dalle attese; nessuna ricostruzione inventata. Nessun residuo per questa UI.
