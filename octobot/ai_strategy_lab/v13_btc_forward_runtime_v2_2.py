"""BTC forward preparation V2.2; gated research-only runtime, no execution access.
Work card: work-card-1df93f9a-9cc0-4248-9d16-3fd4a7e96dbc."""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import ssl
import sqlite3
import stat
import subprocess
import tarfile
import urllib.error
import urllib.parse
import urllib.request

PRODUCER_PATH = Path(__file__).with_name("v13_btc_research_v2.py")
SPEC = importlib.util.spec_from_file_location("v13_btc_research_v2_candidate", PRODUCER_PATH)
p = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(p)

ENDPOINT = "https://api-futures.kucoin.com/api/v1/kline/query"
MAX_BYTES = 2_000_000
COLLECTOR_VERSION = "v13-btc-public-klines-collector-v2.2"
PRODUCER_SHA = hashlib.sha256(PRODUCER_PATH.read_bytes()).hexdigest()
VERIFY_PATH = PRODUCER_PATH.with_name("v13_btc_research_verify_v2.py")
VERIFY_SPEC = importlib.util.spec_from_file_location("v13_btc_forward_verifier", VERIFY_PATH)
verifier = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(verifier)


def query_url(slot, started):
    slot = p.slot_time(slot)
    start = p.utc_time(started)
    if not slot <= start <= slot + dt.timedelta(minutes=10):
        raise ValueError("COLLECTION_OUTSIDE_SLOT")
    lower = int((slot.replace(minute=0) - dt.timedelta(days=141)).timestamp()*1000)
    upper = int(start.timestamp()*1000)
    query = urllib.parse.urlencode({"symbol":p.EXCHANGE_SYMBOL,"granularity":1440,
                                    "from":lower,"to":upper})
    return ENDPOINT + "?" + query


def validate_url(url, slot, started):
    if url != query_url(slot, started):
        raise ValueError("SOURCE_URL_MISMATCH")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        raise ValueError("SOURCE_REDIRECT_DENIED")


def public_get(url):
    """Only the pinned public Futures HTTPS endpoint; no credentials/proxies/redirects."""
    if not url.startswith(ENDPOINT + "?"):
        raise ValueError("SOURCE_URL_MISMATCH")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
                                         urllib.request.HTTPSHandler(context=ssl.create_default_context()),
                                         NoRedirect())
    request = urllib.request.Request(url, headers={"User-Agent":"v13-btc-research-v2"}, method="GET")
    with opener.open(request, timeout=15) as response:
        if response.status != 200 or response.geturl() != url:
            raise ValueError("SOURCE_HTTP_INVALID")
        body = response.read(MAX_BYTES+1)
        if len(body) > MAX_BYTES:
            raise ValueError("SOURCE_TOO_LARGE")
        return body, response.status, response.headers.get("Date")


def collect_once(archive, slot_utc, *, clock=None, fetch=None):
    """One public capture attempt. No slot decision is made by this process."""
    clock = clock or (lambda: dt.datetime.now(p.UTC))
    fetch = fetch or public_get
    started = clock()
    url = query_url(slot_utc, started.isoformat())
    raw, status, server_date = fetch(url)
    received = clock()
    if (not isinstance(received, dt.datetime) or received.tzinfo is None
        or received < started or received > p.slot_time(slot_utc)+dt.timedelta(minutes=10)
        or status != 200 or not isinstance(raw, bytes) or len(raw) > MAX_BYTES):
        raise ValueError("SOURCE_CAPTURE_INVALID")
    validate_url(url, slot_utc, started.isoformat())
    # Parse before any archive write. Empty/gapped responses cannot be inferred.
    p.parse_raw(raw)
    receipt_id = p.capture(archive, raw, received.isoformat(), request_url=url)
    receipt, _ = p.load_receipt(archive, receipt_id)
    attestation = {"schema_version":1,"collector_version":COLLECTOR_VERSION,
                   "slot_utc":p.slot_time(slot_utc).isoformat(),"request_url":url,
                   "request_started_at":started.isoformat(),"received_at":received.isoformat(),
                   "http_status":status,"server_date":server_date,
                   "receipt_id":receipt_id,"raw_sha256":receipt["raw_sha256"]}
    day = p.slot_time(slot_utc).strftime("%Y%m%d")
    p._atomic_new(Path(archive)/"attestations"/day/(p.sha(attestation)+".json"),
                  p.canonical(attestation)+b"\n")
    return {"receipt_id":receipt_id,"attestation_id":p.sha(attestation),
            "raw_sha256":receipt["raw_sha256"]}


