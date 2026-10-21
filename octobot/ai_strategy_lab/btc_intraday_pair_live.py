"""Authorized deployment wrapper; the qualified strategy package stays unchanged.

work-card-8fd80afc-9599-40ca-abf9-68d2d2d082a9. Local projections only,
no network, credential, existing-account or web command channel.
"""
import argparse
import hashlib
import os
from pathlib import Path
import time

from intraday_pair import receipts
from intraday_pair.runner import Pair
from intraday_pair.service import authority, atomic, root_document
from intraday_pair.source import NS, digest, strict

SCOPE = 'SYNTHETIC_RESEARCH_PAPER_NOT_KUCOIN_ORDER_ADMISSIBILITY'


def projection(pair):
    """Bounded observations from this writer's own databases, never a source scan."""
    now = pair.clock.sample()['utc_ns']
    accounts = {}
    for name, e in pair.engines.items():
        v = e.view(now)
        s = e.s
        accounts[name] = dict(account=e.account, scenario='stress' if e.stress_mode else 'primary',
            cursor=s['last_input_seq'], input_sha=s['last_input_sha'], equity=e.equity(),
            q=s['q'], fills=s['fills'], fees=s['fees'], funding=s['funding'], realized=s['realized'],
            reason=s['reason'], complete=e.accounting_complete(),
            integrity_halt=s['integrity_halt'], drawdown_halt=s['drawdown_halt'],
            daily_halt=bool(s['daily'] and s['daily']['halt']),
            last_market_ns=s['last_market_received'], last_book_ns=s['last_book_ns'],
            warmup_rows=v['warmup_rows'], slots=[dict(slot_ns=r['slot_ns'], status=r['status'],
                feature=r['detail'].get('feature')) for r in v['slots']],
            trades=[dict(at_ns=r['at_ns'], quantity=r['quantity'], price=r['price'], fee=r['fee'],
                realized=r['realized'], kind=r['detail']['kind'], before=r['detail']['before'],
                after=r['detail']['after'], equity_impact=r['detail']['equity_impact']) for r in v['fills']],
            points=[dict(at_ns=r[0], equity=r[1], complete=bool(r[3])) for r in v['equity']])
    # Read completed before heartbeat: concurrent readers may validate against
    # their read completion, never against the beginning of a monitor sample.
    checked = pair.clock.sample()['utc_ns']
    phase = ('PRESTART' if checked < pair.t0 else 'COMPLETED' if checked >= pair.t0+90*86400*NS
             else 'WARMUP' if min(accounts[k]['warmup_rows'] for k in
                                   ('control-primary', 'candidate-primary')) < 289 else 'OBSERVING')
    return dict(schema=1, scope=SCOPE, no_real_orders=True, mode=pair.mode,
        active_account=pair.authorized, protocol_sha=pair.identity['protocol_sha'],
        activation_sha=pair.identity['bundle_sha'], checked_at_ns=checked,
        t0_ns=pair.t0, t1_ns=pair.t0+90*86400*NS, phase=phase,
        input_seq=pair.seq, input_sha=pair.previous if pair.seq else None, arms=accounts,
        real_min_quantity='UNKNOWN', real_min_notional='UNKNOWN', scientific_validity='UNASSESSED')


def authorized(config, initialize=False):
    approval = authority(config, initialize=initialize)
    if approval.get('live_wrapper_sha256') != hashlib.sha256(Path(__file__).read_bytes()).hexdigest():
        raise ValueError('exact_live_wrapper_required')
    out = Path(config['projection'])
    if out.is_symlink() or out.parent.is_symlink() or not out.parent.is_dir():
        raise ValueError('projection_destination')
    state = Path(config['directory']).resolve()
    resolved = out.resolve()
    for private in (state, Path(config['source']).resolve(), Path(config['book']).resolve().parent):
        if resolved.is_relative_to(private) or private.is_relative_to(resolved.parent):
            raise ValueError('projection_source_or_state_overlap')
    if out.parent.stat().st_uid != os.geteuid() or out.parent.stat().st_mode & 0o022:
        raise ValueError('projection_custody')
    return approval


def run(config, initialize=False):
    approval = authorized(config, initialize)
    pair = Pair(config['directory'], approval['t0_ns'], digest(approval),
                initialize=initialize, activation=approval)
    try:
        pair.drain()
        atomic(Path(config['projection']), projection(pair))
        if initialize:
            return
        reader = receipts.BookReader(config['book'], pair.clock)
        last_projection = 0
        last_grid = None
        while True:
            pair.poll_sources(config['source'], reader)
            control = Path(config['control'])
            if control.is_symlink() or control.stat().st_uid != 0 or control.stat().st_mode & 0o022:
                raise ValueError('root_control_directory_required')
            if (control/'close.json').exists():
                pair.administrative_file(control/'close.json')
            now = pair.clock.sample()['utc_ns']
            slot = now//(300*NS)*(300*NS)
            if pair.t0 <= slot <= approval['t1_ns'] and now >= slot+2*NS and slot != last_grid:
                pair.observe_grid(slot)
                last_grid = slot
            if now-last_projection >= 5*NS:
                atomic(Path(config['projection']), projection(pair))
                last_projection = now
            time.sleep(.05)
    except BaseException as error:
        atomic(Path(config['projection']), dict(schema=1, scope=SCOPE, no_real_orders=True,
            checked_at_ns=time.time_ns(), phase='BLOCKED', error_code=type(error).__name__))
        raise
    finally:
        pair.close()


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', required=True)
    p.add_argument('--initialize', action='store_true')
    args = p.parse_args()
    os.umask(0o027)
    run(root_document(args.config), initialize=args.initialize)
