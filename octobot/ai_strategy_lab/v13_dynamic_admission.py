"""Read-only real-consumer preconditions. Does not create a grant or ledger.

Approval fingerprint must come from the reviewed deployment context, not the
candidate file itself. Contract acceptance remains distinct from activation.
"""
import hashlib
import json
import time
from pathlib import Path
try:
    from . import v13_universe_qualification_evaluate as qualification
except ImportError:
    import v13_universe_qualification_evaluate as qualification


def inspect(repo, approval_path, expected_approval_sha256, archive, activation):
    repo=Path(repo).resolve();approval_path=Path(approval_path)
    if approval_path.is_symlink():raise ValueError('approval_symlink')
    raw=approval_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_approval_sha256:
        raise ValueError('approval_fingerprint_mismatch')
    approval=json.loads(raw)
    if approval.get('kind')!='OWNER_CONTRACT_APPROVAL_NOT_ACTIVATION' or approval.get('decision')!='APPROVED':
        raise ValueError('contract_approval_required')
    relative=Path(approval['contract_path'])
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('contract_path')
    path=repo/relative
    if path.is_symlink() or not path.resolve().is_relative_to(repo):raise ValueError('contract_path')
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=approval['contract_file_sha256']:
        raise ValueError('contract_fingerprint_mismatch')
    contract=json.loads(raw)
    if contract.get('scope')!='RESEARCH_SIMULATION_ONLY':raise ValueError('research_contract_required')
    # These pins describe the reviewed snapshot; never silently refresh them.
    changed=[]
    for name,expected in contract['code_sha256'].items():
        p=Path(name)
        if p.is_absolute() or '..' in p.parts or not (repo/p).resolve().is_relative_to(repo):
            raise ValueError('code_path')
        if not (repo/p).is_file() or hashlib.sha256((repo/p).read_bytes()).hexdigest()!=expected:
            changed.append(name)
    verdict=qualification.evaluate_bound(repo,archive,activation,time.time())
    blockers=[]
    if verdict.get('status')!='QUALIFIED':blockers.append('qualification_not_passed')
    if changed:blockers.append('final_bundle_not_frozen')
    if contract['funding']['settlement_schedule_evidence']=='UNRESOLVED':blockers.append('funding_coverage_unresolved')
    # No activation grant or consumer authority is derived from this receipt.
    blockers.append('comparison_activation_not_authorized')
    return dict(scope='ABC_REAL_CONSUMER_PRECONDITIONS',contract_approved=True,
                qualification=verdict,changed_code=changed,blockers=blockers,
                execution_ready=False,orders_authorized=False,paper_orders_authorized=False)