def read_attestations(archive, slot_utc):
    slot = p.slot_time(slot_utc)
    directory = Path(archive)/"attestations"/slot.strftime("%Y%m%d")
    if not directory.exists():
        return []
    found = []
    for path in sorted(directory.glob("*.json")):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o022 or info.st_size > 8192:
            raise ValueError("ATTESTATION_FILE_INVALID")
        doc = json.loads(path.read_bytes(), object_pairs_hook=p.pairs_unique)
        if (path.name != p.sha(doc)+".json" or set(doc) != {
            "schema_version","collector_version","slot_utc","request_url",
            "request_started_at","received_at","http_status","server_date",
            "receipt_id","raw_sha256"} or doc["schema_version"] != 1
            or doc["collector_version"] != COLLECTOR_VERSION or doc["slot_utc"] != slot.isoformat()
            or doc["http_status"] != 200):
            raise ValueError("ATTESTATION_INVALID")
        started = p.utc_time(doc["request_started_at"])
        received = p.utc_time(doc["received_at"])
        if not slot <= started <= received <= slot+dt.timedelta(minutes=10):
            raise ValueError("ATTESTATION_TIME_INVALID")
        validate_url(doc["request_url"],slot_utc,started.isoformat())
        receipt, _ = p.load_receipt(archive,doc["receipt_id"])
        if (receipt["raw_sha256"] != doc["raw_sha256"]
            or receipt["received_at"] != doc["received_at"]
            or receipt["request_url"] != doc["request_url"]):
            raise ValueError("ATTESTATION_RECEIPT_MISMATCH")
        found.append(doc)
    return found


def finalize_from_archive(journal, archive, slot_utc, *, clock=None):
    """Finalize timely input before 00:20; after deadline only MISSING is allowed."""
    clock = clock or (lambda: dt.datetime.now(p.UTC))
    now = clock()
    slot = p.slot_time(slot_utc)
    if now < slot:
        raise ValueError("SLOT_NOT_OPEN")
    deadline = slot+dt.timedelta(minutes=10)
    try:
        attestations = read_attestations(archive,slot_utc)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        if now < deadline:
            raise ValueError("SLOT_NOT_FINALIZABLE") from exc
        decision, source = p.missing(slot_utc,now.isoformat(),PRODUCER_SHA,"INTEGRITY_FAILURE")
        return p.append_slot(journal,decision,source,now.isoformat()),decision
    if Path(journal).exists():
        db = sqlite3.connect(f"file:{Path(journal)}?mode=ro",uri=True)
        try:
            prior = db.execute("SELECT decision_json FROM slots WHERE slot_utc=?",(slot_utc,)).fetchone()
        finally:
            db.close()
        if prior:
            existing = json.loads(prior[0])
            # A terminal missed slot cannot become a retrospective proposal.
            # Timely bytes left by a crashed collector are expected, not a conflict.
            if existing["status"] == "MISSING":
                return False, existing
            for doc in attestations:
                try:
                    candidate, source = p.produce(archive,doc["receipt_id"],slot_utc,
                                                  deadline.isoformat(),PRODUCER_SHA)
                except ValueError:
                    continue
                if candidate["decision_id"] != existing["decision_id"]:
                    # Persist the conflict, but never replace the old slot.
                    p.append_slot(journal,candidate,source,now.isoformat())
            return False,existing
    if not attestations:
        if now < deadline:
            raise ValueError("SLOT_NOT_FINALIZABLE")
        decision, source = p.missing(slot_utc,now.isoformat(),PRODUCER_SHA,"SOURCE_FAILURE")
        return p.append_slot(journal,decision,source,now.isoformat()),decision
    if now > deadline:
        # Even a timely response cannot be converted into a late decision.
        return p.finalize_slot(journal,archive,attestations[0]["receipt_id"],
                               slot_utc,now.isoformat(),PRODUCER_SHA)
    candidates = []
    for doc in attestations:
        try:
            decision, _ = p.produce(archive,doc["receipt_id"],slot_utc,now.isoformat(),PRODUCER_SHA)
        except ValueError:
            continue
        verifier.verify(archive, decision, {"receipt_id": doc["receipt_id"],
                        "raw_sha256": doc["raw_sha256"], "received_at": doc["received_at"]},
                        PRODUCER_SHA)
        candidates.append((decision,doc))
    if candidates and len({item[0]["decision_id"] for item in candidates}) > 1:
        if now < deadline:
            raise ValueError("SLOT_NOT_FINALIZABLE")
        decision, source = p.missing(slot_utc,now.isoformat(),PRODUCER_SHA,"INTEGRITY_FAILURE")
        return p.append_slot(journal,decision,source,now.isoformat()),decision
    if candidates:
        chosen = min(candidates,key=lambda item:(item[1]["received_at"],item[1]["receipt_id"]))
        return p.finalize_slot(journal,archive,chosen[1]["receipt_id"],
                               slot_utc,now.isoformat(),PRODUCER_SHA)
    # Validly attested HTTP bytes may still lack the required daily sequence.
    if now < deadline:
        raise ValueError("SLOT_NOT_FINALIZABLE")
    return p.finalize_slot(journal,archive,attestations[0]["receipt_id"],
                           slot_utc,now.isoformat(),PRODUCER_SHA)


