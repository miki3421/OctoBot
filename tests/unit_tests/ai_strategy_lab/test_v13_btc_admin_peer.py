"""Real Unix peer credential check in an isolated root-owned temporary directory."""
import json
import os
import pathlib
import shutil
import signal
import socket
import tempfile
import time

import pytest

from octobot.ai_strategy_lab import v13_admin_close
from tests.unit_tests.ai_strategy_lab.test_v13_btc_issuer_isolated import as_uid

pytestmark=pytest.mark.skipif(os.geteuid()!=0,reason='isolated peer UID test requires root')


def test_unix_socket_rejects_wrong_uid_even_when_group_can_connect():
    root=pathlib.Path(tempfile.mkdtemp(prefix='v13-admin-peer-'))
    root.chmod(0o755)
    directory=root/'socket';directory.mkdir();directory.chmod(0o750)
    path=directory/'close.sock'
    pid=os.fork()
    if pid==0:
        try:
            v13_admin_close.serve(path,allowed_uid=0,allowed_gid=0,
                ledger_path=root/'missing.sqlite',market_journal=root/'missing.jsonl',lock_path=root/'lock')
        finally:
            os._exit(0)
    try:
        for _ in range(200):
            if path.exists():
                break
            time.sleep(.01)
        assert path.exists()
        def request():
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as client:
                client.connect(str(path))
                return json.loads(client.recv(4096))['reason']
        denied=as_uid(30010,0,request)
        assert denied=={'ok':True,'value':'admin_peer_denied'}
    finally:
        os.kill(pid,signal.SIGTERM)
        os.waitpid(pid,0)
        shutil.rmtree(root)
