"""Exact I/O continuation plus one equivalent valuation-plan optimization.

Existing activation and I/O custody checks remain mandatory. No initialization,
source rewrite, deadline extension or change to the frozen trading engine.
"""
import argparse
import hashlib
import os
from pathlib import Path
import time

import btc_intraday_pair_live as previous
from btc_intraday_pair_io import RecoveringBookReader, append_event
from btc_intraday_pair_latency import FastValuationPair
from intraday_pair.service import atomic, root_document
from intraday_pair.source import NS, digest


def authorized(config):
    approval = previous.authorized(config)
    predecessor = Path(config['io_predecessor_configuration'])
    prior = root_document(predecessor)
    receipt = root_document(config['latency_continuation'])
    expected = {'btc_intraday_pair_latency.py', 'btc_intraday_pair_latency_live.py'}
    if (receipt.get('scope') != 'AUTHORIZED_PAPER_PAIR_LATENCY_CONTINUATION'
            or receipt.get('prior_activation_sha256') != digest(approval)
            or receipt.get('predecessor_configuration_sha256') != hashlib.sha256(predecessor.read_bytes()).hexdigest()
            or receipt.get('directory') != config['directory']
            or receipt.get('strategy_unchanged') is not True
            or receipt.get('state_reset_allowed') is not False
            or any(receipt.get(k) is not False for k in ('real_orders', 'exchange_credentials', 'operational_grants'))
            or not isinstance(receipt.get('operator_acceptance_reference'), str)
            or not receipt['operator_acceptance_reference'].strip()
            or set(receipt.get('runtime_files', {})) != expected
            or {k: v for k, v in config.items() if k not in ('io_predecessor_configuration', 'latency_continuation')} != prior):
        raise ValueError('exact_latency_continuation_required')
    for name, sha in receipt['runtime_files'].items():
        if hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() != sha:
            raise ValueError('latency_runtime_pin_mismatch')
    return approval


def run(config):
    approval = authorized(config)
    pair = FastValuationPair(config['directory'], approval['t0_ns'], digest(approval), activation=approval)
    try:
        pair.drain()
        atomic(Path(config['projection']), previous.projection(pair))
        reader = RecoveringBookReader(config['book'], pair.clock,
            lambda event: append_event(config['source_io_log'], event))
        last_projection = 0
        last_grid = None
        while True:
            pair.poll_sources(config['source'], reader)
            control = Path(config['control'])
            if control.is_symlink() or control.stat().st_uid != 0 or control.stat().st_mode & 0o022:
                raise ValueError('root_control_directory_required')
            if (control / 'close.json').exists():
                pair.administrative_file(control / 'close.json')
            now = pair.clock.sample()['utc_ns']
            slot = now // (300 * NS) * (300 * NS)
            if pair.t0 <= slot <= approval['t1_ns'] and now >= slot + 2 * NS and slot != last_grid:
                pair.observe_grid(slot)
                last_grid = slot
            if now - last_projection >= 5 * NS:
                atomic(Path(config['projection']), previous.projection(pair, reader))
                last_projection = now
            time.sleep(.05)
    except BaseException as error:
        atomic(Path(config['projection']), dict(schema=1, scope=previous.SCOPE, no_real_orders=True,
            checked_at_ns=time.time_ns(), phase='BLOCKED', error_code=type(error).__name__))
        raise
    finally:
        pair.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    os.umask(0o027)
    run(root_document(args.config))
