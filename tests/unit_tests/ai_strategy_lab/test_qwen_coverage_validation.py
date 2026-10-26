"""Bounded descriptive validator regression; no model or trading access."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'octobot/ai_strategy_lab'))
import v13_qwen_analysis as q


def fixture():
    source = {'metrics': {'symbols': [], 'windows': {'24h': {'complete': False}},
                          'top_positive_contribution_pct': None},
              'evidence': {key: 'Synthetic measured evidence.' for key in
                           ('account', 'composition', 'sample', 'window_24h')}}
    value = {'summary': 'Il campione osservato limita le conclusioni.',
             'strengths': [],
             'weaknesses': ['La copertura completa non è garantita nel periodo osservato.'],
             'watch': ['Osservare la continuità dei dati disponibili.'],
             'evidence_ids': list(source['evidence'])}
    return value, source


class CoverageValidationTests(unittest.TestCase):
    def test_only_cited_measured_incomplete_coverage_is_licensed(self):
        value, source = fixture()
        before = copy.deepcopy(value)
        self.assertEqual(q.validate_comment(value, source), before)
        self.assertEqual(value, before)
        value['weaknesses'] = ['La copertura non è garantita nel periodo osservato.']
        self.assertEqual(q.validate_comment(value, source), value)
        value['evidence_ids'].remove('window_24h')
        with self.assertRaises(ValueError):
            q.validate_comment(value, source)
        value, source = fixture()
        source['metrics']['windows']['24h']['complete'] = True
        with self.assertRaises(ValueError):
            q.validate_comment(value, source)

    def test_other_guarantees_actions_or_numbers_still_fail_closed(self):
        texts = [
            'La copertura completa è garantita nel periodo osservato.',
            'La copertura completa non è garantita, ma il profitto è garantito.',
            'La copertura non è garantita: compra BTCUSDT.',
            'La copertura non è garantita con rendimento del 99 percento.',
        ]
        for text in texts:
            value, source = fixture()
            value['weaknesses'] = [text]
            with self.subTest(text=text), self.assertRaises(ValueError):
                q.validate_comment(value, source)

    def test_open_pnl_sign_for_account_and_every_named_symbol(self):
        value, source = fixture()
        source['metrics'].update(totals={'unrealized_pnl': -20}, symbols=[
            dict(symbol='BTCUSDT', unrealized_pnl=-25),
            dict(symbol='NEARUSDT', unrealized_pnl=5)])
        source['evidence'].update(symbol_0='BTCUSDT: open loss.', symbol_1='NEARUSDT: open gain.')
        value['evidence_ids'] += ['symbol_0', 'symbol_1']
        for text, valid in [
            ('I guadagni aperti sostengono il conto osservato.', False),
            ('Le perdite aperte pesano sul conto osservato.', True),
            ('BTCUSDT presenta guadagni aperti nel periodo osservato.', False),
            ('BTCUSDT presenta perdite aperte nel periodo osservato.', True),
            ('NEARUSDT presenta guadagni aperti nel periodo osservato.', True),
            ('NEARUSDT presenta perdite aperte nel periodo osservato.', False),
            ('BTCUSDT e NEARUSDT presentano guadagni aperti.', False),
        ]:
            value['summary'] = text
            with self.subTest(text=text):
                if valid:
                    self.assertEqual(q.validate_comment(value, source), value)
                else:
                    with self.assertRaisesRegex(ValueError, 'contradicted_open_pnl'):
                        q.validate_comment(value, source)
        source['metrics']['totals']['unrealized_pnl'] = 0
        value['summary'] = 'I guadagni aperti sostengono il conto osservato.'
        with self.assertRaisesRegex(ValueError, 'contradicted_open_pnl'):
            q.validate_comment(value, source)

    def test_no_measured_critical_concentration_threshold_is_invented(self):
        value, source = fixture()
        value['summary'] = 'La concentrazione resta sotto la soglia critica.'
        with self.assertRaisesRegex(ValueError, 'unmeasured_critical_threshold'):
            q.validate_comment(value, source)

    def test_cached_ready_attempt_cannot_conceal_new_content_rejection(self):
        value, source = fixture()
        now = dt.datetime(2032, 5, 10, 6, tzinfo=dt.timezone.utc)
        source.update(as_of=now.isoformat())
        source['metrics']['totals'] = {'unrealized_pnl': -20}
        value['summary'] = 'I guadagni aperti sostengono il conto osservato.'
        record = dict(contract=q.CONTRACT, model=q.MODEL, status='ready',
                      generated_at=now.isoformat(), source=source, comment=value)
        record['report_hash'] = q.analytics.digest({key: record[key] for key in
            ['contract', 'model', 'generated_at', 'source', 'comment']})
        attempt = dict(contract=q.ATTEMPT_CONTRACT, attempt_id='a'*32,
                       started_at=(now-dt.timedelta(minutes=1)).isoformat(),
                       updated_at=now.isoformat(), state='ready', stage='complete',
                       reason=None, elapsed_seconds=60)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'status.json'
            path.write_text(json.dumps(record))
            path.with_name('attempt.json').write_text(json.dumps(attempt))
            # Source contract validation is covered separately; content and
            # cache validation here execute normally, with a real report hash.
            with mock.patch.object(q, 'validate_source', return_value=source):
                result = q.public_view(path, now)
            self.assertFalse(result['available'])
            self.assertNotIn('comment', result)
            self.assertEqual(result['status'], 'rejected')
            self.assertEqual(result['reason_code'], 'contradicted_open_pnl')


if __name__ == '__main__':
    unittest.main()
