"""Prepare an immutable technical continuation. Does not stop or start services."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess


ROOT = Path('/root/auto_trading_sys')
REPO = ROOT / 'octobot-source'
OLD = Path('/opt/btc-intraday-pair-io-v2')
RUNTIME = Path('/opt/btc-intraday-pair-latency-v1')
RELEASE = ROOT / 'octobot-local/btc-intraday-pair-latency-v1'


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    assert os.geteuid() == 0
    config = ROOT / 'octobot-local/btc-intraday-pair-v1/configuration'
    activation = json.loads((config / 'activation.json').read_text())
    for name, pin in activation['code_pins'].items():
        assert sha(OLD / 'intraday_pair' / name) == pin
        assert sha(REPO / 'octobot/ai_strategy_lab/intraday_pair' / name) == pin
    assert not RUNTIME.exists() and not RELEASE.exists(), 'Never overwrite an earlier release'
    shutil.copytree(OLD, RUNTIME)
    RELEASE.mkdir(mode=0o700)
    for name in ('btc_intraday_pair_latency.py', 'btc_intraday_pair_latency_live.py'):
        shutil.copyfile(REPO / 'octobot/ai_strategy_lab' / name, RUNTIME / name)
    shutil.copyfile(REPO / 'docker/scalping-observer-low-latency-entrypoint.sh',
                    RUNTIME / 'scalping-observer-low-latency-entrypoint.sh')
    files = {str(p.relative_to(RUNTIME)): sha(p) for p in sorted(RUNTIME.rglob('*'))
             if p.is_file() and p.name != 'files.sha256'}
    (RUNTIME / 'files.sha256').write_text(''.join(f'{pin}  {name}\n' for name, pin in files.items()))
    new = json.loads((config / 'config-io-v2.json').read_text())
    new.update(io_predecessor_configuration='/configuration/config-io-v2.json',
               latency_continuation='/configuration/latency-continuation-v1.json')
    template = dict(scope='AUTHORIZED_PAPER_PAIR_LATENCY_CONTINUATION',
        prior_activation_sha256=hashlib.sha256(json.dumps(activation, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest(),
        predecessor_configuration_sha256=sha(config / 'config-io-v2.json'), directory=new['directory'],
        strategy_unchanged=True, state_reset_allowed=False, real_orders=False,
        exchange_credentials=False, operational_grants=False, operator_acceptance_reference=None,
        runtime_files={n:files[n] for n in ('btc_intraday_pair_latency.py', 'btc_intraday_pair_latency_live.py')})
    for name, value in [('config-latency-v1.json', new), ('latency-continuation-template.json', template)]:
        (RELEASE / name).write_text(json.dumps(value, indent=2)+'\n')
    manifest = dict(scope='PREPARED_INTRADAY_LATENCY_NOT_DEPLOYED', runtime=str(RUNTIME),
        runtime_files=files, checksum_file_sha256=sha(RUNTIME / 'files.sha256'),
        image_id='sha256:7e825796375e06e3cfb6ea46b5b7202bdba4c0bb998bdffea5e02b8bd9d67575',
        preserved_activation_sha256=sha(config / 'activation.json'),
        preserved_configuration_files={p.name:sha(p) for p in config.glob('*.json')},
        stage_files={p.name:sha(p) for p in RELEASE.iterdir() if p.is_file()},
        compose_files={n:sha(REPO / n) for n in ('docker-compose.btc-intraday-pair-latency-v1.yml',
                                               'docker-compose.scalping-persistence-100ms.yml')},
        base_compose_sha256=sha(REPO / 'docker-compose.local.yml'),
        activation_helper_sha256=sha(REPO / 'scripts/activate_intraday_pair_latency.py'))
    (RELEASE / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, indent=2)+'\n')
    for path in RUNTIME.rglob('*'):
        os.chown(path, 0, 30910)
        path.chmod(0o555 if path.is_dir() else 0o444)
    RUNTIME.chmod(0o555)
    for path in RELEASE.iterdir():
        path.chmod(0o440)
    print(json.dumps(dict(prepared=True, activated=False, manifest_sha256=sha(RELEASE / 'manifest.json'))))


if __name__ == '__main__':
    main()
