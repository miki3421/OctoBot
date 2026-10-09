"""Internal synthetic plumbing tests, not scientific or independent QA evidence.
work-card-3fdd6ea6-217d-415d-963e-5c8e0328c389.
Unmodified original reconstruction is exercised separately in the evidence probe.
"""
from contextlib import closing
import copy
import datetime as dt
import gzip
import multiprocessing
import os
from pathlib import Path
import sqlite3

import pytest
from octobot.ai_strategy_lab import v13_receipt_publication_review as r
from octobot.ai_strategy_lab import v13_capture_receipt_review as c
from octobot.ai_strategy_lab import v13_original_publication_review as a
from octobot.ai_strategy_lab import v13_original_verify as v
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_causal_publication_fixture as s
from tests.unit_tests.ai_strategy_lab.test_v13_causal_publication_fixture import _as_uid as _fork_uid

REPO = Path(__file__).resolve().parents[3]
START = '2099-01-01T00:00:00Z'
CUTOFF = '2099-01-01T00:03:00Z'
PUB = '2099-01-01T00:04:00Z'
DER = '2099-01-01T00:06:00Z'
CHECK = '2099-01-01T00:07:00Z'


def _as_uid(uid, action):
    if uid == os.geteuid(): return action()
    result = _fork_uid(uid, action)
    if result[0] == 'ok': return result[1]
    errors = {'Rejected':p.Rejected,'PermissionError':PermissionError,'FileNotFoundError':FileNotFoundError,
              'OSError':OSError,'KeyError':KeyError,'OperationalError':sqlite3.OperationalError}
    raise errors.get(result[1], RuntimeError)(result[2])


def timer(config, seconds=0):
    def sample():
        nonlocal seconds
        value = {'utc': (p.timestamp(START)+dt.timedelta(seconds=seconds)).isoformat(),
                 'monotonic_ns': seconds*1000000000, 'clock_evidence_ref': config['clock_evidence_ref']}
        seconds += 1
        return value
    return sample


def head(root, config):
    with closing(s._witness_db(root, config)) as db: return s._head(db)


