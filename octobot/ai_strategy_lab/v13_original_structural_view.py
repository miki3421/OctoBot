"""Read-only successor label/boundary on the existing account comparison slot."""
import copy
import datetime as dt
import json
import os
from pathlib import Path
import stat


def merge(data, path='/v13-paper/research/execution/structural-successor.json', now=None):
    path = Path(path)
    if not path.exists():
        return data
    result = copy.deepcopy(data)
    now = now or dt.datetime.now(dt.timezone.utc)
    try:
        fd = os.open(path, os.O_RDONLY|os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != 30914 or info.st_mode & 0o022 or info.st_size > 100000:
                raise ValueError('successor_projection_custody')
            value = json.loads(os.read(fd, 100001))
        finally:
            os.close(fd)
        if (value['scope'] != 'ORIGINAL_STRUCTURAL_SUCCESSOR_PROJECTION' or value['account'] != 'v13-paper-v2'
                or value['real_orders_authorized'] is not False or value['schema'] != 1):
            raise ValueError('successor_projection_scope')
        age = (now-dt.datetime.fromisoformat(value['generated_at'])).total_seconds()
        if not 0 <= age <= 180:
            raise ValueError('successor_projection_stale')
        variant = result['variants']['ORIGINAL']
        if variant['account_id'] != value['account']:
            raise ValueError('successor_account_mismatch')
        variant.update(label=value['label'], strategy_epoch=value['boundary'],
            epoch_change=variant['metrics']['equity']-value['boundary']['metrics']['equity'],
            epoch_change_pct=(variant['metrics']['equity']/value['boundary']['metrics']['equity']-1)*100)
        result['original_successor'] = value
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        result['original_successor_unverified'] = True
    return result
