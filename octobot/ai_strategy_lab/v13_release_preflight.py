"""Pure/read-only preparation checks. Does not issue activation or create stores."""
import hashlib
import json
from pathlib import Path


def assess(plan,manifest,root):
    errors=[];pending=[];root=Path(root).resolve()
    if plan.get('scope')!='ABC_INACTIVE_RELEASE_PLAN_V1':errors.append('plan_scope')
    if plan.get('active') is not False or plan.get('orders_authorized') is not False:errors.append('inactive_plan_required')
    if manifest.get('comparison_active',manifest.get('active')) is not False:errors.append('inactive_bundle_required')
    files=manifest.get('files')
    if not isinstance(files,dict) or not files:errors.append('bundle_files_missing')
    else:
        for name,pin in files.items():
            path=Path(name)
            if path.is_absolute() or '..' in path.parts or not (root/path).resolve().is_relative_to(root):
                errors.append('unsafe_bundle_path');continue
            if (root/path).is_symlink() or not (root/path).is_file():errors.append('bundle_file_missing:'+name);continue
            if hashlib.sha256((root/path).read_bytes()).hexdigest()!=pin:errors.append('bundle_hash:'+name)
    uids=plan.get('uids',{})
    assigned=[]
    for role in ('collector','producer','executor'):
        value=uids.get(role)
        if value is None:pending.append('assign_uid:'+role)
        elif type(value) is not int or value<=0:errors.append('invalid_uid:'+role)
        else:assigned.append(value)
    if len(set(assigned))!=len(assigned):errors.append('writers_not_separated')
    paths=plan.get('paths',{});stores=[]
    for key in ('forward','intents','execution','status'):
        value=paths.get(key)
        if not isinstance(value,str):errors.append('path_missing:'+key);continue
        p=Path(value)
        if not p.is_absolute() or '..' in p.parts:errors.append('unsafe_store_path:'+key);continue
        stores.append(p.resolve())
    if len(set(stores))!=len(stores):errors.append('store_alias')
    # A shared writable parent would defeat the intended writer separation.
    if all(isinstance(paths.get(k),str) for k in ('forward','intents','execution')):
        parents=[Path(paths[k]).resolve().parent for k in ('forward','intents','execution')]
        if len(set(parents))!=3 or any(a!=b and (a in b.parents or b in a.parents) for a in parents for b in parents):
            errors.append('writer_directory_overlap')
    for key in ('start_utc','lineage','warmup_report_sha256','funding_calendar_sha256','approved_release_reference'):
        value=plan.get(key)
        if value is None:pending.append('bind:'+key)
        elif not isinstance(value,str) or not value.strip():errors.append('invalid_binding:'+key)
        elif key.endswith('_sha256') and (len(value)!=64 or any(c not in '0123456789abcdef' for c in value)):errors.append('invalid_pin:'+key)
    if plan.get('start_utc'):
        import datetime as dt
        try:
            start=dt.datetime.fromisoformat(plan['start_utc'].replace('Z','+00:00'))
            cutoff=dt.datetime.fromisoformat(plan['qualification_cutoff'].replace('Z','+00:00'))
            if start.utcoffset()!=dt.timedelta(0) or start<=cutoff or (start.hour,start.minute,start.second,start.microsecond)!=(0,15,0,0):errors.append('invalid_common_start')
        except (ValueError,TypeError):errors.append('invalid_common_start')
    values=plan.get('candidate_timing',{})
    for key,maximum in [('poll_seconds',30),('intent_validity_seconds',60)]:
        v=values.get(key)
        if type(v) is not int or not 1<=v<=maximum:errors.append('invalid_timing:'+key)
    inputs=plan.get('inputs',{})
    for key in ('repo','qualification_archive','qualification_uid','qualification_start','qualification_binding','qualification_activation','warmup_path','approval_path','approval_sha256','calendar_path'):
        value=inputs.get(key)
        if value is None:pending.append('input:'+key)
        elif key=='qualification_uid':
            if type(value) is not int or value<=0:errors.append('invalid_input:'+key)
        elif not isinstance(value,str) or not value.strip():errors.append('invalid_input:'+key)
        elif (key.endswith('_sha256') or key=='qualification_binding') and (len(value)!=64 or any(c not in '0123456789abcdef' for c in value)):
            errors.append('invalid_input_pin:'+key)
    required=['qualification_pass','funding_coverage_review','uid_and_filesystem_review','activation_receipt']
    for gate in required:
        # This kit inventories evidence; booleans in a draft never open gates.
        if plan.get('gate_evidence',{}).get(gate) is not None:errors.append('draft_cannot_assert_gate:'+gate)
    return dict(scope='ABC_PREPARATION_REPORT_V1',technical_checks_passed=not errors,errors=errors,
                bindings_pending=pending,activation_gates=required,execution_ready=False,
                orders_authorized=False,stores_created=False)


def configurations(plan):
    """Candidate fragments, deliberately NOT runtime CLI scopes."""
    common=dict(scope='DRAFT_NOT_RUNTIME_CONFIGURATION',active=False,orders_authorized=False,
                start_utc=plan['start_utc'],lineage=plan['lineage'],**plan['candidate_timing'])
    paths=plan['paths'];uids=plan['uids']
    inputs=plan['inputs']
    configs={role:dict(common,role=role,uid=uids[role],writable_paths=([paths['execution'],paths['status']] if role=='executor' else [paths['forward'] if role=='collector' else paths['intents']]),
                      read_only_paths=([paths['forward'],paths['intents']] if role=='executor' else [paths['forward']] if role=='producer' else []))
            for role in ('collector','producer','executor')}
    configs['collector'].update(intended_runtime_scope='ABC_FORWARD_COLLECTOR_CONFIGURATION_V1',
        repo=inputs['repo'],archive=paths['forward'],collector_uid=uids['collector'],public_downloads_authorized=True)
    configs['producer'].update(intended_runtime_scope='ABC_PRODUCER_CONFIGURATION_V1',
        repo=inputs['repo'],intents=paths['intents'],producer_uid=uids['producer'],executor_uid=uids['executor'],forward_uid=uids['collector'],forward_path=paths['forward'],
        qualification_archive=inputs['qualification_archive'],qualification_uid=inputs['qualification_uid'],qualification_start=inputs['qualification_start'],qualification_binding=inputs['qualification_binding'],
        warmup_path=inputs['warmup_path'],warmup_report_sha256=plan['warmup_report_sha256'],start=plan['start_utc'])
    configs['executor'].update(intended_runtime_scope='ABC_SERVICE_CONFIGURATION_V1',
        repo=inputs['repo'],intents=paths['intents'],producer_uid=uids['producer'],executor_uid=uids['executor'],forward_uid=uids['collector'],forward_path=paths['forward'],
        ledger_path=paths['execution'],status_path=paths['status'],approval_path=inputs['approval_path'],approval_sha256=inputs['approval_sha256'],archive=inputs['qualification_archive'],activation=inputs['qualification_activation'],
        calendar_path=inputs['calendar_path'],calendar_sha256=plan['funding_calendar_sha256'])
    return configs