def setup(tmp, monkeypatch, *, uids=None, subset=None):
    """36 distinct per-symbol responses, mocked scientific calculation explicitly."""
    uids = uids or {role: 0 for role in r.ROLES}
    inputs_root = tmp/'inputs'; inputs_root.mkdir(); (inputs_root/'raw').mkdir(); (inputs_root/'daily').mkdir()
    research = tmp/'research'; research.mkdir(); control = tmp/'control'; control.mkdir()
    lock = control/'lock.json'; lock.write_text('{}')
    contract, _ = p.load_contract(REPO)
    cr = tmp/'capture'; cp = c.init_review(cr, uids={k:uids[k] for k in c.ROLES}, fixture_started_at=START)
    cc = p.read_json((cr/'config.json').read_bytes()); bindings = {}; symbols = {}; chead = None
    for number, symbol in enumerate(contract['universe']):
        artifacts = {}
        for kind, keykind in [('daily_klines','daily'),('funding_pages','funding')]:
            key = 'scientific_'+keykind+':'+symbol
            raw = p.canonical_bytes([{'symbol':symbol,'fundingTime':1790553600000,'fundingRate':'0.001'}]
                                    if keykind=='funding' else [[number,1,2,3,4,5]])
            compressed = gzip.compress(raw, mtime=0); name = symbol+'-'+keykind+'.gz'
            (inputs_root/'raw'/name).write_bytes(compressed)
            art = {'path':name,'artifact_sha256':a.sha(compressed),'response_sha256':a.sha(raw),'url':cc['requests'][key]['url']}
            artifacts[kind] = [art] if keykind=='funding' else art
            cap = _as_uid(uids['custodian'], lambda:c.capture(cr,p.digest(key),key,expected_config_hash=cp,
                fixture_chunks=[raw],http_status=200,declared_length=len(raw),clock=timer(cc)))
            ack = _as_uid(uids['witness'],lambda:c.attest(cr,cap['capture_id'],expected_config_hash=cp,
                expected_capture_hash=cap['capture_hash'],expected_witness_head=chead,clock=timer(cc,10)))
            chead = ack['event_hash']
            bindings['raw/'+name] = {'ident':cap['capture_id'],'expected_capture_hash':cap['capture_hash'],'expected_ack_hash':ack['ack_hash']}
        symbols[symbol] = {'raw':artifacts}
    record = {'bar_date':'2026-09-27','symbols':symbols}
    (inputs_root/'daily/2026-09-27.json.gz').write_bytes(gzip.compress(p.canonical_bytes(record),mtime=0))
    prefix = [{'journal_record_hash':'b'*64,'unit_fixture':True}]
    (inputs_root/'decisions.jsonl').write_bytes(p.canonical_bytes(prefix[0])+b'\n')
    monkeypatch.setattr(v,'_load_runner',lambda *args:(None,None))
    monkeypatch.setattr(v,'load_daily_prefix',lambda inputs,*args:[p.read_json(gzip.decompress((inputs.archive_root/'daily/2026-09-27.json.gz').read_bytes()))])
    monkeypatch.setattr(v,'load_source_prefix',lambda *args:(prefix[0],prefix))
    monkeypatch.setattr(v,'_raw_bytes',lambda inputs,art,**kw:gzip.decompress((inputs.archive_root/'raw'/art['path']).read_bytes()))
    calls=[]
    def reconstruct(inputs, *, source_bar_date):
        calls.append(str(inputs.archive_root)); inv=a.inventory(inputs,source_bar_date=source_bar_date)
        targets={symbol:'0' for symbol in contract['universe']}; targets['BTCUSDT']='0.1'
        return p.seal_receipt({'schema_version':1,'kind':'v13-original-derivation-v1',
            'candidate_contract_sha256':p.CONTRACT_SHA256,'verifier_version':v.VERSION,
            'code_hashes':{'adapter':a.sha(Path(p.__file__).read_bytes()),'verifier':a.sha(Path(v.__file__).read_bytes())},
            'source_record_hash':inv['source_record_hash'],'source_journal_prefix_hash':inv['source_prefix_hash'],
            'daily_prefix_records':inv['daily_prefix_records'],'source_prefix_records':inv['source_prefix_records'],
            'raw_response_hashes':sorted(set(x['response_sha256'] for x in inv['dependencies'] if x['kind']=='raw_response')),
            'scientific_lineage_ref':contract['scientific_lineage_ref'],'universe_hash':contract['universe_hash'],
            'source_bar_date':source_bar_date,'causal_input_hash':'c'*64,'targets':targets,
            'verified_at':'2099-01-01T00:05:00Z','derivation_status':'VERIFIED','availability_status':'UNRESOLVED',
            'source_available_at':None,'research_only':True,'execution_approved':False,'issuable':False,
            'independent_custody_verified':False})
    monkeypatch.setattr(v,'reconstruct',reconstruct)
    inputs=v.Inputs(REPO,research,inputs_root,lock);inv=a.inventory(inputs,source_bar_date='2026-09-27')
    ar=tmp/'archive';ap=a.init_review(ar,inputs,source_bar_date='2026-09-27',expected_inventory_hash=p.digest(inv),uids=uids)
    ident=_as_uid(uids['custodian'],lambda:a.capture_archive(ar,inputs,expected_config_hash=ap))
    _as_uid(uids['publisher'],lambda:a.publish(ar,ident,expected_config_hash=ap))
    aa=_as_uid(uids['witness'],lambda:a.attest(ar,ident,stage='publication',expected_config_hash=ap,clock=lambda:CUTOFF))
    root=tmp/'integration'
    kwargs=dict(capture_root=cr,capture_config_hash=cp,capture_head=chead,archive_root=ar,archive_config_hash=ap,
        inventory_hash=ident,archive_publication_ack_hash=aa['ack_hash'],dependency_bindings=bindings,
        uids=uids,fixture_cutoff_at=CUTOFF)
    if subset: kwargs['dependency_bindings']=subset(bindings)
    pin=r.init_review(root,**kwargs)
    return {'root':root,'pin':pin,'uids':uids,'cr':cr,'cp':cp,'cc':cc,'ar':ar,'ap':ap,'inventory':inv,
            'bindings':bindings,'inputs':inputs,'calls':calls,'init':kwargs}


def publish(x):return _as_uid(x['uids']['publisher'],lambda:r.publish(x['root'],expected_config_hash=x['pin']))


