"""ABC lifecycle controller. No credentials, downloads or implicit activation.

Card work-card-56a72d4d-956c-47f1-b7b5-47bbc74546a1.
Deadline is an explicit deployment input; this module does not approve its value.
"""
import json
import os
import sqlite3
import tempfile
import datetime as dt
from pathlib import Path
try:
    from . import v13_dynamic_consumer as consumer
except ImportError:
    import v13_dynamic_consumer as consumer


class Service:
    def __init__(self, executor, status_path, *, intent_validity_seconds):
        if type(intent_validity_seconds) is not int or intent_validity_seconds <= 0:
            raise ValueError('explicit_intent_validity_required')
        self.executor=executor;self.path=Path(status_path);self.validity=intent_validity_seconds
        if self.path.is_symlink():raise ValueError('status_symlink')

    def cycle(self):
        now=consumer.utc_now();result=dict(schema=1,at=now,status='WAITING',orders_authorized=False)
        try:
            readiness=self.executor.readiness()
            if readiness.get('execution_ready') is not True or readiness.get('blockers'):
                result.update(status='BLOCKED',reasons=readiness.get('blockers') or ['execution_not_authorized'])
            else:
                row=self.executor.intents.db.execute('SELECT id,payload,sealed_at FROM intents ORDER BY rowid DESC LIMIT 1').fetchone()
                if row is None:result.update(reasons=['no_intent'])
                elif row[2] is None:result.update(status='BLOCKED',reasons=['unsealed_intent_requires_review'])
                else:
                    stored=self.executor.intents._decode(row)
                    slot=consumer.cash.selector.timestamp(stored['derived']['selection']['slot'])
                    stamp=consumer.cash.selector.timestamp(now)
                    consumed=False;account_exists=False
                    if self.executor.ledger_path.exists():
                        db=sqlite3.connect(self.executor.ledger_path.absolute().as_uri()+'?mode=ro',uri=True)
                        try:
                            consumed=db.execute('SELECT 1 FROM batches WHERE id=?',(row[0],)).fetchone() is not None
                            account_exists=db.execute('SELECT 1 FROM batches LIMIT 1').fetchone() is not None
                        finally:db.close()
                    if consumed:
                        self.executor.observe();result.update(status='OBSERVED',intent_id=row[0])
                    elif not 0 <= (stamp-slot).total_seconds() < self.validity:
                        if account_exists:self.executor.observe()
                        result.update(status='EXPIRED',intent_id=row[0],observation_updated=account_exists,reasons=['intent_outside_execution_window'])
                    else:
                        self.executor.consume(row[0],valid_until=(slot+dt.timedelta(seconds=self.validity)).isoformat());result.update(status='COMMITTED',intent_id=row[0])
        except consumer.AdmissionDenied as exc:result.update(status='BLOCKED',reasons=exc.reasons)
        except (ValueError,sqlite3.Error,OSError,KeyError,TypeError):
            # Avoid leaking filesystem paths or raw data through UI diagnostics.
            result.update(status='ERROR',reasons=['cycle_failed_no_success_claim'])
        with tempfile.NamedTemporaryFile(mode='w',dir=self.path.parent,prefix='.abc-status-',delete=False) as stream:
            temporary=Path(stream.name)
            json.dump(result,stream,allow_nan=False);stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,self.path)
        descriptor=os.open(self.path.parent,os.O_DIRECTORY)
        try:os.fsync(descriptor)
        finally:os.close(descriptor)
        return result


def main(argv=None):
    """Explicit, root-pinned configuration; never installs/enables a service."""
    import argparse
    import hashlib
    import time
    try:
        from . import v13_dynamic_intent as intents
    except ImportError:
        import v13_dynamic_intent as intents
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config',required=True)
    parser.add_argument('--config-sha256',required=True)
    parser.add_argument('--once',action='store_true')
    parser.add_argument('--close-command')
    parser.add_argument('--close-command-sha256')
    args=parser.parse_args(argv)
    path=Path(args.config)
    consumer.data.capture.safe_path(path,0)
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=args.config_sha256:raise ValueError('service_config_pin')
    config=json.loads(raw)
    if config.get('scope')!='ABC_SERVICE_CONFIGURATION_V1':raise ValueError('service_config_scope')
    if type(config['executor_uid']) is not int or os.geteuid()!=config['executor_uid'] or os.geteuid()==0:
        raise ValueError('dedicated_executor_required')
    interval=config['poll_seconds']
    if type(interval) is not int or not 1<=interval<=60:raise ValueError('poll_interval')
    for key,uid in [('intents',config['producer_uid']),('forward_path',config['forward_uid'])]:
        if uid==config['executor_uid']:raise ValueError('separate_writer_required')
        consumer.data.store_path(config[key],uid)
    for key in ('ledger_path','status_path'):
        consumer.data.capture.safe_path(Path(config[key]).parent,config['executor_uid'],directory=True)
    if len({str(Path(config[k]).resolve()) for k in ('intents','forward_path','ledger_path','status_path')})!=4:
        raise ValueError('separate_stores_required')
    store=intents.IntentStore(config['intents'],read_only=True)
    try:
        kwargs={k:config[k] for k in ('repo','approval_path','approval_sha256','archive','activation','ledger_path',
                                     'forward_path','forward_uid','calendar_path','calendar_sha256')}
        executor=consumer.Consumer(intents=store,**kwargs)
        if args.close_command or args.close_command_sha256:
            if not args.close_command or not args.close_command_sha256:raise ValueError('command_and_pin_required')
            executor.close_all(args.close_command,args.close_command_sha256);return 0
        runner=Service(executor,config['status_path'],intent_validity_seconds=config['intent_validity_seconds'])
        while True:
            runner.cycle()
            if args.once:return 0
            time.sleep(interval)
    finally:store.close()


if __name__=='__main__':
    raise SystemExit(main())
