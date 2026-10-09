# Qwen osservatore V13 — contratto V1

29 settembre 2026. Autorizzazione utente: «implementiamolo allora», dopo la
prova del modello locale già caricato. Scope: spiegazione del conto V13 paper
di ricerca esistente. Nessuna strategia LLM, proposta, promozione scientifica
o autorizzazione d'ordine. Questo contratto aggiunge un osservatore separato;
non riscrive l'HLD storico né i protocolli BTC sigillati.

Card contratto: `work-card-221c9a30-4a81-4e9d-b73c-d9b985c0ff75`.
Implementazione: `work-card-76a235d2-9b79-4250-86f8-ce6f24f81433`.
Test autore: `work-card-73767dab-cc0a-4809-b3fb-d9e2af9eacbd`.
Consegna: `work-card-7cf6d48f-4d9d-4791-9c1c-1eb694506f3b`.

## Contratto congelato prima delle nuove richieste

L'API UI genera uno snapshot ristretto del solo V13 multiasset di ricerca:
modalità, stato verificato, vincolo agli ingressi, contatori, funding stimato
e minimi reali UNKNOWN. Non include prezzi, saldi, storico, posizioni,
decisioni, note libere, credenziali o alcun dato BTC 30/120. Le frasi sono
prodotte da un adattatore deterministico con vocabolario chiuso. L'hash dello
snapshot identifica questi fatti, non il payload completo del conto.

Il modello sceglie 3–5 identificatori di fatti, includendo sempre modalità,
stato e vincolo agli ingressi. L'output è soltanto `evidence_ids`; non può
produrre stati, numeri, target o autorizzazioni. La spiegazione visualizzata
usa esattamente le frasi associate agli identificatori verificati. È una
selezione editoriale assistita da LLM, non una diagnosi libera o previsione.
La grammatica JSON vincola la forma; il validatore controlla autonomamente
schema, unicità, riferimenti e fatti obbligatori. Nessun testo del modello
viene interpretato come HTML, comando o decisione.

Modello esistente: Qwen3.6-35B-A3B UD-Q4_K_XL, alias `moe-private`, servito
da llama.cpp su loopback 8090. Nessun avvio, modifica o installazione del
modello. Sampling: temperatura 0, seed 13120, thinking disabilitato,
massimo 128 token. Endpoint fisso, senza proxy, redirect o tool. Timeout
globale client 35 secondi; servizio oneshot massimo 50 secondi. Se lo slot
condiviso è occupato, si salta la richiesta: nessuna coda intenzionale.

## Isolamento e disponibilità

Un UID dedicato legge solo l'API dello snapshot UI e il servizio Qwen su
loopback; non è membro dei gruppi di trading. Sorgenti root-owned in `/opt`,
home protette, filesystem read-only salvo la propria directory di output.
Nessun mount dei journal, approvals, ledger, control o ricerca BTC. Il server
Qwen preesistente resta un servizio separato; gli si inviano soltanto i fatti
ristretti. Nessun accesso aggiuntivo ai file è concesso al modello.

Timer ogni 10 minuti. La UI legge soltanto la cache pubblicata, mai invoca il
modello. Prima di pubblicare si rileggono i fatti: una variazione durante
l'inferenza invalida il commento. La UI nasconde commenti più vecchi di 15
minuti o riferiti a fatti diversi. Busy/offline, schema invalido e guasto
storage rendono il pannello indisponibile; non modificano il conto e non
bloccano l'executor. Scrittura atomica; errori preservati nel journal del
servizio, senza prompt operativi. Nessun fallback a cloud o Ollama.

## Qualificazione e limiti

Nuovi casi sintetici preregistrati prima dell'inferenza: cooldown, limite
perdita, dati scaduti, conto assente, nota con injection e campi vietati.
Tutti gli esiti e tempi sono conservati. Il benchmark precedente resta 3/5
rispetto al suo contratto originale: nessuna modifica retroattiva degli
oracoli. I test del nuovo schema dimostrano selezione di fatti e isolamento,
non comprensione generale, affidabilità predittiva o ammissibilità KuCoin.

Il timer viene abilitato soltanto nella successiva card di consegna, dopo le
prove del contratto e dell'implementazione. Minimi KuCoin UNKNOWN,
exchange-faithful BLOCKED, policy approvata e ricerca BTC sigillata invariati.