def finish(x):
    ident=publish(x);root=x['root'];pin=x['pin'];uids=x['uids']
    aa=_as_uid(uids['witness'],lambda:r.attest(root,ident,stage='publication',expected_config_hash=pin,
        expected_witness_head=None,clock=lambda:PUB))
    receipt=_as_uid(uids['verifier'],lambda:r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=aa['ack_hash']))
    bb=_as_uid(uids['witness'],lambda:r.attest(root,ident,stage='derivation',expected_config_hash=pin,
        expected_witness_head=aa['event_hash'],clock=lambda:DER))
    return ident,aa,bb,receipt


def verify(x, ident, aa, bb, **kwargs):
    args=dict(expected_config_hash=x['pin'],expected_publication_ack_hash=aa['ack_hash'],
              expected_derivation_ack_hash=bb['ack_hash'],expected_witness_head=bb['event_hash'],checked_at=CHECK)
    args.update(kwargs)
    return _as_uid(x['uids']['verifier'],lambda:r.verify_review(x['root'],ident,**args))


def test_complete_fixture_proof_and_recalculated_derivation(tmp_path,monkeypatch):
    x=setup(tmp_path,monkeypatch);ident,aa,bb,_=finish(x);result=verify(x,ident,aa,bb)
    assert len(result['targets'])==18 and result['capture_dependency_count']==36
    assert result['current_fixture_bundle_available_at']=='2099-01-01T00:06:00+00:00'
    assert result['issuable'] is False and result['source_available_at_operational'] is None
    assert result['historical_availability_status']=='UNRESOLVED' and result['readiness']=='BLOCKED'
    assert result['historical_capture_receipts_created'] is False and result['kucoin_order_admissibility_proven'] is False
    # Calls are in forked processes, so inspect the preserved original artifact.
    original=p.read_json((x['ar']/'verifier'/(p.digest(x['inventory'])+'.json')).read_bytes())
    assert original['original_targets_reconstructed'] is True
    assert original['original_derivation']['availability_status']=='UNRESOLVED'
    c._config(x['cr'],x['cp'])
    assert p.read_json((x['root']/'config.json').read_bytes())['operational_policy']==dict.fromkeys(['daily_loss','drawdown','order_frequency','cooldown'])


@pytest.mark.parametrize('field',['expected_config_hash','expected_publication_ack_hash','expected_derivation_ack_hash','expected_witness_head'])
def test_external_pins_required(tmp_path,monkeypatch,field):
    x=setup(tmp_path,monkeypatch);ident,aa,bb,_=finish(x)
    with pytest.raises(p.Rejected):verify(x,ident,aa,bb,**{field:'0'*64})


@pytest.mark.parametrize('kind',['missing','extra','swapped_symbol','swapped_kind','swapped_payload'])
def test_exact_dependency_coverage_and_binding(tmp_path,monkeypatch,kind):
    def change(bindings):
        z=copy.deepcopy(bindings);keys=list(z)
        if kind=='missing':z.pop(keys[0])
        elif kind=='extra':z['raw/foreign.gz']=z[keys[0]]
        else:
            first='raw/AAVEUSDT-daily.gz'
            other={'swapped_symbol':'raw/ADAUSDT-daily.gz','swapped_kind':'raw/AAVEUSDT-funding.gz','swapped_payload':'raw/ADAUSDT-funding.gz'}[kind]
            z[first]=z[other]
        return z
    x=setup(tmp_path,monkeypatch,subset=change)
    with pytest.raises(p.Rejected):publish(x)
    assert not list((x['root']/'publisher').glob('*.json'))


@pytest.mark.parametrize('kind',['raw','capture','capture_ack','capture_db','archive_raw','archive_daily','manifest','derivation','ack','integration_db'])
def test_tamper_denies_existing_bundle(tmp_path,monkeypatch,kind):
    x=setup(tmp_path,monkeypatch);ident,aa,bb,_=finish(x);root=x['root'];dep=next(iter(x['bindings'].values()))
    if kind.endswith('_db'):
        target=x['cr'] if kind=='capture_db' else root
        with sqlite3.connect(target/'witness/witness.sqlite') as db:db.execute("UPDATE attestations SET slot='foreign' WHERE sequence=1")
    else:
        path={'raw':x['cr']/'custodian'/dep['ident']/'raw.bin','capture':x['cr']/'custodian'/dep['ident']/'capture.json',
            'capture_ack':x['cr']/'witness'/(dep['ident']+'-capture.json'),
            'archive_raw':x['ar']/'custodian'/p.digest(x['inventory'])/'archive/raw/AAVEUSDT-daily.gz',
            'archive_daily':x['ar']/'custodian'/p.digest(x['inventory'])/'archive/daily/2026-09-27.json.gz',
            'manifest':root/'publisher'/(ident+'.json'),'derivation':root/'verifier'/(ident+'.json'),
            'ack':root/'witness'/(ident+'-derivation.json')}[kind]
        path.chmod(0o644);path.write_bytes(b'{}');path.chmod(0o444)
    with pytest.raises((p.Rejected,KeyError,OSError)):verify(x,ident,aa,bb)


