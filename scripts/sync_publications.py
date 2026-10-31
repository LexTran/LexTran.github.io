#!/usr/bin/env python3
"""Conservative synchronization of one verified public Scholar profile.

No login, CAPTCHA bypass, proxy rotation, or deletion of missing papers.
The public catalogue keeps editorial fields separate from observed metadata.
"""
import argparse
import copy
from datetime import datetime, timezone
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import time
import unicodedata
from urllib.parse import parse_qs, urlencode, urljoin, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
PROFILE_ID = 'wtordYAAAAAJ'
PROFILE_URL = 'https://scholar.google.com/citations?user=' + PROFILE_ID


class SyncError(Exception):
    pass


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return ' '.join(''.join(c.text() if isinstance(c, Node) else c for c in self.children).split())

    def find_all(self, tag=None, cls=None, id=None):
        found = []
        for child in self.children:
            if not isinstance(child, Node):
                continue
            if ((tag is None or child.tag == tag) and
                (cls is None or cls in child.attrs.get('class', '').split()) and
                (id is None or child.attrs.get('id') == id)):
                found.append(child)
            found.extend(child.find_all(tag, cls, id))
        return found

    def one(self, **kwargs):
        return next(iter(self.find_all(**kwargs)), None)


class DOM(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = Node()
        self.stack = [self.root]
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def safe_url(url):
    parts = urlsplit(url)
    if parts.scheme not in ('https', 'http') or not parts.netloc or parts.username:
        raise SyncError('Invalid scholarly link')
    return url


def arxiv_id(text):
    match = re.search(r'\b(\d{4}\.\d{4,5})(?:v\d+)?\b', text)
    return match.group(1) if match else ''


def parse_profile(html):
    root = DOM(html).root
    name, verified = root.one(id='gsc_prf_in'), root.one(id='gsc_prf_ivh')
    if not name or normalized(name.text()) != 'lixingtan':
        title = root.one(tag='title')
        page_title = title.text()[:100] if title else '(no title)'
        raise SyncError(f'Scholar profile missing or identity mismatch; response title: {page_title}')
    if not verified or not re.search(r'\bVerified email at buaa\.edu\.cn\b', verified.text(), re.I):
        raise SyncError('Scholar verified Beihang email domain is missing')
    rows = []
    for tr in root.find_all(cls='gsc_a_tr'):
        title = tr.one(cls='gsc_a_at')
        gray = tr.find_all(cls='gs_gray')
        year_node = tr.one(cls='gsc_a_y')
        if not title or len(gray) < 2:
            raise SyncError('Incomplete Scholar publication row')
        detail_url = urljoin(PROFILE_URL, title.attrs.get('href', ''))
        query = parse_qs(urlsplit(detail_url).query)
        citation = query.get('citation_for_view', [''])[0]
        if not citation.startswith(PROFILE_ID + ':') or query.get('user') != [PROFILE_ID]:
            raise SyncError('Citation belongs to a different Scholar profile')
        year = year_node.text() if year_node else ''
        # The visible venue includes a separate ', YEAR' span.
        venue = re.sub(r',\s*' + re.escape(year) + r'\s*$', '', gray[1].text()) if year else gray[1].text()
        rows.append({'id': citation, 'title': title.text(), 'authors': gray[0].text(),
                     'venue': venue, 'year': int(year) if year.isdigit() else 0,
                     'url': 'https://scholar.google.com/citations?' + urlencode({
                         'view_op': 'view_citation', 'hl': 'en', 'user': PROFILE_ID,
                         'citation_for_view': citation})})
    if not rows:
        raise SyncError('Scholar returned no papers; existing catalogue is retained')
    more = root.one(id='gsc_bpf_more')
    has_more = more is not None and 'disabled' not in more.attrs
    return rows, has_more


def parse_detail(html, row):
    root = DOM(html).root
    title = root.one(id='gsc_oci_title')
    if not title or normalized(title.text()) != normalized(row['title']):
        raise SyncError('Scholar detail is unavailable or has an unexpected title')
    fields = {}
    for node in root.find_all(cls='gs_scl'):
        key, value = node.one(cls='gsc_oci_field'), node.one(cls='gsc_oci_value')
        if key and value:
            fields[key.text()] = value.text()
    authors = fields.get('Authors', '')
    if not authors or '…' in authors or '...' in authors:
        raise SyncError('Complete author list unavailable')
    venue = next((fields[k] for k in ('Journal', 'Conference', 'Book', 'Source') if fields.get(k)), row['venue'])
    if not venue or '…' in venue or '...' in venue:
        raise SyncError('Complete publication venue unavailable')
    year_match = re.match(r'(\d{4})', fields.get('Publication date', ''))
    link = root.one(cls='gsc_oci_title_link')
    paper_url = safe_url(link.attrs['href']) if link and link.attrs.get('href') else row['url']
    return {'title': row['title'], 'authors': [a.strip() for a in re.split(r',|;', authors) if a.strip()],
            'venue': venue, 'year': int(year_match.group(1)) if year_match else row['year'],
            'paper_url': paper_url, 'publication_date': fields.get('Publication date', '')}


def section_for(venue):
    if re.search(r'arxiv|biorxiv|medrxiv|preprint|under review|submitted', venue, re.I):
        return 'preprints'
    return 'publications' if venue.strip() else None


def match_paper(papers, row):
    for p in papers:
        if p.get('scholar', {}).get('id') == row['id']:
            return p
    aid = arxiv_id(row['venue'])
    matches = [p for p in papers if (aid and p.get('arxiv_id') == aid) or
               normalized(row['title']) in {normalized(t) for t in [p['title']] + p.get('aliases', [])}]
    if len(matches) > 1:
        raise SyncError('Ambiguous duplicate in local publication catalogue')
    return matches[0] if matches else None


def topics_for(title):
    topics = []
    if re.search(r'medical|coronary|ccta|x.ray|vertebra|segmentation|ct scans', title, re.I):
        topics.append('medical')
    if re.search(r'motion.language', title, re.I):
        topics.append('motion')
    if re.search(r'generation|generative|synthesis|video', title, re.I):
        topics.append('generation')
    return topics


def display_venue(detail, section):
    if section == 'preprints':
        return {'en': 'Preprint' + (f" · {detail['year']}" if detail['year'] else ''),
                'zh': '预印本' + (f" · {detail['year']}" if detail['year'] else '')}
    venue = detail['venue']
    if detail['year'] and str(detail['year']) not in venue:
        venue += ' · ' + str(detail['year'])
    return {'en': venue, 'zh': venue}


def author_records(names):
    return [{'name': 'Lixing Tan' if normalized(n) in ('ltan', 'lixingtan', 'tanlixing') else n,
             'self': normalized(n) in ('ltan', 'lixingtan', 'tanlixing'), 'marks': ''} for n in names]


def merge(papers, rows, get_detail):
    result = copy.deepcopy(papers)
    added, updated, warnings = [], [], []
    for row in rows:
        paper = match_paper(result, row)
        if paper and paper.get('scholar') == row:
            continue
        old = copy.deepcopy(paper)
        previous = paper.get('scholar') if paper else None
        promotion = bool(paper and paper['section'] == 'preprints' and section_for(row['venue']) == 'publications')
        # Existing curated records do not require a full fetch unless metadata changes.
        needs_detail = paper is None or promotion or bool(previous and previous != row)
        detail = None
        if needs_detail:
            try:
                detail = get_detail(row)
            except (SyncError, OSError, ValueError) as exc:
                warnings.append(f"{row['id']}: {type(exc).__name__}: {exc}")
                continue  # Keep old metadata, so the next run retries the detail request.
        if paper is None:
            section = section_for(detail['venue'])
            if not section:
                warnings.append(f"{row['id']}: publication status unknown")
                continue
            paper = {'id': 'paper-scholar-' + row['id'].split(':', 1)[1], 'title': detail['title'],
                     'authors': author_records(detail['authors']), 'section': section, 'year': detail['year'],
                     'venue': display_venue(detail, section), 'summary': {'en': '', 'zh': ''}, 'image': None,
                     'links': [{'label': {'en': 'Paper', 'zh': '论文'}, 'url': detail['paper_url']}],
                     'topics': topics_for(detail['title']), 'arxiv_id': arxiv_id(detail['venue']),
                     'aliases': [], 'locked_fields': []}
            result.append(paper)
            added.append(paper['id'])
        elif detail:
            locks = set(paper.get('locked_fields', []))
            if 'title' not in locks:
                if paper['title'] != detail['title']:
                    paper['aliases'] = sorted(set(paper.get('aliases', []) + [paper['title']]))
                paper['title'] = detail['title']
            if 'authors' not in locks:
                marks = {normalized(a['name']): a['marks'] for a in paper['authors']}
                paper['authors'] = author_records(detail['authors'])
                for author in paper['authors']:
                    author['marks'] = marks.get(normalized(author['name']), '')
            new_section = section_for(detail['venue'])
            # Accepted/published records never regress when Scholar lists an arXiv version.
            if new_section == 'publications' and 'section' not in locks:
                paper['section'] = new_section
            venue_changed = not previous or previous['venue'] != row['venue'] or previous['year'] != row['year']
            if 'venue' not in locks and paper['section'] == new_section and (promotion or venue_changed):
                paper['venue'] = display_venue(detail, paper['section'])
            if 'year' not in locks:
                paper['year'] = detail['year'] or paper['year']
            if 'links' not in locks:
                links = [l for l in paper['links'] if l['label']['en'] != 'Paper']
                paper['links'] = [{'label': {'en': 'Paper', 'zh': '论文'}, 'url': detail['paper_url']}] + links
        paper['scholar'] = row
        if old and old != paper:
            updated.append(paper['id'])
    result.sort(key=lambda p: -p['year'])  # Stable within a year: preserves curated order.
    return result, added, updated, warnings


def fetch(url):
    req = Request(url, headers={'User-Agent': 'AcademicHomepageSync/1.0 (+https://lextran.github.io/)',
                               'Accept-Language': 'en-US,en;q=0.9'})
    with urlopen(req, timeout=30) as response:
        if urlsplit(response.url).hostname != 'scholar.google.com':
            raise SyncError('Scholar redirected away from its public site; no login attempted')
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise SyncError('Unexpectedly large Scholar response')
        return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')


def collect_rows(get_html=fetch):
    rows, seen = [], set()
    for page in range(10):
        if page:
            time.sleep(3)
        url = 'https://scholar.google.com/citations?' + urlencode({
            'user': PROFILE_ID, 'hl': 'en', 'cstart': page * 100, 'pagesize': 100})
        batch, more = parse_profile(get_html(url))
        ids = {r['id'] for r in batch}
        if seen & ids or len(ids) != len(batch):
            raise SyncError('Repeated Scholar pagination; refusing an incomplete snapshot')
        rows.extend(batch)
        seen.update(ids)
        if not more:
            return rows
    raise SyncError('Scholar pagination limit reached')


def write_json(path, data):
    text = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    if path.exists() and path.read_text() == text:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    temp.write_text(text)
    temp.replace(path)


def run(root=ROOT):
    catalogue = root / '_data/publications.json'
    status_path = root / '_data/scholar_sync.json'
    papers = json.loads(catalogue.read_text())
    previous = json.loads(status_path.read_text()) if status_path.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    status = {'profile': PROFILE_URL, 'last_attempt': now, 'last_success': previous.get('last_success'),
              'status': 'failed', 'added': [], 'updated': [], 'warnings': []}
    try:
        rows = collect_rows()
        def detail(row):
            time.sleep(3)
            return parse_detail(fetch(row['url']), row)
        result, added, updated, warnings = merge(papers, rows, detail)
        write_json(catalogue, result)
        status.update(status='partial' if warnings else 'success', added=added, updated=updated,
                      warnings=warnings, profile_papers=len(rows), catalogue_papers=len(result))
        if not warnings:
            status['last_success'] = now
    except (SyncError, OSError, ValueError) as exc:
        status['warnings'] = [f'{type(exc).__name__}: {exc}']
    write_json(status_path, status)
    summary = (f"Scholar sync: {status['status']}\n"
               f"Added: {len(status['added'])}; updated: {len(status['updated'])}.\n"
               f"Profile: {PROFILE_URL}\n")
    print(summary)
    for warning in status['warnings']:
        print('Warning:', warning)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write('## Publication synchronization\n\n' + summary.replace('\n', '  \n'))
            if status['warnings']:
                f.write('\nThe previous records were retained for unavailable items. See the sync log.\n')
    return 0 if status['status'] == 'success' else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    raise SystemExit(run(args.root))
