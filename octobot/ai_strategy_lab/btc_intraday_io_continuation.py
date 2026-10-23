"""IO-only continuation of the initial BTC intraday account, never a new strategy.

Card work-card-d0b2e5a9-508b-4419-8393-0498500f0011. All four qualified
runtime files and the historical activation/configuration stay byte-identical.
"""
import argparse
import hashlib
import os
from pathlib import Path
import stat
import sys

# Only the immutable sibling bundle is used by the executable. No live strategy
# module or package of the paired experiment is imported or modified.
sys.path.insert(0, str(Path(__file__).resolve().parent / 'frozen'))
import btc_intraday_paper as frozen
from btc_intraday_source_io import RecoveringBookReader, append_event

FILES = {'btc_intraday_io_continuation.py', 'btc_intraday_source_io.py'}
SCOPE = 'AUTHORIZED_INITIAL_INTRADAY_IO_CONTINUATION'


def root_document(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_mode & 0o022 or info.st_size > 65536:
            raise ValueError('root_owned_bounded_document_required')
        raw = os.read(fd, 65537)
        if len(raw) > 65536:
            raise ValueError('root_document_size')
        return raw, frozen.strict(raw)
    finally:
        os.close(fd)


def authorized(config):
    if set(config) != {'predecessor_configuration', 'io_continuation', 'source_io_log'}:
        raise ValueError('exact_continuation_configuration_required')
    prior_raw, prior = root_document(config['predecessor_configuration'])
    _, approval = root_document(config['io_continuation'])
    activation_raw, activation = root_document(prior['activation'])
    legacy_raw, _ = root_document(prior['continuation'])
    if (approval.get('scope') != SCOPE or approval.get('account') != frozen.ACCOUNT
            or approval.get('predecessor_configuration_sha256') != hashlib.sha256(prior_raw).hexdigest()
            or approval.get('activation_sha256') != hashlib.sha256(activation_raw).hexdigest()
            or approval.get('legacy_continuation_sha256') != hashlib.sha256(legacy_raw).hexdigest()
            or approval.get('protocol_sha256') != activation.get('protocol_sha256')
            or approval.get('strategy_unchanged') is not True
            or approval.get('state_reset_allowed') is not False
            or approval.get('real_orders') is not False
            or approval.get('exchange_credentials') is not False
            or approval.get('operational_grants') is not False
            or not isinstance(approval.get('operator_acceptance_reference'), str)
            or not approval['operator_acceptance_reference'].strip()
            or set(approval.get('runtime_files', {})) != FILES):
        raise ValueError('exact_io_continuation_required')
    for name, sha in approval['runtime_files'].items():
        path = Path(__file__).with_name(name)
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != sha:
            raise ValueError('io_runtime_pin_mismatch')
    log = Path(config['source_io_log'])
    if (log != Path(prior['db']).parent / 'source-read-events.jsonl'
            or log.is_symlink() or log.parent.is_symlink()
            or log.parent.stat().st_uid != os.geteuid() or log.parent.stat().st_mode & 0o022):
        raise ValueError('private_io_log_destination')
    # Original authority verifies the entire old bundle, unchanged protocol and
    # pre-T0 receipt/snapshot. It returns the ORIGINAL account activation.
    frozen.authority(prior)
    return prior


def run(config):
    prior = authorized(config)
    original = frozen.receipt.BookReader

    def reader(path, clock):
        return RecoveringBookReader(path, clock,
            lambda event: append_event(config['source_io_log'], event), factory=original)

    # The immutable loop, engines, witness and protective heartbeats remain the
    # original implementations. Only the source-reader boundary is adapted.
    frozen.receipt.BookReader = reader
    try:
        frozen.run(prior)
    finally:
        frozen.receipt.BookReader = original


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    os.umask(0o027)
    _, config = root_document(args.config)
    run(config)