def test_replay_preserves_first_times_and_scientific_identity(tmp_path,monkeypatch):
    x=setup(tmp_path,monkeypatch);ident,aa,bb,receipt=finish(x)
    assert publish(x)==ident
    assert r.derive(x['root'],ident,expected_config_hash=x['pin'],expected_publication_ack_hash=aa['ack_hash'])==receipt
    for stage,expected in [('publication',aa),('derivation',bb)]:
        assert r.attest(x['root'],ident,stage=stage,expected_config_hash=x['pin'],expected_witness_head=bb['event_hash'],clock=lambda:CHECK)==expected
    obj=p.read_json((x['root']/'verifier'/(ident+'.json')).read_bytes());cfig=r._config(x['root'],x['pin'])
    alt=r._wrap(cfig,'a'*64,dict(aa['ack'],post_commit_observed_at_fixture=CHECK),obj['original_derivation'])
    assert alt['snapshot_id']==obj['snapshot_id'] and alt['publication_hash']!=obj['publication_hash']
    with closing(r._db(x['root'],cfig)) as db:assert db.execute('SELECT count(*) FROM attestations').fetchone()[0]==2
    # An unconsumed future journal line does not affect the selected prefix.
    journal=x['inputs'].archive_root/'decisions.jsonl';journal.write_bytes(journal.read_bytes()+b'{future invalid record}\n')
    assert a.inventory(x['inputs'],source_bar_date='2026-09-27')==x['inventory']


@pytest.mark.parametrize('stage',['publication','derivation'])
@pytest.mark.parametrize('where',['before_commit','after_commit'])
def test_actual_process_death_requires_reconciled_head(tmp_path,monkeypatch,stage,where):
    x=setup(tmp_path,monkeypatch);ident=publish(x);previous=None
    if stage=='derivation':
        aa=r.attest(x['root'],ident,stage='publication',expected_config_hash=x['pin'],expected_witness_head=None,clock=lambda:PUB)
        r.derive(x['root'],ident,expected_config_hash=x['pin'],expected_publication_ack_hash=aa['ack_hash']);previous=aa['event_hash']
    def child():
        def die(point,db):
            if point==where:os._exit(81)
        r.attest(x['root'],ident,stage=stage,expected_config_hash=x['pin'],expected_witness_head=previous,clock=lambda:DER,fault=die)
    proc=multiprocessing.get_context('fork').Process(target=child);proc.start();proc.join(10)
    assert proc.exitcode==81
    assert not (x['root']/'witness'/(ident+'-'+stage+'.json')).exists()
    actual=head(x['root'],r._config(x['root'],x['pin']))
    if where=='after_commit':
        with pytest.raises(p.Rejected,match='external_witness_head_mismatch'):
            r.attest(x['root'],ident,stage=stage,expected_config_hash=x['pin'],expected_witness_head=previous,clock=lambda:DER)
    recovered=r.attest(x['root'],ident,stage=stage,expected_config_hash=x['pin'],expected_witness_head=actual,clock=lambda:DER)
    assert recovered['ack']['own_ack_commit_time_known'] is False


@pytest.mark.parametrize('stage',['publication','derivation'])
def test_ack_fsync_failure_no_usable_confirmation(tmp_path,monkeypatch,stage):
    x=setup(tmp_path,monkeypatch);ident=publish(x);previous=None
    if stage=='derivation':
        aa=r.attest(x['root'],ident,stage='publication',expected_config_hash=x['pin'],expected_witness_head=None,clock=lambda:PUB)
        r.derive(x['root'],ident,expected_config_hash=x['pin'],expected_publication_ack_hash=aa['ack_hash']);previous=aa['event_hash']
    ack=x['root']/'witness'/(ident+'-'+stage+'.json');real=s._fsync_dir
    def fail(path):
        if ack.exists():raise OSError('fixture fsync failure')
        return real(path)
    monkeypatch.setattr(s,'_fsync_dir',fail)
    with pytest.raises(OSError):r.attest(x['root'],ident,stage=stage,expected_config_hash=x['pin'],expected_witness_head=previous,clock=lambda:DER)
    assert not ack.exists()


