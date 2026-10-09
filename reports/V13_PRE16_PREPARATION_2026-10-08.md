# V13 A/B/C — preparazione anticipata e verifica funding

8 ottobre 2026. Preparazione statica completata; conti A/B/C non attivi.

| Lavoro | Esito |
| --- | --- |
| Continuità funding disponibile | 232/232 ricevute valide, 29 simboli, 14:10–14:50 UTC; nessun gap |
| Riconciliazione storico pubblico | 29 risposte HTTP200 con data:null; indisponibilità esplicita, nessuno zero sostitutivo |
| Warm-up separato | 3.509 barre verificate, 121 per simbolo fino al 30 settembre, ricevute oggi |
| Identità e permessi | UID 30931/30932/30933 assegnati, shell nologin, gruppi read-only; matrice Unix/SQLite passata in isolamento |
| Collegamenti statici | Lineage, percorsi, immagine locale fissata, configurazioni DRAFT e tre unità non installate |
| Archivi | Input forward e intenti vuoti, integrity_check ok; nessun ledger/nuovo conto |
| Test | 118 test offline superati; controllo host e sintassi systemd positivi |

La verifica funding è diagnostica, non una certificazione di copertura: nella
finestra analizzata non è ancora maturato il primo regolamento annunciato.
Il nuovo verificatore confronta ricevute prospettiche e storico separato,
rileva missing, eventi inattesi, hash alterati, duplicati e tempi incompatibili.
Non emette calendari approvati e non certifica il prezzo mark.

Il warm-up non modifica né retrodata il forward o la qualifica. L'archivio
originale della qualifica mantiene permessi e binding: le tre nuove identità
non vi accedono. Prova dei permessi svolta su fixture isolate con gli UID reali,
senza scrivere dati sintetici negli archivi predisposti.

Consegna: `docs/deployment/V13_ABC_PRE16_HANDOFF.md`, piano inattivo v2 e
bundle v8. Evidenze in `audit-evidence/v13-pre16-20261008/` alla radice del lab.
Schede ad198a58 (funding), 4967bd0a (binding), 2bbccd2a (warm-up), 4983b3a1 (test).

Restano necessari: esito effettivo della qualifica dal 16 ottobre, riconciliazione
dei regolamenti e copertura prezzi, calendario revisionato, copia qualificata,
partenza comune e autorizzazione/integrazione di rilascio con i test finali.
Il primo collaudo del pacchetto isolato ha rilevato dipendenze Python mancanti; il bundle v8 include la chiusura degli import locali e i contratti JSON necessari e gli entrypoint selezionano esplicitamente il codice del bundle. La prova fallita precedente resta conservata. Il controllo di ammissione resta chiuso. Nessun servizio A/B/C avviato, grant,
ordine reale o modifica al paper V13 esistente. Minimi reali KuCoin UNKNOWN.
