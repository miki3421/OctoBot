"""Fail closed if any persistent writable mount lacks the OS mount boundary."""
import os
import pathlib
import sys


def main():
    required = os.environ.get('PAPER_REQUIRED_WRITABLE', '').split(':')
    if not required or any(not path.startswith('/') for path in required):
        raise SystemExit('P0-05: missing absolute writable mount declaration')
    mounted = {}
    for line in pathlib.Path('/proc/self/mountinfo').read_text().splitlines():
        fields = line.split()
        mounted[fields[4]] = set(fields[5].split(','))
    for path in required:
        options = mounted.get(path)
        if options is None or not {'rw', 'noexec', 'nosuid', 'nodev'} <= options:
            raise SystemExit(f'P0-05: unsafe writable mount {path}')
    if os.geteuid() != 30000 or os.getegid() != 30001 or os.getgroups() != [30001]:
        raise SystemExit('P0-05: unexpected runtime identity')


if __name__ == '__main__':
    main()
