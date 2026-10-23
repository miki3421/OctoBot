"""Prepare, never activate, the managed M1 continuation.

Card work-card-8f398480-1842-4f8e-88d1-947756d0916c.
No Docker actions, password generation, approval, or live ledger writes.
"""
import argparse,datetime as dt,hashlib,json,os,shutil,sqlite3
from pathlib import Path

NEW=('v13_m1_weekly.py','v13_m1_managed.py','v13_m1_universe_capture.py','v13_m1_approval_broker.py','v13_m1_management_web.py','v13_m1_paper.py','v13_variant_charts.py')

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value,mode=0o440):
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n');os.chown(path,0,30910);path.chmod(mode)
def folder(path,uid,mode=0o750):
    path.mkdir(parents=True,exist_ok=True)
    if path.is_symlink():raise ValueError('release_directory_symlink')
    os.chown(path,uid,30910);path.chmod(mode)

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--runtime',type=Path,required=True);p.add_argument('--snapshot',type=Path,required=True);args=p.parse_args()
    if os.geteuid()!=0:raise SystemExit('Root preparer required')
    root=args.root.resolve();repo=root/'octobot-source';base=root/'octobot-local/v13-m1-paper-v1/configuration';target=root/'octobot-local/v13-m1-management-v1';runtime=args.runtime
    if runtime.exists() or target.exists():raise SystemExit('Refuse to overwrite an existing release')
    snapshot=args.snapshot.resolve()
    db=sqlite3.connect(snapshot.as_uri()+'?mode=ro',uri=True)
    assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
    identity=json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='identity'").fetchone()[0]);db.close()
    shutil.copytree('/opt/v13-m1-paper-runtime-v2',runtime)
    for name in NEW:shutil.copyfile(repo/'octobot/ai_strategy_lab'/name,runtime/'octobot/ai_strategy_lab'/name)
    for path in runtime.rglob('*'):
        if path.is_symlink():raise ValueError('runtime_symlink')
        os.chown(path,0,0);path.chmod(0o555 if path.is_dir() else 0o444)
    runtime.chmod(0o555)
    folder(target,0);folder(target/'configuration',0)
    for name,uid in [('source',30944),('approvals',30945)]:folder(target/name,uid)
    control=root/'octobot-local/v13-paper/m1-management-control';folder(control,0);folder(control/'socket',30945)
    pins={str(x.relative_to(runtime)):sha(x) for x in runtime.rglob('*') if x.is_file()}
    code={f'octobot/ai_strategy_lab/{name}':pins[f'octobot/ai_strategy_lab/{name}'] for name in NEW}
    code['octobot/ai_strategy_lab/v13_dynamic_universe.py']=pins['octobot/ai_strategy_lab/v13_dynamic_universe.py']
    c=json.loads((base/'config.json').read_text());c['protocol']='/configuration/protocol.json';c['runtime_upgrade']='/configuration/runtime-upgrade.json'
    c['management']=dict(scope='M1_WEEKLY_MANAGEMENT_V1',source='/management-source',capture_uid=30944,approval_uid=30945,approvals='/approvals/approvals.sqlite',projection='/projection/management.json',code_pins=code)
    write(target/'configuration/config.json',c)
    proto=json.loads((base/'protocol-v2.json').read_text());proto['source_code_pins']={k:pins[k] for k in proto['source_code_pins']};proto['management_extension']='M1_WEEKLY_SELECTION_MANAGEMENT_V1'
    proto['strategy'].update(normal='Causal V13 weights for weekly approved membership, constrained by side budgets and monotone LONG quantity ceilings',short_sizing='Independent approved SHORT weight budgets triggered by unchanged original 18-asset M1 filter',no_longs='An approved SHORT budget may be used from FLAT; no unapproved asset or weight')
    proto['source_code_pins'].update(code);write(target/'configuration/protocol.json',proto)
    account=json.loads((root/'octobot-local/v13-m1-paper-v1/seed/clone-receipt.json').read_text())['account_id']
    template=dict(scope='M1_WEEKLY_SELECTION_MANAGEMENT_V1',account=account,from_identity=identity,to_identity=dict(seed=identity['seed'],protocol=sha(target/'configuration/protocol.json'),runner=code['octobot/ai_strategy_lab/v13_m1_paper.py']),authorized_at=None,owner_reference='PENDING_OPERATOR_MANUAL_ACTIVATION',backup_sha256=sha(snapshot))
    write(target/'configuration/runtime-upgrade-template.json',template)
    broker=dict(scope='M1_APPROVAL_WRITER_V1',approval_uid=30945,runner_uid=30943,account=account,database='/approvals/approvals.sqlite',socket='/control/approval.sock',verifier='/configuration/verifier.json',projection='/projection/management.json',web_peer_uids=[0])
    write(target/'configuration/broker.json',broker)
    # Start far enough back to continue the existing account's funding cursors;
    # no recomputation of historical account cash or synthetic missing rates.
    capture=dict(scope='M1_WEEKLY_PUBLIC_CAPTURE_V1',capture_uid=30944,output='/capture',poll_seconds=30,public_downloads_authorized=True,authorization_reference='User authorized periodic public acquisition for all 29 symbols',funding_start_ms=int(dt.datetime(2026,10,17,tzinfo=dt.timezone.utc).timestamp()*1000))
    write(target/'configuration/capture.json',capture)
    manifest=dict(scope='M1_WEEKLY_PREPARED_NOT_ACTIVATED',account=account,prepared_at=dt.datetime.now(dt.timezone.utc).isoformat(),runtime_files=pins,config_files={str(x.relative_to(target)):sha(x) for x in (target/'configuration').iterdir() if x.is_file()},runtime=str(runtime),image='sha256:7e825796375e06e3cfb6ea46b5b7202bdba4c0bb998bdffea5e02b8bd9d67575',source_snapshot_sha256=sha(snapshot),orders_authorized=False,activation_authorized=False,requires=['operator password verifier','manual activation reference','fresh stopped-ledger backup','specific proposal approval in UI'])
    write(target/'release-manifest.json',manifest)
    print(json.dumps(dict(account=account,prepared=True,activated=False,files=len(pins))))
if __name__=='__main__':main()