def test_sqlite_full_no_ack(tmp_path,monkeypatch):
    x=setup(tmp_path,monkeypatch);ident=publish(x)
    def full(where,db):
        if where=='before_commit':
            pages=db.execute('PRAGMA page_count').fetchone()[0];db.execute('PRAGMA max_page_count='+str(pages))
            db.execute('INSERT INTO attestations VALUES (99,?,?,?,?,?)',('fill','fill',ident,'x'*100000,'fill'))
    with pytest.raises(sqlite3.OperationalError,match='full'):
        r.attest(x['root'],ident,stage='publication',expected_config_hash=x['pin'],expected_witness_head=None,clock=lambda:PUB,fault=full)
    assert not list((x['root']/'witness').glob('*-publication.json'))


@pytest.mark.parametrize('case',['before_capture','before_publication','before_derivation','checked_too_early'])
def test_temporal_availability_fail_closed(tmp_path,monkeypatch,case):
    x=setup(tmp_path,monkeypatch);ident=publish(x)
    if case=='before_capture':
        with pytest.raises(p.Rejected):r.attest(x['root'],ident,stage='publication',expected_config_hash=x['pin'],expected_witness_head=None,clock=lambda:START)
        return
    aa=r.attest(x['root'],ident,stage='publication',expected_config_hash=x['pin'],expected_witness_head=None,clock=lambda:PUB)
    r.derive(x['root'],ident,expected_config_hash=x['pin'],expected_publication_ack_hash=aa['ack_hash'])
    if case in ['before_publication','before_derivation']:
        at=CUTOFF if case=='before_publication' else PUB
        with pytest.raises(p.Rejected):r.attest(x['root'],ident,stage='derivation',expected_config_hash=x['pin'],expected_witness_head=aa['event_hash'],clock=lambda:at)
    else:
        bb=r.attest(x['root'],ident,stage='derivation',expected_config_hash=x['pin'],expected_witness_head=aa['event_hash'],clock=lambda:DER)
        with pytest.raises(p.Rejected):verify(x,ident,aa,bb,checked_at=PUB)


def test_restore_old_database_denied_by_external_head(tmp_path,monkeypatch):
    x=setup(tmp_path,monkeypatch);ident=publish(x)
    aa=r.attest(x['root'],ident,stage='publication',expected_config_hash=x['pin'],expected_witness_head=None,clock=lambda:PUB)
    db=x['root']/'witness/witness.sqlite';old=db.read_bytes()
    r.derive(x['root'],ident,expected_config_hash=x['pin'],expected_publication_ack_hash=aa['ack_hash'])
    bb=r.attest(x['root'],ident,stage='derivation',expected_config_hash=x['pin'],expected_witness_head=aa['event_hash'],clock=lambda:DER)
    db.write_bytes(old)
    with pytest.raises(p.Rejected):verify(x,ident,aa,bb)


@pytest.mark.parametrize('role',['strategy','custodian','publisher','witness'])
def test_strategy_and_other_roles_cannot_verify_as_verifier(tmp_path,monkeypatch,role):
    tmp_path.chmod(0o755);tmp_path.parent.chmod(0o755);tmp_path.parent.parent.chmod(0o755)
    uids={name:30810+10*i for i,name in enumerate(r.ROLES)}
    x=setup(tmp_path,monkeypatch,uids=uids);ident,aa,bb,_=finish(x)
    assert verify(x,ident,aa,bb)['fixture_uids_distinct'] is True
    with pytest.raises(p.Rejected,match='wrong_integration_role'):
        _as_uid(uids[role],lambda:r.verify_review(x['root'],ident,expected_config_hash=x['pin'],
            expected_publication_ack_hash=aa['ack_hash'],expected_derivation_ack_hash=bb['ack_hash'],
            expected_witness_head=bb['event_hash'],checked_at=CHECK))


