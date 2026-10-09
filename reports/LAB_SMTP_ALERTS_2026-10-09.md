# Avvisi SMTP del laboratorio — 9 ottobre 2026

Scheda `work-card-575258a8-ad83-45b7-ae2d-630cb57959b3`.
Integrazione richiesta dal proprietario, con account e password per app
forniti tramite file privato. Nessun identificativo personale o password
in questo report, nel codice o nel commit.

Il notificatore separato legge soltanto `resource-monitor/status.json` e scrive
il proprio stato SQLite nella directory `mail-alerts` sul disco del laboratorio.
La password è caricata da systemd tramite LoadCredential in un file temporaneo
privato; il monitor rimane privo di credenziali e senza rete IP. Il notificatore
usa SMTP STARTTLS con verifica del certificato prima del login.

`trading-lab-mail-alerts.timer` esegue il controllo ogni cinque minuti, al minuto
successivo al campionamento del monitor. Un incidente apre una segnalazione;
la scomparsa degli allarmi produce un avviso di recupero. Nuovi aggiornamenti
sono distanziati di almeno 30 minuti; un problema invariato riceve un promemoria
dopo 24 ore. Lo stato persistente evita ripetizioni dopo il riavvio. La prima
mail di prova registra anche gli allarmi correnti, evitando un secondo invio
identico al primo giro del timer.

Se il monitor manca o è vecchio di oltre 15 minuti, viene segnalato come tale.
Se SMTP o SQLite falliscono, il servizio di notifica registra un errore senza
testo del server o segreti e riprova al giro successivo. Non modifica monitor,
collector, paper o protocolli. SMTP non garantisce esattamente un invio: una
connessione interrotta dopo l'accettazione del messaggio può rendere ambiguo
l'esito e causare un duplicato al tentativo successivo. La deduplicazione locale
copre gli invii con esito confermato.

Verifiche: 11 test complessivi monitor/notificatore; casi di riavvio, recupero,
cooldown, promemoria, guasto SMTP, monitor mancante/stale e TLS fallito prima
del login. Validazione systemd, esecuzione del servizio reale, stato SQLite
integro e timer attivo. La mail di prova è stata accettata dal server Gmail;
l'effettiva comparsa nella casella destinataria richiede riscontro del destinatario.
Allarme presente nella prova: occupazione elevata dello swap, senza attribuirla
automaticamente a thrashing o ai timeout Qwen.

Ricevuta tecnica senza segreti: `audit-evidence/lab-smtp-20261009/receipt.json`
nella radice del workspace. Credenziali e stato runtime restano fuori da Git.
