"""Manual exact-bundle gate and local worker. Never generates its own approval.

No service is registered by this module. A future operator must supply a
root-owned receipt and initialize a new namespace explicitly. Existing
accounts, credentials, networking and grants are not exposed here.
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import time

from . import engine, receipts
from .runner import Pair
from .source import canonical, strict, digest, NS


def root_document(path):
    fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK)
    try:
        s=os.fstat(fd)
        if not stat.S_ISREG(s.st_mode) or s.st_uid!=0 or s.st_mode&0o022 or s.st_size>65536:
            raise ValueError('root_owned_bounded_read_only_document_required')
        raw=os.read(fd,65537)
        if len(raw)>65536:raise ValueError('root_document_size')
        return strict(raw)
    finally:os.close(fd)


def authority(config,*,initialize=False,now_ns=None):
    receipt=root_document(config['activation'])
    if (receipt.get('scope')!='AUTHORIZED_SYNTHETIC_PAPER_PAIR' or
            receipt.get('paper_pair_activation_authorized') is not True or
            receipt.get('real_orders') is not False or receipt.get('exchange_credentials') is not False or
            receipt.get('operational_grants') is not False or
            receipt.get('protocol_sha256')!=engine.PROTOCOL_SHA or
            not isinstance(receipt.get('operator_acceptance_reference'),str) or
            not receipt['operator_acceptance_reference'].strip()):
        raise ValueError('explicit_operator_receipt_required')
    t0=receipt.get('t0_ns');t1=receipt.get('t1_ns')
    now=time.time_ns() if now_ns is None else now_ns
    if type(t0) is not int or t0%(86400*NS) or t1!=t0+90*86400*NS or (initialize and t0<=now):
        raise ValueError('future_common_horizon_required')
    directory=Path(config['directory']).resolve()
    if directory!=Path(receipt.get('directory','')).resolve():raise ValueError('activation_destination_mismatch')
    if set(receipt.get('account_ids',[]))!={'btc-intraday-short-control-v1','btc-intraday-long-short-v1'}:
        raise ValueError('paired_account_ids')
    runtime=Path(__file__).parent
    expected={p.name for p in runtime.glob('*.py')}|{'protocol.json'}
    if set(receipt.get('code_pins',{}))!=expected:raise ValueError('complete_runtime_pin_set_required')
    for name,sha in receipt['code_pins'].items():
        if hashlib.sha256((runtime/name).read_bytes()).hexdigest()!=sha:raise ValueError('runtime_pin_mismatch')
    for source in (Path(config['source']).resolve(),Path(config['book']).resolve().parent):
        if directory.is_relative_to(source) or source.is_relative_to(directory):
            raise ValueError('source_destination_overlap')
    return receipt


def atomic(path,value):
    temporary=path.with_suffix('.pending')
    with open(temporary,'wb') as f:f.write(canonical(value)+b'\n');f.flush();os.fsync(f.fileno())
    os.replace(temporary,path)
    fd=os.open(path.parent,os.O_RDONLY|os.O_DIRECTORY)
    try:os.fsync(fd)
    finally:os.close(fd)


def run(config,*,initialize=False):
    activation=authority(config,initialize=initialize)
    pair=Pair(config['directory'],activation['t0_ns'],digest(activation),
              initialize=initialize,activation=activation)
    try:
        pair.drain()
        reader=receipts.BookReader(config['book'],pair.clock)
        last_projection=0
        while True:
            pair.poll_sources(config['source'],reader)
            if config.get('control'):
                control=Path(config['control'])
                if control.is_symlink() or control.stat().st_uid!=0 or control.stat().st_mode&0o022:
                    raise ValueError('root_control_directory_required')
                if (control/'close.json').exists():pair.administrative_file(control/'close.json')
            now=pair.clock.sample()['utc_ns']
            slot=now//(300*NS)*(300*NS)
            if activation['t0_ns']<=slot<=activation['t1_ns'] and now>=slot+2*NS:
                pair.observe_grid(slot)
            if now-last_projection>=5*NS:
                atomic(pair.path/'projection.json',pair.status());last_projection=now
            time.sleep(.05)
    except BaseException as error:
        try:atomic(pair.path/'projection.json',dict(status='BLOCKED',reason=type(error).__name__,no_real_orders=True))
        finally:pair.close()
        raise


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',required=True);p.add_argument('--initialize',action='store_true')
    args=p.parse_args();os.umask(0o027)
    run(root_document(args.config),initialize=args.initialize)
