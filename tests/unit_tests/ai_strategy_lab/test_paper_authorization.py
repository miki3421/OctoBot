"""Isolated administrative storage only: no operational authorization grants."""
import concurrent.futures
import dataclasses
import datetime as dt
import json
import os
import pathlib
import sqlite3
import threading
from unittest.mock import Mock, patch

import pytest
from octobot.ai_strategy_lab import paper_authorization as auth
from octobot.ai_strategy_lab.paper_authorization_admin import Admin

NOW = dt.datetime(2026, 9, 24, tzinfo=dt.timezone.utc)
# Synthetic policy for the registry contract only, NOT adopted economic limits.
POLICY = {k: {'fixture_only': True, 'defined': True} for k in auth.REQUIRED_CONTROLS}


@pytest.fixture
def rig(tmp_path):
    admin = Admin(tmp_path/'control', clock=lambda: NOW)
    admin.initialize()
    identity = auth.Identity('test-paper', 'test-strategy', 'a'*64, 'test-policy', auth.digest(POLICY), 'test-grant')
    registry = auth.Registry(admin.root, tmp_path/'audit.sqlite', clock=lambda: NOW)
    return admin, registry, identity


def activate(rig, *, expires_at=None):
    admin, registry, identity = rig
    admin.grant(identity, valid_from=NOW.isoformat(), expires_at=expires_at)
    admin.set_kill(False)
    return registry, identity


def attempt(registry, identity, effect, *, entry_id='decision-1', policy=POLICY, decision=None):
    with registry.entry(identity, entry_id, policy, decision or (lambda: True)):
        effect()


def denied(registry, identity, code, *, entry_id='decision-1', policy=POLICY, decision=None):
    effect = Mock()
    with pytest.raises(auth.Denied) as caught:
        attempt(registry, identity, effect, entry_id=entry_id, policy=policy, decision=decision)
    effect.assert_not_called()
    assert caught.value.code == code
    return caught.value


def test_initialization_does_not_grant_anything(rig):
    admin, registry, identity = rig
    doc = json.loads((admin.root/'registry.json').read_text())
    assert doc['global_kill']['active'] is True and doc['authorizations'] == {}
    denied(registry, identity, 'global_kill_active')


@pytest.mark.parametrize('kind', ['registry', 'gate', 'directory'])
def test_missing_storage(rig, kind):
    admin, registry, identity = rig
    if kind == 'directory': registry.root = admin.root/'absent'
    else: (admin.root/('registry.json' if kind == 'registry' else 'gate.lock')).unlink()
    denied(registry, identity, 'authorization_missing')


@pytest.mark.parametrize('mode', [0, 0o666, 0o660])
def test_unreadable_or_runtime_writable_registry(rig, mode):
    admin, registry, identity = rig
    (admin.root/'registry.json').chmod(mode)
    denied(registry, identity, 'authorization_storage_failure')


@pytest.mark.parametrize('contents', ['{broken', '{}', '[]', '{"schema_version":1,"schema_version":1}', 'null'])
def test_malformed_registry(rig, contents):
    admin, registry, identity = rig
    (admin.root/'registry.json').write_text(contents)
    denied(registry, identity, 'authorization_malformed')


def test_unknown_grant_account_never_inferred_from_health(rig):
    admin, registry, identity = rig
    admin.set_kill(False)
    (admin.root/'health.json').write_text(json.dumps(dict(healthy=True, paper_orders_authorized=True)))
    denied(registry, identity, 'authorization_missing')


def test_active_valid_grant_and_durable_claim(rig):
    registry, identity = activate(rig)
    effect = Mock()
    attempt(registry, identity, effect)
    effect.assert_called_once()
    with sqlite3.connect(registry.audit) as db:
        rows = [json.loads(r[0]) for r in db.execute('SELECT payload FROM checks')]
        assert rows[0]['result'] == 'GLOBAL_CLAIM'
        assert rows[-1]['result'] == 'ALLOW_ENTRY_PREFLIGHT'
        assert rows[0]['global_kill'] is False
        assert rows[0]['identity'] == dataclasses.asdict(identity)
    denied(registry, identity, 'entry_already_claimed')


@pytest.mark.parametrize('field,value,code', [('account', 'other', 'account_mismatch'),
    ('strategy', 'other', 'strategy_mismatch'), ('lineage_hash', 'b'*64, 'lineage_mismatch'),
    ('risk_policy', 'other', 'risk_policy_mismatch'), ('risk_policy_hash', 'b'*64, 'risk_policy_mismatch')])
