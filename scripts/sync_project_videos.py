#!/usr/bin/env python3
"""Discover explicit overview/method videos without executing project-page scripts."""
import argparse
from datetime import datetime, timezone
import ipaddress
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from sync_publications import DOM, Node, ROOT, write_json

VIDEO_WORDS = re.compile(r'overview|method|teaser|presentation|explain|explanation|讲解|介绍', re.I)
JS_TOKENS = re.compile(r'''("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`)|/\*[\s\S]*?\*/|//[^\n]*''')


def public_url(value, base=''):
    url = urljoin(base, value)
    p = urlsplit(url)
    if p.scheme != 'https' or not p.hostname or p.username or p.password:
        raise ValueError('Expected a public HTTPS URL')
    host = p.hostname.lower()
    if host == 'localhost' or host.endswith(('.local', '.internal', '.localhost')):
        raise ValueError('Not a public host')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        if not address.is_global:
            raise ValueError('Not a public address')
    return url


def candidates(html, page_url):
    root = DOM(html).root
    found = {}

    def add(raw, description, score):
        if not raw or not VIDEO_WORDS.search(description):
            return
        try:
            url = public_url(raw, page_url)
        except ValueError:
            return
        if not re.search(r'\.(mp4|webm)$', urlsplit(url).path, re.I):
            return
        record = {'url': url, 'evidence': description[:200], 'score': score}
        if url not in found or score > found[url]['score']:
            found[url] = record

    def walk(node, context=''):
        if node.tag in ('section', 'figure'):
            heading = next((c for c in node.children if isinstance(c, Node) and c.tag in ('h1', 'h2', 'h3', 'figcaption')), None)
            context = ' '.join([node.attrs.get('id', ''), heading.text() if heading else ''])
        if node.tag == 'video':
            sources = [node.attrs.get('src'), node.attrs.get('data-src')]
            sources += [s.attrs.get('src') or s.attrs.get('data-src') for s in node.find_all(tag='source')]
            for src in filter(None, sources):
                own = ' '.join([node.attrs.get('aria-label', ''), node.attrs.get('title', ''), node.attrs.get('id', ''), src])
                add(src, own if VIDEO_WORDS.search(own) else context, 100 if VIDEO_WORDS.search(own) else 60)
        for child in node.children:
            if isinstance(child, Node):
                walk(child, context)
    walk(root)
    for script in root.find_all(tag='script'):
        code = ''.join(c for c in script.children if isinstance(c, str))
        # Preserve quoted URLs; ignore examples inside JS comments. Never eval remote code.
        code = JS_TOKENS.sub(lambda m: m.group(1) or '', code)
        for match in re.finditer(r'''\b((?:method|overview|teaser|presentation|explanation)Video)\s*:\s*\{[^{}]*?\bsrc\s*:\s*(['"])([^'"\n]+)\2''', code, re.I):
            add(match.group(3), match.group(1), 110)
    return sorted(found.values(), key=lambda c: -c['score'])


def fetch_page(url):
    with urlopen(Request(public_url(url), headers={'User-Agent': 'AcademicProjectVideoDiscovery/1.0'}), timeout=25) as response:
        public_url(response.url)
        if response.headers.get_content_type() not in ('text/html', 'application/xhtml+xml'):
            raise ValueError('Project URL did not return HTML')
        data = response.read(2_000_001)
        if len(data) > 2_000_000:
            raise ValueError('Project HTML exceeds size limit')
        return data.decode(response.headers.get_content_charset() or 'utf-8', errors='replace'), response.url


def verify_video(url):
    with urlopen(Request(public_url(url), method='HEAD'), timeout=25) as response:
        public_url(response.url)
        if response.headers.get_content_type() not in ('video/mp4', 'video/webm'):
            raise ValueError('Video URL did not return MP4/WebM media')


def synchronize(papers, previous, get_page=fetch_page, check_video=verify_video):
    records, warnings = {}, []
    for paper in papers:
        project = next((l['url'] for l in paper['links'] if l['label']['en'].casefold() in ('project', 'project page')), None)
        if not project:
            continue
        old = previous.get(paper['id'], {})
        try:
            html, resolved = get_page(public_url(project))
            choices = candidates(html, resolved)
            if choices:
                # Equal-confidence candidates need editorial choice; never pick a random demo.
                if len(choices) > 1 and choices[0]['score'] == choices[1]['score']:
                    raise ValueError('Multiple equally likely overview videos; needs review')
                selected = choices[0]
                check_video(selected['url'])
                records[paper['id']] = {'project_url': project, 'status': 'available', 'video': selected}
            else:
                records[paper['id']] = {'project_url': project, 'status': 'no_supported_video'}
        except (OSError, ValueError) as exc:
            # A temporary outage must not erase a previously verified preview.
            records[paper['id']] = dict(old) if old.get('project_url') == project else {'project_url': project}
            records[paper['id']]['status'] = 'check_failed'
            warnings.append(f"{paper['id']}: {exc}")
    return records, warnings


def run(root):
    path = root / '_data/project_videos.json'
    previous = json.loads(path.read_text()) if path.exists() else {}
    papers = json.loads((root / '_data/publications.json').read_text())
    records, warnings = synchronize(papers, previous)
    write_json(path, records)
    status = {'last_attempt': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'warnings': warnings,
              'available': [pid for pid, r in records.items() if r.get('video')]}
    write_json(root / '_data/project_video_sync.json', status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    raise SystemExit(run(parser.parse_args().root))
