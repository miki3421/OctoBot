"""Inactive archive publication + original target reconstruction, never issuance.

Card work-card-824a3cd4-3dc8-437f-abbf-6a233b0ce0a5. Existing raw is copied
without inventing historical capture receipts. Low-level persistence helpers
are reused; the synthetic normalizer/config/receipts are NOT reused as authority.
"""
from __future__ import annotations
from contextlib import closing
import datetime as dt
import fcntl
import gzip
import hashlib
import math
import os
from pathlib import Path

from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_original_verify as original
from octobot.ai_strategy_lab import v13_causal_publication_fixture as storage

VERSION = 'v13-original-archive-publication-review-v1'
SCOPE = 'LEGACY_ARCHIVE_REVIEW'
ROLES = ('strategy','custodian','publisher','verifier','witness')
MARKER = (VERSION+'\n').encode()


def sha(raw): return hashlib.sha256(raw).hexdigest()


def _code_pins():
    return {name:sha(Path(module.__file__).read_bytes()) for name,module in
            [('wrapper',__import__(__name__,fromlist=[''])),('original_verifier',original),
             ('portfolio',p),('storage_helpers',storage)]}


def inventory(inputs, *, source_bar_date):
    """Read-only inventory of exactly the consumed prefix and preserved raw bytes."""
    contract,_ = p.load_contract(inputs.repo_root)
    day = p.bar_date(source_bar_date)
    runner,context = original._load_runner(inputs,contract)
    records = original.load_daily_prefix(inputs,runner,context,day)
    source,prefix = original.load_source_prefix(original._safe(inputs.archive_root,'decisions.jsonl'),day,contract)
    files = {}
    def add(relative,raw,kind,**extra):
        entry = {'path':relative,'sha256':sha(raw),'length':len(raw),'kind':kind,**extra}
        if relative in files and files[relative] != entry: raise p.Rejected('dependency_path_conflict')
        files[relative] = entry
    # Preserve original journal bytes through this slot, not a reserialized tail.
    lines=[]
    with (inputs.archive_root/'decisions.jsonl').open('rb') as stream:
        for _ in prefix: lines.append(stream.readline(p.MAX_JSON_BYTES+1))
    add('decisions.jsonl',b''.join(lines),'source_journal_prefix')
    raw_seen={}; funding_seen={}
    first = int(p.timestamp(records[0]['bar_date']+'T00:00:00Z').timestamp()*1000)
    last = int((p.timestamp(day.isoformat()+'T00:00:00Z')+dt.timedelta(days=1)).timestamp()*1000)
    for record in records:
        relative='daily/'+record['bar_date']+'.json.gz'
        add(relative,original._bytes(original._safe(inputs.archive_root,relative)),'normalized_daily')
        for symbol in contract['universe']:
            values=record['symbols'][symbol]
            for kind,artifacts,endpoint in [('daily_klines',[values['raw']['daily_klines']],'/fapi/v1/klines'),
                ('settled_funding',values['raw']['funding_pages'],'/fapi/v1/fundingRate')]:
                for artifact in artifacts:
                    raw = original._raw_bytes(inputs,artifact,symbol=symbol,endpoint=endpoint,cache=raw_seen)
                    relative='raw/'+artifact['path']
                    add(relative,original._bytes(original._safe(inputs.archive_root,relative)),'raw_response',
                        response_sha256=artifact['response_sha256'],request_url=artifact['url'],
                        request_method='GET',research_exchange='BINANCE_FUTURES',
                        historical_capture_receipt_status='MISSING',request_started_at=None,
                        response_completed_at=None,historical_receipt_committed_at=None,
                        clock_evidence_ref=None,credentials_used=False)
                    if kind == 'settled_funding':
                        for row in p.read_json(raw):
                            instant=row['fundingTime']
                            if type(instant) is not int or instant <= 0: raise p.Rejected('invalid_raw_settlement_time')
                            if first < instant <= last:
                                rate=float(row['fundingRate'])
                                if not math.isfinite(rate):raise p.Rejected('nonfinite_raw_funding')
                                key=(symbol,instant)
                                if key in funding_seen and funding_seen[key] != rate:
                                    raise p.Rejected('conflicting_raw_funding_duplicate')
                                funding_seen[key]=rate
    result={'version':VERSION,'scope':SCOPE,'source_bar_date':day.isoformat(),
        'account':contract['account'],'scientific_lineage_ref':contract['scientific_lineage_ref'],
        'universe_hash':contract['universe_hash'],'source_record_hash':source['journal_record_hash'],
        'source_prefix_hash':p.digest(prefix),'daily_prefix_records':len(records),'source_prefix_records':len(prefix),
        'dependencies':sorted(files.values(),key=lambda x:x['path']),
        'historical_availability_status':'UNRESOLVED','historical_capture_receipts_created':False,
        'execution_approved':False,'issuable':False}
    return result


