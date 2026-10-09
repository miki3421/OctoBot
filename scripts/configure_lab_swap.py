"""One-time, bounded host swap reserve setup authorized by the lab owner.

Card work-card-a26f1ef8-c617-4587-a05c-88dbd249d12b.
Never disables old swap, changes VM allocations or deletes persistent data.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile

TARGET = Path('/var/lib/libvirt/trading-ai-lab/host-swap/reserve.swap')
TUNING = Path('/etc/sysctl.d/90-trading-lab-swap.conf')
SIZE = 16 * 1024**3
ENTRY = str(TARGET) + ' none swap sw,nofail,pri=100 0 0\n'


def command(args):
    return subprocess.check_output(args, text=True).strip()


def atomic(path, data, mode=0o644):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.lab-swap-')
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as stream:
            stream.write(data); stream.flush(); os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name): os.unlink(name)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--finish-reviewed', action='store_true',
                        help='Finish only the exact already-activated reserve from this evidence plan')
    args = parser.parse_args()
    if os.geteuid() != 0:
        raise ValueError('root_required')
    if (TARGET.parent.exists() and not args.finish_reviewed) or TUNING.exists():
        raise ValueError('existing_target_requires_review')
    ancestor = TARGET.parent.parent
    for p in (ancestor, *ancestor.parents):
        info = p.lstat()
        if p.is_symlink() or info.st_uid != 0 or info.st_mode & 0o022:
            raise ValueError('untrusted_target_ancestor')
    if command(['findmnt','-no','FSTYPE','-T',str(ancestor)]) != 'ext4':
        raise ValueError('expected_ext4_filesystem')
    free = shutil.disk_usage(ancestor).free
    if free < SIZE + 64 * 1024**3:
        raise ValueError('insufficient_disk_margin')
    fstab = Path('/etc/fstab')
    if fstab.is_symlink() or fstab.stat().st_uid != 0:
        raise ValueError('untrusted_fstab')
    before = fstab.read_text()
    if str(TARGET) in before:
        raise ValueError('existing_swap_entry')
    old_swappiness = int(command(['sysctl','-n','vm.swappiness']))
    plan = dict(target=str(TARGET),size_bytes=SIZE,priority=100,new_swappiness=20,
        old_swappiness=old_swappiness,disk_free_bytes=free,
        previous_fstab_sha256=hashlib.sha256(before.encode()).hexdigest(),
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        no_swapoff=True,vm_changes=False)
    evidence = Path(args.evidence)
    if args.finish_reviewed:
        previous = json.loads((evidence/'plan.json').read_text())
        info = TARGET.lstat()
        if (previous['target'] != str(TARGET) or previous['size_bytes'] != SIZE
                or previous['previous_fstab_sha256'] != plan['previous_fstab_sha256']
                or TARGET.is_symlink() or not TARGET.is_file() or info.st_uid != 0
                or info.st_mode & 0o077 or info.st_size != SIZE
                or str(TARGET) not in Path('/proc/swaps').read_text()):
            raise ValueError('existing_reserve_does_not_match_reviewed_plan')
    else:
        evidence.mkdir(mode=0o700)
        (evidence/'plan.json').write_text(json.dumps(plan,indent=2))
        (evidence/'fstab.before').write_text(before)
    if not args.apply and not args.finish_reviewed:
        print(json.dumps(plan)); return
    if not args.finish_reviewed:
        TARGET.parent.mkdir(mode=0o700)
        fd = os.open(TARGET, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        command(['fallocate','-l',str(SIZE),str(TARGET)])
        command(['mkswap',str(TARGET)])
        command(['swapon','--priority','100',str(TARGET)])
    if str(TARGET) not in Path('/proc/swaps').read_text():
        raise RuntimeError('swap_activation_not_confirmed')
    if fstab.read_text() != before:
        raise RuntimeError('fstab_changed_concurrently')
    new = before.rstrip() + '\n\n# Trading AI Lab additional swap reserve\n' + ENTRY
    temporary = evidence/'fstab.candidate'
    temporary.write_text(new)
    # Verify the changed swap entries; unrelated boot-order errors already in
    # the original fstab must not cause this tool to rewrite boot mounts.
    verification = subprocess.run(['findmnt','--verify','--types','swap','--tab-file',str(temporary)],capture_output=True,text=True)
    (evidence/'fstab-verification.txt').write_text(verification.stdout+verification.stderr)
    if verification.returncode:
        raise RuntimeError('candidate_fstab_invalid_swap_active_not_persisted')
    atomic(fstab,new,fstab.stat().st_mode & 0o777)
    atomic(TUNING,'# Authorized Trading AI Lab host swap margin fix\nvm.swappiness = 20\n')
    command(['sysctl','-p',str(TUNING)])
    command(['systemctl','daemon-reload'])
    plan.update(applied=True,active_swaps=command(['swapon','--show','--bytes']),
                effective_swappiness=command(['sysctl','-n','vm.swappiness']))
    (evidence/'applied.json').write_text(json.dumps(plan,indent=2))
    print(json.dumps({k:plan[k] for k in ['applied','size_bytes','effective_swappiness','active_swaps']}))


if __name__ == '__main__':
    main()
