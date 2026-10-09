"""Offline paired directional-score evaluator, sealed until preregistered review.
Author implementation; no profit, exchange-admissibility or promotion claim.
Card work-card-ef81ac4d-1ff5-4693-94ce-98228018e69a.
"""
import argparse
import datetime as dt
import importlib.util
import math
from pathlib import Path
import random
import sqlite3

spec=importlib.util.spec_from_file_location('shadow_custody',Path(__file__).with_name('qwen_shadow_custody_v2.py'))
c=importlib.util.module_from_spec(spec);spec.loader.exec_module(c)
p=c.p


def percentile(values, quantile):
    ordered=sorted(values);position=(len(ordered)-1)*quantile;left=int(position);right=min(left+1,len(ordered)-1)
    return ordered[left]+(ordered[right]-ordered[left])*(position-left)


def bootstrap(calendar):
    if len(calendar)!=180:raise ValueError('BOOTSTRAP_CALENDAR_INVALID')
    rng=random.Random(13120);replicas=[]
    for _ in range(10000):
        indices=[(start+j)%180 for start in [rng.randrange(180) for _ in range(13)] for j in range(14)][:180]
        sample=[calendar[i] for i in indices if calendar[i] is not None]
        if not sample:raise ValueError('EMPTY_BOOTSTRAP_REPLICA')
        replicas.append(math.fsum(sample)/len(sample))
    return [percentile(replicas,.025),percentile(replicas,.975)]


