"""Real issuer logic, explicitly synthetic governance, isolated UID fixtures.

Work card: work-card-69a717fd-b2e7-488b-aef6-6e9bbf58c6a5.
No operational source is promoted and no executor/ledger is involved.
"""
import copy
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile

import pytest

from octobot.ai_strategy_lab import v13_original_portfolio as p
from octobot.ai_strategy_lab import v13_original_issuer as issuer

pytestmark = pytest.mark.skipif(os.geteuid() != 0, reason="real UID fixture setup needs isolated root")
ROOT = Path(__file__).resolve().parents[3]
NOW = "2026-09-28T00:15:00+00:00"
STRATEGY, ISSUER, VERIFIER, EXECUTOR = 30010, 30020, 30030, 30040


def as_uid(uid, gid, callback):
    reader, writer = os.pipe();pid = os.fork()
    if pid == 0:
        os.close(reader)
        try:
            os.setgroups([]);os.setgid(gid);os.setuid(uid)
            result = {"ok": True, "value": callback()}
        except BaseException as error:
            result = {"ok": False, "type": type(error).__name__, "error": str(error)}
        with os.fdopen(writer, "wb") as stream:stream.write(json.dumps(result).encode())
        os._exit(0)
    os.close(writer)
    with os.fdopen(reader, "rb") as stream:result = json.load(stream)
    os.waitpid(pid, 0)
    return result


