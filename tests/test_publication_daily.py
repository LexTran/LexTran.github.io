from datetime import datetime
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_publications as sync

NOW = '2026-10-31T10:30:00+00:00'
SUCCESS = '2026-10-30T17:00:00+00:00'  # Same Beijing day despite different UTC day.


class DailyPublicationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / '_data').mkdir()
        self.previous = {'profile': sync.PROFILE_URL, 'last_attempt': SUCCESS,
                         'last_success': SUCCESS, 'status': 'success'}
        self.write('publications.json', [])
        self.write('scholar_sync.json', self.previous)

    def write(self, filename, value):
        (self.root / '_data' / filename).write_text(json.dumps(value))

    def read(self, filename):
        return json.loads((self.root / '_data' / filename).read_text())

    def run_sync(self, daily=True):
        with patch.object(sync, 'datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat(NOW)
            return sync.run(self.root, daily=daily)

    def test_beijing_calendar_boundary_not_utc_or_rolling_24_hours(self):
        self.assertTrue(sync.already_synced_today(self.previous, NOW))
        previous = dict(self.previous, last_success='2026-10-31T15:59:00+00:00')
        self.assertFalse(sync.already_synced_today(previous, '2026-10-31T16:00:00+00:00'))

    def test_invalid_future_naive_or_foreign_checkpoint_does_not_skip(self):
        for value in [None, '', 'invalid', '2026-10-31T10:00:00', '2026-10-31T11:00:00+00:00']:
            self.assertFalse(sync.already_synced_today(dict(self.previous, last_success=value), NOW))
        self.assertFalse(sync.already_synced_today(dict(self.previous, profile='another profile'), NOW))

    def test_repeated_pushes_make_no_scholar_requests_and_keep_real_timestamps(self):
        with patch.object(sync, 'collect_rows') as rows, patch.object(sync, 'fetch') as fetch:
            self.assertEqual(self.run_sync(), 0)
            self.assertEqual(self.run_sync(), 0)
            rows.assert_not_called()
            fetch.assert_not_called()
        status = self.read('scholar_sync.json')
        self.assertEqual(status['status'], 'skipped')
        self.assertEqual(status['last_check'], NOW)
        self.assertEqual(status['last_attempt'], SUCCESS)
        self.assertEqual(status['last_success'], SUCCESS)

    def test_failed_or_partial_without_success_today_allows_retry(self):
        for state in ['failed', 'partial']:
            self.write('scholar_sync.json', dict(self.previous, status=state, last_attempt=NOW,
                                               last_success='2026-10-29T17:00:00+00:00'))
            with patch.object(sync, 'collect_rows', side_effect=sync.SyncError('offline')) as rows:
                self.assertEqual(self.run_sync(), 2)
                rows.assert_called_once()
            self.assertEqual(self.read('scholar_sync.json')['last_attempt'], NOW)

    def test_previous_failure_does_not_erase_earlier_success_today(self):
        self.write('scholar_sync.json', dict(self.previous, status='failed', last_attempt=NOW))
        with patch.object(sync, 'collect_rows') as rows:
            self.assertEqual(self.run_sync(), 0)
            rows.assert_not_called()

    def test_scheduled_or_manual_check_still_fetches(self):
        with patch.object(sync, 'collect_rows', side_effect=sync.SyncError('offline')) as rows:
            self.assertEqual(self.run_sync(daily=False), 2)
            rows.assert_called_once()

    def test_skip_still_generates_news_and_reorders_local_acceptance(self):
        for filename in ['publications.json', 'news.json', 'news_state.json', 'venue_rankings.json', 'jcr_rankings.json']:
            shutil.copy(sync.ROOT / '_data' / filename, self.root / '_data' / filename)
        papers = self.read('publications.json')
        paper = next(p for p in papers if p['id'] == 'paper-2610.30717')
        paper.update(section='publications', acceptance_date='2026-10-31',
                     venue={'en': 'ICLR 2027 · Accepted', 'zh': 'ICLR 2027 · 已录用'})
        self.write('publications.json', papers)
        with patch.object(sync, 'collect_rows') as rows, patch.object(sync, 'fetch') as fetch:
            self.assertEqual(self.run_sync(), 0)
            rows.assert_not_called()
            fetch.assert_not_called()
        events = [n for n in self.read('news.json') if n.get('paper_id') == paper['id']]
        self.assertEqual(len(events), 1)
        updated = next(p for p in self.read('publications.json') if p['id'] == paper['id'])
        self.assertIn('publication_order', updated)
        self.assertEqual(updated['ranking']['label'], 'CCF A')


if __name__ == '__main__':
    unittest.main()