def test_exact_identity_and_restart_after_change(rig, field, value, code):
    registry, identity = activate(rig)
    restarted = auth.Registry(registry.root, registry.audit, clock=lambda: NOW)
    denied(restarted, dataclasses.replace(identity, **{field:value}), code)


def test_expired_and_exact_expiry_restart(rig):
    expiry = NOW + dt.timedelta(seconds=1)
    registry, identity = activate(rig, expires_at=expiry.isoformat())
    for instant in (expiry, expiry+dt.timedelta(days=1)):
        denied(auth.Registry(registry.root, registry.audit, clock=lambda: instant), identity, 'authorization_expired')


def test_future_validity(rig):
    admin, registry, identity = rig
    admin.grant(identity, valid_from=(NOW+dt.timedelta(seconds=1)).isoformat())
    admin.set_kill(False)
    denied(registry, identity, 'authorization_not_yet_valid')


def test_revoke_survives_reopen_and_cannot_reactivate_id(rig):
    registry, identity = activate(rig)
    rig[0].revoke(identity.authorization_id)
    denied(auth.Registry(registry.root, registry.audit, clock=lambda: NOW), identity, 'authorization_revoked')
    with pytest.raises(ValueError): rig[0].grant(identity, valid_from=NOW.isoformat())


def test_kill_survives_restart(rig):
    registry, identity = activate(rig)
    rig[0].set_kill(True)
    denied(auth.Registry(registry.root, registry.audit, clock=lambda: NOW), identity, 'global_kill_active')


@pytest.mark.parametrize('field', auth.REQUIRED_CONTROLS)
def test_undefined_policy_is_not_filled_with_invented_limits(rig, field):
    admin, registry, identity = rig
    policy = dict(POLICY, **{field:None})
    identity = dataclasses.replace(identity, risk_policy_hash=auth.digest(policy))
    admin.grant(identity, valid_from=NOW.isoformat()); admin.set_kill(False)
    denied(registry, identity, 'risk_policy_incomplete', policy=policy)


def test_policy_content_must_match_hash(rig):
    registry, identity = activate(rig)
    denied(registry, identity, 'risk_policy_mismatch', policy=dict(POLICY, extra='changed'))


@pytest.mark.parametrize('field,value', [('lineage_hash', '*'), ('risk_policy_hash', '*'), ('account','*'), ('environment','live')])
def test_no_wildcards_or_live_authorizations(rig, field, value):
    admin, registry, identity = rig
    invalid = dataclasses.replace(identity, **{field:value})
    with pytest.raises(auth.Denied): admin.grant(invalid, valid_from=NOW.isoformat())
    assert json.loads((admin.root/'registry.json').read_text())['authorizations'] == {}
    denied(registry, invalid, 'paper_environment_required' if field=='environment' else 'authorization_identity_invalid')


@pytest.mark.parametrize('decision', [lambda: False, lambda: (_ for _ in ()).throw(ValueError('P0-01 unavailable'))])
def test_decision_authorization_failure_never_executes(rig, decision):
    registry, identity = activate(rig)
    denied(registry, identity, 'decision_authorization_invalid', decision=decision)
    denied(registry, identity, 'entry_already_claimed')


def test_missing_decision_adapter_never_executes(rig):
    registry, identity = activate(rig)
    effect = Mock()
    with pytest.raises(auth.Denied, match='decision_authorization_missing'):
        with registry.entry(identity, 'd', POLICY, None): effect()
    effect.assert_not_called()


@pytest.mark.parametrize('kind', ['corrupt', 'unwritable', 'insert_failure'])
def test_audit_storage_failure_never_becomes_allow(rig, kind):
    registry, identity = activate(rig)
    if kind == 'corrupt': registry.audit.write_bytes(b'not sqlite')
    elif kind == 'unwritable': registry.audit = registry.audit.parent/'absent'/'audit.sqlite'
    else:
        with sqlite3.connect(registry.audit) as db:
            db.execute('CREATE TABLE checks(id INTEGER PRIMARY KEY, payload TEXT NOT NULL)')
            db.execute("CREATE TRIGGER fail_checks BEFORE INSERT ON checks BEGIN SELECT RAISE(ABORT,'audit failed'); END")
    decision = Mock(return_value=True)
    error = denied(registry, identity, 'authorization_storage_failure', decision=decision)
    assert error.persisted is False
    decision.assert_not_called()


