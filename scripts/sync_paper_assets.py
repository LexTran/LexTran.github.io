#!/usr/bin/env python3
"""Fill missing paper thumbnails and explicitly advertised project/code links."""
import argparse
from datetime import datetime, timezone, timedelta
from io import BytesIO
import json
import os
from pathlib import Path
import re
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from PIL import Image, ImageOps
from site_data import DOM, Node, ROOT, write_json
from sync_publications import ID_PATTERN, normalized
from sync_project_videos import public_url

_LAST_ARXIV_REQUEST = 0.0


def fetch_resource(url, limit=8_000_000):
    global _LAST_ARXIV_REQUEST
    url = public_url(url)
    if urlsplit(url).hostname == 'arxiv.org':
        time.sleep(max(0, 3 - (time.monotonic() - _LAST_ARXIV_REQUEST)))
        _LAST_ARXIV_REQUEST = time.monotonic()
    req = Request(url, headers={'User-Agent': 'AcademicHomepageAssets/1.0 (+https://lextran.github.io/)'})
    with urlopen(req, timeout=30) as response:
        resolved = public_url(response.url)
        data = response.read(limit + 1)
        if len(data) > limit:
            raise ValueError('Resource exceeds size limit')
        return data, response.headers.get_content_type(), resolved


def html_resource(url, get=fetch_resource):
    data, mime, resolved = get(url)
    if mime not in ('text/html', 'application/xhtml+xml'):
        raise ValueError('Expected an HTML page')
    return data.decode('utf-8', errors='replace'), resolved


def link_candidates(html, base):
    """Use explicit project/code labels, excluding citations and site navigation."""
    root = DOM(html).root
    found = {}
    def walk(node, parents=()):
        classes = node.attrs.get('class', '').split()
        if node.tag in ('nav', 'footer', 'script', 'style') or any('bibliograph' in c or c == 'ltx_bibitem' for c in classes):
            return
        if node.tag == 'a' and parents:
            raw = node.attrs.get('href', '')
            if raw.startswith(('https://', 'http://')):
                try:
                    url = public_url(raw)
                except ValueError:
                    url = ''
                context = parents[-1].text()
                # Restrict context to this link, not a remote label elsewhere in a large section.
                label = node.text()
                index = context.find(label) if label else -1
                nearby = context[max(0, index - 100):index + len(label) + 100] if index >= 0 else label
                project = re.search(r'project\s*(?:page|website|homepage)|project\s*[:：]|homepage\s*[:：]', nearby, re.I)
                code = re.search(r'our\s+(?:source\s+)?code|source\s+code|code\s+(?:is\s+)?(?:available|released)|code\s*[:：]', nearby, re.I)
                host = urlsplit(url).hostname if url else ''
                if url and host not in ('arxiv.org', 'info.arxiv.org') and (project or code):
                    kind = 'Project' if project else 'Code'
                    found[(kind, url)] = {'kind': kind, 'url': url, 'evidence': nearby[:250]}
        for child in node.children:
            if isinstance(child, Node):
                walk(child, parents + (node,))
    walk(root)
    return list(found.values())


def figure_candidates(html, base):
    candidates = []
    for index, figure in enumerate(DOM(html).root.find_all(tag='figure')):
        caption = figure.one(tag='figcaption')
        text = caption.text() if caption else ''
        if not text or re.match(r'Table\b', text, re.I):
            continue
        images = figure.find_all(tag='img')
        for img in images:
            try:
                url = public_url(img.attrs.get('src', ''), base)
            except ValueError:
                continue
            if not img.attrs.get('src') or urlsplit(url).hostname != 'arxiv.org':
                continue
            score = 30 - min(index, 20)
            if re.search(r'overview|framework|architecture|pipeline', text, re.I):
                score += 100
            if re.search(r'comparison|ablation|failure|sensitivity', text, re.I):
                score -= 40
            if len(images) > 1:
                score -= 30  # Prefer a complete diagram to one panel of a larger figure.
            candidates.append({'url': url, 'figure': figure.attrs.get('id', ''),
                               'caption': text[:300], 'score': score})
    return sorted(candidates, key=lambda c: -c['score'])


