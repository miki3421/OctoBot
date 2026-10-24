"""Exact, operator-directed legacy retirement. No deletion, order or risk reset."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time

ROOT=Path('/root/auto_trading_sys');REPO=ROOT/'octobot-source'
EVIDENCE=ROOT/'audit-evidence/btc-legacy-retirement-20261024'
RELEASE=ROOT/'octobot-local/btc-intraday-retirement-v1'
MONITOR=Path('/opt/trading-lab-resource-monitor-v5')
WEB=REPO/'packages/tentacles/Services/Interfaces/web_interface'
STATE=ROOT/'octobot-local/btc-intraday-m1-l5-paper-v1/state'
PROJECTION=ROOT/'octobot-local/v13-paper/intraday-ui/account.json'
RECEIPT=ROOT/'octobot-local/v13-paper/intraday-retirement/receipt.json'
TARGET='octobot-btc-intraday-paper'


def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def run(*args):return subprocess.check_output(list(args),cwd=REPO,text=True).strip()
def write(p,v):
    tmp=p.with_suffix('.pending')
    with tmp.open('w') as f:json.dump(v,f,sort_keys=True,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
    tmp.chmod(0o444);os.replace(tmp,p)


def states():
    out={}
    for name in ('account','stress'):
        c=sqlite3.connect((STATE/(name+'.sqlite')).resolve().as_uri()+'?mode=ro',uri=True);c.execute('PRAGMA query_only=ON')
        try:
            value=json.loads(c.execute('SELECT payload FROM state').fetchone()[0])
            assert not c.execute("SELECT 1 FROM funding WHERE status='PENDING' LIMIT 1").fetchone(),'unsettled_funding'
            out[name]=value
        finally:c.close()
    return out


def flat(value):return all(s['q']==0 and s.get('pending') is None for s in value.values())


def inventory():
    names=run('docker','ps','--filter','name=octobot-','--format','{{.Names}}').splitlines()
    return {v['Name'].lstrip('/'):dict(id=v['Id'],started=v['State']['StartedAt'],restarts=v['RestartCount'],health=v['State'].get('Health',{}).get('Status')) for v in json.loads(run('docker','inspect',*names))}


def prepare():
    assert not RELEASE.exists() and not MONITOR.exists()
    RELEASE.mkdir(mode=0o700);(RELEASE/'ui').mkdir()
    dirty_templates=EVIDENCE/'ui-candidate'
    for name in ('templates/v13_variants.html','templates/components/lab_sidebar.html','templates/btc_intraday.html','static/js/common/v13_variants_lifecycle.js','static/js/common/btc_intraday.js'):
        src=dirty_templates/name if (dirty_templates/name).exists() else WEB/name
        dst=RELEASE/'ui'/name;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,dst)
    shutil.copytree('/opt/trading-lab-resource-monitor-v4',MONITOR)
    shutil.copyfile(REPO/'scripts/lab_resource_monitor_retirement.py',MONITOR/'entrypoint.py')
    shutil.copyfile(REPO/'octobot/ai_strategy_lab/btc_intraday_retirement.py',MONITOR/'btc_intraday_retirement.py')
    c=json.loads((MONITOR/'config.json').read_text());assert TARGET in c['containers'] and 'intraday' in c['paper_accounts']
    c['containers'].remove(TARGET);item=c['paper_accounts'].pop('intraday');c['retired_accounts']={'intraday':dict(path=item['path'],uid=item['uid'],receipt=str(RECEIPT))}
    write(MONITOR/'config.json',c)
    p=MONITOR/'trading-lab-resource-monitor.service';s=p.read_text().replace('/opt/trading-lab-resource-monitor-v4',str(MONITOR)).replace('-B monitor.py','-B entrypoint.py');p.write_text(s)
    pins={str(p.relative_to(MONITOR)):sha(p) for p in sorted(MONITOR.rglob('*')) if p.is_file() and p.name!='files.sha256'}
    (MONITOR/'files.sha256').write_text(''.join(f'{h}  {n}\n' for n,h in pins.items()))
    manifest=dict(scope='PREPARED_LEGACY_INTRADAY_RETIREMENT',monitor_files=pins,monitor_checksums=sha(MONITOR/'files.sha256'),
        ui_files={str(p.relative_to(RELEASE/'ui')):sha(p) for p in (RELEASE/'ui').rglob('*') if p.is_file()},
        source_files={n:sha(REPO/n) for n in ('octobot/ai_strategy_lab/btc_intraday_view.py','octobot/ai_strategy_lab/btc_intraday_retirement.py','scripts/retire_btc_intraday.py')},
        before_templates={n:sha(WEB/n) for n in ('templates/v13_variants.html','templates/components/lab_sidebar.html')},
        previous_monitor_unit_sha256=sha(Path('/etc/systemd/system/trading-lab-resource-monitor.service')))
    write(RELEASE/'manifest.json',manifest)
    for p in MONITOR.rglob('*'):
        os.chown(p,0,0);p.chmod(0o555 if p.is_dir() else 0o444)
    MONITOR.chmod(0o555)
    print(json.dumps(dict(prepared=True,activated=False,manifest_sha256=sha(RELEASE/'manifest.json'))))


def activate(args):
    assert sha(RELEASE/'manifest.json')==args.manifest_sha256,'exact_manifest'
    m=json.loads((RELEASE/'manifest.json').read_text());assert m['scope']=='PREPARED_LEGACY_INTRADAY_RETIREMENT'
    for name,h in m['monitor_files'].items():assert sha(MONITOR/name)==h
    assert sha(MONITOR/'files.sha256')==m['monitor_checksums']
    for name,h in m['ui_files'].items():assert sha(RELEASE/'ui'/name)==h
    for name,h in m['source_files'].items():assert sha(REPO/name)==h
    for name,h in m['before_templates'].items():assert sha(WEB/name)==h,'template_drift'
    assert sha(Path('/etc/systemd/system/trading-lab-resource-monitor.service'))==m['previous_monitor_unit_sha256']
    if not args.operator_reference:
        print(json.dumps(dict(verified=True,activated=False)));return
    assert not RECEIPT.exists() and 0<len(args.operator_reference)<=240
    assert flat(states()),'wait_flat_no_pending_in_both_scenarios'
    assert shutil.disk_usage(STATE).free>30*2**30
    before=inventory();out=EVIDENCE/('manual-'+time.strftime('%Y%m%dT%H%M%SZ',time.gmtime()));out.mkdir(mode=0o700)
    write(out/'before-containers.json',before)
    run('systemctl','stop','trading-lab-resource-monitor.timer')
    until=time.monotonic()+60
    while run('systemctl','show','trading-lab-resource-monitor.service','-p','ActiveState','--value')=='activating':
        assert time.monotonic()<until;time.sleep(1)
    run('docker','stop','--timeout','30',TARGET)
    stopped=states();assert flat(stopped),'stopped_state_changed_review_required'
    write(out/'stopped-states.json',stopped)
    run('ionice','-c','3','nice','-n','10','cp','-a','--reflink=auto','--sparse=always',str(STATE),str(out/'raw-state'))
    raw=PROJECTION.read_bytes();v=json.loads(raw)
    assert v['state']['fills']==stopped['account']['fills'] and v['metrics']['equity']==stopped['account']['cash'],'projection_money_changed'
    assert v['stress']['fills']==stopped['stress']['fills'] and v['stress']['equity']==stopped['stress']['cash'],'stress_money_changed'
    receipt=dict(schema=1,scope='RETIRED_SYNTHETIC_PAPER_ACCOUNT',account='btc-intraday-m1-l5-paper-v1',container=TARGET,
        retired=True,real_orders=False,both_scenarios_flat=True,both_scenarios_no_pending=True,retired_at_ns=time.time_ns(),
        operator_reference=args.operator_reference,projection_sha256=hashlib.sha256(raw).hexdigest())
    sys_path=str(REPO/'octobot/ai_strategy_lab')
    import sys;sys.path.insert(0,sys_path)
    from btc_intraday_retirement import validate
    RECEIPT.parent.mkdir(mode=0o755);os.chown(RECEIPT.parent,0,0);write(RECEIPT,receipt)
    validate(RECEIPT,raw,now_ns=time.time_ns())
    run('docker','update','--restart=no',TARGET)
    for name in m['ui_files']:
        dst=WEB/name;shutil.copyfile(RELEASE/'ui'/name,dst)
    shutil.copyfile(MONITOR/'trading-lab-resource-monitor.service','/etc/systemd/system/trading-lab-resource-monitor.service')
    run('systemctl','daemon-reload');run('systemctl','start','trading-lab-resource-monitor.timer')
    run('docker','restart','octobot-local')
    run('systemctl','start','trading-lab-resource-monitor.service')
    until=time.monotonic()+180
    while time.monotonic()<until:
        after=inventory()
        if after.get('octobot-local',{}).get('health')=='healthy':break
        time.sleep(2)
    else:raise ValueError('dashboard_health_timeout')
    assert len(after)==len(before)-1 and TARGET not in after
    for name,value in before.items():
        if name not in (TARGET,'octobot-local'):assert all(after[name][k]==value[k] for k in ('id','started','restarts')),'unrelated_container_changed'
    run('ionice','-c','3','nice','-n','10','cp','-a','--reflink=auto','--sparse=always',str(out/'raw-state'),str(out/'checked-state'))
    checks={}
    for p in (out/'checked-state').rglob('*.sqlite'):
        c=sqlite3.connect(p);c.execute('SELECT COUNT(*) FROM sqlite_master').fetchone();c.close()
        c=sqlite3.connect(p.resolve().as_uri()+'?mode=ro',uri=True);c.execute('PRAGMA query_only=ON');assert c.execute('PRAGMA integrity_check').fetchone()[0]=='ok';c.close();checks[str(p.relative_to(out/'checked-state'))]='ok'
    assert states()==stopped and PROJECTION.read_bytes()==raw,'retired_archive_changed'
    write(out/'result.json',dict(retired=True,receipt_sha256=sha(RECEIPT),projection_sha256=receipt['projection_sha256'],
        other_containers_unchanged=True,integrity=checks,final_states=stopped,market_observer_active=True))
    print(json.dumps(dict(retired=True,evidence=str(out),active_containers=len(after))))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--prepare',action='store_true');p.add_argument('--manifest-sha256');p.add_argument('--operator-reference');a=p.parse_args()
    assert os.geteuid()==0
    if a.prepare:prepare()
    else:activate(a)
