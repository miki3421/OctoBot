"""Plumbing-only synthetic cases; actual original calculation is a separate probe.
Card work-card-a8e4020b-5b68-40a0-9fda-cd51c64634b4.
"""
import copy
import datetime as dt
import gzip
import multiprocessing
import os
from pathlib import Path
import sqlite3
from types import SimpleNamespace
import pytest
from octobot.ai_strategy_lab import v13_original_publication_review as r
from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_original_verify as v
from octobot.ai_strategy_lab import v13_causal_publication_fixture as s

REPO=Path(__file__).resolve().parents[3]
PUB='2099-01-01T00:01:00Z'
DER='2099-01-01T00:02:00Z'
CHECK='2099-01-01T00:03:00Z'


def plumbing_inputs(tmp,monkeypatch,*,conflict=False):
    """Explicit unit doubles replace scientific work ONLY in these unit tests."""
    contract,_=p.load_contract(REPO)
    archive=tmp/'input';archive.mkdir();(archive/'daily').mkdir();(archive/'raw').mkdir()
    research=tmp/'research';research.mkdir();control=tmp/'control';control.mkdir()
    lock=control/'lock.json';lock.write_text('{}')
    fund=[{'fundingTime':1790553600000,'fundingRate':'0.001'}]
    if conflict:fund.append({'fundingTime':1790553600000,'fundingRate':'0.002'})
    raw=p.canonical_bytes(fund);compressed=gzip.compress(raw,mtime=0)
    (archive/'raw'/'fund.gz').write_bytes(compressed)
    kraw=b'[[1,2]]';kcompressed=gzip.compress(kraw,mtime=0);(archive/'raw'/'klines.gz').write_bytes(kcompressed)
    symbols={symbol:{'raw':{'daily_klines':{'path':'klines.gz','artifact_sha256':r.sha(kcompressed),'response_sha256':r.sha(kraw),'url':'https://fapi.binance.com/fake-klines'},
             'funding_pages':[{'path':'fund.gz','artifact_sha256':r.sha(compressed),'response_sha256':r.sha(raw),'url':'https://fapi.binance.com/fake-funding'}]}} for symbol in contract['universe']}
    record={'bar_date':'2026-09-27','symbols':symbols}
    (archive/'daily/2026-09-27.json.gz').write_bytes(gzip.compress(p.canonical_bytes(record),mtime=0))
    prefix=[{'unit_fixture':True,'journal_record_hash':'b'*64}]
    (archive/'decisions.jsonl').write_bytes(p.canonical_bytes(prefix[0])+b'\n')
    monkeypatch.setattr(v,'_load_runner',lambda *args:(None,None))
    monkeypatch.setattr(v,'load_daily_prefix',lambda *args:[record])
    monkeypatch.setattr(v,'load_source_prefix',lambda *args:(prefix[0],prefix))
    def raw_bytes(inputs,artifact,**kw):return gzip.decompress((inputs.archive_root/'raw'/artifact['path']).read_bytes())
    monkeypatch.setattr(v,'_raw_bytes',raw_bytes)
    calls=[]
    def reconstruct(inputs,*,source_bar_date):
        calls.append(str(inputs.archive_root))
        descriptor=r.inventory(inputs,source_bar_date=source_bar_date)
        targets={symbol:'0' for symbol in contract['universe']};targets['BTCUSDT']='0.1'
        return p.seal_receipt({'schema_version':1,'kind':'v13-original-derivation-v1',
            'candidate_contract_sha256':p.CONTRACT_SHA256,'verifier_version':v.VERSION,
            'code_hashes':{'adapter':r.sha(Path(p.__file__).read_bytes()),'verifier':r.sha(Path(v.__file__).read_bytes())},
            'source_record_hash':descriptor['source_record_hash'],'source_journal_prefix_hash':descriptor['source_prefix_hash'],
            'daily_prefix_records':descriptor['daily_prefix_records'],'source_prefix_records':descriptor['source_prefix_records'],
            'raw_response_hashes':sorted(set(x['response_sha256'] for x in descriptor['dependencies'] if x['kind']=='raw_response')),
            'scientific_lineage_ref':contract['scientific_lineage_ref'],'universe_hash':contract['universe_hash'],
            'source_bar_date':source_bar_date,'causal_input_hash':'c'*64,'targets':targets,
            'verified_at':dt.datetime.now(p.UTC).isoformat(),'verification_clock_source':'process_completion_clock',
            'derivation_status':'VERIFIED','availability_status':'UNRESOLVED','source_available_at':None,
            'research_only':True,'execution_approved':False,'issuable':False,'independent_custody_verified':False})
    monkeypatch.setattr(v,'reconstruct',reconstruct)
    return v.Inputs(REPO,research,archive,lock),calls


