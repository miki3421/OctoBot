# Qwen BTC shadow V2 — bundle candidato, non attivo

29 settembre 2026. Esperimento `qwen-btc-direction-shadow-v1`, nuova lineage
forward distinta dalla qualificazione V1 sintetica. Card implementazione
`work-card-ef81ac4d-1ff5-4693-94ce-98228018e69a`; UI
`work-card-a21f31fc-0da2-42bd-afdb-5894516fa76d`; verifiche autore
`work-card-e9bee595-96b1-4f79-ad0a-4b28a1f9a4bc`; consegna
`work-card-e3fc1208-cdde-4e4f-a8ee-8afc5433feb9`.

## Decisione concreta proposta

Approvare per **questo solo challenger research-only** la preregistrazione
`QWEN_SHADOW_FORWARD_PREREGISTRATION_CANDIDATE_V1.md`, gli artefatti e
l'ambiente identificati dal manifest/bundle V2, le GET pubbliche indipendenti
KuCoin Classic Futures XBTUSDTM e il calendario seguente. Il bundle rimane
PREPARED finché la decisione non è registrata. Nessun avvio è implicito nella
qualificazione o nella pubblicazione della pagina.

- Primo slot candidato: **3 ottobre 2026, 00:10 UTC** (02:10 Italia).
- 180 slot giornalieri; ultimo slot **31 marzo 2027, 00:10 UTC**.
- Ultima acquisizione/maturazione: **1 aprile 2027**; review unica da
  **2 aprile 2027, 00:30 UTC**.
- Una GET al giorno alle 00:11, senza credenziali/proxy/redirect; decisione
  alle 00:12, termine 00:20. Recupero alle 00:21 scrive solo MISSING;
  maturazione alle 00:22 usa esclusivamente la cattura del giorno successivo.
  Nessuna rigenerazione, backfill, estensione o tuning in corso d'opera.
- Qwen già installato, CPU locale, artefatto UD-Q4_K_XL, temperatura 0,
  seed 13120, thinking disabilitato, 128 token, timeout client 35 secondi.
  Nessun download, installazione o spesa esterna. GGUF/server/template e
  prompt esatto sono identificati nel manifest. I checksum sono locali,
  non una verifica del distributore.
- Score direzionale close-to-close, non P/L. Astensione valida vale zero
  nello score; dati/outcome mancanti restano mancanti. Copertura minima
  170/180; per ramo 60 direzionali, almeno 20 LONG e 20 SHORT; media paired
  e limite inferiore CI bilaterale bootstrap >0, nessun conflitto/buco.
  Bootstrap calendario 180, blocchi circolari 14, 10.000 repliche seed13120.
  Un regime assente resta INSUFFICIENT. Un PASS richiede review umana.

Se la decisione o le prove di custodia arrivano troppo tardi, si propone un
nuovo calendario **prima** dei dati e si rigenera il bundle: nessuno slot
viene anticipato o retrodatato. La data candidata non è il Day 1 del BTC
ufficiale V2.2. Il contratto scientifico originale non viene modificato.

## Custodia minima e confini

Unità candidate in `deploy/qwen-shadow-v2/`, verificate ma **non installate**.
Stage root-owned `/opt/qwen-btc-shadow-v2` con file 0444 e lock di hash.
Dati separati `/srv/qwen-btc-shadow-v2`, root755; ruoli numerici candidati,
predisposti come account locked/nologin per le prove di custodia; nessun
timer o directory dati forward è attivato:

| Ruolo | UID | Directory propria / gruppo lettura | Accesso consentito |
|---|---:|---|---|
| Collector | 30917 | archive / 30922 | RW raw/receipt; sole GET pubbliche, loopback negato |
| Writer | 30918 | journal / 30921 | RW shadow-forward.sqlite; RO archive, rete solo loopback Qwen |
| Outcome/evaluator | 30920 | outcomes / 30923 | RW outcomes.sqlite, RO archive/journal, rete privata |
| Publisher | 30919 | published / 30919 | RW status.json, RO journal/outcomes, rete privata |
| Web UI | esistente | mount published:ro | Solo proiezione chiusa, nessuna inferenza o lettura DB |

