import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_publications as sync

FIXTURE = Path(__file__).parent / 'fixtures/arxiv/author.atom'


class PublicationSyncTests(unittest.TestCase):
    def setUp(self):
        self.xml = FIXTURE.read_text()
        self.author = sync.load_author()
        self.rows, _ = sync.parse_feed(self.xml, self.author)
        self.row = next(r for r in self.rows if r['id'] == '2611.01541')
        self.paper = sync.merge([], [self.row], self.author)[0][0]
        self.paper.update(summary={'en': 'Curated summary', 'zh': '手工简介'},
                          image={'src': '/figure.webp'}, locked_fields=['title', 'authors', 'links', 'summary', 'image', 'topics'])
        self.paper['authors'][0]['marks'] = '†'

    def feed(self, change):
        feed = ET.fromstring(self.xml)
        change(feed)
        return ET.tostring(feed, encoding='unicode')

    def test_author_feed_full_authors_version_and_dates(self):
        rows, warnings = sync.parse_feed(self.xml, self.author)
        self.assertEqual(len(rows), 7)
        self.assertEqual(warnings, [])
        cu = next(r for r in rows if r['id'] == '2611.01536')
        self.assertEqual(cu['version'], 2)
        self.assertEqual(len(cu['authors']), 7)
        self.assertEqual(cu['authors'][0], 'Lixing Tan')
        self.assertEqual(cu['published'][:10], '2026-11-01')
        self.assertEqual(cu['updated'][:10], '2026-11-05')
        self.assertTrue(cu['published'].endswith('+00:00'))

    def test_wrong_identity_blocked_page_and_empty_feed_rejected(self):
        empty = self.feed(lambda f: [f.remove(e) for e in f.findall('a:entry', sync.NS)])
        for bad in ['<html>Sign in</html>', self.xml.replace('tan_l_3', 'tan_l_1'),
                    self.xml.replace('Lixing Tan', 'Another Author'),
                    self.xml.replace('0000-0002-0323-8802', '0000-0000-0000-0000'), empty,
                    '<!DOCTYPE feed>' + self.xml]:
            with self.subTest(bad=bad[:80]), self.assertRaises(sync.SyncError):
                sync.parse_feed(bad, self.author)

    def test_invalid_entry_is_reported_while_other_entries_remain_usable(self):
        for field, value in [('a:id', 'https://example.org/abs/2611.01536'), ('a:published', 'bad'),
                             ('a:updated', '2001-01-01T00:00:00Z'), ('a:title', '')]:
            xml = self.feed(lambda f: setattr(f.find('a:entry/' + field, sync.NS), 'text', value))
            rows, warnings = sync.parse_feed(xml, self.author)
            self.assertEqual(len(rows), 6)
            self.assertEqual(len(warnings), 1)
        xml = self.feed(lambda f: setattr(f.find('a:entry/a:author/a:name', sync.NS), 'text', 'Other Author'))
        rows, warnings = sync.parse_feed(xml, self.author)
        self.assertEqual(len(rows), 6)
        self.assertIn('absent', warnings[0])

    def test_duplicate_pagination_and_count_mismatch_rejected(self):
        changes = [lambda f: f.append(copy.deepcopy(f.find('a:entry', sync.NS))),
                   lambda f: ET.SubElement(f, '{'+sync.NS['a']+'}link', rel='next', href='https://arxiv.org/next'),
                   lambda f: setattr(ET.SubElement(f, '{'+sync.NS['o']+'}totalResults'), 'text', '99')]
        for change in changes:
            with self.assertRaises(sync.SyncError):
                sync.parse_feed(self.feed(change), self.author)

    def test_new_paper_and_repeat_are_idempotent(self):
        papers, added, updated, warnings = sync.merge([], [self.row], self.author)
        self.assertEqual(added, ['paper-2611.01541'])
        self.assertFalse(updated or warnings)
        self.assertEqual(papers[0]['section'], 'preprints')
        self.assertIsNone(papers[0]['image'])
        self.assertTrue(papers[0]['authors'][0]['self'])
        self.assertEqual(papers[0]['topics'], ['motion'])
        again, added, updated, warnings = sync.merge(papers, [self.row], self.author)
        self.assertEqual(again, papers)
        self.assertFalse(added or updated or warnings)

    def test_version_change_deduplicates_and_preserves_editorial_fields(self):
        row = dict(self.row, version=2, updated='2026-11-10T00:00:00+00:00', title='A revised title')
        papers, added, updated, warnings = sync.merge([self.paper], [row], self.author)
        self.assertEqual(len(papers), 1)
        self.assertFalse(added or warnings)
        self.assertEqual(updated, [self.paper['id']])
        for field in self.paper['locked_fields']:
            self.assertEqual(papers[0][field], self.paper[field])
        self.assertEqual(papers[0]['arxiv']['version'], 2)
        stale, _, _, warnings = sync.merge(papers, [self.row], self.author)
        self.assertEqual(stale, papers)
        self.assertIn('stale', warnings[0])

    def test_unlocked_author_marks_and_title_alias_survive_update(self):
        self.paper['locked_fields'] = []
        row = dict(self.row, title='MoPort: Revised title')
        papers, *_ = sync.merge([self.paper], [row], self.author)
        self.assertIn(self.paper['title'], papers[0]['aliases'])
        self.assertEqual(papers[0]['authors'][0]['marks'], '†')

    def test_title_alias_match_and_conflicting_id_do_not_duplicate(self):
        self.paper.update(title='Editorial title', aliases=[self.row['title']], arxiv_id='', arxiv={})
        papers, added, *_ = sync.merge([self.paper], [self.row], self.author)
        self.assertFalse(added)
        self.assertEqual(papers[0]['arxiv_id'], self.row['id'])
        self.paper['arxiv_id'] = '2601.00001'
        papers, added, updated, warnings = sync.merge([self.paper], [self.row], self.author)
        self.assertEqual(papers, [self.paper])
        self.assertFalse(added or updated)
        self.assertIn('different arXiv ID', warnings[0])

    def test_missing_feed_records_and_accepted_records_are_preserved(self):
        accepted = copy.deepcopy(self.paper)
        accepted.update(section='publications', year=2027, venue={'en': 'Accepted', 'zh': '已录用'})
        missing = dict(self.paper, id='missing', arxiv_id='2601.99999', arxiv={})
        row = dict(self.row, version=2, updated='2026-11-10T00:00:00+00:00')
        papers, *_ = sync.merge([accepted, missing], [row], self.author)
        self.assertEqual(papers[1], missing)
        self.assertEqual(papers[0]['section'], 'publications')
        self.assertEqual(papers[0]['year'], 2027)
        self.assertEqual(papers[0]['venue'], accepted['venue'])

    def test_only_explicit_journal_reference_promotes_not_doi_or_submission(self):
        for ref in ['', 'Submitted to CVPR 2027', 'arXiv preprint', 'Under review']:
            row = dict(self.row, doi='10.1234/example', journal_ref=ref)
            papers, *_ = sync.merge([self.paper], [row], self.author)
            self.assertEqual(papers[0]['section'], 'preprints')
        row = dict(self.row, journal_ref='Proceedings of CVPR 2027')
        papers, *_ = sync.merge([self.paper], [row], self.author)
        self.assertEqual(papers[0]['section'], 'publications')
        self.assertEqual(papers[0]['year'], 2027)
        self.assertTrue(papers[0]['publication']['confirmed'])
        self.assertEqual(papers[0]['image'], self.paper['image'])
        self.paper['locked_fields'].append('venue')
        papers, *_ = sync.merge([self.paper], [row], self.author)
        self.assertEqual(papers[0]['section'], 'preprints')

    def test_preprint_order_uses_first_submission_not_latest_revision(self):
        rows = copy.deepcopy(self.rows)
        rows[-1]['updated'] = '2026-11-12T00:00:00+00:00'
        papers, *_ = sync.merge([], rows, self.author)
        self.assertEqual(papers[-1]['arxiv_id'], '2404.11889')
        self.assertEqual({p['arxiv_id'] for p in papers[:2]}, {'2611.01541', '2611.01536'})

    def test_failure_preserves_catalogue_and_last_success(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sync.write_json(root / '_data/arxiv_author.json', self.author)
            sync.write_json(root / '_data/publications.json', [self.paper])
            sync.write_json(root / '_data/arxiv_sync.json', {'feed_url': self.author['feed_url'],
                                                          'last_success': '2026-10-01T00:00:00+00:00'})
            before = (root / '_data/publications.json').read_bytes()
            with patch.object(sync, 'collect_rows', side_effect=sync.SyncError('Offline')):
                self.assertEqual(sync.run(root), 2)
            self.assertEqual(before, (root / '_data/publications.json').read_bytes())
            status = json.loads((root / '_data/arxiv_sync.json').read_text())
            self.assertEqual(status['status'], 'failed')
            self.assertEqual(status['last_success'], '2026-10-01T00:00:00+00:00')

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