def setup(tmp,monkeypatch,*,uids=None):
    inputs,calls=plumbing_inputs(tmp,monkeypatch)
    descriptor=r.inventory(inputs,source_bar_date='2026-09-27')
    root=tmp/'review'
    pin=r.init_review(root,inputs,source_bar_date='2026-09-27',expected_inventory_hash=p.digest(descriptor),
                      uids=uids or {role:os.geteuid() for role in r.ROLES})
    ident=r.capture_archive(root,inputs,expected_config_hash=pin)
    r.publish(root,ident,expected_config_hash=pin)
    return root,pin,ident,inputs,calls


def finish(root,pin,ident):
    a=r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:PUB)
    receipt=r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=a['ack_hash'])
    b=r.attest(root,ident,stage='derivation',expected_config_hash=pin,clock=lambda:DER)
    return a,b,receipt


def verify(root,pin,ident,a,b,**kw):
    args={'expected_config_hash':pin,'expected_publication_ack_hash':a['ack_hash'],
          'expected_derivation_ack_hash':b['ack_hash'],'expected_witness_head':b['event_hash'],'checked_at':CHECK}
    args.update(kw);return r.verify_review(root,ident,**args)


def test_plumbing_calls_verifier_with_preserved_copy_never_enables(tmp_path,monkeypatch):
    root,pin,ident,inputs,calls=setup(tmp_path,monkeypatch);a,b,_=finish(root,pin,ident)
    result=verify(root,pin,ident,a,b)
    assert calls==[str(root/'custodian'/ident/'archive')]
    assert result['historical_availability_status']=='UNRESOLVED' and result['source_available_at'] is None
    assert result['current_review_available_at']=='2099-01-01T00:02:00+00:00'
    assert len(result['targets'])==18 and result['raw_response_count']==2
    assert result['issuable'] is False and result['execution_approved'] is False
    assert result['historical_capture_receipts_created'] is False
    assert result['kucoin_order_admissibility_proven'] is False and result['readiness']=='BLOCKED'
    deps=p.read_json((root/'custodian'/ident/'inventory.json').read_bytes())['dependencies']
    for entry in deps:
        if entry['kind']=='raw_response':
            assert entry['response_completed_at'] is None and entry['historical_capture_receipt_status']=='MISSING'


@pytest.mark.parametrize('pinfield',['expected_config_hash','expected_publication_ack_hash','expected_derivation_ack_hash','expected_witness_head'])
def test_external_pins_fail_closed(tmp_path,monkeypatch,pinfield):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch);a,b,_=finish(root,pin,ident)
    with pytest.raises(p.Rejected):verify(root,pin,ident,a,b,**{pinfield:'0'*64})


@pytest.mark.parametrize('kind',['raw','daily','journal','manifest','derivation','ack','witness'])
def test_tamper(tmp_path,monkeypatch,kind):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch);a,b,_=finish(root,pin,ident)
    if kind=='witness':
        with sqlite3.connect(root/'witness'/'witness.sqlite') as db:db.execute("UPDATE attestations SET slot='foreign' WHERE sequence=1")
    else:
        path={'raw':root/'custodian'/ident/'archive/raw/fund.gz',
              'daily':root/'custodian'/ident/'archive/daily/2026-09-27.json.gz',
              'journal':root/'custodian'/ident/'archive/decisions.jsonl',
              'manifest':root/'publisher'/(ident+'.json'),'derivation':root/'verifier'/(ident+'.json'),
              'ack':root/'witness'/(ident+'-publication.json')}[kind]
        path.chmod(0o644);path.write_bytes(b'{}');path.chmod(0o444)
    with pytest.raises((p.Rejected,KeyError)):verify(root,pin,ident,a,b)


def test_conflicting_raw_funding_before_copy_denied(tmp_path,monkeypatch):
    inputs,_=plumbing_inputs(tmp_path,monkeypatch,conflict=True)
    with pytest.raises(p.Rejected,match='conflicting_raw_funding_duplicate'):r.inventory(inputs,source_bar_date='2026-09-27')