def write_json(path, value, uid=0, gid=EXECUTOR):
    path.write_bytes(p.canonical_bytes(value))
    os.chown(path, uid, gid);path.chmod(0o640)
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def sandbox():
    root=Path(tempfile.mkdtemp(prefix="v13-original-issuer-test-"));root.chmod(0o755)
    try:
        (root/"sandbox.marker").write_bytes(issuer.MARKER);(root/"sandbox.marker").chmod(0o444)
        for name, uid, gid in [("strategy",STRATEGY,EXECUTOR),("verifier",VERIFIER,EXECUTOR),("issuer",ISSUER,EXECUTOR)]:
            d=root/name;d.mkdir();os.chown(d,uid,gid);d.chmod(0o750)
        contract,schema=p.load_contract(ROOT)
        component_hashes={"adapter":hashlib.sha256(Path(p.__file__).read_bytes()).hexdigest(),
                          "issuer":hashlib.sha256(Path(issuer.__file__).read_bytes()).hexdigest(),
                          "verifier":hashlib.sha256((ROOT/"octobot/ai_strategy_lab/v13_original_verify.py").read_bytes()).hexdigest()}
        binding={"status":issuer.FIXTURE,"owner_decision_ref":"fixture:unit-tests-only",
                 "account":"v13-paper-v2","account_epoch":"c"*64,"effective_not_before":"2026-09-28T00:10:00Z",
                 "baseline_bar_date":"2026-09-26","baseline_source_record_hash":"0"*64,
                 "ttl_seconds":120,"max_proposal_age_seconds":120}
        proposal={"schema_version":1,"account":"v13-paper-v2","portfolio_id":contract["portfolio_id"],"environment":"paper",
                  "scientific_lineage_ref":contract["scientific_lineage_ref"],"universe_hash":contract["universe_hash"],
                  "account_epoch":binding["account_epoch"],"execution_binding_ref":p.digest(binding),
                  "source_record_hash":"d"*64,"source_bar_date":"2026-09-27","complete_portfolio":True,
                  "source_available_at":"2026-09-28T00:12:00Z","decision_timestamp":"2026-09-28T00:13:00Z",
                  "proposal_timestamp":"2026-09-28T00:14:00Z","targets":{s:"0" for s in contract["universe"]}}
        proposal["targets"]["BTCUSDT"]="0.1"
        identity={k:proposal[k] for k in ("source_record_hash","source_bar_date","scientific_lineage_ref","universe_hash")}
        publication=p.seal_receipt({**identity,"kind":"v13-original-publication-v1","causal_input_hash":"a"*64,
                                    "dependency_receipts":{"1"*64:"2026-09-28T00:10:01Z"},"completed_at":"2026-09-28T00:11:00Z"})
        derivation=p.seal_receipt({**identity,"kind":"v13-original-derivation-v1","causal_input_hash":"a"*64,
                                   "raw_response_hashes":["1"*64],"targets":proposal["targets"],
                                   "verified_at":"2026-09-28T00:12:00Z","availability_status":"VERIFIED","derivation_status":"VERIFIED",
                                   "research_only":True,"execution_approved":False,"code_hashes":{k:component_hashes[k] for k in ("adapter","verifier")}})
        proof={}
        for name,value,owner,directory in [("derivation",derivation,VERIFIER,root/"verifier"),("publication",publication,0,root)]:
            path=directory/(name+".json");sha=write_json(path,value,owner)
            proof[name]={"path":str(path),"owner_uid":owner,"file_sha256":sha,"receipt_hash":value["receipt_hash"]}
        proposal.update(derivation_receipt_hash=derivation["receipt_hash"],source_publication_receipt_hash=publication["receipt_hash"])
        proposal["proposal_id"]=p.proposal_id(proposal);proposal_path=root/"strategy/proposal.json";write_json(proposal_path,proposal,STRATEGY)
        policy={"scope":issuer.FIXTURE,"scientific_certified":False,"version":"fixture-risk-v1",
                "daily_loss":0.02,"drawdown":0.05,"order_frequency":4,"cooldown":3600}
        policy_path=root/"policy.json";policy_hash=write_json(policy_path,policy)
        admissibility={"scope":issuer.FIXTURE,"mode":"synthetic_control_pipeline","version":"fixture-issuance-v1",
                       "scientific_certified":False,"kucoin_order_admissibility_proven":False}
        admissibility_path=root/"admissibility.json";admissibility_hash=write_json(admissibility_path,admissibility)
        config={"schema_version":1,"mode":"architecture_fixture","fixture_label":issuer.FIXTURE,"sandbox_root":str(root),
                "repo_root":str(ROOT),"issuer_uid":ISSUER,"strategy_uid":STRATEGY,"verifier_uid":VERIFIER,"executor_gid":EXECUTOR,
                "approval_db":str(root/"issuer/approvals.sqlite"),"component_hashes":component_hashes,"store_id":hashlib.sha256(str(root).encode()).hexdigest(),
                "fixture_binding":binding,"fixture_policy":{"path":str(policy_path),"file_sha256":policy_hash},
                "fixture_admissibility":{"path":str(admissibility_path),"file_sha256":admissibility_hash},
                "fixture_proofs":{proposal["source_record_hash"]:proof},"diagnostic_receipt":proof["derivation"]}
        path=root/"issuer-config.json";sha=write_json(path,config)
        value={"root":root,"config":config,"config_path":path,"config_sha":sha,"proposal":proposal,
               "proposal_path":proposal_path,"derivation":derivation,"publication":publication,"policy":policy,
               "admissibility":admissibility}
        yield value
    finally:shutil.rmtree(root)


def run(sandbox, action="issue", **kwargs):
    def invoke():
        obj=issuer.Issuer(sandbox["config_path"],expected_config_sha256=sandbox["config_sha"])
        if action=="init":obj.store.initialize();return True
        if action=="diagnose":return obj.diagnose(checked_at=kwargs.get("now",NOW))
        return obj.issue(sandbox["proposal_path"],checked_at=kwargs.get("now",NOW))
    return as_uid(ISSUER,EXECUTOR,invoke)


def init(s):assert run(s,"init")=={"ok":True,"value":True}