Directory dati 2750 con owner del ruolo e gruppo indicato; file 0640,
UMask0027. Gruppi di lettura: writer30922; outcome30921+30922;
publisher30921+30923. Nessun gruppo operativo V13/BTC o docker. Le unità
limitano ulteriormente mount/percorsi, filesystem in sola lettura e rete.
I filesystem separano **file**, non tabelle SQLite. Il collector non scrive
il journal; il writer non scrive outcome; nessun processo strategy/LLM scrive
approvazioni, claim, ledger, kill/control o credenziali.

Raw e receipt sono create con O_EXCL e fsync, senza sovrascritture. Tentativo
GET persistito prima della rete; un guasto resta visibile, senza retry.
Hash raw/tempi separati dall'identità delle sole 121 barre causali. Entrambi
i rami condividono observation_id. Reservation persistita prima del modello;
SQLite synchronous FULL e record hash-chained, append-only. Storage non
scrivibile prima dell'inferenza impedisce la chiamata; guasto dopo la
chiamata conserva la reservation, poi Qwen MISSING senza rigenerazione.
Il collector custodisce le acquisizioni: è un ruolo di acquisizione fidato,
non una firma crittografica dell'exchange o prova di trasparenza globale.

L'outcome conserva il close origine della decisione e usa solo raw/receipt
indipendenti del giorno di maturazione. MISSING non viene riparato con
acquisizioni posteriori. L'evaluator verifica la derivazione, il registro,
la copertura e il cutoff **prima** di aprire i dati. Non autorizza nulla.
Il publisher espone solo stati, motivi da enum, latenza, integrità e
conteggio maturità. Nessun close futuro, score, hit rate o confronto arriva
alla UI, neppure dopo la review; il report scientifico è un artefatto offline.
La custodia protegge dagli utenti di servizio; root rimane autorità fidata.

## Attivazione subordinata alla decisione

1. Registrare la decisione sul **digest esatto** del bundle, protocollo,
   calendario e GET indipendenti prima del primo slot. Non creare grant.
2. Verificare UID/GID predisposti, provisioning delle directory e permessi; qualificare ciascun
   ruolo con fixture sotto sandbox, replay da altro processo, guasto storage
   e letture/scritture vietate. Nessun test scrive i dataset ufficiali.
3. Root verifica GGUF e binario già identificati, stat prima/dopo, processo
   `llama-moe` e socket loopback. L'API espone nome/ftype/build/template,
   **non** un digest attestato del GGUF in memoria: il binding del modello
   richiede la custodia root del processo e del file, non solo `/props`.
   Nessun riavvio del modello. Se l'identità cambia, fermarsi/refreeze.
4. Installare solo unità shadow candidate e stage dopo verifica completa
   dei pin. Decisione root-owned `/etc/qwen-btc-shadow-v2/activation.json`
   0440, schema chiuso: status `APPROVED_SHADOW_FORWARD_ONLY`, manifest_sha256,
   lineage, public_gets_authorized=true, approved_at, bundle_sha256.
   Assenza/mismatch, UID errato, clock NTP non sincronizzato o artefatti
   cambiati negano il runtime prima di acquisizione/inferenza.
5. Verificare ogni ruolo reale e clock; abilitare solo i cinque timer shadow.
   La UI leggerà una proiezione recente in stato WAITING. Non anticipare
   lo slot. Persistent al riavvio non permette una nuova previsione tardiva.
6. Verificare Day 1 e tenere visibili errori/copertura; report scientifico
   soltanto al cutoff preregistrato. Non chiamare la verifica autore review
   indipendente, non riciclare risultati sintetici come osservazioni forward.

V13 paper originale, observer editoriale Qwen e ricerca BTC ufficiale restano
separati. Non si leggono raw/journal/outcome del BTC sigillato. Minimi KuCoin
UNKNOWN, P0 integri, nessun ordine reale o nuova approvazione paper.