def test_inventory_pin_and_replay(tmp_path,monkeypatch):
    root,pin,ident,inputs,_=setup(tmp_path,monkeypatch);a,b,receipt=finish(root,pin,ident)
    assert r.capture_archive(root,inputs,expected_config_hash=pin)==ident
    a2,b2,receipt2=finish(root,pin,ident)
    assert (a,b,receipt)==(a2,b2,receipt2)
    with sqlite3.connect(root/'witness'/'witness.sqlite') as db:
        assert db.execute('SELECT count(*) FROM attestations').fetchone()[0]==2
    path=inputs.archive_root/'raw/klines.gz';path.write_bytes(b'changed')
    with pytest.raises((p.Rejected,OSError,EOFError)):r.capture_archive(root,inputs,expected_config_hash=pin)


@pytest.mark.parametrize('stage',['before_commit','after_commit'])
def test_actual_process_death_before_or_after_commit(tmp_path,monkeypatch,stage):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch)
    def child():
        def kill(where,db):
            if where==stage:os._exit(81)
        r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:PUB,_fault=kill)
    process=multiprocessing.get_context('fork').Process(target=child);process.start();process.join(10)
    assert process.exitcode==81
    assert not (root/'witness'/(ident+'-publication.json')).exists()
    with pytest.raises(FileNotFoundError):r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash='0'*64)
    a,b,_=finish(root,pin,ident);verify(root,pin,ident,a,b)


@pytest.mark.parametrize('stage',['publication','derivation'])
def test_fsync_failure_never_returns_ack(tmp_path,monkeypatch,stage):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch)
    if stage=='derivation':
        a=r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:PUB)
        r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=a['ack_hash'])
    real=s._fsync_dir
    def fail(path):
        if (root/'witness'/(ident+'-'+stage+'.json')).exists():raise OSError('failed fsync')
        real(path)
    monkeypatch.setattr(s,'_fsync_dir',fail)
    with pytest.raises(OSError):r.attest(root,ident,stage=stage,expected_config_hash=pin,clock=lambda:DER)
    assert not (root/'witness'/(ident+'-'+stage+'.json')).exists()
    monkeypatch.setattr(s,'_fsync_dir',real)
    a,b,_=finish(root,pin,ident);verify(root,pin,ident,a,b)


def test_sqlite_full_preserves_no_authority(tmp_path,monkeypatch):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch)
    def fill(stage,db):
        if stage=='before_commit':
            pages=db.execute('PRAGMA page_count').fetchone()[0];db.execute('PRAGMA max_page_count='+str(pages))
            db.execute('INSERT INTO attestations VALUES (99,?,?,?,?,?)',('fill','fill',ident,'x'*100000,'fill'))
    with pytest.raises(sqlite3.OperationalError,match='full'):
        r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:PUB,_fault=fill)
    assert not (root/'witness'/(ident+'-publication.json')).exists()
    a,b,_=finish(root,pin,ident);verify(root,pin,ident,a,b)


def test_no_backdating_or_preavailability(tmp_path,monkeypatch):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch)
    with pytest.raises(p.Rejected,match='backdating'):
        r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:'2026-09-21T00:00:00Z')
    a,b,_=finish(root,pin,ident)
    with pytest.raises(p.Rejected,match='not_available'):verify(root,pin,ident,a,b,checked_at=PUB)


def test_strategy_cannot_write_or_run_trusted_roles(tmp_path,monkeypatch):
    for ancestor in [tmp_path,*tmp_path.parents]:
        if ancestor in (Path('/tmp'),Path('/')):break
        ancestor.chmod(0o755)
    inputs,calls=plumbing_inputs(tmp_path,monkeypatch)
    uids=dict(zip(r.ROLES,[30210,30220,30230,30240,30250]))
    descriptor=r.inventory(inputs,source_bar_date='2026-09-27');root=tmp_path/'review'
    pin=r.init_review(root,inputs,source_bar_date='2026-09-27',expected_inventory_hash=p.digest(descriptor),uids=uids)
    for path in inputs.archive_root.rglob('*'):
        path.chmod(0o755 if path.is_dir() else 0o444)
    inputs.archive_root.chmod(0o755)
    from tests.unit_tests.ai_strategy_lab.test_v13_causal_publication_fixture import _as_uid
    outcome=_as_uid(uids['custodian'],lambda:r.capture_archive(root,inputs,expected_config_hash=pin))
    assert outcome[0]=='ok',outcome
    ident=outcome[1]
    outcome=_as_uid(uids['publisher'],lambda:r.publish(root,ident,expected_config_hash=pin));assert outcome[0]=='ok',outcome
    outcome=_as_uid(uids['witness'],lambda:r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:PUB));assert outcome[0]=='ok',outcome
    a=outcome[1]
    outcome=_as_uid(uids['verifier'],lambda:r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=a['ack_hash']));assert outcome[0]=='ok',outcome
    outcome=_as_uid(uids['witness'],lambda:r.attest(root,ident,stage='derivation',expected_config_hash=pin,clock=lambda:DER));assert outcome[0]=='ok',outcome
    b=outcome[1]
    outcome=_as_uid(uids['strategy'],lambda:verify(root,pin,ident,a,b));assert outcome[0]=='ok',outcome
    assert outcome[1]['roles_distinct_in_sandbox'] is True
    for path in [root/'config.json',root/'custodian'/ident/'inventory.json',root/'publisher'/(ident+'.json'),root/'verifier'/(ident+'.json'),root/'witness'/'witness.sqlite']:
        outcome=_as_uid(uids['strategy'],lambda:path.write_bytes(b'bad'));assert outcome[0:2]==('error','PermissionError'),outcome
    outcome=_as_uid(uids['strategy'],lambda:r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=a['ack_hash']))
    assert outcome[0:2]==('error','Rejected') and 'wrong_review_role' in outcome[2]
    for path in [root,*[x for x in root.rglob('*') if x.is_dir()]]:os.chown(path,0,-1)