def test_positive_fixture_and_restart_duplicate(sandbox):
    init(sandbox);first=run(sandbox);second=run(sandbox)
    assert first["ok"] and first["value"]["status"]=="APPROVE"
    assert second["ok"] and second["value"]["status"]=="DUPLICATE"
    a,b=first["value"]["receipt"],second["value"]["receipt"]
    assert a==b and len(a["proposal"]["targets"])==18
    assert a["scope"]==issuer.FIXTURE and a["operational_approval"] is False
    assert a["risk_policy_sha256"]==sandbox["config"]["fixture_policy"]["file_sha256"]
    assert a["candidate_contract_sha256"]==p.CONTRACT_SHA256 and a["proposal_schema_sha256"]==p.SCHEMA_SHA256
    assert a["admissibility_contract_sha256"]==sandbox["config"]["fixture_admissibility"]["file_sha256"]
    assert a["fixture_binding_sha256"]==sandbox["proposal"]["execution_binding_ref"]
    with sqlite3.connect(sandbox["config"]["approval_db"]) as db:
        assert db.execute("SELECT count(*) FROM approvals").fetchone()[0]==1
        assert db.execute("PRAGMA journal_mode").fetchone()[0]=="delete"
        assert db.execute("PRAGMA integrity_check").fetchall()==[("ok",)]


def test_changed_timestamp_cannot_reissue_same_slot(sandbox):
    init(sandbox);assert run(sandbox)["value"]["status"]=="APPROVE"
    changed=copy.deepcopy(sandbox["proposal"]);changed["proposal_timestamp"]="2026-09-28T00:14:01Z";changed["proposal_id"]=p.proposal_id(changed)
    write_json(sandbox["proposal_path"],changed,STRATEGY)
    result=run(sandbox);assert result["ok"] and result["value"]["reason"]=="source_slot_conflict"


@pytest.mark.parametrize("mutation",[
    lambda s:s["proposal"]["targets"].pop("ETHUSDT"),
    lambda s:s["proposal"].update(approved=True),
    lambda s:s["proposal"].update(account="other"),
    lambda s:s["proposal"].update(account_epoch="e"*64),
    lambda s:s["proposal"].update(execution_binding_ref="e"*64),
    lambda s:s["proposal"].update(source_available_at="2026-09-28T00:14:01Z"),
    lambda s:s["proposal"]["targets"].update(BTCUSDT="0.2"),
])
def test_invalid_or_false_proposal_denied_durably(sandbox,mutation):
    init(sandbox);mutation(sandbox);sandbox["proposal"]["proposal_id"]=p.proposal_id(sandbox["proposal"])
    write_json(sandbox["proposal_path"],sandbox["proposal"],STRATEGY)
    result=run(sandbox);assert result["ok"] and result["value"]["status"]=="DENY" and result["value"]["persisted"]
    with sqlite3.connect(sandbox["config"]["approval_db"]) as db:
        assert db.execute("SELECT count(*) FROM approvals").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM issuer_events WHERE status='DENY'").fetchone()[0]==1


def test_stale_proposal_not_backdated(sandbox):
    init(sandbox);result=run(sandbox,now="2026-09-28T00:17:00Z")
    assert result["ok"] and result["value"]["reason"]=="proposal_stale"


@pytest.mark.parametrize("kind",["derivation","publication"])
def test_receipt_tamper_denied(sandbox,kind):
    init(sandbox);proof=sandbox["config"]["fixture_proofs"]["d"*64][kind]
    Path(proof["path"]).write_text('{"forged":true}')
    result=run(sandbox);assert result["ok"] and result["value"]["reason"]=="input_pin_mismatch"


def test_wrong_verifier_owner_denied(sandbox):
    init(sandbox);path=Path(sandbox["config"]["diagnostic_receipt"]["path"]);os.chown(path,STRATEGY,EXECUTOR)
    result=run(sandbox);assert result["ok"] and result["value"]["reason"]=="unsafe_input_owner_or_mode"


def test_strategy_and_executor_cannot_write_approvals(sandbox):
    init(sandbox);run(sandbox)
    for uid,gid in [(STRATEGY,STRATEGY),(EXECUTOR,EXECUTOR)]:
        result=as_uid(uid,gid,lambda:sqlite3.connect(sandbox["config"]["approval_db"]).execute("CREATE TABLE forged(x)"))
        assert result["ok"] is False
    def reader():
        with sqlite3.connect(Path(sandbox["config"]["approval_db"]).as_uri()+"?mode=ro",uri=True) as db:
            db.execute("PRAGMA query_only=ON");return db.execute("SELECT count(*) FROM approvals").fetchone()[0]
    assert as_uid(EXECUTOR,EXECUTOR,reader)=={"ok":True,"value":1}
    assert not as_uid(STRATEGY,STRATEGY,lambda:Path(sandbox["config_path"]).write_text("forged"))["ok"]
    assert not as_uid(STRATEGY,STRATEGY,lambda:Path(sandbox["config"]["diagnostic_receipt"]["path"]).write_text("forged"))["ok"]


