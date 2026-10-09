"""Offline administrative writer. Never imported by a model/strategy runtime.

P0-05 ownership: root-owned directory 0750, registry and stable gate 0640;
trading identity read-only group access. Consumer audit is a separate directory.
No implicit initialization, health migration, network or live authorization.
"""
from contextlib import contextmanager
from dataclasses import asdict
import argparse
import fcntl
import json
import os
import pathlib
import tempfile

from octobot.ai_strategy_lab import paper_authorization as auth


class Admin:
    def __init__(self, root, *, clock=auth.now):
        self.root, self.clock = pathlib.Path(root), clock

    def initialize(self, *, reader_gid=None):
        self.root.mkdir(mode=0o750, parents=False, exist_ok=False)
        if reader_gid is not None:
            if type(reader_gid) is not int or reader_gid < 1:
                raise ValueError('dedicated reader GID required')
            os.chown(self.root, -1, reader_gid)
        # Setgid makes both the stable gate and each atomic replacement inherit
        # the dedicated reader group. The parent must be admin-owned.
        os.chmod(self.root, 0o2750)
        fd = os.open(self.root/'gate.lock', os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o640)
        os.fsync(fd)
        os.close(fd)
        self._write(dict(schema_version=1, revision=1,
            global_kill=dict(active=True, changed_at=self.clock().isoformat()), authorizations={}))

    def _write(self, doc):
        auth.validate_registry(doc)
        fd, name = tempfile.mkstemp(prefix='.registry-', dir=self.root)
        try:
            with os.fdopen(fd, 'w') as stream:
                os.fchmod(stream.fileno(), 0o640)
                stream.write(auth.canonical(doc))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, self.root/'registry.json')
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    @contextmanager
    def _change(self):
        fd = auth.secure_read(self.root/'gate.lock')
        try:
            # No waiting while pretending a kill has activated. Busy means the
            # change has NOT happened; administrator must retry explicitly.
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with os.fdopen(auth.secure_read(self.root/'registry.json')) as stream:
                doc = auth.validate_registry(json.load(stream, object_pairs_hook=auth.unique_object))
            pending = self.root/'mutation.pending'
            marker = os.open(pending, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o640)
            try:
                os.fsync(marker)
            finally:
                os.close(marker)
            directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
            # Any failed validation/write leaves a durable fail-closed marker.
            yield doc
            doc['revision'] += 1
            self._write(doc)
            pending.unlink()
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def set_kill(self, active):
        if type(active) is not bool:
            raise ValueError('boolean kill state required')
        with self._change() as doc:
            doc['global_kill'] = dict(active=active, changed_at=self.clock().isoformat())

    def grant(self, identity, *, valid_from, expires_at=None):
        identity.validate()
        with self._change() as doc:
            if identity.authorization_id in doc['authorizations']:
                raise ValueError('authorization ID cannot be reused or reactivated')
            doc['authorizations'][identity.authorization_id] = dict(asdict(identity),
                created_at=self.clock().isoformat(), valid_from=valid_from,
                expires_at=expires_at, status='ACTIVE')

    def revoke(self, authorization_id):
        with self._change() as doc:
            doc['authorizations'][authorization_id]['status'] = 'REVOKED'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=pathlib.Path, required=True)
    parser.add_argument('--reader-gid', type=int, help='dedicated paper reader group for initialization')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('initialize-denied')
    sub.add_parser('kill')
    sub.add_parser('allow-new-risk')
    grant = sub.add_parser('grant')
    grant.add_argument('--identity-json', type=pathlib.Path, required=True)
    grant.add_argument('--valid-from', required=True)
    grant.add_argument('--expires-at')
    revoke = sub.add_parser('revoke')
    revoke.add_argument('--authorization-id', required=True)
    args = parser.parse_args()
    admin = Admin(args.root)
    if args.command == 'initialize-denied': admin.initialize(reader_gid=args.reader_gid)
    elif args.command == 'kill': admin.set_kill(True)
    elif args.command == 'allow-new-risk': admin.set_kill(False)
    elif args.command == 'revoke': admin.revoke(args.authorization_id)
    else:
        admin.grant(auth.Identity(**json.loads(args.identity_json.read_text())),
                    valid_from=args.valid_from, expires_at=args.expires_at)


if __name__ == '__main__':
    main()