def status_only(journal):
    """Operational health surface: no outcomes or performance values."""
    db = sqlite3.connect(f"file:{Path(journal)}?mode=ro",uri=True)
    try:
        counts = {state:0 for state in p.TERMINAL}
        last = None
        previous = None
        for raw, provenance, recorded_at, prior, digest in db.execute(
                "SELECT decision_json,provenance_json,recorded_at,previous_hash,record_hash FROM slots ORDER BY rowid"):
            decision = json.loads(raw)
            source = json.loads(provenance) if provenance else None
            if prior != previous or p.sha({"decision":decision,"provenance":source,
                                          "recorded_at":recorded_at,"previous_hash":prior}) != digest:
                raise ValueError("SLOT_CHAIN_INVALID")
            previous = digest
            counts[decision["status"]] += 1
            last = {"slot_utc":decision["slot_utc"],"state":decision["status"],
                    "reason_code":decision["reason_code"]}
        return {"integrity":"ok","slot_counts":counts,"latest":last,
                "mature_outcome_count":db.execute("SELECT count(*) FROM outcomes").fetchone()[0],
                "conflict_count":db.execute("SELECT count(*) FROM conflicts").fetchone()[0]}
    finally:
        db.close()


def mature_previous(journal, archive, current_slot_utc, *, clock=None):
    """Use only today's timely archived capture for yesterday's mature bar."""
    clock = clock or (lambda: dt.datetime.now(p.UTC))
    current = p.slot_time(current_slot_utc)
    if clock() < current+dt.timedelta(minutes=10):
        raise ValueError("OUTCOME_CAPTURE_WINDOW_OPEN")
    prior = current-dt.timedelta(days=1)
    db = sqlite3.connect(f"file:{Path(journal)}?mode=ro",uri=True)
    try:
        row = db.execute("SELECT decision_json FROM slots WHERE slot_utc=?",(prior.isoformat(),)).fetchone()
    finally:
        db.close()
    if not row:
        raise ValueError("OUTCOME_SLOT_MISSING")
    if json.loads(row[0])["status"] not in ("LONG","SHORT"):
        return False
    attestations = read_attestations(archive,current_slot_utc)
    if not attestations:
        raise ValueError("OUTCOME_SOURCE_MISSING")
    expected = int(prior.replace(minute=0).timestamp()*1000)
    closes = set()
    for doc in attestations:
        _, bars = p.load_receipt(archive,doc["receipt_id"])
        matches = [bar[1] for bar in bars if bar[0] == expected]
        if len(matches) != 1:
            raise ValueError("OUTCOME_BAR_MISSING")
        closes.add(matches[0])
    if len(closes) != 1:
        raise ValueError("OUTCOME_SOURCE_CONFLICT")
    chosen = min(attestations,key=lambda item:(item["received_at"],item["receipt_id"]))
    return p.mature(journal,archive,prior.isoformat(),chosen["receipt_id"])


