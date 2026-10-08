import copy
import tempfile
import unittest
from pathlib import Path
from note_automation.core import number, append_snapshot, compare, generate, save_draft
from note_automation.browser import note_url, SafetyError


def sample():
    return {'collected_at': '2026-10-05T00:00:00+00:00', 'period': '全期間', 'period_key': '全期間', 'totals': {'impressions': 96, 'page_views': 12, 'likes': 0, 'comments': 0, 'sales_yen': 0}, 'articles': [{'id': 'https://note.com/example/n/one', 'title': 'テスト記事', 'published_at': None, 'impressions': 80, 'page_views': 11, 'likes': None, 'comments': None}], 'referrers': None}


class CoreTests(unittest.TestCase):
    def test_strict_numbers(self):
        self.assertEqual(number('1,234円'), 1234)
        for value in ['12 PV', '約12', '1.2万', '-1', '', '12 13']:
            with self.assertRaises(ValueError):
                number(value)

    def test_append_dedup_and_conflict(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'metrics.json'
            first, added = append_snapshot(path, sample())
            self.assertTrue(added)
            second, added = append_snapshot(path, sample())
            self.assertFalse(added)
            self.assertEqual(first, second)
            changed = sample()
            changed['totals']['page_views'] = 13
            with self.assertRaises(ValueError):
                append_snapshot(path, changed)
            changed['collected_at'] = '2026-10-06T00:00:00+00:00'
            history, added = append_snapshot(path, changed)
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0], first[0])

    def test_source_aggregation_dedup(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / 'metrics.json'
            first = sample()
            first.update(source='note_rendered_dom', source_aggregated_at='2026/10/5 12:00 集計')
            append_snapshot(path, first)
            second = copy.deepcopy(first)
            second['collected_at'] = '2026-10-05T01:00:00+00:00'
            history, added = append_snapshot(path, second)
            self.assertFalse(added)
            self.assertEqual(len(history), 1)
            second['totals']['page_views'] = 99
            with self.assertRaises(ValueError):
                append_snapshot(path, second)

    def test_comparison(self):
        before, after = sample(), sample()
        after['totals']['page_views'] = 15
        after['totals']['impressions'] = None
        result = compare(after, before)
        self.assertEqual(result['totals_delta']['page_views'], 3)
        self.assertIsNone(result['totals_delta']['impressions'])
        self.assertIsNone(result['articles_delta'][after['articles'][0]['id']]['likes'])
        after['period'] = '今月'
        self.assertFalse(compare(after, before)['comparable'])
        self.assertIsNone(compare(after, before)['totals_delta']['page_views'])

    def test_generation_and_frontmatter(self):
        snapshot = sample()
        snapshot['totals']['sales_yen'] = None
        with tempfile.TemporaryDirectory() as d:
            history, _ = append_snapshot(Path(d) / 'history.json', snapshot)
            s = history[0]
            article = generate(s, compare(s, None))
            self.assertEqual(len(article['title_candidates']), 5)
            self.assertNotIn('売上（円）：', article['body'])
            self.assertIn('厳密なCTRではない', article['body'])
            self.assertEqual(generate(s, compare(s, None), 'A')['category'], 'D')
            path = save_draft(d, s, article)
            self.assertIn('"status": "draft"', path.read_text())
            self.assertTrue(path.with_suffix('.metadata.json').exists())

    def test_url_allowlist(self):
        for url in ['https://evil.com', 'http://note.com', 'https://note.com.evil.com', 'https://user:password@note.com']:
            with self.assertRaises(SafetyError):
                note_url(url)


if __name__ == '__main__':
    unittest.main()
