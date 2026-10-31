import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_publications as sync

FIXTURES = Path(__file__).parent / 'fixtures/scholar'


class PublicationSyncTests(unittest.TestCase):
    def setUp(self):
        self.html = (FIXTURES / 'profile.html').read_text()
        self.rows, _ = sync.parse_profile(self.html)
        self.c2r = next(r for r in self.rows if r['title'].startswith('C2R:'))
        self.detail = sync.parse_detail((FIXTURES / 'c2r.html').read_text(), self.c2r)
        self.preprint = next(r for r in self.rows if r['title'].startswith('PhyEvolve:'))
        self.paper = {
            'id': 'paper-test', 'title': self.preprint['title'], 'section': 'preprints', 'year': 2026,
            'authors': [{'name': 'Yang-Hao Zhou', 'self': False, 'marks': '†'},
                        {'name': 'Lixing Tan', 'self': True, 'marks': '†'},
                        {'name': 'Xiao Yang', 'self': False, 'marks': '‡'}],
            'venue': {'en': 'Preprint · First posted Oct 2026', 'zh': '预印本 · 2026.10 首次公开'},
            'summary': {'en': 'Curated summary', 'zh': '手工简介'}, 'image': {'src': '/figure.webp'},
            'links': [{'label': {'en': 'Project', 'zh': '项目主页'}, 'url': 'https://example.org/'}],
            'topics': ['generation'], 'arxiv_id': '2610.30717', 'aliases': [],
            'locked_fields': ['title', 'authors', 'links', 'summary', 'image', 'topics'],
            'scholar': copy.deepcopy(self.preprint),
        }

    def test_real_profile_and_full_detail(self):
        self.assertEqual(len(self.rows), 7)
        self.assertFalse(sync.parse_profile(self.html)[1])
        self.assertEqual(self.detail['authors'][2], 'Lixing Tan')
        self.assertEqual(len(self.detail['authors']), 7)
        self.assertIn('(CVIDL)', self.detail['venue'])
        self.assertTrue(self.detail['paper_url'].startswith('https://ieeexplore.ieee.org/'))

    def test_blocked_or_wrong_identity_rejected(self):
        for bad in ['<html>Sign in</html>', self.html.replace('Lixing Tan', 'Other Researcher'),
                    self.html.replace('buaa.edu.cn', 'other.edu')]:
            with self.assertRaises(sync.SyncError):
                sync.parse_profile(bad)

    def test_empty_profile_rejected(self):
        with self.assertRaises(sync.SyncError):
            sync.parse_profile('<div id="gsc_prf_in">Lixing Tan</div><div id="gsc_prf_ivh">Verified email at buaa.edu.cn</div>')

    def test_foreign_citation_rejected(self):
        with self.assertRaises(sync.SyncError):
            sync.parse_profile(self.html.replace('citation_for_view=wtordYAAAAAJ', 'citation_for_view=anotherUser'))

    def test_idempotence_and_absent_curated_paper_preserved(self):
        curated = copy.deepcopy(self.paper)
        curated.update(id='accepted-paper', title='Not on Scholar yet', arxiv_id='', scholar={})
        result, added, updated, warnings = sync.merge([self.paper, curated], [self.preprint], lambda _: self.fail('No detail fetch needed'))
        self.assertEqual(result, [self.paper, curated])
        self.assertEqual((added, updated, warnings), ([], [], []))

    def test_new_paper_full_authors_and_blank_figure(self):
        papers, added, _, warnings = sync.merge([], [self.c2r], lambda _: self.detail)
        self.assertEqual(len(added), 1)
        self.assertEqual(warnings, [])
        self.assertEqual(papers[0]['section'], 'publications')
        self.assertIsNone(papers[0]['image'])
        self.assertTrue(papers[0]['authors'][2]['self'])
        self.assertEqual(papers[0]['topics'], ['medical'])
        self.assertTrue(all(not a['marks'] for a in papers[0]['authors']))

    def test_arxiv_dedup_even_if_title_changed(self):
        row = dict(self.preprint, id=sync.PROFILE_ID + ':alternate', title='An alternate title')
        result, added, _, _ = sync.merge([self.paper], [row], lambda _: dict(self.detail, title=row['title']))
        self.assertEqual(len(result), 1)
        self.assertEqual(added, [])
        self.assertEqual(result[0]['title'], self.paper['title'])

    def test_promotion_preserves_manual_author_marks_and_visuals(self):
        row = dict(self.preprint, venue='Example Conference 2027', year=2027)
        detail = dict(self.detail, title=row['title'], venue=row['venue'], year=2027)
        papers, _, updated, _ = sync.merge([self.paper], [row], lambda _: detail)
        p = papers[0]
        self.assertEqual(p['section'], 'publications')
        self.assertEqual(p['venue']['en'], row['venue'])
        for field in ['authors', 'summary', 'image', 'links', 'title', 'topics']:
            self.assertEqual(p[field], self.paper[field])
        self.assertEqual(updated, ['paper-test'])

    def test_accepted_paper_never_downgraded(self):
        self.paper.update(section='publications', venue={'en': 'Accepted', 'zh': '已录用'})
        row = dict(self.preprint, title='Minor title revision')
        detail = dict(self.detail, title=row['title'], venue='arXiv preprint arXiv:2610.30717')
        papers, *_ = sync.merge([self.paper], [row], lambda _: detail)
        self.assertEqual(papers[0]['section'], 'publications')
        self.assertEqual(papers[0]['venue'], self.paper['venue'])

    def test_unrelated_metadata_change_keeps_curated_posted_date(self):
        row = dict(self.preprint, authors='Y Zhou, L Tan, X Yang')
        detail = dict(self.detail, venue=self.preprint['venue'])
        papers, *_ = sync.merge([self.paper], [row], lambda _: detail)
        self.assertEqual(papers[0]['venue'], self.paper['venue'])

    def test_failed_detail_keeps_record_retryable(self):
        row = dict(self.preprint, venue='Example Journal')
        def unavailable(_):
            raise sync.SyncError('Unavailable')
        result, added, updated, warnings = sync.merge([self.paper], [row, self.c2r], unavailable)
        self.assertEqual(result, [self.paper])
        self.assertFalse(added or updated)
        self.assertEqual(len(warnings), 2)

    def test_truncated_authors_and_unsafe_links_rejected(self):
        html = (FIXTURES / 'c2r.html').read_text()
        with self.assertRaises(sync.SyncError):
            sync.parse_detail(html.replace('Lele Yue', 'Lele Yue…'), self.c2r)
        for url in ['javascript:alert(1)', 'file:///tmp/x', '//example.org']:
            with self.assertRaises(sync.SyncError):
                sync.safe_url(url)

    def test_pagination_duplicates_rejected(self):
        html = self.html.replace('disabled=""', '')
        with self.assertRaises(sync.SyncError), patch.object(sync.time, 'sleep'):
            sync.collect_rows(lambda _: html)

    def test_fetch_failure_preserves_catalogue_and_last_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sync.write_json(root / '_data/publications.json', [self.paper])
            sync.write_json(root / '_data/scholar_sync.json', {'last_success': '2026-10-01T00:00:00+00:00'})
            before = (root / '_data/publications.json').read_bytes()
            with patch.object(sync, 'collect_rows', side_effect=sync.SyncError('Blocked')):
                self.assertEqual(sync.run(root), 2)
            self.assertEqual(before, (root / '_data/publications.json').read_bytes())
            status = json.loads((root / '_data/scholar_sync.json').read_text())
            self.assertEqual(status['status'], 'failed')
            self.assertEqual(status['last_success'], '2026-10-01T00:00:00+00:00')
            self.assertTrue(status['last_attempt'])

    def test_catalogue_keeps_existing_editorial_requirements(self):
        papers = json.loads((sync.ROOT / '_data/publications.json').read_text())
        phy = next(p for p in papers if p['arxiv_id'] == '2610.30717')
        self.assertEqual(next(a for a in phy['authors'] if a['self'])['marks'], '†')
        self.assertEqual(next(a for a in phy['authors'] if a['name'] == 'Xiao Yang')['marks'], '‡')
        gs = next(p for p in papers if p['id'] == 'paper-gsmedqa')
        self.assertEqual(gs['section'], 'publications')
        self.assertTrue(all(not a['marks'] for a in gs['authors']))
        self.assertEqual([a['name'] for a in gs['authors']], ['Guo Yuting', 'Zhenyu Yang', 'Lixing Tan', 'Yujing Yan', 'Wenfeng Song', 'Xia Hou'])


if __name__ == '__main__':
    unittest.main()