def require_synchronized_clock():
    try:
        result = subprocess.run(["chronyc","-c","tracking"],capture_output=True,
                                text=True,timeout=5,check=False)
    except (OSError,subprocess.TimeoutExpired):
        result = None
    if result is not None and result.returncode == 0:
        fields = result.stdout.strip().split(",")
        try:
            now = dt.datetime.now(p.UTC).timestamp()
            healthy = (len(fields) == 14 and 1 <= int(fields[2]) <= 15
                       and 0 <= now-float(fields[3]) <= 3600
                       and abs(float(fields[4])) <= 1
                       and 0 <= float(fields[11]) <= 1
                       and fields[13] == "Normal")
        except (ValueError,IndexError):
            healthy = False
        if not healthy:
            raise ValueError("CLOCK_NOT_SYNCHRONIZED")
        return
    try:
        fallback = subprocess.run(["timedatectl","show","-p","NTPSynchronized","--value"],
                                  capture_output=True,text=True,timeout=5,check=False)
    except (OSError,subprocess.TimeoutExpired) as exc:
        raise ValueError("CLOCK_NOT_SYNCHRONIZED") from exc
    if fallback.returncode != 0 or fallback.stdout.strip().lower() != "yes":
        raise ValueError("CLOCK_NOT_SYNCHRONIZED")


def _read_root_activation(path):
    fd = os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 8192:
            raise ValueError("ACTIVATION_OWNERSHIP_INVALID")
        with os.fdopen(fd,"rb",closefd=False) as stream:
            activation = json.loads(stream.read(),object_pairs_hook=p.pairs_unique)
    finally:
        os.close(fd)
    expected = {"status","bundle_sha256","start_slot_utc","end_slot_utc",
                "collector_uid","finalizer_uid","archive_path","journal_path"}
    if set(activation) != expected or activation["status"] != "APPROVED_FORWARD_RESEARCH_ONLY":
        raise ValueError("ACTIVATION_INVALID")
    start = p.slot_time(activation["start_slot_utc"])
    end = p.slot_time(activation["end_slot_utc"])
    if end-start != dt.timedelta(days=179):
        raise ValueError("ACTIVATION_WINDOW_INVALID")
    if (type(activation["collector_uid"]) is not int or type(activation["finalizer_uid"]) is not int
        or activation["collector_uid"] <= 0 or activation["finalizer_uid"] <= 0
        or activation["collector_uid"] == activation["finalizer_uid"]):
        raise ValueError("ACTIVATION_UID_INVALID")
    if (not Path(activation["archive_path"]).is_absolute()
        or not Path(activation["journal_path"]).is_absolute()
        or not isinstance(activation["bundle_sha256"],str)
        or len(activation["bundle_sha256"]) != 64
        or any(ch not in "0123456789abcdef" for ch in activation["bundle_sha256"])):
        raise ValueError("ACTIVATION_PATH_OR_HASH_INVALID")
    return activation,start,end


def verify_bundle(bundle):
    """Ensure the running source tree exactly matches the root-approved tar."""
    root = Path(__file__).resolve().parents[2]
    with tarfile.open(bundle,mode="r:") as tar:
        names = set()
        for member in tar:
            if (not member.isfile() or member.name in names or member.name.startswith("/")
                or ".." in Path(member.name).parts or member.size > 2_000_000):
                raise ValueError("BUNDLE_MEMBER_INVALID")
            names.add(member.name)
            target = root/member.name
            if target.is_symlink() or not target.is_file() or target.stat().st_uid != 0 or target.stat().st_mode & 0o022 or hashlib.sha256(tar.extractfile(member).read()).digest() != hashlib.sha256(target.read_bytes()).digest():
                raise ValueError("RUNNING_ARTIFACT_MISMATCH")
        if ("octobot/ai_strategy_lab/v13_btc_forward_runtime_v2_2.py" not in names
            or "octobot/ai_strategy_lab/v13_btc_research_v2.py" not in names):
            raise ValueError("BUNDLE_REQUIRED_ARTIFACT_MISSING")


