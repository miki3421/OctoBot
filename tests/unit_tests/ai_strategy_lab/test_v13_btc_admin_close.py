"""Isolated paper ledger tests; no operational socket or journal."""
import datetime as dt
import json
import sqlite3

import pytest

from octobot.ai_strategy_lab import v13_admin_close
from tests.unit_tests.ai_strategy_lab.test_v13_trusted_execution import rig, NOW, market_v2, counts


def command(position, *, at=NOW+dt.timedelta(seconds=1), quantity=None):
    return dict(schema_version=1,command_id='close-1',account='v13-paper-v2',symbol='BTCUSDT',
        position_id=position['position_id'],position_generation=position['position_generation'],
        issued_at=at.isoformat(),expires_at=(at+dt.timedelta(minutes=1)).isoformat(),
        maximum_quantity_to_reduce=abs(position['quantity']) if quantity is None else quantity)


def position_at(root):
    with sqlite3.connect(root/'ledger'/'v13.sqlite') as db:
        return json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])['positions']['BTCUSDT']


def close(root, cmd, *, at=NOW+dt.timedelta(seconds=1), fault=None):
    return v13_admin_close.execute(cmd,ledger_path=root/'ledger'/'v13.sqlite',
        market_journal=root/'market'/'v2.jsonl',lock_path=root/'ledger'/'executor.lock',now=at,fault=fault)


def test_admin_close_with_strategy_and_issuer_offline_kill_active(rig):
    root,admin,_,_,_,run=rig
    assert run()['accepted']
    initial=position_at(root)
    admin.set_kill(True)
    with sqlite3.connect(root/'ledger'/'v13.sqlite') as db:
        db.execute('CREATE TABLE equity_peak(account TEXT PRIMARY KEY,equity REAL)')
        db.execute('INSERT INTO equity_peak VALUES (?,?)',('v13-paper-v2',20000.))
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(NOW+dt.timedelta(seconds=1)))+'\n')
    result=close(root,command(initial))
    assert result['accepted'] and result['position']==0
    assert counts(root)[0]==2
    with sqlite3.connect(root/'ledger'/'v13.sqlite') as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok'
        assert db.execute('SELECT COUNT(*) FROM admin_commands').fetchone()[0]==1
    with pytest.raises(ValueError,match='admin_command_replay'):
        close(root,command(initial))
    assert counts(root)[0]==2


@pytest.mark.parametrize('change,reason',[
    ({'position_id':'wrong'},'position_identity_mismatch'),
    ({'position_generation':99},'position_identity_mismatch'),
    ({'maximum_quantity_to_reduce':100000.},'admin_close_exceeds_position'),
    ({'issued_at':(NOW-dt.timedelta(minutes=10)).isoformat(),
      'expires_at':(NOW-dt.timedelta(minutes=5)).isoformat()},'admin_command_expired_or_future'),
])
def test_admin_close_rejects_wrong_identity_size_or_time(rig,change,reason):
    root,_,_,_,_,run=rig
    assert run()['accepted']
    original=position_at(root)
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(NOW+dt.timedelta(seconds=1)))+'\n')
    request=command(original)
    request.update(change)
    with pytest.raises(ValueError,match=reason):
        close(root,request)
    assert counts(root)[0]==1
    assert position_at(root)['quantity']==original['quantity']
    if reason != 'admin_command_expired_or_future':
        with sqlite3.connect(root/'ledger'/'v13.sqlite') as db:
            assert db.execute('SELECT reason_code FROM admin_denials ORDER BY id DESC LIMIT 1').fetchone()[0]==reason


@pytest.mark.parametrize('fault',['before_claim','after_claim'])
def test_admin_close_crash_before_commit_rolls_back(rig,fault):
    root,_,_,_,_,run=rig
    assert run()['accepted']
    original=position_at(root)
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(NOW+dt.timedelta(seconds=1)))+'\n')
    request=command(original)
    with pytest.raises(RuntimeError):
        close(root,request,fault=fault)
    assert counts(root)[0]==1
    assert position_at(root)['quantity']==original['quantity']
    assert close(root,request)['accepted']
    assert counts(root)[0]==2