def test_strategy_cannot_write_trusted_files(tmp_path,monkeypatch):
    tmp_path.chmod(0o755);tmp_path.parent.chmod(0o755);tmp_path.parent.parent.chmod(0o755)
    uids={name:30810+10*i for i,name in enumerate(r.ROLES)};x=setup(tmp_path,monkeypatch,uids=uids);ident,aa,bb,_=finish(x)
    for path in [x['root']/'config.json',x['root']/'publisher'/(ident+'.json'),x['root']/'verifier'/(ident+'.json'),
                 x['root']/'witness/witness.sqlite',x['cr']/'config.json']:
        with pytest.raises(PermissionError):_as_uid(uids['strategy'],lambda:path.write_bytes(b'fake'))
    for role in ['publisher','verifier','witness']:
        with pytest.raises(PermissionError):_as_uid(uids['strategy'],lambda:(x['root']/role/'fake').write_bytes(b'fake'))
    assert verify(x,ident,aa,bb)['issuable'] is False


@pytest.mark.parametrize('case',['url','status','ack_after_cutoff','capture_head'])
def test_same_bytes_are_insufficient_without_exact_request_and_availability(tmp_path,monkeypatch,case):
    x=setup(tmp_path,monkeypatch)
    if case=='url':
        ar=x['inputs'].archive_root;path=ar/'daily/2026-09-27.json.gz'
        record=p.read_json(gzip.decompress(path.read_bytes()))
        record['symbols']['AAVEUSDT']['raw']['daily_klines']['url']+='&startTime=1'
        path.write_bytes(gzip.compress(p.canonical_bytes(record),mtime=0))
        inv=a.inventory(x['inputs'],source_bar_date='2026-09-27');newar=tmp_path/'archive-url'
        ap=a.init_review(newar,x['inputs'],source_bar_date='2026-09-27',expected_inventory_hash=p.digest(inv),uids=x['uids'])
        ih=a.capture_archive(newar,x['inputs'],expected_config_hash=ap);a.publish(newar,ih,expected_config_hash=ap)
        aa=a.attest(newar,ih,stage='publication',expected_config_hash=ap,clock=lambda:CUTOFF)
        kw=copy.deepcopy(x['init']);kw.update(archive_root=newar,archive_config_hash=ap,inventory_hash=ih,archive_publication_ack_hash=aa['ack_hash'])
    else:
        kw=copy.deepcopy(x['init'])
        if case=='capture_head':kw['capture_head']='0'*64
        else:
            path='raw/AAVEUSDT-daily.gz';dep=x['bindings'][path]
            originalraw=(x['cr']/'custodian'/dep['ident']/'raw.bin').read_bytes()
            cap=c.capture(x['cr'],'f'*64,'scientific_daily:AAVEUSDT',expected_config_hash=x['cp'],fixture_chunks=[originalraw],
                http_status=503 if case=='status' else 200,declared_length=len(originalraw),clock=timer(x['cc']))
            aa=c.attest(x['cr'],cap['capture_id'],expected_config_hash=x['cp'],expected_capture_hash=cap['capture_hash'],
                expected_witness_head=kw['capture_head'],clock=timer(x['cc'],seconds=240 if case=='ack_after_cutoff' else 10))
            kw['capture_head']=aa['event_hash'];kw['dependency_bindings'][path]={'ident':cap['capture_id'],
                'expected_capture_hash':cap['capture_hash'],'expected_ack_hash':aa['ack_hash']}
    root=tmp_path/'variant';pin=r.init_review(root,**kw)
    with pytest.raises(p.Rejected):r.publish(root,expected_config_hash=pin)


def test_existing_derivation_before_new_publication_is_denied(tmp_path,monkeypatch):
    x=setup(tmp_path,monkeypatch)
    # The archive's prior calculation exists before a later candidate publication.
    a.derive(x['ar'],p.digest(x['inventory']),expected_config_hash=x['ap'],expected_publication_ack_hash=x['init']['archive_publication_ack_hash'])
    ident=publish(x)
    aa=r.attest(x['root'],ident,stage='publication',expected_config_hash=x['pin'],expected_witness_head=None,clock=lambda:DER)
    with pytest.raises(p.Rejected,match='derivation_predates_publication'):
        r.derive(x['root'],ident,expected_config_hash=x['pin'],expected_publication_ack_hash=aa['ack_hash'])
    assert not list((x['root']/'verifier').glob('*.json'))