def init_review(root, inputs, *, source_bar_date, expected_inventory_hash, uids):
    """Bootstrap a sandbox only; numeric test UIDs are not installed identities."""
    p.require_hash(expected_inventory_hash);p.bar_date(source_bar_date)
    if set(uids)!=set(ROLES) or any(type(v) is not int or v<0 for v in uids.values()):raise p.Rejected('invalid_roles')
    root=Path(root).absolute()
    if 'octobot-local' in root.parts or '..' in root.parts:raise p.Rejected('operational_output_forbidden')
    for location in (inputs.repo_root,inputs.research_root,inputs.archive_root,inputs.implementation_lock.parent):
        if root.is_relative_to(Path(location).absolute()):raise p.Rejected('input_output_overlap')
    root.mkdir(mode=0o755)
    storage._path(root,root,directory=True)
    storage._write(root/'sandbox.marker',MARKER)
    for role in ROLES:
        directory=root/role;directory.mkdir(mode=0o755);os.chown(directory,uids[role],-1)
    contract,_=p.load_contract(inputs.repo_root)
    config={'version':VERSION,'scope':SCOPE,'root_owner':os.geteuid(),'uids':uids,'code_pins':_code_pins(),
        'review_started_at':dt.datetime.now(p.UTC).isoformat(),
        'account':contract['account'],'scientific_lineage_ref':contract['scientific_lineage_ref'],
        'universe_hash':contract['universe_hash'],'source_bar_date':source_bar_date,
        'expected_inventory_hash':expected_inventory_hash,
        'repo_root':str(Path(inputs.repo_root).absolute()),'research_root':str(Path(inputs.research_root).absolute()),
        'implementation_lock':str(Path(inputs.implementation_lock).absolute()),
        'operational_custody_approved':False,'clock_policy_approved':False,
        'execution_approved':False,'issuable':False,'min_quantity':None,'min_notional':None}
    storage._write(root/'config.json',p.canonical_bytes(config));storage._fsync_dir(root)
    return p.digest(config)


def _config(root,pin,role=None):
    root=Path(root).absolute();p.require_hash(pin)
    raw=storage._path(root,root/'config.json').read_bytes()
    if sha(raw)!=pin:raise p.Rejected('external_config_pin_mismatch')
    config=p.read_json(raw)
    if (config['version']!=VERSION or config['scope']!=SCOPE or config['code_pins']!=_code_pins()
        or any(config.get(k) is not False for k in ('operational_custody_approved','clock_policy_approved','execution_approved','issuable'))
        or config.get('min_quantity') is not None or config.get('min_notional') is not None):
        raise p.Rejected('review_contract_mismatch')
    storage._path(root,root,directory=True,owner=config['root_owner'])
    storage._path(root,root/'config.json',owner=config['root_owner'])
    if storage._path(root,root/'sandbox.marker',owner=config['root_owner']).read_bytes()!=MARKER:
        raise p.Rejected('not_review_sandbox')
    for name in ROLES:storage._path(root,root/name,directory=True,owner=config['uids'][name])
    if role and os.geteuid()!=config['uids'][role]:raise p.Rejected('wrong_review_role')
    return config


