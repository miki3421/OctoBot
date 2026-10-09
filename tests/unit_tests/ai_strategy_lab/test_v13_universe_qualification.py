"""Offline adversarial tests, work-card-37b485cd-810c-413a-aecb-a70947f78614.

All source data, clocks, identities and responses are synthetic.
"""
import contextlib
import fcntl
import gzip
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import v13_universe_qualification as q

REPO = Path(__file__).resolve().parents[3]
START = 1790899200  # 2026-10-02 00:00 UTC, synthetic window.


class Crash(BaseException):
    pass


class QualificationTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.plan = q.load_plan(REPO)
        self.now = START-100
        self.calls = []
        self.net_guard = patch.object(socket.socket, 'connect', side_effect=AssertionError('NETWORK_FORBIDDEN'))
        self.net_guard.start(); self.addCleanup(self.net_guard.stop)
        self.c = self.collector()
        self.c.initialize()

    def collector(self, fetch=None, binding='synthetic-test-only'):
        return q.Collector(self.root, self.plan, START, binding, fetch or self.fetch, lambda: self.now)

    def fetch(self, url, limit):
        self.calls.append(url)
        endpoint = urlsplit(url).path
        query = parse_qs(urlsplit(url).query)
        if endpoint.endswith('exchangeInfo'):
            data = {'symbols': [dict(symbol=s, baseAsset=s[:-4], quoteAsset='USDT', marginAsset='USDT',
                                     contractType='PERPETUAL', status='TRADING') for s in self.plan['universe']]}
        elif endpoint.endswith('contracts/active'):
            data = {'code': '200000', 'data': [dict(symbol=r, baseCurrency='XBT' if s == 'BTCUSDT' else s[:-4],
                    quoteCurrency='USDT', settleCurrency='USDT', status='Open', isInverse=False, expireDate=None,
                    multiplier=1) for s, r in self.plan['symbol_mapping_to_verify_at_collection'].items()]}
        elif endpoint.endswith('depth20'):
            data = {'code': '200000', 'data': {'ts': int(self.now*1e9), 'bids': [[100,100]], 'asks': [[100.1,100]]}}
        elif endpoint.endswith('klines'):
            start = int(query['startTime'][0]); end = int(query['endTime'][0])
            data = [[start, '100', '101', '99', '100', '20', end]]
        else:
            data = {'code': '200000', 'data': [{'timepoint': int(query['from'][0]), 'fundingRate': 0.0001}]}
        return 200, q.canonical(data)

    def rows(self, query='SELECT * FROM jobs', params=()):
        with self.c.connection() as db:
            return list(db.execute(query, params))

    def mutate(self, sql, values=()):
        with self.c.connection() as db:
            db.execute(sql, values)

    def first(self):
        self.now = START
        self.c.tick()

    def test_full_schedule_and_previous_closed_day(self):
        jobs = self.c.jobs
        self.assertEqual(len(jobs), 39816)
        self.assertEqual(len({j[0] for j in jobs}), len(jobs))
        self.assertEqual(sum(j[1]=='books' for j in jobs), 38976)
        self.assertEqual(sum(j[1]=='daily' for j in jobs), 406)
        for _, kind, _, slot, deadline, url in jobs:
            self.assertLess(slot, START+14*q.DAY)
            self.assertEqual(deadline, slot+60)
            self.assertIn(url.split('?')[0], q.BASE.values())
            if kind == 'daily':
                params = parse_qs(urlsplit(url).query)
                self.assertLess(int(params['endTime'][0])/1000, slot-599)
        self.assertNotIn('PEPEUSDT', self.plan['universe'])

    def test_positive_synthetic_cycle_and_unknown_minima(self):
        self.first()
        self.assertEqual(len(self.calls), 31)
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE state='valid'")),31)
        for row in self.rows("SELECT * FROM jobs WHERE kind='books' AND state='valid'"):
            metrics = json.loads(row['metrics'])
            self.assertIsNone(metrics['min_quantity']); self.assertIsNone(metrics['min_notional'])
            self.assertEqual(metrics['bid_vwap_for_3150_mid_notional'], 100)
            self.assertEqual(q.sha(gzip.decompress(row['raw_gzip'])), row['raw_hash'])
        self.now = START+600
        self.c.tick()
        self.assertEqual(len(self.calls), 89)
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE kind='funding' AND state='valid'")),29)

    def test_restart_does_not_repeat_success_or_reinitialize(self):
        self.first(); before = len(self.calls)
        self.collector().tick()
        self.assertEqual(before,len(self.calls))
        self.now = START-1
        with self.assertRaises(FileExistsError):
            self.collector().initialize()

    def test_crash_after_claim_before_response_never_retried(self):
        def crash(url, limit):
            self.calls.append(url)
            raise Crash()
        self.now = START
        with self.assertRaises(Crash):
            self.collector(crash).tick()
        claimed = self.rows("SELECT * FROM jobs WHERE state='claimed'")[0]
        self.assertEqual(claimed['started'], START)
        self.assertGreater(claimed['reserved'],0)
        self.collector().tick()
        self.assertEqual(self.calls.count(claimed['url']),1)
        uncertain = self.rows("SELECT * FROM jobs WHERE state='uncertain'")
        self.assertEqual(len(uncertain),1)
        self.assertEqual(len(uncertain[0]['raw_gzip']),uncertain[0]['reserved'])

    def test_claim_storage_failure_prevents_network(self):
        self.mutate("CREATE TRIGGER fail_claim BEFORE UPDATE OF state ON jobs WHEN NEW.state='claimed' BEGIN SELECT RAISE(ABORT,'disk_full_fixture'); END")
        self.now = START
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.tick()
        self.assertEqual(self.calls, [])

    def test_response_commit_failure_preserves_uncertain_claim(self):
        self.mutate("CREATE TRIGGER fail_receipt BEFORE UPDATE OF state ON jobs WHEN NEW.state='valid' BEGIN SELECT RAISE(ABORT,'disk_full_fixture'); END")
        self.now = START
        with self.assertRaises(sqlite3.DatabaseError):
            self.c.tick()
        self.assertEqual(len(self.calls),1)
        url = self.calls[0]
        self.mutate('DROP TRIGGER fail_receipt')
        self.collector().tick()
        self.assertEqual(self.calls.count(url),1)
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE state='uncertain'")),1)

    def test_process_kill_preserves_claim_on_disk(self):
        script = '''
import os, signal, sys
from pathlib import Path
import v13_universe_qualification as q
plan=q.load_plan(Path(sys.argv[1]))
def terminate(url, limit):
    os.kill(os.getpid(), signal.SIGKILL)
c=q.Collector(Path(sys.argv[2]),plan,int(sys.argv[3]),'synthetic-test-only',terminate,lambda:int(sys.argv[3]))
c.tick()
'''
        result=subprocess.run([sys.executable,'-c',script,str(REPO),str(self.root),str(START)],check=False)
        self.assertEqual(result.returncode,-9)
        claimed=self.rows("SELECT * FROM jobs WHERE state='claimed'")[0]
        self.now=START;self.collector().tick()
        self.assertNotIn(claimed['url'],self.calls)
        self.assertEqual(self.rows('PRAGMA integrity_check')[0][0],'ok')

    def test_oversized_rate_limit_body_preserves_stop_and_prefix(self):
        self.now=START
        result=self.collector(lambda u,l:(429,b'x'*(l+1))).tick()
        self.assertEqual(result['reason'],'http_rate_limit')
        row=self.rows("SELECT * FROM jobs WHERE state='invalid'")[0]
        self.assertIn('incomplete_raw',row['error'])
        self.assertEqual(len(gzip.decompress(row['raw_gzip'])),4*1024*1024)

    def test_timeout_preserves_attempt_without_retry(self):
        self.now=START
        def timeout(url,limit):
            self.calls.append(url)
            raise TimeoutError()
        self.collector(timeout).tick()
        before=list(self.calls);self.collector().tick()
        for url in before:self.assertEqual(self.calls.count(url),1)
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE error='TimeoutError'")),2)

    def test_cli_missing_activation_cannot_acquire(self):
        result=subprocess.run([sys.executable,str(Path(q.__file__)), 'tick','--repo',str(REPO)],
                              capture_output=True,text=True,check=False)
        self.assertEqual(result.returncode,2)
        self.assertIn('activation receipt required',result.stderr)

    def test_budget_stop_persists_after_restart(self):
        self.now = START
        with patch.object(q,'RAW_CAP',100):
            self.assertEqual(self.c.tick()['reason'],'budget_limit')
        self.assertEqual(self.collector().tick()['reason'],'budget_limit')
        self.assertEqual(self.calls,[])

    def test_attempt_cap_includes_failed_request(self):
        self.now = START
        with patch.object(q,'ATTEMPT_CAP',1):
            result = self.collector(lambda u,l:(500,b'failure')).tick()
        self.assertEqual(result['reason'],'budget_limit')
        self.assertEqual(self.rows('SELECT count(started) FROM jobs')[0][0],1)

    def test_no_backfill_after_missed_window(self):
        self.now = START+61
        self.assertEqual(self.c.tick()['completed_this_tick'],0)
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE state='missing'")),31)
        self.assertEqual(self.calls,[])

    def test_expiry_no_renewal(self):
        self.now = START+14*q.DAY
        self.assertEqual(self.c.tick()['reason'],'window_complete')
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE state='missing'")),39816)
        self.assertEqual(self.calls,[])

    def test_clock_rollback_persists(self):
        self.first(); self.now -= 1
        self.assertEqual(self.c.tick()['reason'],'clock_rollback')
        self.now += 1000
        self.assertEqual(self.collector().tick()['reason'],'clock_rollback')
        self.assertEqual(len(self.calls),31)

    def test_rate_limit_no_retry_after_restart(self):
        self.now = START
        for status in (418,429):
            with self.subTest(status=status):
                self.mutate('UPDATE control SET stopped=NULL')
                # Only for exercising the second isolated fixture condition.
                result=self.collector(lambda u,l:(status,b'limited')).tick()
                self.assertEqual(result['reason'],'http_rate_limit')
                self.assertEqual(self.collector().tick()['reason'],'http_rate_limit')
        self.assertEqual(self.calls,[])

    def test_repeated_invalid_books_suspend(self):
        def bad(url,limit):
            status, raw = self.fetch(url,limit)
            if 'depth20' in url:
                value=json.loads(raw); value['data']['asks']=[[99,1]]
                raw=q.canonical(value)
            return status,raw
        self.now=START
        self.assertEqual(self.collector(bad).tick()['reason'],'repeated_errors')
        self.assertEqual(len(self.calls),5)
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE state='invalid'")),3)

    def test_mapping_change_denies_all_symbol_requests(self):
        def wrong(url,limit):
            status,raw=self.fetch(url,limit)
            if 'exchangeInfo' in url:
                value=json.loads(raw);value['symbols'][0]['baseAsset']='1000OTHER'
                raw=q.canonical(value)
            return status,raw
        self.now=START; self.collector(wrong).tick()
        self.assertEqual(len(self.calls),2)
        self.assertEqual(len(self.rows("SELECT * FROM jobs WHERE state='missing'")),29)

    def test_stale_metadata_not_used_next_day(self):
        self.first(); self.now=START+q.DAY+900
        self.c.tick()
        self.assertEqual(len(self.calls),31)

    def test_stale_future_and_late_book_are_invalid(self):
        self.first()
        job=self.rows("SELECT * FROM jobs WHERE kind='books' AND slot=?",(START,))[0]
        contract={'multiplier':1}
        for timestamp,receipt in [(START-61,START),(START+1,START),(START,START+61)]:
            raw=q.canonical({'code':'200000','data':{'ts':int(timestamp*1e9),'bids':[[100,1]],'asks':[[101,1]]}})
            with self.assertRaises(ValueError):self.c.validate(job,raw,receipt,contract)

    def test_future_candle_and_funding_duplicates_denied(self):
        day=self.rows("SELECT * FROM jobs WHERE kind='daily'")[0]
        raw=q.canonical([[START*1000,1,1,1,1,1,(START+q.DAY)*1000-1]])
        with self.assertRaises(ValueError):self.c.validate(day,raw,START+600,{})
        funding=self.rows("SELECT * FROM jobs WHERE kind='funding'")[0]
        point={'timepoint':(START-q.DAY)*1000,'fundingRate':0.1}
        with self.assertRaises(ValueError):self.c.validate(funding,q.canonical({'code':'200000','data':[point,point]}),START+600,{})

    def test_missing_and_corrupt_database_fail_without_fetch(self):
        other=self.root/'other';other.mkdir()
        c=q.Collector(other,self.plan,START,'test',self.fetch,lambda:START)
        with self.assertRaises(ValueError):c.tick()
        (other/'qualification.sqlite').write_bytes(b'not sqlite')
        with self.assertRaises(sqlite3.DatabaseError):c.tick()
        self.assertEqual(self.calls,[])

    def test_schedule_tamper_and_binding_change_denied(self):
        self.now=START
        with self.assertRaises(ValueError):self.collector(binding='different').tick()
        self.mutate("UPDATE jobs SET url='https://example.invalid' WHERE id=(SELECT id FROM jobs LIMIT 1)")
        with self.assertRaises(ValueError):self.c.tick()
        self.assertEqual(self.calls,[])

    def test_metadata_raw_tamper_denied(self):
        self.first()
        self.mutate("UPDATE jobs SET raw_hash='altered' WHERE kind='kucoin_metadata' AND state='valid'")
        self.now=START+900;self.c.tick()
        self.assertEqual(len(self.calls),31)

    def test_concurrent_writer_denied(self):
        with open(self.root/'collector.lock','w') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):self.c.tick()
        self.assertEqual(self.calls,[])

    def test_symlink_archive_denied(self):
        self.c.db_path.rename(self.root/'saved.sqlite')
        self.c.db_path.symlink_to(self.root/'saved.sqlite')
        with self.assertRaises(ValueError):self.c.tick()
        self.assertEqual(self.calls,[])

    def test_transport_rejects_other_host_and_redirect(self):
        for url in ('http://api-futures.kucoin.com/api/v1/contracts/active',
                    'https://user:password@api-futures.kucoin.com/api/v1/contracts/active',
                    'https://example.invalid/api/v1/contracts/active'):
            with self.assertRaises(ValueError):q.public_get(url,100)
        with self.assertRaises(ValueError):q.NoRedirect().redirect_request(None,None,None,None,None,None)

    def test_activation_requires_explicit_download_and_nonroot(self):
        p=self.root/'activation.json'
        config=dict(schema_version=1,plan_sha256=q.PLAN_HASH,collector_sha256=q.sha(Path(q.__file__).read_bytes()),
            periodic_downloads_authorized=False,service_activation_authorized=True,orders_authorized=False,
            owner_decision_reference='SYNTHETIC TEST ONLY',collector_uid=1234,start_utc='2026-10-02T00:00:00Z',
            end_utc='2026-10-16T00:00:00Z',storage_root=str(self.root),attempt_cap=q.ATTEMPT_CAP,compressed_raw_bytes_cap=q.RAW_CAP)
        # These mocks isolate schema validation; the next test covers actual filesystem rejection.
        with patch.object(q,'safe_path'),patch.object(os,'geteuid',return_value=1234):
            p.write_bytes(q.canonical(config))
            with self.assertRaises(ValueError):q.read_activation(p,self.plan,START-1)
            config['periodic_downloads_authorized']=True;p.write_bytes(q.canonical(config))
            self.assertEqual(q.read_activation(p,self.plan,START-1)['collector_uid'],1234)
            config['collector_uid']=0;p.write_bytes(q.canonical(config))
            with self.assertRaises(ValueError):q.read_activation(p,self.plan,START-1)

    def test_actual_untrusted_activation_path_denied(self):
        path=self.root/'activation.json';path.write_text('{}')
        with self.assertRaises(ValueError):q.read_activation(path,self.plan,START)

    def test_no_initialization_after_start(self):
        self.now=START
        with self.assertRaises(ValueError):self.c.initialize()


if __name__ == '__main__':
    unittest.main()