def test_config_tamper_or_wrong_writer_never_approves(sandbox):
    init(sandbox);sandbox["config_path"].write_text('{}');assert run(sandbox)["ok"] is False


@pytest.mark.parametrize("field",["mode","component_hashes","store_id","issuer_uid"])
def test_invalid_root_pinned_config_denied(sandbox,field):
    if field=="mode":sandbox["config"][field]="operational"
    elif field=="component_hashes":sandbox["config"][field]["adapter"]="e"*64
    elif field=="store_id":sandbox["config"][field]="bad"
    else:sandbox["config"][field]=STRATEGY
    sandbox["config_sha"]=write_json(sandbox["config_path"],sandbox["config"])
    assert not run(sandbox,"init")["ok"]


@pytest.mark.parametrize("kind",["policy","admissibility"])
def test_incomplete_pinned_fixture_contract_denied(sandbox,kind):
    item=sandbox[kind]
    if kind=="policy":item["cooldown"]=None
    else:item["scope"]="operational"
    descriptor=sandbox["config"]["fixture_"+kind]
    descriptor["file_sha256"]=write_json(Path(descriptor["path"]),item)
    sandbox["config_sha"]=write_json(sandbox["config_path"],sandbox["config"])
    init(sandbox);result=run(sandbox)
    assert result["ok"] and result["value"]["status"]=="DENY" and result["value"]["persisted"]


@pytest.mark.parametrize("kind",["config","derivation","proposal","store"])
def test_symlink_substitution_denied(sandbox,kind):
    init(sandbox)
    paths={"config":sandbox["config_path"],"derivation":Path(sandbox["config"]["diagnostic_receipt"]["path"]),
           "proposal":sandbox["proposal_path"],"store":Path(sandbox["config"]["approval_db"])}
    path=paths[kind];target=path.with_suffix(".other");path.rename(target);path.symlink_to(target)
    result=run(sandbox)
    if kind in ("config","store"):assert not result["ok"]
    else:assert result["ok"] and result["value"]["status"]=="DENY" and result["value"]["persisted"]


@pytest.mark.parametrize("failure",["missing","corrupt","readonly","wal","schema"])
def test_storage_failure_has_no_valid_result(sandbox,failure):
    init(sandbox);path=Path(sandbox["config"]["approval_db"])
    if failure=="missing":path.unlink()
    elif failure=="corrupt":path.write_bytes(b'not a sqlite database')
    elif failure=="readonly":path.chmod(0o440)
    else:
        with sqlite3.connect(path) as db:
            if failure=="wal":db.execute("PRAGMA journal_mode=WAL")
            else:db.execute("CREATE TABLE forged(x)")
    assert run(sandbox)["ok"] is False


@pytest.mark.parametrize("failure",["missing","corrupt","readonly"])
def test_cli_reports_unpersisted_storage_failure(sandbox,failure):
    init(sandbox);path=Path(sandbox["config"]["approval_db"])
    if failure=="missing":path.unlink()
    elif failure=="corrupt":path.write_bytes(b'not a sqlite database')
    else:path.chmod(0o440)
    def invoke():
        command=[sys.executable,"-m","octobot.ai_strategy_lab.v13_original_issuer",
                 "--config",str(sandbox["config_path"]),"--config-sha256",sandbox["config_sha"],
                 "--proposal",str(sandbox["proposal_path"])]
        result=subprocess.run(command,capture_output=True,text=True)
        return {"returncode":result.returncode,"result":json.loads(result.stdout)}
    outcome=as_uid(ISSUER,EXECUTOR,invoke)
    assert outcome["ok"] and outcome["value"]["returncode"]==2
    result=outcome["value"]["result"]
    assert result["status"]=="DENY" and result["persisted"] is False and result["operational_approval"] is False


