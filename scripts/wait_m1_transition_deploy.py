"""One-shot continuation of the operator-authorized exact deploy.

Only reads M1 until NORMAL with no intent. No trading policy or timing changes.
Company/repository checkpoint changes stop the job for review. Not a collector.
"""
import argparse
from contextlib import contextmanager
import datetime as dt
import json
import os
from pathlib import Path
import signal
import shutil
import sqlite3
import subprocess
import sys
import time

ROOT=Path('/root/auto_trading_sys');RELEASE=ROOT/'octobot-local/v13-m1-management-v2-r2'
SHA='b454f2d0763b349c103dde0baa1a3a83586de34b8c79f45a48192ef8099baa6d'
PROJECT='project-tranding-ai-lab'


@contextmanager
def ui_target_alias(alias=Path('/workspace'), target=None):
    """Resolve the approved installer's container asset links on the host.

    Never replace a host path. Only a link created by this invocation is removed.
    The approved manifest, helper and two UI artifacts remain unchanged.
    """
    target=(ROOT/'octobot-source' if target is None else Path(target)).resolve()
    if not target.is_dir():raise ValueError('canonical_ui_checkout_unavailable')
    created=False
    if alias.exists() or alias.is_symlink():
        if not alias.is_symlink() or alias.resolve()!=target:
            raise ValueError('workspace_alias_conflicts_with_existing_host_path')
    else:
        alias.symlink_to(target,target_is_directory=True);created=True
    try:
        yield
    finally:
        if created and alias.is_symlink() and alias.resolve()==target:alias.unlink()


def status(path,phase,**fields):
    value=dict(phase=phase,at=dt.datetime.now(dt.timezone.utc).isoformat(),rebalance_approved=False,**fields)
    tmp=path.with_suffix('.pending');tmp.write_text(json.dumps(value,indent=2)+'\n');tmp.chmod(0o600);os.replace(tmp,path)
    print(json.dumps(value),flush=True)


def read_control():
    p=ROOT/'octobot-local/v13-m1-paper-v1/state/account.sqlite'
    db=sqlite3.connect(p.as_uri()+'?mode=ro',uri=True);db.execute('PRAGMA query_only=ON')
    try:return json.loads(db.execute("SELECT payload FROM m1_meta WHERE key='control'").fetchone()[0])
    finally:db.close()


def governance(expected_revision,baseline_path):
    sys.path.insert(0,'/root/.ops/tmp');import cp_daily_20261007 as cp
    baseline=json.loads(baseline_path.read_text())['data']
    output=Path('/root/.ops/tmp/m1-v2-deferred-onboarding.json')
    cursor=Path('/root/.ops/control-plane.cursor').read_text().strip()
    command=['curl','--disable','--fail-with-body','--silent','--show-error','--proto','=https','--get','--data-urlencode','after='+cursor,
             '-H','Accept: application/json','-H','CF-Access-Client-Id: '+os.environ['CF_ACCESS_CLIENT_ID'],
             '-H','CF-Access-Client-Secret: '+os.environ['CF_ACCESS_CLIENT_SECRET'],'--output',str(output),
             '--write-out','%{http_code}\n%{content_type}\n%{redirect_url}\n','https://control-plane.mmtech.website/v1/kb/onboarding']
    run=subprocess.run(command,capture_output=True,text=True,timeout=45)
    if run.returncode or run.stdout.splitlines()[:2]!=['200','application/json; charset=utf-8'] or len(run.stdout.splitlines())<3 or run.stdout.splitlines()[2]:raise ValueError('control_plane_resync_failed')
    now=json.loads(output.read_text())['data']
    for key in ('access_role','company_rules','instructions','skills_manifest','operating_model','coordination_governance','work_board_governance','knowledge_base'):
        if now[key]!=baseline[key]:raise ValueError('company_contract_changed_review_required')
    if now['company_change_feed']['changes']:raise ValueError('company_change_feed_requires_review')
    cp.PROJECT=next(p for p in now['assigned_projects'] if p['id']==PROJECT);cp.FIELDS=now['work_board_governance']['create_contract']['accepted_fields']
    active=cp.cp('GET',cp.PROJECT['active_coordination_session_url'])['session']
    if active['current_execution_checkpoint']['recorded_revision']!=expected_revision:raise ValueError('project_checkpoint_changed_review_required')
    Path('/root/.ops/control-plane.cursor').write_text(now['company_change_feed']['next_cursor']+'\n')
    return cp


