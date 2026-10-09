"""Periodic deterministic ABC producer; no execution authority or network."""
import datetime as dt
import sqlite3
try:
    from . import v13_dynamic_data as data
    from . import v13_dynamic_forward as forward
except ImportError:
    import v13_dynamic_data as data
    import v13_dynamic_forward as forward


class Sources:
    """Bindings and ownership must come from the root-pinned deployment config."""
    def __init__(self,config):self.config=config

    def read(self,slot):
        c=self.config;as_of=data.capture.utc(slot)
        data.store_path(c['forward_path'],c['forward_uid'])
        data.store_path(c['qualification_archive'],c['qualification_uid'])
        records=data.read_warmup(c['warmup_path'],c['warmup_report_sha256'])
        start=data.capture.utc(c['qualification_start'])
        for day in range(int(start),int(min(start+14*86400,as_of//86400*86400+1)),86400):
            records.extend(data.read_day(c['qualification_archive'],data.capture.load_plan(c['repo']),start,
                                        c['qualification_binding'],day,as_of,kinds=('daily',)))
        source=forward.ForwardArchive(c['forward_path'],c['repo'])
        try:
            days=[r[0] for r in source.db.execute("SELECT DISTINCT slot FROM jobs WHERE kind='kucoin_metadata' AND received<=? ORDER BY slot",(as_of,))]
            for day in days:records.extend(source.read(day,as_of,kinds=('daily',)))
        finally:source.close()
        return data.bridge_daily(records,slot=slot)['records']


class Producer:
    def __init__(self,store,sources,*,start,lineage,validity_seconds):
        data.selector.slot_index(start,start)
        if type(validity_seconds) is not int or validity_seconds<=0:raise ValueError('explicit_validity_required')
        self.store=store;self.sources=sources;self.start=start;self.lineage=lineage;self.validity=validity_seconds

    def step(self,now):
        origin=data.selector.timestamp(self.start);at=data.selector.timestamp(now)
        days=(at.date()-origin.date()).days
        slot=origin+dt.timedelta(days=days)
        if days<0 or days%7 or not 0<=(at-slot).total_seconds()<self.validity:return {'status':'OUTSIDE_SLOT'}
        last=self.store.db.execute('SELECT id,payload,sealed_at FROM intents ORDER BY rowid DESC LIMIT 1').fetchone()
        if last:
            old=self.store._decode(last)['derived']['selection']
            if old['start']!=self.start or old['lineage']!=self.lineage:raise ValueError('producer_identity_changed')
            if last[2] is None:raise ValueError('unsealed_intent_requires_review')
            if data.selector.timestamp(old['slot'])==slot:return {'status':'ALREADY_SEALED','id':last[0]}
        elif days!=0:raise ValueError('initial_slot_missing')
        result=self.store.record(self.sources.read(slot.isoformat()),slot=slot.isoformat(),start=self.start,lineage=self.lineage)
        return dict(status='SEALED',**result)


def main(argv=None):
    import argparse
    import json
    import os
    import time
    from pathlib import Path
    try:
        from . import v13_dynamic_intent as intents
    except ImportError:
        import v13_dynamic_intent as intents
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True);parser.add_argument('--config-sha256',required=True)
    parser.add_argument('--once',action='store_true');args=parser.parse_args(argv)
    data.capture.safe_path(args.config,0);raw=Path(args.config).read_bytes()
    if data.capture.sha(raw)!=args.config_sha256:raise ValueError('producer_config_pin')
    config=json.loads(raw)
    if config.get('scope')!='ABC_PRODUCER_CONFIGURATION_V1':raise ValueError('producer_config_scope')
    if type(config['producer_uid']) is not int or config['producer_uid']==0 or os.geteuid()!=config['producer_uid']:
        raise ValueError('dedicated_producer_required')
    if config['producer_uid'] in (config['forward_uid'],config['executor_uid']):raise ValueError('separate_writer_required')
    if type(config['poll_seconds']) is not int or not 1<=config['poll_seconds']<=30:raise ValueError('poll_interval')
    data.store_path(config['intents'],config['producer_uid'])
    store=intents.IntentStore(config['intents'])
    try:
        producer=Producer(store,Sources(config),start=config['start'],lineage=config['lineage'],validity_seconds=config['intent_validity_seconds'])
        while True:
            producer.step(dt.datetime.now(dt.timezone.utc).isoformat())
            if args.once:return 0
            time.sleep(config['poll_seconds'])
    finally:store.close()


if __name__=='__main__':raise SystemExit(main())
