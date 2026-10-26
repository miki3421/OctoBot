"""Publish read-only accounting metrics from existing paper ledgers."""
import argparse
import datetime as dt
import json
from pathlib import Path
import sys
import types


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    # An isolated stdlib publisher loads only the accounting modules, without
    # initializing OctoBot, exchange clients, credentials or trading services.
    package = types.ModuleType('octobot')
    package.__path__ = [str(Path(config['code'])/'octobot')]
    sys.modules['octobot'] = package
    laboratory = types.ModuleType('octobot.ai_strategy_lab')
    laboratory.__path__ = [str(Path(config['code'])/'octobot/ai_strategy_lab')]
    sys.modules['octobot.ai_strategy_lab'] = laboratory
    from octobot.ai_strategy_lab import v13_m1_live_review as review
    try:
        result = review.publish(config)
    except (OSError, ValueError, KeyError, TypeError, TimeoutError):
        review.atomic(Path(config['output']).with_name('status.json'),
                      dict(scope=review.SCOPE, status='ERROR', checked_at=dt.datetime.now(review.UTC).isoformat()))
        raise
    review.atomic(Path(config['output']).with_name('status.json'),
                  dict(scope=review.SCOPE, status='READY', checked_at=dt.datetime.now(review.UTC).isoformat()))
    print(json.dumps(dict(snapshot_id=result['snapshot_id'], end=result['end'],
                          current=result['m1']['totals']['since_version'], publication=result['publication'])))


if __name__ == '__main__':
    main()