def main():
    p=argparse.ArgumentParser();p.add_argument('--checkpoint-revision',type=int,required=True);p.add_argument('--browser-image',required=True);p.add_argument('--check-only',action='store_true');a=p.parse_args()
    output=ROOT/'audit-evidence/m1-v2-ui-20261024/deferred-technical-deploy';output.mkdir(exist_ok=True,mode=0o700);path=output/'status.json'
    control=read_control()
    if a.check_only:
        print(json.dumps(dict(phase=control['phase'],pending=bool(control.get('pending')),ready=control['phase']=='NORMAL' and not control.get('pending'),mutated=False)));return
    probe=output/'live-probe.py';shutil.copyfile(ROOT/'octobot-source/tests/browser/v13_m1_v2_live_probe.py',probe);probe.chmod(0o440)
    baseline_path=output/'company-contract-baseline.json';shutil.copyfile('/root/.ops/tmp/m1-v2-activate-20261024-onboarding.json',baseline_path);baseline_path.chmod(0o600)
    deadline=min(dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=14),dt.datetime.fromisoformat(json.loads((RELEASE/'configuration/transition-proposal.json').read_text())['expires_at'])-dt.timedelta(minutes=15))
    signal.signal(signal.SIGTERM,lambda *_:(_ for _ in ()).throw(KeyboardInterrupt()))
    prior=None
    try:
        while True:
            control=read_control();label=(control['phase'],bool(control.get('pending')))
            if label!=prior:
                status(path,'WAITING_NORMAL',account_phase=label[0],pending=label[1],exit_due=control.get('exit_due'),deadline=deadline.isoformat());prior=label
            if dt.datetime.now(dt.timezone.utc)>=deadline:raise ValueError('normal_phase_not_reached_before_deadline')
            if control['phase']=='NORMAL' and not control.get('pending'):break
            time.sleep(30)
        cp=governance(a.checkpoint_revision,baseline_path)
        status(path,'DEPLOYING_AUTHORIZED_PACKAGE')
        command=[sys.executable,str(ROOT/'octobot-source/scripts/activate_m1_transition_release.py'),'--release',str(RELEASE),'--release-sha256',SHA,
                 '--manual-operator-deploy','--operator-reference','Explicit operator technical-only approval 2026-10-24; deferred until NORMAL; no rebalance approval']
        with ui_target_alias():
            with (output/'deploy.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        browser=output/'browser';browser.mkdir(exist_ok=True)
        command=['docker','run','--rm','--pull=never','--network','host','--read-only','--memory','1g','--cpus','2','--shm-size','256m','--tmpfs','/tmp:rw,size=256m',
                 '-v',str(probe)+':/live-probe.py:ro','-v',str(browser)+':/evidence:rw','--entrypoint','python3',a.browser_image,
                 '-B','/live-probe.py']
        with (output/'browser.log').open('w') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
        board=cp.cp('GET',cp.PROJECT['work_board_url']);ids=json.loads(Path('/root/.ops/tmp/m1-v2-ui-20261024-cards.json').read_text())
        for key in ('runner','ui','test','release'):
            card=next(v for v in board['cards'] if v['id']==ids[key]['id'])
            if card['status']=='blocked':card=cp.change(card,status=card['blocked_from_status'] or 'in_progress',blocker_reason=None)
            cp.change(card,status='test',blocker_reason=None,next_action='Passaggio tecnico e browser operativo verificati. V2 visibile, zero decisioni e policy assente; attendere accettazione tecnica operatore e separata scelta economica in UI.',evidence_refs=['reports/V13_M1_V2_UI_RUNNER_2026-10-24.md','audit-evidence/m1-v2-ui-20261024/deferred-technical-deploy/status.json'])
        session=cp.cp('GET',cp.PROJECT['active_coordination_session_url'])['session']
        if session['current_execution_checkpoint']['recorded_revision']==a.checkpoint_revision:
            git=['git','-c','safe.directory=/var/lib/libvirt/trading-ai-lab/auto_trading_sys/octobot-source','-C',str(ROOT/'octobot-source')]
            head=subprocess.check_output(git+['rev-parse','HEAD'],text=True).strip();branch=subprocess.check_output(git+['branch','--show-current'],text=True).strip()
            body=dict(expected_revision=session['revision'],event_type='execution_checkpoint_recorded',payload=dict(request_summary='Completed explicitly authorized deferred M1 v2 technical deployment; no rebalance approval',repository_alias='octobot-source',branch=branch,head_commit=head,worktree_state='dirty',changed_paths=['docker-compose.local.yml'],changed_paths_truncated=True,current_action='Authorized exact package loaded after NORMAL phase. Fresh stopped-ledger backup, healthy services and live desktop/mobile browser verification passed. V2 proposed, decisions zero and maintenance policy absent. Original and all other accounts and collectors unchanged.',next_action='Operator may accept the technical delivery and separately approve or reject the precise LONG maintenance proposal in UI. No valid operator credential used by the agent and no strategy shutdowns.'))
            cp.cp('POST',cp.PROJECT['coordination_sessions_url']+'/'+session['id']+'/events',body)
        status(path,'COMPLETED_TECHNICAL_ONLY',live_browser='PASS',economic_approval='STILL_REQUIRED_IN_UI')
    except KeyboardInterrupt:
        status(path,'CANCELLED_NO_FURTHER_ACTION');raise SystemExit(130)
    except Exception as error:
        status(path,'STOPPED_REVIEW_REQUIRED',reason=type(error).__name__+': '+str(error));raise


if __name__=='__main__':main()
