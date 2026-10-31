import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from sync_project_videos import candidates, synchronize, public_url

BASE = 'https://example.org/paper/'
PAPERS = [{'id': 'p1', 'links': [{'label': {'en': 'Project'}, 'url': BASE}]}]

class ProjectVideoTests(unittest.TestCase):
    def test_overview_source_preferred_over_demo(self):
        html = '<video src="horse.mp4"></video><video aria-label="Overview video"><source src="assets/overview.mp4"></video>'
        result = candidates(html, BASE)
        self.assertEqual([v['url'] for v in result], [BASE + 'assets/overview.mp4'])

    def test_method_config_ignores_commented_examples(self):
        html = '''<script>/* methodVideo: { src: 'example.mp4' } */
        const SITE = { methodVideo: { src: 'anon/Method_video.mp4', embed: null, cap: {en: ''} } };
        // overviewVideo: { src: 'unused.mp4' }
        </script><video src="horse.mp4"></video>'''
        self.assertEqual([v['url'] for v in candidates(html, BASE)], [BASE + 'anon/Method_video.mp4'])

    def test_https_inside_config_string_is_not_a_comment(self):
        html = '<script>const SITE = { methodVideo: {src: "https://cdn.example.org/intro.mp4"} }</script>'
        self.assertEqual(candidates(html, BASE)[0]['url'], 'https://cdn.example.org/intro.mp4')

    def test_section_and_lazy_source(self):
        html = '<section id="method"><video><source data-src="movie.webm"></video></section>'
        self.assertEqual(candidates(html, BASE)[0]['url'], BASE + 'movie.webm')

    def test_ordinary_demo_and_unsupported_embed_are_not_selected(self):
        self.assertEqual(candidates('<video src="dog.mp4"></video><iframe src="https://youtube.com/embed/abc"></iframe>', BASE), [])

    def test_unsafe_sources_excluded(self):
        for url in ['javascript:alert(1)', 'http://example.org/overview.mp4', 'https://127.0.0.1/overview.mp4', 'https://localhost/overview.mp4']:
            with self.assertRaises(ValueError): public_url(url)
            self.assertEqual(candidates(f'<video aria-label="Overview" src="{url}"></video>', BASE), [])

    def test_sync_validates_source_and_is_idempotent(self):
        checks = []
        fetch = lambda url: ('<video src="overview.mp4"></video>', BASE)
        result, warnings = synchronize(PAPERS, {}, fetch, checks.append)
        self.assertEqual(checks, [BASE + 'overview.mp4'])
        self.assertFalse(warnings)
        self.assertEqual(synchronize(PAPERS, result, fetch, lambda _: None)[0], result)

    def test_outage_preserves_verified_video_but_changed_project_does_not(self):
        old = {'p1': {'project_url': BASE, 'video': {'url': BASE + 'overview.mp4'}}}
        def fail(_): raise OSError('offline')
        result, warnings = synchronize(PAPERS, old, fail)
        self.assertEqual(result['p1']['video'], old['p1']['video'])
        self.assertTrue(warnings)
        old['p1']['project_url'] = 'https://other.example.org/'
        self.assertNotIn('video', synchronize(PAPERS, old, fail)[0]['p1'])

    def test_successful_removal_disables_preview(self):
        old = {'p1': {'project_url': BASE, 'video': {'url': BASE + 'overview.mp4'}}}
        result, _ = synchronize(PAPERS, old, lambda _: ('<h1>Paper</h1>', BASE))
        self.assertNotIn('video', result['p1'])

    def test_ambiguous_videos_are_not_guessed(self):
        html = '<video src="overview-one.mp4"></video><video src="overview-two.mp4"></video>'
        result, warnings = synchronize(PAPERS, {}, lambda _: (html, BASE), lambda _: None)
        self.assertNotIn('video', result['p1'])
        self.assertIn('needs review', warnings[0])

if __name__ == '__main__': unittest.main()
