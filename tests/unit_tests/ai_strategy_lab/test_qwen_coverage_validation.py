"""Bounded descriptive validator regression; no model or trading access."""
import copy
from pathlib import Path
import sys
import unittest

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


if __name__ == '__main__':
    unittest.main()