def _relative(root,base,relative,owner):
    if not isinstance(relative,str) or Path(relative).is_absolute() or '..' in Path(relative).parts:
        raise p.Rejected('invalid_dependency_path')
    return storage._path(root,base/relative,owner=owner)


def capture_archive(root,inputs,*,expected_config_hash,_fault=None):
    """Archive-copy persistence today. NEVER an attestation of historical receipt."""
    root=Path(root).absolute();config=_config(root,expected_config_hash,'custodian')
    descriptor=inventory(inputs,source_bar_date=config['source_bar_date'])
    ident=p.digest(descriptor)
    if ident!=config['expected_inventory_hash']:raise p.Rejected('external_inventory_pin_mismatch')
    base=root/'custodian'/ident
    base.mkdir(mode=0o755,exist_ok=True);storage._path(root,base,directory=True,owner=config['uids']['custodian'])
    for item in descriptor['dependencies']:
        target=base/'archive'/item['path']
        target.parent.mkdir(mode=0o755,parents=True,exist_ok=True)
        storage._path(root,target.parent,directory=True,owner=config['uids']['custodian'])
        if item['kind']=='source_journal_prefix':
            raw=b''
            with (inputs.archive_root/'decisions.jsonl').open('rb') as stream:
                for _ in range(descriptor['source_prefix_records']):raw+=stream.readline(p.MAX_JSON_BYTES+1)
        else:raw=original._bytes(original._safe(inputs.archive_root,item['path']))
        if sha(raw)!=item['sha256'] or len(raw)!=item['length']:raise p.Rejected('source_changed_during_copy')
        storage._write(target,raw)
        if _fault:_fault('copied_dependency')
    for directory in sorted([x for x in base.rglob('*') if x.is_dir()],key=lambda x:len(x.parts),reverse=True):
        storage._fsync_dir(directory)
    storage._write(base/'inventory.json',p.canonical_bytes(descriptor))
    storage._fsync_dir(base);storage._fsync_dir(base.parent)
    if _fault:_fault('after_capture_fsync')
    return ident


def _inventory(root,ident,config,*,sync=False):
    p.require_hash(ident);base=Path(root)/'custodian'/ident
    descriptor=p.read_json(storage._path(root,base/'inventory.json',owner=config['uids']['custodian']).read_bytes())
    if p.digest(descriptor)!=ident or ident!=config['expected_inventory_hash']:
        raise p.Rejected('inventory_pin_mismatch')
    for item in descriptor['dependencies']:
        path=_relative(root,base/'archive',item['path'],config['uids']['custodian'])
        raw=original._bytes(path)
        if sha(raw)!=item['sha256'] or len(raw)!=item['length']:raise p.Rejected('dependency_changed')
        if sync:
            with path.open('rb') as stream:os.fsync(stream.fileno())
    if sync:
        with (base/'inventory.json').open('rb') as stream:os.fsync(stream.fileno())
        for directory in sorted([base,*[x for x in base.rglob('*') if x.is_dir()]],key=lambda x:len(x.parts),reverse=True):
            storage._fsync_dir(directory)
        storage._fsync_dir(base.parent)
    return descriptor


def _manifest(descriptor):
    return {'version':VERSION,'scope':SCOPE,'inventory_hash':p.digest(descriptor),
        'source_bar_date':descriptor['source_bar_date'],'account':descriptor['account'],
        'scientific_lineage_ref':descriptor['scientific_lineage_ref'],'universe_hash':descriptor['universe_hash'],
        'historical_availability_status':'UNRESOLVED','historical_capture_receipts_created':False,
        'execution_approved':False,'issuable':False}


def publish(root,ident,*,expected_config_hash,_fault=None):
    config=_config(root,expected_config_hash,'publisher')
    descriptor=_inventory(root,ident,config,sync=True)
    manifest=_manifest(descriptor);path=Path(root)/'publisher'/(ident+'.json')
    storage._write(path,p.canonical_bytes(manifest));storage._fsync_dir(path.parent)
    if _fault:_fault('after_publication_fsync')
    return p.digest(manifest)


