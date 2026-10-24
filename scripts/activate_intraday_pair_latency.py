"""Manual exact-artifact deployment. Default is verification only.

Only the pair executor and shared public-book persistence worker are restarted.
The operator gate is separate from local preparation, tests and acceptance.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

ROOT = Path('/root/auto_trading_sys')
REPO = ROOT / 'octobot-source'
RELEASE = ROOT / 'octobot-local/btc-intraday-pair-latency-v1'
CONFIG = ROOT / 'octobot-local/btc-intraday-pair-v1/configuration'
STATE = ROOT / 'octobot-local/btc-intraday-pair-v1/state'
ARMS = ('control-primary', 'candidate-primary', 'control-stress', 'candidate-stress')
TARGETS = ('octobot-btc-intraday-pair', 'octobot-scalping-observer')


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*args):
    return subprocess.check_output(list(args), cwd=REPO, text=True).strip()


def read(path, sql):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    try:
        return db.execute(sql).fetchone()
    finally:
        db.close()


def account_states():
    return {name: json.loads(read(STATE / 'accounts' / (name+'.sqlite'),
                                  'SELECT payload FROM state')[0]) for name in ARMS}


def containers():
    names = run('docker', 'ps', '--filter', 'name=octobot-', '--format', '{{.Names}}').splitlines()
    return {v['Name'].lstrip('/'): dict(id=v['Id'], started=v['State']['StartedAt'], restarts=v['RestartCount'],
        health=v['State'].get('Health', {}).get('Status')) for v in json.loads(run('docker', 'inspect', *names))}


def write(path, value):
    path.write_text(json.dumps(value, sort_keys=True, indent=2)+'\n')
    path.chmod(0o440)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest-sha256', required=True)
    parser.add_argument('--manual-operator-deploy', action='store_true')
    parser.add_argument('--operator-reference')
    args = parser.parse_args()
    assert os.geteuid() == 0 and sha(RELEASE / 'manifest.json') == args.manifest_sha256, 'exact_root_release_required'
    manifest = json.loads((RELEASE / 'manifest.json').read_text())
    assert manifest['scope'] == 'PREPARED_INTRADAY_LATENCY_NOT_DEPLOYED'
    runtime = Path(manifest['runtime'])
    for name, pin in manifest['runtime_files'].items():
        path = runtime / name
        assert not path.is_symlink() and path.stat().st_uid == 0 and not path.stat().st_mode & 0o022 and sha(path) == pin
    assert sha(runtime / 'files.sha256') == manifest['checksum_file_sha256']
    for name, pin in manifest['compose_files'].items():
        assert sha(REPO / name) == pin
    assert sha(REPO / 'docker-compose.local.yml') == manifest['base_compose_sha256']
    assert sha(Path(__file__)) == manifest['activation_helper_sha256']
    for name, pin in manifest['preserved_configuration_files'].items():
        assert sha(CONFIG / name) == pin
    for name, pin in manifest['stage_files'].items():
        assert sha(RELEASE / name) == pin
    for name in TARGETS:
        assert run('docker', 'inspect', name, '--format', '{{.Image}}') == manifest['image_id']
    assert shutil.disk_usage(STATE).free > 60 * 2**30, 'cold_copy_capacity_required'
    if not args.manual_operator_deploy:
        print(json.dumps(dict(verified=True, activated=False, manual_operator_gate=True)))
        return
    assert args.operator_reference and len(args.operator_reference) <= 240
    assert not (CONFIG / 'config-latency-v1.json').exists(), 'no_repeated_deploy'
    states = account_states()
    assert all(not s['q'] and not s.get('pending') for s in states.values()), 'wait_pair_flat_no_pending'
    before = containers()
    stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    evidence = ROOT / 'audit-evidence/intraday-pair-latency-20261024' / ('manual-deploy-'+stamp)
    evidence.mkdir(mode=0o700)
    write(evidence / 'containers-before.json', before)
    # Stop execution before the shared source. No artificial close or fill.
    for name in TARGETS:
        run('docker', 'stop', '--timeout', '30', name)
    stopped = account_states()
    assert all(not s['q'] and not s.get('pending') for s in stopped.values()), 'state_changed_keep_stopped_for_review'
    write(evidence / 'accounts-stopped.json', stopped)
    run('cp', '-a', '--reflink=auto', '--sparse=always', str(STATE), str(evidence / 'state-raw'))
    identities = {}
    anchors = {}
    for name in ARMS:
        path = STATE / 'accounts' / (name+'.sqlite')
        identities[name] = read(path, 'SELECT payload FROM identity')[0]
        anchors[name] = read(path, 'SELECT seq,sha FROM events ORDER BY seq DESC LIMIT 1')
    write(evidence / 'identity-and-prefix-anchors.json', dict(identities=identities, anchors=anchors))
    receipt = json.loads((RELEASE / 'latency-continuation-template.json').read_text())
    receipt['operator_acceptance_reference'] = args.operator_reference
    write(CONFIG / 'latency-continuation-v1.json', receipt)
    os.chown(CONFIG / 'latency-continuation-v1.json', 0, 30910)
    shutil.copyfile(RELEASE / 'config-latency-v1.json', CONFIG / 'config-latency-v1.json')
    (CONFIG / 'config-latency-v1.json').chmod(0o444)
    for name in TARGETS:
        run('docker', 'update', '--restart=no', name)
        run('docker', 'rename', name, name+'-pre-latency-'+stamp)
    run('docker-compose', '-p', 'btc-scalping-persistence-100ms-v1', '-f', 'docker-compose.local.yml',
        '-f', 'docker-compose.scalping-persistence-100ms.yml', 'config', '-q')
    run('docker-compose', '-p', 'btc-scalping-persistence-100ms-v1', '-f', 'docker-compose.local.yml',
        '-f', 'docker-compose.scalping-persistence-100ms.yml', 'up', '-d', '--no-deps', 'scalping-observer')
    run('docker-compose', '-p', 'btc-intraday-pair-latency-v1', '-f', 'docker-compose.btc-intraday-pair-latency-v1.yml',
        'up', '-d', '--no-deps', 'btc-intraday-pair')
    until = time.monotonic()+900
    while time.monotonic() < until:
        after = containers()
        if all(after.get(n, {}).get('health') == 'healthy' for n in TARGETS):
            break
        time.sleep(2)
    else:
        raise ValueError('healthy_timeout_no_blind_retry_inspect_preserved_runtime')
    for name, value in before.items():
        if name not in TARGETS:
            assert all(after.get(name, {}).get(k) == value[k] for k in ('id', 'started', 'restarts')), 'unrelated_service_changed'
    assert sha(CONFIG / 'activation.json') == manifest['preserved_activation_sha256']
    for name in ARMS:
        path = STATE / 'accounts' / (name+'.sqlite')
        assert read(path, 'SELECT payload FROM identity')[0] == identities[name]
        seq, pin = anchors[name]
        assert read(path, 'SELECT sha FROM events WHERE seq='+str(int(seq)))[0] == pin, 'historical_anchor_changed'
    # Keep the source outage short. Heavy integrity work is only on a second
    # private copy after the two workers are healthy; raw evidence is untouched.
    run('cp', '-a', '--reflink=auto', '--sparse=always', str(evidence / 'state-raw'), str(evidence / 'state-check'))
    for path in (evidence / 'state-check/accounts').rglob('*.sqlite'):
        with sqlite3.connect(path) as db:
            db.execute('SELECT COUNT(*) FROM sqlite_master').fetchone()
        assert read(path, 'PRAGMA integrity_check')[0] == 'ok', 'backup_integrity_failed_review_required'
    for name in ARMS:
        assert json.loads(read(evidence / 'state-check/accounts' / (name+'.sqlite'),
                              'SELECT payload FROM state')[0]) == stopped[name]
    write(evidence / 'result.json', dict(activated=True, operator_reference=args.operator_reference,
        states_before=stopped, containers=after, other_containers_unchanged=True,
        same_accounts=True, strategy_unchanged=True, real_orders=False, collector_commit_seconds=.1))
    print(json.dumps(dict(activated=True, evidence=str(evidence), other_containers_unchanged=True)))


if __name__ == '__main__':
    main()
