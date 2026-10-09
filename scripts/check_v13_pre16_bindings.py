"""Read-only host verification of the prepared identities, dirs and warm-up.

Does not open qualification results, create stores, install units or authorize execution.
"""
import argparse
import hashlib
import json
import os
import pwd
import stat
import sys
from pathlib import Path


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--plan',required=True)
    p.add_argument('--repo',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    plan=json.loads(Path(a.plan).read_text());errors=[];identities={}
    for role,uid in plan['uids'].items():
        user=pwd.getpwuid(uid)
        groups=os.getgrouplist(user.pw_name,user.pw_gid)
        expected=[uid]
        if role!='collector':expected.append(plan['read_groups']['forward'])
        if role=='executor':expected.append(plan['read_groups']['intents'])
        if user.pw_name!='v13-abc-'+role or user.pw_shell!='/usr/sbin/nologin' or sorted(groups)!=sorted(expected):errors.append('identity:'+role)
        identities[role]=dict(uid=uid,gid=user.pw_gid,groups=groups,shell=user.pw_shell)
        key={'collector':'forward','producer':'intents','executor':'execution'}[role]
        directory=Path(plan['paths'][key]).parent
        info=directory.lstat()
        gid=plan['read_groups']['forward' if role=='collector' else 'intents'] if role!='executor' else uid
        mode=0o2750 if role!='executor' else 0o700
        if not stat.S_ISDIR(info.st_mode) or info.st_uid!=uid or info.st_gid!=gid or stat.S_IMODE(info.st_mode)!=mode:errors.append('directory:'+role)
        for ancestor in directory.parents:
            st=ancestor.lstat()
            if not stat.S_ISDIR(st.st_mode) or st.st_uid!=0 or st.st_mode&0o022:errors.append('ancestor:'+role)
    root=Path(plan['inputs']['warmup_path']);envelope=json.loads((root/'report.json').read_text())
    body=json.dumps(envelope['report'],sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    if hashlib.sha256(body).hexdigest()!=plan['warmup_report_sha256'] or envelope['report_sha256']!=plan['warmup_report_sha256']:errors.append('warmup_pin')
    for receipt in envelope['report']['receipts']:
        f=root/'raw'/(receipt['receipt_id']+'.raw')
        if f.is_symlink() or hashlib.sha256(f.read_bytes()).hexdigest()!=receipt['raw_sha256']:errors.append('warmup_raw')
    for role in plan['uids']:
        config=json.loads((Path(a.repo)/('docs/deployment/abc-'+role+'-prepared-v2.json')).read_text())
        if config['scope']!='DRAFT_NOT_RUNTIME_CONFIGURATION' or config['uid']!=plan['uids'][role]:errors.append('draft_config:'+role)
    ledger=Path(plan['paths']['execution'])
    # These predicates only attest this pre-cutoff state; not a future execution gate.
    result=dict(scope='HOST_PRE_CUTOFF_BINDINGS_CHECK',checks_passed=not errors,errors=errors,
        identities=identities,ledger_exists=ledger.exists(),qualification_opened=False,
        common_start_bound=plan['start_utc'] is not None,
        calendar_exists=Path(plan['inputs']['calendar_path']).exists(),execution_ready=False)
    with Path(a.output).open('x') as stream:json.dump(result,stream,indent=2)
    print(json.dumps(result));return int(bool(errors))


if __name__=='__main__':raise SystemExit(main())