def _publication(root,ident,config):
    descriptor=_inventory(root,ident,config)
    manifest=p.read_json(storage._path(root,Path(root)/'publisher'/(ident+'.json'),owner=config['uids']['publisher']).read_bytes())
    if manifest!=_manifest(descriptor):raise p.Rejected('publication_mismatch')
    return manifest,descriptor


def _ack(root,ident,stage,config):
    ack=p.read_json(storage._path(root,Path(root)/'witness'/(ident+'-'+stage+'.json'),owner=config['uids']['witness']).read_bytes())
    event=ack['event']
    if (ack['version']!=VERSION or ack['scope']!=SCOPE or event['publication_id']!=ident
        or event['stage']!=stage or event['slot']!=config['source_bar_date'] or event['scope']!=SCOPE
        or ack['event_hash']!=p.digest(event) or ack['historical_availability_attested'] is not False):
        raise p.Rejected('ack_identity_mismatch')
    p.timestamp(ack['post_commit_observed_at'])
    with closing(storage._witness_db(root,config)) as db:
        storage._head(db)
        row=db.execute('SELECT payload FROM attestations WHERE event_hash=?',(ack['event_hash'],)).fetchone()
        if row is None or p.read_json(row[0])!=event:raise p.Rejected('uncommitted_ack')
    return ack


def _derivation(root,ident,config,manifest):
    receipt=p.read_json(storage._path(root,Path(root)/'verifier'/(ident+'.json'),owner=config['uids']['verifier']).read_bytes())
    original_receipt=receipt['original_derivation'];p.check_receipt(original_receipt,receipt['original_receipt_hash'])
    _bound_derivation(original_receipt,_inventory(root,ident,config),config)
    ack=_ack(root,ident,'publication',config)
    expected=_wrap_derivation(config,ident,manifest,ack,original_receipt)
    if receipt!=expected:raise p.Rejected('derivation_mismatch')
    return receipt


def _wrap_derivation(config,ident,manifest,ack,derived):
    if (derived['kind']!='v13-original-derivation-v1' or derived['derivation_status']!='VERIFIED'
        or derived['availability_status']!='UNRESOLVED' or derived['source_available_at'] is not None
        or derived['research_only'] is not True or derived['execution_approved'] is not False
        or derived['issuable'] is not False or derived['independent_custody_verified'] is not False
        or derived['source_bar_date']!=config['source_bar_date']
        or derived['scientific_lineage_ref']!=config['scientific_lineage_ref'] or derived['universe_hash']!=config['universe_hash']):
        raise p.Rejected('not_original_research_derivation')
    contract,_=p.load_contract(config['repo_root'])
    if not isinstance(derived['targets'],dict) or set(derived['targets'])!=set(contract['universe']):
        raise p.Rejected('portfolio_incomplete')
    for value in derived['targets'].values():p.decode_weight(value)
    snapshot=p.digest({'version':VERSION,'scientific_lineage_ref':config['scientific_lineage_ref'],
        'universe_hash':config['universe_hash'],'source_bar_date':config['source_bar_date'],
        'causal_input_hash':derived['causal_input_hash']})
    return {'version':VERSION,'scope':SCOPE,'inventory_hash':ident,'publication_hash':p.digest(manifest),
        'publication_ack_hash':p.digest(ack),'original_derivation':derived,'original_receipt_hash':derived['receipt_hash'],
        'snapshot_id':snapshot,'original_targets_reconstructed':True,
        'historical_availability_status':'UNRESOLVED','execution_approved':False,'issuable':False}