def evaluate(manifest, journal, outcomes, archive, *, clock=p.now):
    # Gate precedes ANY reading of decisions or outcomes, including missing storage.
    p.check_manifest(manifest)
    if clock()<p.utc(manifest['review_at']):raise ValueError('PERFORMANCE_SEALED')
    original,records=c.sources(journal,manifest)
    slots=[(p.utc(manifest['start_slot_utc'])+i*c.DAY).isoformat() for i in range(180)]
    indexed={(r['slot_utc'],r['arm']):r for r in records}
    if set(original)!=set(slots) or len(records)!=360:raise ValueError('UNRECORDED_SLOTS')
    with sqlite3.connect(Path(journal).resolve().as_uri()+'?mode=ro',uri=True) as db:
        conflicts=db.execute("SELECT count(*) FROM events WHERE kind='CONFLICT'").fetchone()[0]
        if conflicts:raise ValueError('UNRESOLVED_CONFLICT')
        provenance={s:p.strict_json(raw) for s,raw in db.execute('SELECT slot,receipt FROM provenance')}
    for slot,source in original.items():
        if 'causal_bars' not in source:continue
        receipt,bars=c.capture(archive,slot,manifest)
        if provenance.get(slot)!=receipt or p.observation(bars,slot,receipt['received_at'],manifest)!=source:raise ValueError('SOURCE_DERIVATION_INVALID')
        if any(p.utc(indexed[(slot,a)]['recorded_at'])<p.utc(receipt['received_at']) for a in ('baseline','qwen')):raise ValueError('NONCAUSAL_RECORD')
    with sqlite3.connect(Path(outcomes).resolve().as_uri()+'?mode=ro',uri=True) as db:
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or p.strict_json(db.execute('SELECT manifest FROM metadata').fetchone()[0])!=manifest:raise ValueError('OUTCOMES_INVALID')
        rows=db.execute('SELECT slot,payload,previous_hash,record_hash FROM outcomes ORDER BY rowid').fetchall()
    previous='0'*64;returns={}
    for slot,raw,parent,digest in rows:
        value=p.strict_json(raw);source=original.get(slot)
        if (not source or slot in returns or parent!=previous or digest!=p.sha({'payload':value,'previous_hash':parent}) or
            value['slot_utc']!=slot or value['lineage']!=manifest['lineage'] or value['observation_id']!=source['observation_id'] or
            p.utc(value['recorded_at'])<p.utc(slot)+c.DAY or p.utc(value['recorded_at'])>clock()):raise ValueError('OUTCOME_CHAIN_INVALID')
        previous=digest
        if value['status']=='MISSING':returns[slot]=None;continue
        if value['status']!='AVAILABLE' or p.utc(value['recorded_at'])>p.utc(slot)+c.DAY+dt.timedelta(minutes=20):raise ValueError('OUTCOME_TIME_INVALID')
        receipt,bars=c.capture(archive,(p.utc(slot)+c.DAY).isoformat(),manifest)
        nexts=[r[1] for r in bars if r[0]==source['causal_bars'][-1][0]+p.DAY_MS]
        from decimal import Decimal
        if (len(nexts)!=1 or value['receipt']!=receipt or p.utc(receipt['received_at'])>p.utc(value['recorded_at']) or
            value['origin_close']!=source['causal_bars'][-1][1] or Decimal(value['next_close'])!=Decimal(str(nexts[0]))):raise ValueError('OUTCOME_DERIVATION_INVALID')
        returns[slot]=math.log(float(value['next_close'])/float(value['origin_close']))
    if set(returns)!=set(slots):raise ValueError('OUTCOME_REGISTRATION_INCOMPLETE')
    counts={a:{'valid_mature':0,'LONG':0,'SHORT':0,'NO_PROPOSAL':0,'missing_reasons':{},'directional_hits':0} for a in ('baseline','qwen')}
    paired=[];arm_scores={a:[] for a in counts};regimes={'positive':[],'negative':[],'zero':[]}
    for slot in slots:
        score={};ret=returns[slot]
        for arm in counts:
            result=indexed[(slot,arm)]['result'];decision=result['decision'];stats=counts[arm]
            if decision=='MISSING':
                for reason in result['reason_codes']:stats['missing_reasons'][reason]=stats['missing_reasons'].get(reason,0)+1
            elif ret is not None:
                stats['valid_mature']+=1;stats[decision]+=1;sign={'LONG':1,'SHORT':-1,'NO_PROPOSAL':0}[decision]
                score[arm]=sign*ret;arm_scores[arm].append(score[arm])
                if sign and sign*ret>0:stats['directional_hits']+=1
        difference=score['qwen']-score['baseline'] if len(score)==2 else None;paired.append(difference)
        if difference is not None:
            source=original[slot];from decimal import Decimal
            r120=Decimal(source['causal_bars'][-1][1])/Decimal(source['causal_bars'][0][1])-1
            regimes['positive' if r120>0 else 'negative' if r120<0 else 'zero'].append(difference)
    def mean(v):
        valid=[x for x in v if x is not None]
        return math.fsum(valid)/len(valid) if valid else None
    joint=sum(x is not None for x in paired)
    interval=bootstrap(paired) if joint else None
    sufficient=joint>=170 and all(v['LONG']+v['SHORT']>=60 and v['LONG']>=20 and v['SHORT']>=20 for v in counts.values())
    status='INSUFFICIENT' if not sufficient else 'CANDIDATE_EVIDENCE_PASS' if mean(paired)>0 and interval[0]>0 else 'NO_DIRECTIONAL_EVIDENCE'
    for arm,stats in counts.items():
        directional=stats['LONG']+stats['SHORT'];stats['coverage_denominator']=180
        stats['directional_hit_rate']=stats['directional_hits']/directional if directional else None
        stats['mean_score']=mean(arm_scores[arm])
    return {'scope':p.SCOPE,'lineage':manifest['lineage'],'review_status':status,'joint_valid_mature':joint,'coverage_denominator':180,
            'paired_mean':mean(paired),'paired_ci_95':interval,'arms':counts,
            'calendar_blocks':[{'joint':sum(x is not None for x in paired[i:i+60]),'mean':mean(paired[i:i+60])} for i in (0,60,120)],
            'regimes':{k:{'joint':len(v),'mean':mean(v)} for k,v in regimes.items()},
            'economic_pnl':None,'human_review_required':True,'execution_approved':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--journal',type=Path,required=True);parser.add_argument('--outcomes',type=Path,required=True);parser.add_argument('--archive',type=Path,required=True);args=parser.parse_args()
    print(p.canonical(evaluate(p.strict_json(args.manifest.read_bytes()),args.journal,args.outcomes,args.archive)).decode())