def matches_paper(html, paper):
    root = DOM(html).root
    headers = root.find_all(tag='title') + root.find_all(tag='h1')
    text = normalized(' '.join(n.text() for n in headers))
    titles = [paper['title'], paper.get('arxiv', {}).get('title', '')] + paper.get('aliases', [])
    for title in filter(None, titles):
        prefix, sep, _ = title.partition(':')
        key = prefix if sep and len(normalized(prefix)) >= 4 else title
        if text and normalized(key) in text:
            return True
    return False


def thumbnail(data):
    with Image.open(BytesIO(data)) as original:
        if original.width < 200 or original.height < 80 or original.width / original.height > 8:
            raise ValueError('Image is too small or shaped like an icon/banner')
        if original.width * original.height > 40_000_000:
            raise ValueError('Image exceeds pixel limit')
        original.load()
        rgba = ImageOps.exif_transpose(original).convert('RGBA')
        image = Image.new('RGB', rgba.size, 'white')
        image.paste(rgba, mask=rgba.getchannel('A'))
        image.thumbnail((1200, 900), Image.Resampling.LANCZOS)
        output = BytesIO()
        image.save(output, format='WEBP', quality=88, method=6)
        return output.getvalue(), image.width, image.height


def pdf_fallback(url, get=fetch_resource):
    """A first-page preview is preferable to guessing a figure crop."""
    import pymupdf
    data, mime, resolved = get(url, limit=30_000_000)
    if not data.startswith(b'%PDF'):
        raise ValueError('Expected a PDF')
    with pymupdf.open(stream=data, filetype='pdf') as doc:
        if not doc.page_count or doc.is_encrypted:
            raise ValueError('PDF is empty or encrypted')
        pix = doc[0].get_pixmap(matrix=pymupdf.Matrix(1.5, 1.5), alpha=False)
        return thumbnail(pix.tobytes('png')), resolved


def image_exists(paper, root):
    image = paper.get('image')
    return bool(image and (root / image['src'].lstrip('/')).is_file())


def scan_paper(paper, root, get=fetch_resource):
    aid = paper['arxiv_id']
    version = paper.get('arxiv', {}).get('version')
    suffix = aid + (f'v{version}' if version else '')
    source = 'https://arxiv.org/html/' + suffix
    record = {'arxiv_id': aid, 'version': version, 'source': source, 'warnings': []}
    html = None
    try:
        html, source = html_resource(source, get)
        if not matches_paper(html, paper):
            raise ValueError('arXiv HTML title does not match the paper')
    except (OSError, ValueError) as exc:
        html = None
        record['warnings'].append(f'HTML: {exc}')

    if html:
        candidates = link_candidates(html, source)
        for kind in ('Project', 'Code'):
            if any(link['label']['en'] == kind for link in paper['links']):
                continue
            verified = []
            for candidate in [c for c in candidates if c['kind'] == kind][:4]:
                try:
                    page, resolved = html_resource(candidate['url'], get)
                    if not matches_paper(page, paper):
                        # Papers may describe another method's code outside the
                        # bibliography. A verified mismatch is a rejected candidate,
                        # not a transient access failure requiring an immediate retry.
                        record.setdefault('rejected_links', []).append(dict(
                            candidate, reason='Linked page title does not identify this paper'))
                        continue
                    verified.append(dict(candidate, url=resolved))
                except (OSError, ValueError) as exc:
                    record['warnings'].append(f'{kind} {candidate["url"]}: {exc}')
            # Never choose between equally plausible project pages.
            by_url = {v['url'].rstrip('/'): v for v in verified}
            if len(by_url) == 1:
                candidate = next(iter(by_url.values()))
                if not any(l['url'].rstrip('/') == candidate['url'].rstrip('/') for l in paper['links']):
                    paper['links'].append({'label': {'en': kind, 'zh': '项目主页' if kind == 'Project' else '代码'},
                                           'url': candidate['url']})
                record[kind.lower()] = candidate
            elif len(by_url) > 1:
                record['warnings'].append(f'Multiple verified {kind.lower()} links; left for review')

    if not image_exists(paper, root):
        chosen = None
        if html:
            for figure in figure_candidates(html, source)[:3]:
                try:
                    data, mime, resolved = get(figure['url'])
                    if not mime.startswith('image/'):
                        raise ValueError('Figure URL did not return an image')
                    result = thumbnail(data)
                    chosen = dict(figure, url=resolved, kind='figure')
                    break
                except (OSError, ValueError) as exc:
                    record['warnings'].append(f'Figure {figure["url"]}: {exc}')
        if chosen is None:
            try:
                result, resolved = pdf_fallback('https://arxiv.org/pdf/' + suffix, get)
                chosen = {'url': resolved, 'kind': 'pdf-first-page', 'page': 1}
            except (OSError, ValueError, RuntimeError, ImportError) as exc:
                record['warnings'].append(f'PDF preview: {exc}')
        if chosen:
            data, width, height = result
            relative = 'assets/img/papers/arxiv-' + aid.replace('/', '-') + '.webp'
            output = root / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            temporary = output.with_suffix('.tmp')
            temporary.write_bytes(data)
            temporary.replace(output)
            short = paper.get('short_title', paper['title'].split(':')[0])
            label = 'paper overview' if chosen['kind'] == 'figure' else 'paper first page'
            label_zh = '论文概览图' if chosen['kind'] == 'figure' else '论文首页'
            paper['image'] = {'src': '/' + relative, 'width': width, 'height': height,
                              'alt': {'en': f'{short} {label}', 'zh': f'{short} {label_zh}'}}
            record['image'] = dict(chosen, file=relative)
    record['status'] = 'partial' if record['warnings'] else 'success'
    return record