def test_duplicate_concurrent_entry_attempts(rig):
    registry, identity = activate(rig)
    start = threading.Barrier(2)
    effect = Mock()
    def worker():
        start.wait()
        try: attempt(registry, identity, effect)
        except auth.Denied as exc: return exc.code
        return 'allowed'
    with concurrent.futures.ThreadPoolExecutor(2) as pool:
        results = list(pool.map(lambda _: worker(), range(2)))
    assert results.count('allowed') <= 1
    assert effect.call_count == results.count('allowed')
    assert set(results) <= {'allowed', 'authorization_storage_failure', 'entry_already_claimed'}


@pytest.mark.parametrize('action', ['kill', 'revoke'])
def test_admin_change_cannot_activate_between_check_and_effect(rig, action):
    registry, identity = activate(rig)
    claimed, proceed = threading.Event(), threading.Event()
    effect = Mock()
    def worker():
        with registry.entry(identity, 'first', POLICY, lambda: True):
            claimed.set()
            assert proceed.wait(5)
            effect()
    with concurrent.futures.ThreadPoolExecutor(1) as pool:
        future = pool.submit(worker)
        assert claimed.wait(5)
        change = lambda: rig[0].set_kill(True) if action == 'kill' else rig[0].revoke(identity.authorization_id)
        try:
            with pytest.raises(BlockingIOError): change()
            doc = json.loads((rig[0].root/'registry.json').read_text())
            assert doc['global_kill']['active'] is False
            assert doc['authorizations'][identity.authorization_id]['status'] == 'ACTIVE'
        finally: proceed.set()
        future.result(timeout=5)
    effect.assert_called_once()
    change()
    denied(registry, identity, 'global_kill_active' if action=='kill' else 'authorization_revoked', entry_id='later')


def test_admin_wins_race_entries_never_start(rig):
    registry, identity = activate(rig)
    fd = auth.secure_read(registry.root/'gate.lock')
    import fcntl
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        denied(registry, identity, 'authorization_storage_failure')
    finally: os.close(fd)
    rig[0].set_kill(True)
    denied(registry, identity, 'global_kill_active', entry_id='later')


def test_claim_survives_effect_crash_no_automatic_retry(rig):
    registry, identity = activate(rig)
    with pytest.raises(RuntimeError):
        with registry.entry(identity, 'crash', POLICY, lambda: True): raise RuntimeError('process failed before effect')
    denied(auth.Registry(registry.root, registry.audit, clock=lambda: NOW), identity, 'entry_already_claimed', entry_id='crash')


def test_symlink_registry_is_rejected(rig, tmp_path):
    admin, registry, identity = rig
    original = admin.root/'registry.json'
    original.rename(tmp_path/'other.json')
    original.symlink_to(tmp_path/'other.json')
    denied(registry, identity, 'authorization_storage_failure')


def test_failed_admin_write_leaves_uncertainty_latch(rig, monkeypatch):
    registry, identity = activate(rig)
    monkeypatch.setattr(rig[0], '_write', Mock(side_effect=OSError('disk failure')))
    with pytest.raises(OSError): rig[0].set_kill(True)
    assert (registry.root/'mutation.pending').exists()
    denied(registry, identity, 'authorization_storage_failure')


def test_complete_global_policy_cannot_ignore_declared_missing_gates(rig):
    admin, registry, identity = rig
    policy = dict(POLICY, missing_gates=['P0-03 adapter'])
    identity = dataclasses.replace(identity, risk_policy_hash=auth.digest(policy))
    admin.grant(identity, valid_from=NOW.isoformat());admin.set_kill(False)
    denied(registry, identity, 'execution_policy_incomplete', policy=policy)


def test_valid_grant_does_not_depend_on_health_or_container_liveness(rig):
    registry, identity = activate(rig)
    (registry.root/'health.json').write_text('{"healthy": false, "paper_orders_authorized": false, "docker": "stopped"}')
    effect = Mock();attempt(registry, identity, effect);effect.assert_called_once()


def test_actual_process_crash_releases_gate_but_does_not_restore_claim(rig):
    import multiprocessing
    registry, identity = activate(rig)
    def crash():
        with registry.entry(identity, 'crashed-process', POLICY, lambda: True):
            os._exit(7)
    process = multiprocessing.get_context('fork').Process(target=crash)
    process.start();process.join(5)
    if process.is_alive():process.terminate();process.join();pytest.fail('child did not finish')
    assert process.exitcode==7
    denied(registry, identity, 'entry_already_claimed', entry_id='crashed-process')
    rig[0].set_kill(True)
    denied(registry, identity, 'global_kill_active', entry_id='after-restart')
