"""Verify the immutable local runtime before importing its research caller."""
import hashlib
import json
import os
from pathlib import Path
import sys


def main():
    if len(sys.argv)!=3 or sys.argv[1]!='--config':raise ValueError('release_config_argument')
    path=Path(sys.argv[2])
    if path.is_symlink() or path.stat().st_uid!=0 or path.stat().st_mode&0o022:raise ValueError('release_config_custody')
    config=json.loads(path.read_text());root=Path(__file__).resolve().parent
    manifest=root/'runtime-files.json'
    if hashlib.sha256(manifest.read_bytes()).hexdigest()!=config['discrete_revision']['runtime_manifest_sha256']:
        raise ValueError('release_manifest_identity')
    pins=json.loads(manifest.read_text())
    for name,expected in pins.items():
        file=root/name
        if Path(name).is_absolute() or '..' in Path(name).parts or file.is_symlink() or file.stat().st_uid!=0 or file.stat().st_mode&0o022:
            raise ValueError('release_file_custody')
        if hashlib.sha256(file.read_bytes()).hexdigest()!=expected:raise ValueError('release_file_hash:'+name)
    sys.path.insert(0,str(root/'runtime'))
    from octobot.ai_strategy_lab.v13_fork_discrete_runtime import main as run
    run()


if __name__=='__main__':main()