def _bound_derivation(derived,descriptor,config):
    expected_hashes=sorted(set(x['response_sha256'] for x in descriptor['dependencies'] if x['kind']=='raw_response'))
    if (derived['source_record_hash']!=descriptor['source_record_hash']
        or derived['source_journal_prefix_hash']!=descriptor['source_prefix_hash']
        or derived['daily_prefix_records']!=descriptor['daily_prefix_records']
        or derived['source_prefix_records']!=descriptor['source_prefix_records']
        or derived['raw_response_hashes']!=expected_hashes
        or derived['candidate_contract_sha256']!=p.CONTRACT_SHA256
        or derived['verifier_version']!=original.VERSION
        or derived['code_hashes']!={'adapter':config['code_pins']['portfolio'],'verifier':config['code_pins']['original_verifier']}):
        raise p.Rejected('original_derivation_inventory_mismatch')


def derive(root,ident,*,expected_config_hash,expected_publication_ack_hash,_fault=None):
    root=Path(root).absolute();config=_config(root,expected_config_hash,'verifier')
    manifest,descriptor=_publication(root,ident,config)
    ack=_ack(root,ident,'publication',config)
    if p.digest(ack)!=expected_publication_ack_hash or ack['event']['object_hash']!=p.digest(manifest):
        raise p.Rejected('publication_ack_pin_mismatch')
    # Read the preserved archive, not a producer-supplied vector or receipt.
    inputs=original.Inputs(Path(config['repo_root']),Path(config['research_root']),
        root/'custodian'/ident/'archive',Path(config['implementation_lock']))
    derived=original.reconstruct(inputs,source_bar_date=config['source_bar_date'])
    p.check_receipt(derived,derived['receipt_hash'])
    _bound_derivation(derived,descriptor,config)
    _inventory(root,ident,config)  # detect changes during calculation
    receipt=_wrap_derivation(config,ident,manifest,ack,derived)
    path=root/'verifier'/(ident+'.json')
    if path.exists():
        existing=_derivation(root,ident,config,manifest)
        # Original v1 records process completion time. On replay keep its first
        # receipt; compare every substantive field, not a new clock reading.
        old=existing['original_derivation'];new=derived.copy()
        new['verified_at']=old['verified_at'];new.pop('receipt_hash')
        if p.seal_receipt(new)!=old:raise p.Rejected('derivation_replay_conflict')
        receipt=existing
    storage._write(path,p.canonical_bytes(receipt));storage._fsync_dir(path.parent)
    if _fault:_fault('after_derivation_fsync')
    return p.digest(receipt)


