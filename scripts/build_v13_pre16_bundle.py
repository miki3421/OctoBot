"""Package the inactive candidate including transitive local Python imports.

No service install/start. Refuses existing archive, manifest and stage targets.
The extracted stage must pass the offline suite before release review.
"""
import argparse
import ast
import hashlib
import json
import shutil
import tarfile
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for arg in ('base','manifest','archive','stage'):p.add_argument('--'+arg,required=True)
    a=p.parse_args();repo=Path(__file__).resolve().parents[1]
    base=json.loads(Path(a.base).read_text());files=set(base['files'])
    files.add('scripts/build_v13_pre16_bundle.py')
    files.update(['octobot/__init__.py','octobot/ai_strategy_lab/__init__.py'])
    # Non-Python resources required by the original V13 science adapter.
    files.update(['docs/contracts/v13-original-portfolio-adapter-candidate-v1.json',
                  'docs/contracts/v13-original-portfolio-proposal.schema.json'])
    visited=set()
    def include(module):
        parts=module.split('.')
        candidates=[Path(*parts).with_suffix('.py'),Path(*parts)/'__init__.py']
        if len(parts)==1:candidates.append(Path('octobot/ai_strategy_lab')/(module+'.py'))
        for path in candidates:
            if (repo/path).is_file():files.add(str(path))
    while files-visited:
        name=sorted(files-visited)[0];visited.add(name);path=Path(name)
        if path.is_absolute() or '..' in path.parts or (repo/path).is_symlink():raise ValueError('unsafe_bundle_file')
        if path.suffix!='.py':continue
        for node in ast.walk(ast.parse((repo/path).read_text())):
            if isinstance(node,ast.Import):
                for item in node.names:include(item.name)
            elif isinstance(node,ast.ImportFrom):
                if node.module:
                    include(node.module)
                    for item in node.names:include(node.module+'.'+item.name)
                elif node.level:
                    for item in node.names:include(item.name)
    value=dict(base,version=base['version']+1,kind='ABC_INACTIVE_PRE_CUTOFF_BINDINGS_COMPLETE_PACKAGE',
               files={name:hashlib.sha256((repo/name).read_bytes()).hexdigest() for name in sorted(files)})
    manifest=Path(a.manifest);archive=Path(a.archive);stage=Path(a.stage)
    if manifest.exists() or archive.exists() or stage.exists():raise ValueError('new_targets_required')
    manifest.write_text(json.dumps(value,indent=2)+'\n');stage.mkdir()
    relative=str(manifest.resolve().relative_to(repo.resolve()))
    with tarfile.open(archive,'x:gz') as tar:
        for name in sorted(files|{relative}):
            tar.add(repo/name,arcname=name)
            dest=stage/name;dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(repo/name,dest);dest.chmod(0o644)
    assert all(hashlib.sha256((stage/name).read_bytes()).hexdigest()==pin for name,pin in value['files'].items())
    print(json.dumps(dict(files=len(files),archive_sha256=hashlib.sha256(archive.read_bytes()).hexdigest(),execution_ready=False)))


if __name__=='__main__':main()
