import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
import v13_dynamic_producer as producer
import v13_dynamic_intent as intent
from test_v13_dynamic_preview import START,receipts

class ProducerTests(unittest.TestCase):
    def test_one_seal_per_slot_across_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'intents.sqlite';store=intent.IntentStore(path,create=True)
            source=Mock();source.read.return_value=receipts()
            def runner():return producer.Producer(store,source,start=START,lineage='synthetic-periodic-test',validity_seconds=60)
            with patch.object(intent,'utc_now',side_effect=['2026-10-19T00:15:01Z','2026-10-19T00:15:02Z']):
                result=runner().step('2026-10-19T00:15:01Z')
            self.assertEqual(result['status'],'SEALED');store.close();store=intent.IntentStore(path)
            self.assertEqual(runner().step('2026-10-19T00:15:03Z')['status'],'ALREADY_SEALED')
            self.assertEqual(source.read.call_count,1);store.close()

    def test_missed_start_never_rebased(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=intent.IntentStore(Path(tmp)/'intents.sqlite',create=True)
            p=producer.Producer(store,Mock(),start=START,lineage='synthetic',validity_seconds=60)
            self.assertEqual(p.step('2026-10-19T00:16:00Z')['status'],'OUTSIDE_SLOT')
            with self.assertRaisesRegex(ValueError,'initial_slot_missing'):p.step('2026-10-26T00:15:01Z')
            self.assertEqual(store.db.execute('SELECT COUNT(*) FROM intents').fetchone()[0],0);store.close()