def test_partial_capture_is_staging_and_restart_completes_same_inventory(tmp_path,monkeypatch):
    inputs,_=plumbing_inputs(tmp_path,monkeypatch);descriptor=r.inventory(inputs,source_bar_date='2026-09-27')
    root=tmp_path/'review';pin=r.init_review(root,inputs,source_bar_date='2026-09-27',expected_inventory_hash=p.digest(descriptor),uids={x:0 for x in r.ROLES})
    def fail(stage):raise OSError('storage failure')
    with pytest.raises(OSError):r.capture_archive(root,inputs,expected_config_hash=pin,_fault=fail)
    ident=p.digest(descriptor)
    assert not (root/'custodian'/ident/'inventory.json').exists()
    with pytest.raises(FileNotFoundError):r.publish(root,ident,expected_config_hash=pin)
    assert r.capture_archive(root,inputs,expected_config_hash=pin)==ident
    r.publish(root,ident,expected_config_hash=pin);a,b,_=finish(root,pin,ident);verify(root,pin,ident,a,b)


def test_derivation_process_death_does_not_publish_derivation_availability(tmp_path,monkeypatch):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch)
    a=r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=lambda:PUB)
    def child():
        r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=a['ack_hash'],_fault=lambda stage:os._exit(82))
    proc=multiprocessing.get_context('fork').Process(target=child);proc.start();proc.join(10);assert proc.exitcode==82
    assert not (root/'witness'/(ident+'-derivation.json')).exists()
    a,b,_=finish(root,pin,ident);verify(root,pin,ident,a,b)


@pytest.mark.parametrize('field,value',[('research_only',False),('issuable',True),('availability_status','VERIFIED'),('source_available_at',PUB)])
def test_original_receipt_cannot_be_promoted_by_resealing(tmp_path,monkeypatch,field,value):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch);a,b,_=finish(root,pin,ident)
    path=root/'verifier'/(ident+'.json');payload=p.read_json(path.read_bytes())
    original=payload['original_derivation'];original[field]=value;original.pop('receipt_hash')
    payload['original_derivation']=p.seal_receipt(original);payload['original_receipt_hash']=payload['original_derivation']['receipt_hash']
    path.chmod(0o644);path.write_bytes(p.canonical_bytes(payload));path.chmod(0o444)
    with pytest.raises(p.Rejected):verify(root,pin,ident,a,b)


def test_original_target_change_on_replay_denied(tmp_path,monkeypatch):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch);a,b,_=finish(root,pin,ident)
    original=v.reconstruct
    def altered(*args,**kw):
        result=original(*args,**kw);result['targets']['BTCUSDT']='0.2';result.pop('receipt_hash');return p.seal_receipt(result)
    monkeypatch.setattr(v,'reconstruct',altered)
    with pytest.raises(p.Rejected,match='replay_conflict'):r.derive(root,ident,expected_config_hash=pin,expected_publication_ack_hash=a['ack_hash'])


def test_clock_callback_observes_committed_witness_state(tmp_path,monkeypatch):
    root,pin,ident,_,_=setup(tmp_path,monkeypatch)
    def clock():
        with sqlite3.connect(root/'witness'/'witness.sqlite') as db:assert db.execute('SELECT count(*) FROM attestations').fetchone()[0]==1
        return PUB
    r.attest(root,ident,stage='publication',expected_config_hash=pin,clock=clock)