def attest(root,ident,*,stage,expected_config_hash,clock=None,_fault=None):
    root=Path(root).absolute();config=_config(root,expected_config_hash,'witness')
    if stage not in ('publication','derivation'):raise p.Rejected('invalid_stage')
    manifest,_=_publication(root,ident,config)
    _inventory(root,ident,config,sync=True)
    path=root/'publisher'/(ident+'.json');object_hash=p.digest(manifest)
    if stage=='derivation':
        receipt=_derivation(root,ident,config,manifest);object_hash=p.digest(receipt)
        path=root/'verifier'/(ident+'.json')
    with path.open('rb') as stream:os.fsync(stream.fileno())
    storage._fsync_dir(path.parent)
    lock=root/'witness'/'writer.lock';fd=os.open(lock,os.O_RDWR|os.O_CREAT|os.O_NOFOLLOW,0o600)
    try:
        storage._path(root,lock,owner=config['uids']['witness']);fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with closing(storage._witness_db(root,config,write=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                previous=storage._head(db)
                row=db.execute('SELECT payload FROM attestations WHERE stage=? AND slot=?',(stage,config['source_bar_date'])).fetchone()
                if row:
                    event=p.read_json(row[0])
                    if event['publication_id']!=ident or event['object_hash']!=object_hash:raise p.Rejected('slot_conflict')
                else:
                    if stage=='derivation':_ack(root,ident,'publication',config)
                    sequence=db.execute('SELECT count(*) FROM attestations').fetchone()[0]+1
                    event={'scope':SCOPE,'stage':stage,'slot':config['source_bar_date'],'publication_id':ident,
                        'object_hash':object_hash,'sequence':sequence,'previous_hash':previous}
                    db.execute('INSERT INTO attestations VALUES (?,?,?,?,?,?)',(sequence,stage,config['source_bar_date'],ident,p.canonical_bytes(event).decode(),p.digest(event)))
                if _fault:_fault('before_commit',db)
                db.commit()
                if _fault:_fault('after_commit',db)
            except BaseException:db.rollback();raise
        storage._fsync_dir(root/'witness')
        path=root/'witness'/(ident+'-'+stage+'.json')
        if path.exists():ack=_ack(root,ident,stage,config)
        else:
            observed=clock() if clock else dt.datetime.now(p.UTC).isoformat()
            if p.timestamp(observed)<p.timestamp(config['review_started_at']):raise p.Rejected('review_clock_backdating')
            if stage=='derivation':
                publication=_ack(root,ident,'publication',config)
                if p.timestamp(observed)<p.timestamp(publication['post_commit_observed_at']):raise p.Rejected('clock_regression')
                if p.timestamp(observed)<p.timestamp(receipt['original_derivation']['verified_at']):raise p.Rejected('clock_before_derivation')
            ack={'version':VERSION,'scope':SCOPE,'event':event,'event_hash':p.digest(event),
                 'post_commit_observed_at':observed,'clock_source':'supplied_diagnostic_clock' if clock else 'local_post_commit_clock',
                 'historical_availability_attested':False}
            try:storage._write(path,p.canonical_bytes(ack));storage._fsync_dir(path.parent)
            except BaseException:path.unlink(missing_ok=True);raise
        if ack['event']!=event:raise p.Rejected('ack_conflict')
        return {'ack_hash':p.digest(ack),'event_hash':p.digest(event),'ack':ack}
    finally:os.close(fd)


def verify_review(root,ident,*,expected_config_hash,expected_publication_ack_hash,
                  expected_derivation_ack_hash,expected_witness_head,checked_at=None):
    config=_config(root,expected_config_hash)
    manifest,descriptor=_publication(root,ident,config);receipt=_derivation(root,ident,config,manifest)
    a=_ack(root,ident,'publication',config);b=_ack(root,ident,'derivation',config)
    with closing(storage._witness_db(root,config)) as db:
        if storage._head(db)!=expected_witness_head:raise p.Rejected('external_witness_head_mismatch')
    if (p.digest(a)!=expected_publication_ack_hash or p.digest(b)!=expected_derivation_ack_hash
        or a['event']['object_hash']!=p.digest(manifest) or b['event']['object_hash']!=p.digest(receipt)):
        raise p.Rejected('external_ack_pin_mismatch')
    available=max(p.timestamp(a['post_commit_observed_at']),p.timestamp(b['post_commit_observed_at']))
    now=p.timestamp(checked_at) if checked_at else dt.datetime.now(p.UTC)
    if (now<available or p.timestamp(b['post_commit_observed_at'])<p.timestamp(a['post_commit_observed_at'])
        or p.timestamp(a['post_commit_observed_at'])<p.timestamp(config['review_started_at'])
        or p.timestamp(b['post_commit_observed_at'])<p.timestamp(receipt['original_derivation']['verified_at'])):
        raise p.Rejected('review_not_available')
    return {'version':VERSION,'scope':SCOPE,'status':'ORIGINAL_DERIVATION_PUBLICATION_REVIEW_VERIFIED',
        'snapshot_id':receipt['snapshot_id'],'original_targets_reconstructed':True,
        'targets':receipt['original_derivation']['targets'],'dependency_count':len(descriptor['dependencies']),
        'raw_response_count':sum(x['kind']=='raw_response' for x in descriptor['dependencies']),
        'current_review_available_at':available.isoformat(),'historical_availability_status':'UNRESOLVED',
        'source_available_at':None,'historical_capture_receipts_created':False,
        'operational_custody_verified':False,'clock_policy_approved':False,
        'roles_distinct_in_sandbox':len(set(config['uids'].values()))==len(ROLES),
        'execution_approved':False,'issuable':False,'kucoin_order_admissibility_proven':False,'readiness':'BLOCKED'}
