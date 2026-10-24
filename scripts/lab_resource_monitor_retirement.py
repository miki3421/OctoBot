"""Add explicit retired-account checks to the unchanged passive monitor."""
import time

import monitor
from btc_intraday_retirement import read

original_collect = monitor.collect


def retired_account(item, inspect=monitor.inspect_containers, now_ns=None):
    result = dict(status='retired', issues=[])
    try:
        info = read(item['receipt'], item['path'], now_ns=time.time_ns() if now_ns is None else now_ns,
                    projection_uid=item['uid'])
        state = inspect(['octobot-btc-intraday-paper'])
        if state.get('container_error') or len(state['containers']) != 1:
            raise ValueError('retired_runtime_unverifiable')
        if state['containers'][0]['state'] != 'exited':
            raise ValueError('retired_runtime_not_stopped')
        result.update(retired_at_ns=info['retired_at_ns'], archive_verified=True,
                      runtime_state='exited', read_only_archive=True)
    except (OSError, ValueError, KeyError, TypeError):
        result.update(status='unavailable', issues=['PAPER_ACCOUNT_UNAVAILABLE:intraday'],
                      error_code='RETIREMENT_OR_STOPPED_RUNTIME_UNVERIFIABLE')
    return result


def collect(config):
    sample = original_collect(config)
    for name, item in config.get('retired_accounts', {}).items():
        if name != 'intraday' or name in config.get('paper_accounts', {}) or 'octobot-btc-intraday-paper' in config['containers']:
            raise ValueError('explicit_retirement_configuration_required')
        sample['paper_accounts'][name] = retired_account(item)
    return sample


if __name__ == '__main__':
    monitor.collect = collect
    monitor.main()
