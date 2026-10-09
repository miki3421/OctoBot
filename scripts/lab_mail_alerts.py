"""SMTP notifications isolated from the monitor and paper runtime.

Card work-card-575258a8-ad83-45b7-ae2d-630cb57959b3.
No shell evaluation, raw credentials in logs, or trading-store access.
"""
import argparse
import datetime as dt
from email.message import EmailMessage
from email.utils import parseaddr
import hashlib
import json
from pathlib import Path
import smtplib
import sqlite3
import ssl
import time

COOLDOWN = 1800
REMINDER = 86400
LABELS = {
    'SWAP_OCCUPANCY_HIGH_NOT_PROOF_OF_THRASHING': 'Swap quasi pieno; questo dato da solo non dimostra rallentamenti.',
    'SWAP_ACTIVITY_OVER_1_MIB_PER_SECOND': 'Attivita di swap superiore a 1 MiB/s.',
    'MEMORY_AVAILABLE_BELOW_10_PERCENT': 'Memoria RAM disponibile inferiore al 10%.',
    'DISK_FREE_BELOW_15_PERCENT': 'Spazio libero sul disco inferiore al 15%',
    'COLLECTOR_STALE_OR_UNREADABLE': 'Collector con dati vecchi o stato non leggibile',
    'COLLECTOR_SOURCE_UNHEALTHY': 'Collector che segnala un problema',
    'CONTAINER_NOT_HEALTHY': 'Container fermo o unhealthy',
    'CONTAINER_STATE_UNAVAILABLE': 'Stato dei container non verificabile.',
    'MONITOR_UNAVAILABLE_OR_STALE': 'Il monitor non pubblica uno stato valido e recente.',
}


def load_credentials(path):
    path = Path(path)
    if path.is_symlink() or path.stat().st_mode & 0o077:
        raise ValueError('private_credential_file_required')
    values = {}
    for line in path.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key in values or '\r' in value or '\n' in value:
            raise ValueError('invalid_credential_config')
        values[key] = value
    required = {'SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURITY', 'SMTP_USERNAME',
                'SMTP_PASSWORD', 'SMTP_FROM', 'SMTP_TO'}
    if set(values) != required or any(not values[k] for k in required):
        raise ValueError('invalid_credential_config')
    if values['SMTP_SECURITY'].lower() != 'starttls' or values['SMTP_PORT'] != '587':
        raise ValueError('verified_starttls_required')
    for field in ('SMTP_FROM', 'SMTP_TO', 'SMTP_USERNAME'):
        address = values[field]
        if parseaddr(address)[1] != address or address.count('@') != 1 or any(c.isspace() for c in address):
            raise ValueError('invalid_mail_address')
    if values['SMTP_HOST'] == 'smtp.gmail.com':
        values['SMTP_PASSWORD'] = ''.join(values['SMTP_PASSWORD'].split())
        if len(values['SMTP_PASSWORD']) != 16:
            raise ValueError('invalid_app_password_length')
    return values


def read_alerts(path, now):
    try:
        sample = json.loads(Path(path).read_text())
        at = dt.datetime.fromisoformat(sample['observed_at'].replace('Z', '+00:00'))
        alerts = sample['alerts']
        if (sample['scope'] != 'PASSIVE_LAB_TELEMETRY_ONLY' or at.tzinfo is None
                or not 0 <= now - at.timestamp() <= 900 or not isinstance(alerts, list)
                or not all(isinstance(a, str) and a.split(':', 1)[0] in LABELS for a in alerts)):
            raise ValueError('invalid_monitor_sample')
        return sorted(set(alerts))
    except (OSError, ValueError, KeyError, TypeError):
        return ['MONITOR_UNAVAILABLE_OR_STALE']


def plan(alerts, state, now, force=False):
    if force:
        return 'TEST'
    if not state:
        return 'PROBLEMA' if alerts else None
    previous = state['alerts']
    if not alerts and previous:
        return 'RECUPERO'
    elapsed = now - state['sent_at']
    if alerts != previous and elapsed >= COOLDOWN:
        return 'AGGIORNAMENTO' if previous else 'PROBLEMA'
    if alerts and alerts == previous and elapsed >= REMINDER:
        return 'PROMEMORIA'
    return None


def deliver(config, kind, alerts, now):
    message = EmailMessage()
    message['From'] = config['SMTP_FROM']
    message['To'] = config['SMTP_TO']
    message['Subject'] = '[Trading AI Lab] ' + kind.capitalize()
    message['Message-ID'] = '<' + hashlib.sha256(json.dumps([kind, alerts, now]).encode()).hexdigest() + '@trading-ai-lab.local>'
    lines = ['Trading AI Lab - monitoraggio automatico',
             'Ora UTC: ' + dt.datetime.fromtimestamp(now, dt.timezone.utc).isoformat(), '']
    if kind == 'TEST':
        lines.append('Prova del canale email. Di seguito lo stato iniziale degli allarmi.')
    if alerts:
        for alert in alerts:
            key, separator, component = alert.partition(':')
            lines.append('- ' + LABELS[key] + (': ' + component if separator else ''))
    else:
        lines.append('Nessun allarme attivo. Le condizioni precedentemente segnalate sono rientrate.')
    lines += ['', 'Questi avvisi sono diagnostici. Il notificatore non modifica il paper trading.',
              'Aggiornamenti distanziati di almeno 30 minuti; promemoria dopo 24 ore.']
    message.set_content('\n'.join(lines))
    with smtplib.SMTP(config['SMTP_HOST'], int(config['SMTP_PORT']), timeout=20) as smtp:
        smtp.ehlo()
        smtp.starttls(context=ssl.create_default_context())
        smtp.ehlo()
        smtp.login(config['SMTP_USERNAME'], config['SMTP_PASSWORD'])
        refused = smtp.send_message(message)
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)


def notify(db, alerts, now, send, force=False):
    db.execute('CREATE TABLE IF NOT EXISTS notification_state(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)')
    db.commit()
    db.execute('BEGIN IMMEDIATE')
    try:
        row = db.execute('SELECT payload FROM notification_state WHERE id=1').fetchone()
        state = json.loads(row[0]) if row else None
        kind = plan(alerts, state, now, force)
        if kind:
            send(kind, alerts, now)
            state = dict(alerts=alerts, sent_at=now)
        elif state is None:
            state = dict(alerts=[], sent_at=now - COOLDOWN)
        if state is not None:
            db.execute('INSERT OR REPLACE INTO notification_state VALUES(1,?)', (json.dumps(state),))
        db.commit()
        return kind or 'DEDUPLICATO'
    except Exception:
        db.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credential', required=True)
    parser.add_argument('--monitor-status', required=True)
    parser.add_argument('--state', required=True)
    parser.add_argument('--test', action='store_true')
    args = parser.parse_args()
    try:
        config = load_credentials(args.credential)
        now = time.time()
        alerts = read_alerts(args.monitor_status, now)
        with sqlite3.connect(args.state, timeout=5) as db:
            result = notify(db, alerts, now, lambda kind, items, at: deliver(config, kind, items, at), args.test)
        print(json.dumps(dict(status=result, active_alerts=len(alerts))))
        return 0
    except (OSError, ValueError, sqlite3.Error, smtplib.SMTPException) as error:
        # Never log SMTP exception text: servers may echo private identities.
        print(json.dumps(dict(status='NOTIFICATION_FAILED', failure_type=type(error).__name__,
                              retry='NEXT_TIMER_RUN')))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