def preflight(args):
    if not args.activation or not args.bundle:
        raise ValueError("FORWARD_APPROVAL_MISSING")
    activation,start,end = _read_root_activation(args.activation)
    if hashlib.sha256(args.bundle.read_bytes()).hexdigest() != activation["bundle_sha256"]:
        raise ValueError("BUNDLE_HASH_MISMATCH")
    verify_bundle(args.bundle)
    if args.archive != Path(activation["archive_path"]) or args.journal != Path(activation["journal_path"]):
        raise ValueError("APPROVED_PATH_MISMATCH")
    if args.mode in ("collect","finalize","mature"):
        slot = p.slot_time(args.slot)
        lower = start+dt.timedelta(days=1) if args.mode == "mature" else start
        upper = end+dt.timedelta(days=1) if args.mode in ("mature","collect") else end
        if not lower <= slot <= upper:
            raise ValueError("SLOT_OUTSIDE_APPROVED_WINDOW")
        today = dt.datetime.now(p.UTC).date()
        if ((args.mode == "collect" and slot.date() != today)
            or (args.mode == "mature" and slot.date() != today)
            or (args.mode == "finalize" and slot.date() > today)):
            raise ValueError("SLOT_DATE_INVALID")
        require_synchronized_clock()
    elif args.mode == "recover":
        require_synchronized_clock()
    role_uid = activation["collector_uid"] if args.mode == "collect" else activation["finalizer_uid"]
    if os.geteuid() != role_uid:
        raise ValueError("ROLE_UID_MISMATCH")
    if args.mode in ("collect","finalize","recover","mature"):
        root = args.archive
        for item in (root,root/"raw",root/"receipts",root/"attestations"):
            info = item.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != activation["collector_uid"] or info.st_mode & 0o022:
                raise ValueError("ARCHIVE_OWNERSHIP_INVALID")
    if args.mode in ("finalize","recover","mature","status"):
        parent = args.journal.parent.lstat()
        if (not stat.S_ISDIR(parent.st_mode) or parent.st_uid != activation["finalizer_uid"]
            or parent.st_mode & 0o022):
            raise ValueError("JOURNAL_OWNERSHIP_INVALID")
    return activation,start,end


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode",choices=("collect","finalize","recover","mature","status"))
    parser.add_argument("--archive",type=Path)
    parser.add_argument("--journal",type=Path)
    parser.add_argument("--slot")
    parser.add_argument("--activation",type=Path)
    parser.add_argument("--bundle",type=Path)
    args = parser.parse_args()
    if args.slot == "today":
        args.slot = dt.datetime.now(p.UTC).replace(hour=0,minute=10,second=0,microsecond=0).isoformat()
    # A root-owned activation file is deliberately absent until human approval.
    activation,start,end = preflight(args)
    if args.mode == "collect":
        result = collect_once(args.archive,args.slot)
    elif args.mode == "finalize":
        result = finalize_from_archive(args.journal,args.archive,args.slot)
    elif args.mode == "recover":
        current = dt.datetime.now(p.UTC)
        result = {"checked_slots":0,"new_missing_slots":0,"new_outcomes":0,"last_slot":None}
        for day in range(180):
            slot = start+dt.timedelta(days=day)
            if slot > end or current < slot+dt.timedelta(minutes=10):
                break
            created,decision = finalize_from_archive(args.journal,args.archive,slot.isoformat())
            result["checked_slots"] += 1
            result["new_missing_slots"] += int(created and decision["status"] == "MISSING")
            result["last_slot"] = slot.isoformat()
        for day in range(1,181):
            slot = start+dt.timedelta(days=day)
            if current < slot+dt.timedelta(minutes=10):
                break
            try:
                matured = mature_previous(args.journal,args.archive,slot.isoformat())
            except ValueError as exc:
                if str(exc) == "OUTCOME_SOURCE_MISSING":
                    continue
                raise
            result["new_outcomes"] += int(matured)
    elif args.mode == "mature":
        result = {"outcome_matured":mature_previous(args.journal,args.archive,args.slot)}
    else:
        result = status_only(args.journal)
    print(json.dumps(result,sort_keys=True))


if __name__ == "__main__":
    main()
