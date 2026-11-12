#!/usr/bin/env python3
"""Synchronize the configured arXiv author's official Atom feed."""
import argparse
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import unicodedata
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET
from zoneinfo import ZoneInfo

from site_data import ROOT, write_json

NS = {'a': 'http://www.w3.org/2005/Atom', 'x': 'http://arxiv.org/schemas/atom',
      'o': 'http://a9.com/-/spec/opensearch/1.1/'}
ID_PATTERN = r'(?:\d{4}\.\d{4,5}|[a-z-]+(?:\.[A-Z]{2})?/\d{7})'


class SyncError(Exception):
    pass


def normalized(text):
    return ''.join(c for c in unicodedata.normalize('NFKC', text).casefold() if c.isalnum())


def load_author(root=ROOT):
    author = json.loads((root / '_data/arxiv_author.json').read_text())
    identifier = author.get('identifier', '')
    if not re.fullmatch(r'[a-z]+_[a-z]+_[1-9]\d*|\d{4}-\d{4}-\d{4}-\d{3}[\dX]', identifier):
        raise SyncError('Invalid arXiv author identifier')
    if not isinstance(author.get('name'), str) or not author['name'].strip():
        raise SyncError('Expected author name is missing')
    if author.get('orcid') and not re.fullmatch(r'\d{4}-\d{4}-\d{4}-\d{3}[\dX]', author['orcid']):
        raise SyncError('Invalid expected ORCID')
    return dict(author, url='https://arxiv.org/a/' + identifier,
                feed_url='https://arxiv.org/a/' + identifier + '.atom')


def same_arxiv_url(value, expected):
    p, target = urlsplit(value), urlsplit(expected)
    return (p.scheme in ('https', 'http') and p.netloc == 'arxiv.org' and
            p.path == target.path and not p.query and not p.fragment)


def parse_article_id(value):
    p = urlsplit(value)
    if p.scheme not in ('https', 'http') or p.netloc != 'arxiv.org':
        raise SyncError('Article ID is not an arXiv URL')
    match = re.fullmatch('/abs/(' + ID_PATTERN + r')(?:v([1-9]\d*))?', p.path)
    if not match or p.query or p.fragment:
        raise SyncError('Invalid arXiv article ID')
    return match[1], int(match[2] or 1)


def timestamp(value):
    try:
        date = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if date.tzinfo is None:
            raise ValueError('Missing timezone')
        return date.astimezone(timezone.utc).isoformat(timespec='seconds')
    except (ValueError, TypeError, AttributeError) as exc:
        raise SyncError('Invalid arXiv timestamp') from exc


