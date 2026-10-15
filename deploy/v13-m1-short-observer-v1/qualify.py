"""Pre-start technical qualification in the observer's exact systemd sandbox.

Card work-card-6e34a16c-52fb-4994-ade1-2abd126f13a9. Does not start the
real study. Captures below are unmistakably fixtures, never forward evidence.
"""
import datetime as dt
import errno
import importlib.util
import json
import os
from pathlib import Path
import socket
import sqlite3
import time

REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('observer', REPO / 'scripts/v13_m1_future_observer.py')
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)


def main():
    protocol = observer.load_protocol()
    assert os.geteuid() == 30942 and os.getegid() == 30910
    assert not (observer.STATE / 'observation.sqlite').exists(), 'qualification_requires_no_real_start'
    # Opening for write is sufficient to prove the kernel denies source writes;
    # no data is ever written, even if the isolation check unexpectedly fails.
    try:
        fd = os.open(observer.ORIGINAL, os.O_WRONLY)
    except OSError as error:
        assert error.errno in (errno.EROFS, errno.EACCES, errno.EPERM)
    else:
        os.close(fd)
        raise AssertionError('source_write_open_allowed')
    for hidden in ('/root/.ops/cp.credential', '/run/docker.sock',
                   '/root/auto_trading_sys/octobot-local/v13-paper/research/approvals'):
        assert not os.access(hidden, os.R_OK), 'unrelated_trust_path_readable'
    try:
        channel = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    except OSError:
        pass
    else:
        channel.close()
        raise AssertionError('network_socket_allowed')
    instant = time.time()
    slot = int(instant) // 300 * 300
    rows = observer.f.read_window(observer.ORIGINAL, slot, protocol['universe'])
    assert len(rows) == 289
    assert all(set(r['prices']) == set(protocol['universe']) and
               all(0 <= r['time'] - at <= 120 for at in r['source_times'].values()) for r in rows), 'causal_window_incomplete'
    feature = observer.f.detector.features(rows, 288)
    assert feature is not None
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    fixtures = observer.STATE / 'qualification' / ('fixture-' + stamp)
    fixtures.mkdir(parents=True)
    # Same production capture function, same source and filesystem protections.
    # A fixture-only sink records a technical receipt without creating a study.
    class Sink:
        def __init__(self):
            self.db = sqlite3.connect(':memory:')
            self.db.execute('CREATE TABLE captures(episode_id TEXT, phase TEXT)')
            self.receipt = None

        def capture(self, episode_id, phase, payload, captured_at):
            assert phase == 'entry' and payload['captured_at'] == captured_at
            assert instant <= captured_at <= instant + 120
            self.receipt = dict(fixture=True, scientific_evidence=False, **payload)

    sink = Sink()
    observer.STATE = fixtures
    observer.take_capture(sink, dict(id='FIXTURE-TECHNICAL-CAPTURE', entry_slot=instant), 'entry', protocol)
    assert sink.receipt is not None
    snapshot = fixtures / 'episodes/FIXTURE-TECHNICAL-CAPTURE/entry.original.sqlite'
    db = sqlite3.connect(snapshot.resolve().as_uri() + '?mode=ro', uri=True)
    try:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        orders = db.execute('SELECT COUNT(*) FROM orders').fetchone()[0]
    finally:
        db.close()
        sink.db.close()
    report = dict(scope='PRE_START_TECHNICAL_QUALIFICATION_NOT_FORWARD_EVIDENCE',
                  checked_at=dt.datetime.now(dt.timezone.utc).isoformat(),
                  uid=os.geteuid(), gid=os.getegid(), network_denied=True,
                  source_write_denied=True, unrelated_trust_paths_hidden=True,
                  causal_rows=len(rows), universe_size=len(protocol['universe']),
                  snapshot_integrity='ok', original_orders_copied=orders,
                  receipt=sink.receipt, real_observation_started=False)
    (fixtures / 'result.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))


if __name__ == '__main__':
    main()
