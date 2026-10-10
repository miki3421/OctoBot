# V13 — esito economico sui marker SELL

Consegna del 10 ottobre 2026. Scheda `work-card-949d673b-345e-4f1a-bfb0-9738b7b798e8`.

Accanto al triangolo SELL, nella panoramica e nel dettaglio, compare un cerchio: verde + per profitto, rosso − per perdita, grigio = per pareggio, · per nessuna esposizione chiusa, ? per contabilità netta non disponibile. Hover e click sul cerchio mostrano la stessa operazione e i dettagli contabili.

L’esito usa il P/L realizzato della parte chiusa meno la commissione di questo fill. Non include commissioni precedenti o funding e non equivale al rendimento completo del trade né all’impatto immediato sull’equity. SELL che apre o aumenta uno short non viene classificato come perdita per la sola commissione. Nessuna modifica a ledger, segnali, policy o autorizzazioni.

Validazione: 12 test contabili superati; browser live desktop/mobile senza errori o overflow; 18 grafici, 134 fill, 70 indicatori SELL. Casi positivo, negativo, pareggio, apertura short e dato ignoto verificati; click sul marker BTC positivo apre il dettaglio. Evidenze locali nella cartella audit-evidence/v13-sell-outcome-markers-20261010. Riavviata esclusivamente l’interfaccia octobot-local; ricerca paper indipendente.
