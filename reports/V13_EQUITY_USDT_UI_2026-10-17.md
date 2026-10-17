# Confronto strategie: equity reale in USDT virtuali

17 ottobre 2026 — aggiornamento UI completato in seguito al feedback utente.

La vista iniziale di `/v13_variants` ora mostra il saldo effettivo dei cinque
conti, senza normalizzarlo a 10.000. Il pulsante **Equity · USDT**, il titolo,
l’asse Y e i tooltip distinguono il valore monetario virtuale dai rendimenti.
Le alternative **Rendimento % · tutti** e **Rendimento % · V13** espongono
percentuali su asse e tooltip, mantenendo i precedenti riferimenti temporali.
Non si mostrano più valori di indice come se fossero USDT.

Nella modalità equity, la tabella indica le variazioni dalla propria copia o
avvio, con periodi diversi espliciti. Le curve raw aggiungono l’ultima
valorizzazione realmente esposta dall’API, se successiva allo storico
sincronizzato, con il suo timestamp; non vengono interpolati punti né copiati
risultati tra conti. BTC intraday conserva il proprio avvio separato.

Verifiche dell’autore: 14 gruppi browser in anteprima, inclusi tooltip raw
110, 180, 50, 12 e 10.100 USDT da fixture e corrispondenti rendimenti +10%,
-10%, 0%, +20% e +1%; casi negativi preesistenti conservati. Smoke live
desktop/mobile e quattro pagine V13 di dettaglio OK, nessun errore JavaScript
o overflow orizzontale. `git diff --check` superato.

Candidato applicativo: `d8a857e898227489862c6271359701ec82596960`.
JavaScript SHA-256:
`5b4659e7191d9883c6f6809211d661ccccbc2fa5a45e4e15227ffb36ab16ec98`.
Asset HTTP 200, MIME JavaScript e byte corrispondenti su localhost e 127.0.0.1.
Dieci container healthy e invariati: nessun riavvio, modifica a strategie,
collector, policy, grant o ledger. Nessun ordine reale o nuova acquisizione
Internet. Evidenze e backup in `audit-evidence/equity-usdt-20261017/` alla
radice del laboratorio; rollback ai due asset del commit
`17e0475c3a12a0229fb33c997c74c052134f3bea`.

Schedine Development:

- UI: `work-card-99eefdda-e1d6-42a2-90c1-675a211914ad`.
- Verifica: `work-card-11e94126-7e54-4a78-a826-498fa6b8d87d`.
- Consegna: `work-card-e5cff038-1071-43d9-8e21-d134b1acb2a6`.

SINGLE_AGENT, MMTech baseline e tracciamento delle schedine; verifiche interne,
non QA indipendente. Stream esclusivo Development. Tempo attivo non riportato:
non misurato separatamente dalle attese, nessuna ricostruzione inventata.
Nessuna attività residua per questa modifica di visualizzazione.