def test_admin_close_rejects_stale_book_and_insufficient_depth(rig):
    root,_,_,_,_,run=rig
    assert run()['accepted']
    original=position_at(root)
    old_record=market_v2(NOW+dt.timedelta(seconds=1))
    (root/'market'/'v2.jsonl').write_text(json.dumps(old_record)+'\n')
    with pytest.raises(ValueError,match='stale'):
        close(root,command(original,at=NOW+dt.timedelta(hours=1)),at=NOW+dt.timedelta(hours=1))
    from tests.unit_tests.ai_strategy_lab.test_v13_market import signed
    future=old_record['symbols']['BTC']['futures']
    future['normalized_bids']=[dict(price=100.4,base_quantity=.000001,quote_quantity=.0001004)]
    future['normalized_asks']=[dict(price=100.6,base_quantity=.000001,quote_quantity=.0001006)]
    future['best_bid']=100.4
    future['best_ask']=100.6
    (root/'market'/'v2.jsonl').write_text(json.dumps(signed(old_record))+'\n')
    with pytest.raises(ValueError,match='insufficient_depth'):
        close(root,command(original))
    assert counts(root)[0]==1


def test_admin_close_storage_failure_keeps_position(rig,monkeypatch):
    root,_,_,_,_,run=rig
    assert run()['accepted']
    original=position_at(root)
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(NOW+dt.timedelta(seconds=1)))+'\n')
    from octobot.ai_strategy_lab import v13_admin_close
    def broken(_):
        raise sqlite3.OperationalError('storage_unavailable')
    with monkeypatch.context() as patch:
        patch.setattr(v13_admin_close.paper,'init_db',broken)
        with pytest.raises(sqlite3.OperationalError,match='storage_unavailable'):
            close(root,command(original))
    assert counts(root)[0]==1
    assert position_at(root)['quantity']==original['quantity']


def test_old_close_cannot_hit_reopened_position_generation(rig):
    from octobot.ai_strategy_lab import v13_intent_client
    root,admin,store,intent,_,run=rig
    assert run()['accepted']
    first=position_at(root)
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(NOW+dt.timedelta(seconds=1)))+'\n')
    assert close(root,command(first))['accepted']
    admin.set_kill(False)
    later=NOW+dt.timedelta(seconds=8)
    new_intent=dict(intent,intent_id='intent-2',decision_id='c'*64,
        decision_authorization_id='token-2',
        decision_timestamp=(NOW+dt.timedelta(seconds=1)).isoformat(),
        intent_timestamp=(NOW+dt.timedelta(seconds=1,milliseconds=500)).isoformat())
    store.issue_fixture_only(dict(decision_id=new_intent['decision_id'],
        token=new_intent['decision_authorization_id'],account=new_intent['account'],
        strategy=new_intent['strategy'],lineage_hash=new_intent['strategy_lineage_hash'],
        symbol=new_intent['symbol'],direction=new_intent['direction'],
        target_weight=new_intent['target_weight'],decision_at=new_intent['decision_timestamp'],
        source_hash=new_intent['decision_id']))
    path=v13_intent_client.submit(new_intent,root/'intents',now=later)
    (root/'market'/'v2.jsonl').write_text(json.dumps(market_v2(later))+'\n')
    reopened=run(path=path,at=later)
    with sqlite3.connect(root/'ledger'/'v13.sqlite') as db:
        details=json.loads(db.execute('SELECT payload FROM state WHERE id=1').fetchone()[0])['risk']
    assert reopened['accepted'], details
    current=position_at(root)
    assert current['position_generation']==first['position_generation']+1
    assert current['position_id']!=first['position_id']
    old_command=command(first,at=later)
    old_command['command_id']='close-old-generation'
    with pytest.raises(ValueError,match='position_identity_mismatch'):
        close(root,old_command,at=later)
    assert counts(root)[0]==3