def parse_feed(xml, author):
    if re.search(r'<!DOCTYPE|<!ENTITY', xml, re.I):
        raise SyncError('Unexpected XML declarations')
    try:
        feed = ET.fromstring(xml)
    except ET.ParseError as exc:
        raise SyncError('arXiv did not return a valid Atom feed') from exc
    if feed.tag != '{' + NS['a'] + '}feed':
        raise SyncError('arXiv did not return an Atom feed')
    if not same_arxiv_url(feed.findtext('a:id', '', NS), author['url']):
        raise SyncError('Atom feed belongs to a different author identifier')
    title = feed.findtext('a:title', '', NS)
    if normalized(title) != normalized(author['name'] + "'s articles on arXiv"):
        raise SyncError('Atom feed author name does not match')
    if author.get('orcid'):
        described = [urlsplit(link.get('href', '')) for link in feed.findall('a:link', NS)
                     if link.get('rel') == 'describes']
        if not any(p.netloc == 'orcid.org' and p.path.strip('/') == author['orcid'] for p in described):
            raise SyncError('Atom feed ORCID does not match')
    if any(link.get('rel') == 'next' for link in feed.findall('a:link', NS)):
        raise SyncError('Paginated author feed; refusing an incomplete snapshot')
    entries = feed.findall('a:entry', NS)
    if not entries:
        raise SyncError('Author feed contains no papers; existing catalogue is retained')
    total = feed.findtext('o:totalResults', None, NS)
    if total is not None and (not total.isdigit() or int(total) != len(entries)):
        raise SyncError('Author feed entry count is incomplete')
    rows, warnings, seen = [], [], set()
    for entry in entries:
        raw_id = entry.findtext('a:id', '', NS)
        try:
            aid, version = parse_article_id(raw_id)
        except SyncError as exc:
            warnings.append(f'{raw_id or "missing ID"}: {exc}')
            continue
        if aid in seen:
            raise SyncError('Repeated arXiv ID in author feed')
        seen.add(aid)
        try:
            text = lambda key: ' '.join(entry.findtext(key, '', NS).split())
            names = [' '.join(a.findtext('a:name', '', NS).split()) for a in entry.findall('a:author', NS)]
            if not text('a:title') or not names or any(not n or '…' in n or '...' in n for n in names):
                raise SyncError('Missing title or complete author list')
            if normalized(author['name']) not in {normalized(n) for n in names}:
                raise SyncError('Configured author is absent from this article')
            published, updated = timestamp(text('a:published')), timestamp(text('a:updated'))
            if updated < published:
                raise SyncError('Updated timestamp precedes first publication')
            rows.append({'id': aid, 'version': version, 'title': text('a:title'), 'authors': names,
                         'published': published, 'updated': updated, 'url': 'https://arxiv.org/abs/' + aid,
                         'journal_ref': text('x:journal_ref'), 'doi': text('x:doi'),
                         'categories': [c.get('term') for c in entry.findall('a:category', NS) if c.get('term')]})
        except SyncError as exc:
            warnings.append(f'{aid}: {exc}')
    if not rows:
        raise SyncError('No valid author-feed entries: ' + '; '.join(warnings))
    return rows, warnings


def fetch(url):
    req = Request(url, headers={'User-Agent': 'AcademicHomepageArxivSync/1.0 (+https://lextran.github.io/)',
                               'Accept': 'application/atom+xml'})
    with urlopen(req, timeout=30) as response:
        if not same_arxiv_url(response.url, url):
            raise SyncError('Author feed redirected to an unexpected URL')
        raw = response.read(4_000_001)
        if len(raw) > 4_000_000:
            raise SyncError('Author feed exceeds size limit')
        return raw.decode('utf-8-sig')


def collect_rows(author, get_xml=None):
    return parse_feed((get_xml or fetch)(author['feed_url']), author)


def match_paper(papers, row):
    matches = [p for p in papers if p.get('arxiv_id') == row['id']]
    if not matches:
        matches = [p for p in papers if normalized(row['title']) in
                   {normalized(t) for t in [p['title']] + p.get('aliases', [])}]
        if any(p.get('arxiv_id') and p['arxiv_id'] != row['id'] for p in matches):
            raise SyncError('Title matches a different arXiv ID')
    if len(matches) > 1:
        raise SyncError('Ambiguous duplicate in the publication catalogue')
    return matches[0] if matches else None


def topics_for(title):
    topics = []
    if re.search(r'medical|coronary|ccta|x.ray|vertebra|segmentation|ct scans|ultrasound|orthopedic', title, re.I):
        topics.append('medical')
    if re.search(r'motion.language', title, re.I):
        topics.append('motion')
    if re.search(r'generation|generative|synthesis|video', title, re.I):
        topics.append('generation')
    return topics


def author_records(names, author):
    return [{'name': n, 'self': normalized(n) == normalized(author['name']), 'marks': ''} for n in names]


def preprint_venue(row):
    date = datetime.fromisoformat(row['published'])
    month = ('Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec').split()[date.month - 1]
    return {'en': f'Preprint · First posted {month} {date.year}',
            'zh': f'预印本 · {date.year}.{date.month:02} 首次公开'}


