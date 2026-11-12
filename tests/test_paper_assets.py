import copy
from io import BytesIO
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

from PIL import Image
import pymupdf

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import sync_paper_assets as assets

SOURCE = 'https://arxiv.org/html/2611.01541v1'
PROJECT = 'https://lextran.github.io/MoPort/'
FIGURE = SOURCE + '/framework.png'
HTML = '''<title>MoPort: A View-Aware 2D Interface for Motion Language Models</title>
<img src="logo.png">
<div class="ltx_note_content">Project page: <a href="https://lextran.github.io/MoPort/">MoPort</a></div>
<figure id="overview"><img src="2611.01541v1/framework.png"><figcaption>Figure 2: MoPort framework overview</figcaption></figure>
<figure><img src="2611.01541v1/ablation.png"><figcaption>Figure 3: Ablation comparison</figcaption></figure>
<section class="ltx_bibliography"><p>Code: <a href="https://github.com/unrelated/library">library</a></p></section>
<footer>Project page: <a href="https://example.org/footer">footer</a></footer>'''
NOW = '2026-11-12T00:00:00+00:00'


class PaperAssetsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.paper = {'id': 'paper-2611.01541', 'title': 'MoPort: A View-Aware 2D Interface for Motion Language Models',
                      'arxiv_id': '2611.01541', 'arxiv': {'version': 1}, 'image': None,
                      'links': [{'label': {'en': 'Paper', 'zh': '论文'}, 'url': 'https://arxiv.org/abs/2611.01541'}],
                      'locked_fields': ['links']}
        data = BytesIO()
        Image.new('RGB', (800, 400), '#5599cc').save(data, format='PNG')
        self.responses = {SOURCE: (HTML.encode(), 'text/html', SOURCE),
                          PROJECT: (b'<title>MoPort project page</title>', 'text/html', PROJECT),
                          FIGURE: (data.getvalue(), 'image/png', FIGURE)}
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(url)
        if url not in self.responses:
            raise OSError('Unavailable')
        return self.responses[url]

    def test_only_explicit_non_bibliography_project_link_is_selected(self):
        links = assets.link_candidates(HTML, SOURCE)
        self.assertEqual([(l['kind'], l['url']) for l in links], [('Project', PROJECT)])
        unsafe = '<p>Project page: <a href="https://127.0.0.1/private">local</a></p>'
        self.assertEqual(assets.link_candidates(unsafe, SOURCE), [])

    def test_overview_beats_ablation_and_ignores_logo_and_table(self):
        html = HTML + '<figure><img src="table.png"><figcaption>Table 1: Overview of results</figcaption></figure>'
        figures = assets.figure_candidates(html, SOURCE)
        self.assertEqual(len(figures), 2)
        self.assertEqual(figures[0]['url'], FIGURE)

    def test_fill_missing_image_and_project_keeps_existing_links(self):
        before = copy.deepcopy(self.paper['links'])
        records, changed, warnings = assets.synchronize([self.paper], {}, self.root, NOW, self.get)
        self.assertEqual(warnings, [])
        self.assertEqual(changed, [self.paper['id']])
        self.assertEqual(self.paper['links'][0], before[0])
        self.assertEqual(self.paper['links'][1]['url'], PROJECT)
        with Image.open(self.root / self.paper['image']['src'].lstrip('/')) as image:
            self.assertEqual(image.format, 'WEBP')
            self.assertEqual(image.size, (800, 400))
        self.assertEqual(records[self.paper['id']]['image']['url'], FIGURE)
        get = Mock(side_effect=AssertionError('Complete assets should be reused'))
        again, changed, warnings = assets.synchronize([self.paper], records, self.root, NOW, get)
        self.assertEqual(again, records)
        self.assertFalse(changed or warnings)
        get.assert_not_called()

    def test_existing_manual_image_and_project_are_never_replaced(self):
        image = self.root / 'manual.webp'
        image.write_bytes(b'curated')
        self.paper['image'] = {'src': '/manual.webp'}
        self.paper['links'].append({'label': {'en': 'Project'}, 'url': 'https://example.org/custom'})
        before = copy.deepcopy(self.paper)
        assets.synchronize([self.paper], {}, self.root, NOW, Mock(side_effect=AssertionError()))
        self.assertEqual(self.paper, before)
        self.assertEqual(image.read_bytes(), b'curated')

    def test_wrong_project_page_rejected_but_figure_still_saved(self):
        self.responses[PROJECT] = (b'<title>Unrelated project</title>', 'text/html', PROJECT)
        records, changed, warnings = assets.synchronize([self.paper], {}, self.root, NOW, self.get)
        self.assertEqual(len(self.paper['links']), 1)
        self.assertTrue(self.paper['image'])
        self.assertFalse(warnings)
        self.assertEqual(records[self.paper['id']]['status'], 'success')
        self.assertEqual(records[self.paper['id']]['rejected_links'][0]['url'], PROJECT)

    def test_ambiguous_project_pages_are_left_for_review(self):
        second = 'https://example.org/MoPort/'
        html = HTML + '<p>Project page: <a href="' + second + '">MoPort</a></p>'
        self.responses[SOURCE] = (html.encode(), 'text/html', SOURCE)
        self.responses[second] = (b'<title>MoPort project</title>', 'text/html', second)
        record = assets.scan_paper(self.paper, self.root, self.get)
        self.assertEqual(len(self.paper['links']), 1)
        self.assertTrue(any('Multiple verified' in w for w in record['warnings']))

    def test_no_project_scan_cached_then_rechecked_after_week_or_new_version(self):
        self.responses[SOURCE] = (HTML.replace('Project page:', 'Supplement:').encode(), 'text/html', SOURCE)
        records, _, _ = assets.synchronize([self.paper], {}, self.root, NOW, self.get)
        get = Mock(side_effect=AssertionError('Recent negative scan should be cached'))
        assets.synchronize([self.paper], records, self.root, NOW, get)
        get.assert_not_called()
        self.calls.clear()
        assets.synchronize([self.paper], records, self.root, '2026-11-20T00:00:00+00:00', self.get)
        self.assertIn(SOURCE, self.calls)
        self.paper['arxiv']['version'] = 2
        self.calls.clear()
        assets.synchronize([self.paper], records, self.root, NOW, self.get)
        self.assertIn(SOURCE.replace('v1', 'v2'), self.calls)

    def test_missing_cached_image_is_repaired(self):
        records, _, _ = assets.synchronize([self.paper], {}, self.root, NOW, self.get)
        path = self.root / self.paper['image']['src'].lstrip('/')
        path.unlink()
        self.calls.clear()
        assets.synchronize([self.paper], records, self.root, NOW, self.get)
        self.assertTrue(path.is_file())
        self.assertIn(FIGURE, self.calls)

    def test_unavailable_resources_preserve_manual_links_and_retry(self):
        before = copy.deepcopy(self.paper)
        get = Mock(side_effect=OSError('offline'))
        records, changed, warnings = assets.synchronize([self.paper], {}, self.root, NOW, get)
        self.assertEqual(self.paper, before)
        self.assertFalse(changed)
        self.assertEqual(len(warnings), 2)
        get.reset_mock()
        assets.synchronize([self.paper], records, self.root, NOW, get)
        self.assertTrue(get.called)

    def test_pdf_first_page_fallback_when_html_has_no_suitable_figure(self):
        self.responses[SOURCE] = (b'<title>MoPort</title>', 'text/html', SOURCE)
        url = 'https://arxiv.org/pdf/2611.01541v1'
        with pymupdf.open() as doc:
            page = doc.new_page()
            page.insert_text((50, 50), 'MoPort: paper preview')
            self.responses[url] = (doc.tobytes(), 'application/pdf', url)
        records, changed, warnings = assets.synchronize([self.paper], {}, self.root, NOW, self.get)
        self.assertFalse(warnings)
        self.assertEqual(records[self.paper['id']]['image']['kind'], 'pdf-first-page')
        self.assertIn('first page', self.paper['image']['alt']['en'])
        self.assertLessEqual(self.paper['image']['height'], 900)

    def test_tiny_images_are_rejected(self):
        data = BytesIO()
        Image.new('RGB', (100, 40)).save(data, format='PNG')
        with self.assertRaises(ValueError):
            assets.thumbnail(data.getvalue())


if __name__ == '__main__':
    unittest.main()