def synchronize(papers, previous, root, now, get=fetch_resource):
    records = dict(previous)
    changed, warnings = [], []
    for paper in papers:
        aid = paper.get('arxiv_id', '')
        if not re.fullmatch(ID_PATTERN, aid):
            continue
        if image_exists(paper, root) and any(l['label']['en'] == 'Project' for l in paper['links']):
            continue
        old = previous.get(paper['id'], {})
        version = paper.get('arxiv', {}).get('version')
        try:
            recent = datetime.fromisoformat(now) - datetime.fromisoformat(old['last_checked']) < timedelta(days=7)
        except (KeyError, TypeError, ValueError):
            recent = False
        if old.get('status') == 'success' and old.get('version') == version and recent:
            # Successful scans with no advertised project are cached for a week.
            # A missing downloaded file should still be repaired immediately.
            if not paper.get('image') or image_exists(paper, root):
                continue
        before = json.dumps(paper, sort_keys=True)
        record = scan_paper(paper, root, get)
        # Keep provenance for assets preserved from an earlier successful scan.
        for key in ('image', 'project', 'code'):
            if key not in record and key in old:
                record[key] = old[key]
        record['last_checked'] = now
        records[paper['id']] = record
        warnings.extend(f'{paper["id"]}: {w}' for w in record['warnings'])
        if before != json.dumps(paper, sort_keys=True):
            changed.append(paper['id'])
    return records, changed, warnings


def run(root=ROOT):
    papers_path = root / '_data/publications.json'
    records_path = root / '_data/paper_assets.json'
    papers = json.loads(papers_path.read_text())
    previous = json.loads(records_path.read_text()) if records_path.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    records, changed, warnings = synchronize(papers, previous, root, now)
    write_json(papers_path, papers)
    write_json(records_path, records)
    status = {'last_check': now, 'status': 'partial' if warnings else 'success', 'updated': changed, 'warnings': warnings}
    write_json(root / '_data/paper_asset_sync.json', status)
    print(f'Paper assets: {status["status"]}; updated {len(changed)} paper(s).')
    for warning in warnings:
        print('Warning:', warning)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as out:
            out.write(f'\n## Paper thumbnails and project links\n\nUpdated {len(changed)} paper(s).\n')
            for warning in warnings:
                out.write('\n- ' + warning)
    return 0  # Missing optional media must not prevent publication of verified metadata.


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    raise SystemExit(run(parser.parse_args().root))