def publication_reference(row):
    ref = row['journal_ref']
    if not ref or re.search(r'arxiv|preprint|under review|submitted|in preparation|withdrawn', ref, re.I):
        return None
    kind = ('conference' if re.search(r'conference|symposium|proceedings', ref, re.I) else
            'journal' if re.search(r'journal|transactions', ref, re.I) else None)
    return {'venue': ref, 'kind': kind, 'confirmed': True, 'source': row['url']}


def merge(papers, rows, author):
    result = copy.deepcopy(papers)
    added, updated, warnings = [], [], []
    for row in rows:
        try:
            paper = match_paper(result, row)
        except SyncError as exc:
            warnings.append(f'{row["id"]}: {exc}')
            continue
        old = copy.deepcopy(paper)
        previous = paper.get('arxiv') if paper else None
        if previous and (row['version'] < previous['version'] or row['updated'] < previous['updated']):
            warnings.append(f'{row["id"]}: stale arXiv version; kept newer metadata')
            continue
        if previous == row:
            continue
        if paper is None:
            paper = {'id': 'paper-' + row['id'].replace('/', '-'), 'title': row['title'],
                     'authors': author_records(row['authors'], author), 'section': 'preprints',
                     'year': int(row['published'][:4]), 'venue': preprint_venue(row),
                     'summary': {'en': '', 'zh': ''}, 'image': None,
                     'links': [{'label': {'en': 'Paper', 'zh': '论文'}, 'url': row['url']}],
                     'topics': topics_for(row['title']), 'arxiv_id': row['id'],
                     'aliases': [], 'locked_fields': []}
            result.append(paper)
            added.append(paper['id'])
        else:
            locks = set(paper.get('locked_fields', []))
            if 'title' not in locks and paper['title'] != row['title']:
                paper['aliases'] = sorted(set(paper.get('aliases', []) + [paper['title']]))
                paper['title'] = row['title']
            if 'authors' not in locks:
                marks = {normalized(a['name']): a.get('marks', '') for a in paper['authors']}
                paper['authors'] = author_records(row['authors'], author)
                for a in paper['authors']:
                    a['marks'] = marks.get(normalized(a['name']), '')
            # An arXiv copy must never undo a curated acceptance or publication.
            if paper['section'] == 'preprints':
                if 'year' not in locks:
                    paper['year'] = int(row['published'][:4])
                if 'venue' not in locks:
                    paper['venue'] = preprint_venue(row)
            paper['arxiv_id'] = row['id']
        locks = set(paper.get('locked_fields', []))
        publication = publication_reference(row)
        if publication and paper['section'] == 'preprints' and not {'section', 'venue'} & locks:
            paper['section'] = 'publications'
            paper['venue'] = {'en': publication['venue'], 'zh': publication['venue']}
            paper['publication'] = publication
            years = set(re.findall(r'\b(?:19|20)\d{2}\b', publication['venue']))
            if len(years) == 1 and 'year' not in locks:
                paper['year'] = int(next(iter(years)))
        paper['arxiv'] = copy.deepcopy(row)
        if old and paper != old:
            updated.append(paper['id'])
    # First submission determines preprint order; a revised old paper stays put.
    def order(p):
        posted = p.get('arxiv', {}).get('published')
        if not posted and re.fullmatch(r'\d{4}\.\d{4,5}', p.get('arxiv_id', '')):
            aid = p['arxiv_id']
            posted = f'20{aid[:2]}-{aid[2:4]}-00'
        return posted or f'{p["year"]:04}-00-00', p.get('arxiv_id', '')
    ordered = iter(sorted((p for p in result if p['section'] == 'preprints'), key=order, reverse=True))
    result = [next(ordered) if p['section'] == 'preprints' else p for p in result]
    return result, added, updated, warnings


