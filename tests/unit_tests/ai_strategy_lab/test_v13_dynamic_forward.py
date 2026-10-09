import json
import tempfile
import unittest
from pathlib import Path
import v13_dynamic_forward as f
import test_v13_universe_qualification as fixture


class ForwardTests(unittest.TestCase):
    def test_raw_receipts_after_qualification_window_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'forward.sqlite';store=f.ForwardArchive(path,fixture.REPO,create=True)
            day=fixture.START+30*86400
            provider=fixture.QualificationTest();provider.plan=store.plan;provider.calls=[]
            jobs=store.jobs(day)
            for ident,job in jobs.items():
                _,kind,symbol,slot,deadline,url=job
                if kind not in ('kucoin_metadata','binance_metadata') and not (kind=='books' and slot==day):continue
                provider.now=slot+(0.25 if kind.endswith('metadata') else 2)
                status,raw=provider.fetch(url,4*1024*1024)
                if kind=='kucoin_metadata':
                    value=json.loads(raw)
                    for c in value['data']:c.update(tickSize=.01,lotSize=1,takerFeeRate=.0006)
                    raw=f.data.capture.canonical(value)
                kwargs=dict(day=day,url=url,started=slot+(0 if kind.endswith('metadata') else 1),received=provider.now,status=status,raw=raw)
                store.ingest(ident,**kwargs);store.ingest(ident,**kwargs)
            rows=store.read(day,day+3,kinds=('books',))
            self.assertEqual(len(rows),29)
            self.assertTrue(all(r['scope']=='VERIFIED_FORWARD_RECEIPT' for r in rows))
            self.assertTrue(all(r['precision']['min_quantity'] is None for r in rows))
            store.close();store=f.ForwardArchive(path,fixture.REPO)
            self.assertEqual(store.read(day,day+3,kinds=('books',)),rows)
            with self.assertRaises(ValueError):store.ingest(ident,**kwargs)
            store.close()

    def test_wrong_endpoint_and_missing_metadata_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=f.ForwardArchive(Path(tmp)/'forward.sqlite',fixture.REPO,create=True)
            ident,job=next((i,j) for i,j in store.jobs(fixture.START).items() if j[1]=='books')
            kwargs=dict(day=fixture.START,url='https://example.invalid',started=job[3]+1,received=job[3]+2,status=200,raw=b'{}')
            with self.assertRaisesRegex(ValueError,'forward_request_binding'):store.ingest(ident,**kwargs)
            kwargs['url']=job[5]
            with self.assertRaisesRegex(ValueError,'same_day_metadata_missing'):store.ingest(ident,**kwargs)
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM jobs').fetchone()[0],0)
            store.close()

    def test_collector_restart_does_not_repeat_completed_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'forward.sqlite';store=f.ForwardArchive(path,fixture.REPO,create=True)
            provider=fixture.QualificationTest();provider.plan=store.plan;provider.calls=[];provider.now=fixture.START+2
            def fetch(url,limit):
                status,raw=provider.fetch(url,limit)
                if 'contracts/active' in url:
                    value=json.loads(raw)
                    for contract in value['data']:contract.update(tickSize=.01,lotSize=1,takerFeeRate=.0006)
                    raw=f.data.capture.canonical(value)
                return status,raw
            first=f.Collector(store,fetch,lambda:provider.now).step()
            self.assertEqual(len(first),31);self.assertTrue(all(r['state']=='valid' for r in first))
            count=len(provider.calls);store.close();store=f.ForwardArchive(path,fixture.REPO,writable=True)
            self.assertEqual(f.Collector(store,fetch,lambda:provider.now).step(),[])
            self.assertEqual(len(provider.calls),count);store.close()

    def test_rate_limit_halt_survives_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'forward.sqlite';store=f.ForwardArchive(path,fixture.REPO,create=True)
            calls=[]
            def fetch(url,limit):calls.append(url);return 429,b'{}'
            self.assertEqual(f.Collector(store,fetch,lambda:fixture.START+2).step()[0]['state'],'halted_rate_limit')
            store.close();store=f.ForwardArchive(path,fixture.REPO,writable=True)
            with self.assertRaisesRegex(ValueError,'collector_requires_operator_review'):
                f.Collector(store,fetch,lambda:fixture.START+3).step()
            self.assertEqual(len(calls),1);store.close()
