"""One-date read-only receipt check. No network, SQLite or trading interface."""
import argparse
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import stat
import tempfile


def read(path,owner,maximum):
    with os.fdopen(os.open(path,os.O_RDONLY|os.O_NOFOLLOW),'rb') as stream:
        info=os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid!=owner or info.st_mode&0o022 or info.st_size>maximum:
            raise ValueError('check_input_custody')
        return stream.read(maximum+1)


def assess(config,now):
    result=dict(schema=1,scope='READ_ONLY_FIRST_DISCRETE_SLOT_CHECK',checked_at=now.isoformat(),issues=[],
                status='REVIEW_REQUIRED',execution_authorized=False)
    try:
        raw=read(config['grant'],0,200000)
        if hashlib.sha256(raw).hexdigest()!=config['grant_sha256']:raise ValueError('grant_hash')
        grant=json.loads(raw);boundary=dt.datetime.fromisoformat(grant['boundary'])
        value=json.loads(read(config['projection'],30934,32*1024*1024))
        revision=value['discrete_revision'];generated=dt.datetime.fromisoformat(value['generated_at'])
        if not 0<=(now-generated).total_seconds()<300:raise ValueError('projection_stale_or_future')
        if (revision['version']!=grant['version'] or revision['boundary']!=grant['boundary']
                or revision['account_ids']!=grant['account_ids'] or not revision['history_preserved']):
            raise ValueError('revision_identity')
        if now<boundary+dt.timedelta(seconds=120):
            result['status']='WAITING_FOR_NATURAL_SLOT';return result
        slots=[s for s in value['slots'] if s['slot']==grant['boundary']]
        if len(slots)!=1:raise ValueError('first_slot_missing')
        slot=slots[0];detail=slot['detail'];result['slot_status']=slot['status']
        if slot['status'] not in ('EXECUTED','OBSERVED_NO_FILL'):raise ValueError('first_slot_not_completed')
        if detail.get('policy_revision')!=grant['version']:raise ValueError('first_slot_wrong_version')
        gap=detail.get('risk_gap')
        if (detail.get('risk_matched') is not True or isinstance(gap,bool) or not isinstance(gap,(int,float))
                or not math.isfinite(gap) or not 0<=gap<=.02):raise ValueError('first_slot_risk_unqualified')
        if value['funding_debt'] is not None or value['valuation_gap'] is not None:raise ValueError('coverage_incomplete')
        if value['health']['status']=='BLOCKED':raise ValueError('runner_blocked')
        result.update(status='QUALIFIED_NATURAL_SLOT',risk_gap=gap,legacy=revision['legacy'],current=revision['current'])
    except (OSError,ValueError,TypeError,KeyError,OverflowError) as error:
        result['issues'].append(str(error))
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--config',type=Path,required=True);args=parser.parse_args()
    config=json.loads(read(args.config,0,200000));value=assess(config,dt.datetime.now(dt.timezone.utc))
    destination=Path(config['output']);destination.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(prefix='.check-',dir=destination.parent)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    os.replace(name,destination)
    print(json.dumps(value))


if __name__=='__main__':main()