def prepare_presentation(root, papers, now):
    from publication_presentation import prepare
    if not (root / '_data/venue_rankings.json').exists():
        return papers, [], []
    def read(name):
        return json.loads((root / '_data' / name).read_text())
    papers, news, state, emitted, review = prepare(
        papers, read('news.json'), read('news_state.json'), read('venue_rankings.json'),
        read('jcr_rankings.json'), datetime.fromisoformat(now).astimezone(ZoneInfo('Asia/Shanghai')).strftime('%Y-%m'))
    write_json(root / '_data/news.json', news)
    write_json(root / '_data/news_state.json', state)
    return papers, emitted, review


def already_synced_today(previous, now, author):
    if previous.get('feed_url') != author['feed_url']:
        return False
    try:
        last, current = datetime.fromisoformat(previous['last_success']), datetime.fromisoformat(now)
        if last.tzinfo is None or last > current:
            return False
        zone = ZoneInfo('Asia/Shanghai')
        return last.astimezone(zone).date() == current.astimezone(zone).date()
    except (KeyError, TypeError, ValueError):
        return False


def run(root=ROOT, daily=False):
    author = load_author(root)
    path = root / '_data/publications.json'
    status_path = root / '_data/arxiv_sync.json'
    papers = json.loads(path.read_text())
    previous = json.loads(status_path.read_text()) if status_path.exists() else {}
    now = datetime.now(timezone.utc).isoformat(timespec='seconds')
    reuse = daily and already_synced_today(previous, now, author)
    same_source = previous.get('feed_url') == author['feed_url']
    status = {'author_identifier': author['identifier'], 'feed_url': author['feed_url'], 'last_check': now,
              'last_attempt': previous.get('last_attempt') if reuse else now,
              'last_success': previous.get('last_success') if same_source else None,
              'status': 'failed', 'added': [], 'updated': [], 'warnings': []}
    result = papers
    if reuse:
        status.update(status='skipped', skip_reason='already_synced_today_Asia/Shanghai')
        for key in ['feed_papers', 'not_in_author_feed']:
            if key in previous:
                status[key] = previous[key]
    else:
        try:
            rows, parse_warnings = collect_rows(author)
            result, added, updated, warnings = merge(papers, rows, author)
            warnings = parse_warnings + warnings
            status.update(status='partial' if warnings else 'success', added=added, updated=updated,
                          warnings=warnings, feed_papers=len(rows),
                          not_in_author_feed=sorted({p['arxiv_id'] for p in papers if p.get('arxiv_id')}
                                                    - {r['id'] for r in rows}))
            if not warnings:
                status['last_success'] = now
        except (SyncError, OSError, ValueError) as exc:
            status['warnings'] = [f'{type(exc).__name__}: {exc}']
    result, emitted, review = prepare_presentation(root, result, now)
    write_json(path, result)
    status.update(catalogue_papers=len(result), acceptance_news_added=emitted, unranked_venues=review)
    write_json(status_path, status)
    summary = (f"arXiv sync: {status['status']}\nAdded: {len(status['added'])}; updated: {len(status['updated'])}.\n"
               f"Author feed: {author['feed_url']}\n")
    if reuse:
        summary += 'Already refreshed successfully today (Asia/Shanghai); reused saved papers.\n'
    print(summary)
    for warning in status['warnings']:
        print('Warning:', warning)
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as f:
            f.write('## arXiv publication synchronization\n\n' + summary.replace('\n', '  \n'))
            for warning in status['warnings']:
                f.write('\n- ' + warning)
    return 0 if status['status'] in ('success', 'skipped') else 2


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--daily', action='store_true', help='Reuse a successful refresh from the same Beijing day')
    parser.add_argument('--presentation-only', action='store_true', help='Rebuild ordering/news without a network request')
    args = parser.parse_args()
    if args.presentation_only:
        path = args.root / '_data/publications.json'
        papers, emitted, review = prepare_presentation(args.root, json.loads(path.read_text()), datetime.now(timezone.utc).isoformat())
        write_json(path, papers)
        print(f'Acceptance news added: {len(emitted)}; unranked venues: {len(review)}')
    else:
        raise SystemExit(run(args.root, daily=args.daily))
