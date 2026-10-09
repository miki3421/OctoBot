"""Less-trusted V13 strategy-side transport for a typed intent, no authority."""
import argparse
import json
import os
import pathlib
import tempfile

from octobot.ai_strategy_lab.v13_trusted_execution import validate_intent
import datetime as dt


def submit(raw, inbox, *, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    intent = validate_intent(raw, now)
    inbox = pathlib.Path(inbox)
    if not inbox.is_dir():
        raise ValueError('intent_inbox_missing')
    # The strategy can forge or modify its own inbox files; executor treats all
    # contents as untrusted and validates against trusted decision/market stores.
    fd, temporary = tempfile.mkstemp(prefix='.intent-', dir=inbox)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(intent, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        target = inbox / (intent['intent_id'] + '.json')
        if target.exists():
            raise ValueError('intent_id_duplicate')
        os.rename(temporary, target)
        return target
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--proposal',type=pathlib.Path,required=True)
    p.add_argument('--inbox',type=pathlib.Path,required=True)
    args = p.parse_args()
    print(submit(json.loads(args.proposal.read_text()),args.inbox))


if __name__ == '__main__':
    main()
