"""Fail-closed mount and identity check for the isolated V13 process pair."""
import json
import os
import pathlib


def main():
    role=os.environ.get('V13_ROLE')
    expected={'strategy':(30010,30010,('/intents',),('/strategy',)),
              'executor':(30000,30001,('/ledger','/audit'),
                          ('/intents','/market','/approvals','/protocol','/policy','/var/lib/octobot-paper-control')),
              'issuer':(30020,30020,('/approvals',),('/issuer','/protocol','/producer','/source-archive')),
              'admin-close':(30000,30030,('/ledger','/admin-socket'),('/market',))}
    if role not in expected:
        raise SystemExit('V13: invalid role')
    uid,gid,writable,readonly=expected[role]
    if os.geteuid()!=uid or os.getegid()!=gid or os.getgroups()!=[gid]:
        raise SystemExit('V13: unexpected identity/groups')
    mounts={}
    for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines():
        parts=line.split()
        mounts[parts[4]]=set(parts[5].split(','))
    for path in writable:
        if not {'rw','noexec','nosuid','nodev'} <= mounts.get(path,set()):
            raise SystemExit('V13: unsafe writable mount '+path)
    for path in readonly:
        if 'ro' not in mounts.get(path,set()):
            raise SystemExit('V13: missing read-only mount '+path)
    if role == 'issuer':
        try:
            config = json.loads(pathlib.Path('/issuer/config.json').read_text())
        except (OSError, ValueError) as exc:
            raise SystemExit('V13: missing issuer config') from exc
        if config.get('schema_version') != 2 or config.get('archive_path') != '/source-archive':
            raise SystemExit('V13: issuer requires verified source config v2')


if __name__=='__main__':
    main()