def test_unlabelled_fixture_profile_cannot_start(sandbox):
    sandbox["config"]["fixture_label"]=None
    sandbox["config_sha"]=write_json(sandbox["config_path"],sandbox["config"])
    assert run(sandbox,"init")["ok"] is False


def test_diagnostic_mode_remains_deny_even_with_fixture_proofs(sandbox):
    sandbox["config"].update(mode="diagnostic_only",fixture_label=None)
    sandbox["config_sha"]=write_json(sandbox["config_path"],sandbox["config"])
    init(sandbox);result=run(sandbox)
    assert result["ok"] and result["value"]["reason"]=="binding_unapproved"


def test_concurrent_issuers_do_not_mint_two_approvals(sandbox):
    init(sandbox)
    children=[]
    for _ in range(2):
        reader,writer=os.pipe();pid=os.fork()
        if pid==0:
            os.close(reader);os.setgroups([]);os.setgid(EXECUTOR);os.setuid(ISSUER)
            try:
                obj=issuer.Issuer(sandbox["config_path"],expected_config_sha256=sandbox["config_sha"])
                result={"ok":True,"value":obj.issue(sandbox["proposal_path"],checked_at=NOW)}
            except BaseException as error:result={"ok":False,"error":str(error)}
            with os.fdopen(writer,"wb") as stream:stream.write(json.dumps(result).encode())
            os._exit(0)
        os.close(writer);children.append((reader,pid))
    outcomes=[]
    for reader,pid in children:
        with os.fdopen(reader,"rb") as stream:outcomes.append(json.load(stream))
        os.waitpid(pid,0)
    assert all(x["ok"] for x in outcomes),outcomes
    assert {x["value"]["status"] for x in outcomes}=={"APPROVE","DUPLICATE"}
    assert outcomes[0]["value"]["receipt"]==outcomes[1]["value"]["receipt"]


def test_failure_during_commit_rolls_back_approval_and_audit(sandbox):
    init(sandbox)
    def failing_issue():
        original=sqlite3.connect
        class Broken(sqlite3.Connection):
            def commit(self):raise sqlite3.OperationalError("fixture disk full")
        sqlite3.connect=lambda *args,**kwargs:original(*args,**kwargs,factory=Broken)
        return issuer.Issuer(sandbox["config_path"],expected_config_sha256=sandbox["config_sha"]).issue(sandbox["proposal_path"],checked_at=NOW)
    result=as_uid(ISSUER,EXECUTOR,failing_issue);assert not result["ok"]
    with sqlite3.connect(sandbox["config"]["approval_db"]) as db:
        assert db.execute("SELECT count(*) FROM approvals").fetchone()[0]==0
        assert db.execute("SELECT count(*) FROM issuer_events").fetchone()[0]==0


@pytest.mark.parametrize("committed",[False,True])
def test_process_crash_around_commit_and_restart(sandbox,committed):
    init(sandbox);pid=os.fork()
    if pid==0:
        os.setgroups([]);os.setgid(EXECUTOR);os.setuid(ISSUER)
        original=sqlite3.connect
        class Interrupted(sqlite3.Connection):
            def commit(self):
                if committed:super().commit()
                os._exit(42)
        sqlite3.connect=lambda *args,**kwargs:original(*args,**kwargs,factory=Interrupted)
        issuer.Issuer(sandbox["config_path"],expected_config_sha256=sandbox["config_sha"]).issue(sandbox["proposal_path"],checked_at=NOW)
        os._exit(99)
    _,status=os.waitpid(pid,0);assert os.waitstatus_to_exitcode(status)==42
    restarted=run(sandbox);assert restarted["ok"]
    assert restarted["value"]["status"]==("DUPLICATE" if committed else "APPROVE")
    with sqlite3.connect(sandbox["config"]["approval_db"]) as db:
        assert db.execute("SELECT count(*) FROM approvals").fetchone()[0]==1
