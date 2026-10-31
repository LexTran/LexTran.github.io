"""Derive publication ordering and idempotent bilingual acceptance news."""
import copy
import re
import unicodedata


def words(value):
    value = unicodedata.normalize('NFKC', value).casefold().replace('&', ' and ')
    value = re.sub(r'\b(?:19|20)\d{2}\b|\b\d+(?:st|nd|rd|th)\b', ' ', value)
    value = re.sub(r'[^\w]+', ' ', value)
    return ' '.join(value.split())


def venue_name(paper):
    publication = paper.get('publication', {})
    return publication.get('venue') or paper['venue']['en'].split(' · ')[0]


def find_ccf(venue, catalogue, kind=None, paper_type=None):
    if kind is None:
        if re.search(r'\b(conference|symposium|proceedings)\b', venue, re.I):
            kind = 'conference'
        elif re.search(r'\b(journal|transactions)\b', venue, re.I):
            kind = 'journal'
    # Findings and companion/workshop papers do not inherit the main venue rank.
    if re.search(r'\b(workshops?|findings|companion|demonstrations?)\b', venue, re.I):
        return None
    if paper_type and paper_type not in ('full', 'regular', 'journal'):
        return None
    key = words(venue)
    bare = re.sub(r'\([^)]*\)', '', venue)
    bare = re.sub(r'^\s*(?:proceedings of\s+(?:the\s+)?|the\s+)', '', bare, flags=re.I)
    keys = {key, words(bare)}
    candidates = []
    for entry in catalogue.get('venues', []):
        if kind in ('journal', 'conference') and entry['kind'] != kind:
            continue
        for alias in [entry['name'], entry['short']] + entry.get('aliases', []):
            a = words(alias)
            if not a:
                continue
            exact = a in keys
            # Never match a full conference name as a prefix of another venue:
            # "...Computer Vision, Image and Deep Learning" is not ICCV.
            distinctive_acronym = (alias == entry['short'] and entry['short'] != entry['name']
                                   and 4 <= len(a.replace(' ', '')) <= 20 and len(a.split()) <= 3)
            acronym_present = re.search(r'(?<!\w)' + re.escape(alias) + r'(?!\w)', venue)
            if exact or (distinctive_acronym and acronym_present):
                candidates.append((10000 + len(a) if exact else len(a), entry))
    if not candidates:
        return None
    score = max(c[0] for c in candidates)
    best = [e for s, e in candidates if s == score]
    if len({(e['name'], e['ccf']) for e in best}) != 1:
        return None
    return best[0]


def verified_jcr(paper, registry):
    venue = words(venue_name(paper))
    entries = list(registry.get('journals', []))
    if paper.get('jcr'):
        entries.append(dict(paper['jcr'], name=venue_name(paper)))
    matched = []
    for entry in entries:
        names = [entry.get('name', '')] + entry.get('aliases', [])
        if venue not in {words(n) for n in names}:
            continue
        # JCR includes non-SCI indexes too; require explicit SCIE verification.
        if ('SCIE' not in entry.get('indexes', []) or not entry.get('source') or
                not entry.get('verified_on') or not isinstance(entry.get('year'), int)):
            continue
        quartiles = [c.get('quartile') for c in entry.get('categories', [])]
        if not quartiles or any(q not in ('Q1', 'Q2', 'Q3', 'Q4') for q in quartiles):
            continue
        matched.append(entry)
    if not matched:
        return None
    entry = max(matched, key=lambda e: e['year'])
    quartile = min(c['quartile'] for c in entry['categories'])
    return dict(entry, quartile=quartile)


def rank_paper(paper, catalogue, jcr):
    if paper['section'] != 'publications':
        return {'priority': 99, 'label': '', 'source': '', 'basis': 'preprint'}
    entry = find_ccf(venue_name(paper), catalogue, paper.get('publication', {}).get('kind'), paper.get('paper_type'))
    if entry:
        return {'priority': {'A': 0, 'B': 1, 'C': 2}[entry['ccf']], 'label': 'CCF ' + entry['ccf'],
                'source': catalogue['source'], 'basis': catalogue['edition'], 'venue': entry['short']}
    journal = verified_jcr(paper, jcr)
    if journal:
        return {'priority': 2 + int(journal['quartile'][1]), 'label': 'SCI / JCR ' + journal['quartile'],
                'source': journal['source'], 'basis': f"JCR {journal['year']} · best category quartile"}
    return {'priority': 7, 'label': '', 'source': '', 'basis': 'unlisted-or-unverified'}


def short_title(paper):
    if paper.get('short_title'):
        return paper['short_title']
    prefix, sep, _ = paper['title'].partition(':')
    if sep and len(prefix) <= 45 and len(prefix.split()) <= 5:
        return prefix
    tokens = paper['title'].split()
    return ' '.join(tokens[:8]) + ('…' if len(tokens) > 8 else '')


def news_venue(paper, catalogue):
    if paper.get('news_venue'):
        return paper['news_venue']
    venue = venue_name(paper)
    entry = find_ccf(venue, catalogue, paper.get('publication', {}).get('kind'))
    kind = paper.get('publication', {}).get('kind') or (entry['kind'] if entry else None)
    if entry:
        label = entry['short']
    else:
        acronym = re.search(r'\(([A-Z][A-Z0-9/-]{2,15})\)', venue)
        label = acronym.group(1) if acronym else venue
    if kind == 'conference' and paper.get('year') and str(paper['year']) not in label:
        label += ' ' + str(paper['year'])
    return label


def acceptance_month(paper, current_month):
    value = paper.get('acceptance_date') or paper.get('publication', {}).get('acceptance_date') or ''
    match = re.match(r'^(\d{4})[-/](\d{1,2})(?:[-/]\d{1,2})?$', value)
    if match and 1 <= int(match.group(2)) <= 12:
        return f'{match.group(1)}-{int(match.group(2)):02}', 'acceptance'
    return current_month, 'announcement'


def prepare(papers, news, state, catalogue, jcr, month):
    papers, news, state = copy.deepcopy(papers), copy.deepcopy(news), copy.deepcopy(state)
    seen = set(state.get('known_publications', []))
    seen.update(n['paper_id'] for n in news if n['type'] == 'acceptance')
    added, review = [], []
    for paper in papers:
        paper['short_title'] = short_title(paper)
        paper['ranking'] = rank_paper(paper, catalogue, jcr)
        if paper['section'] != 'publications':
            continue
        if paper['ranking']['priority'] == 7:
            review.append(paper['id'])
        if paper['id'] in seen:
            continue
        # A local editorial publication entry is explicit user confirmation.
        # Automatic entries need a formal Journal/Conference/Book detail field.
        editorial_acceptance = bool(paper.get('acceptance_date')) or bool(re.search(
            r'\baccepted\b|录用|接收', paper['venue']['en'] + paper['venue']['zh'], re.I))
        formal = not paper.get('scholar') or paper.get('publication', {}).get('confirmed', False) or editorial_acceptance
        if not formal:
            continue
        date, basis = acceptance_month(paper, month)
        event = {'id': 'accepted-' + paper['id'], 'type': 'acceptance', 'paper_id': paper['id'],
                 'month': date, 'date_basis': basis, 'short_title': paper['short_title'],
                 'venue': news_venue(paper, catalogue), 'celebrate': True,
                 'source': paper.get('scholar', {}).get('url', 'editorial')}
        news.insert(0, event)
        added.append(event['id'])
        seen.add(paper['id'])
    # Keep existing announcements up to date without adding a second event.
    by_id = {p['id']: p for p in papers}
    for event in news:
        if event['type'] == 'acceptance' and event['paper_id'] in by_id:
            p = by_id[event['paper_id']]
            event['short_title'] = p['short_title']
            event['venue'] = news_venue(p, catalogue)
    ordered = sorted((p for p in papers if p['section'] == 'publications'),
                     key=lambda p: (p['ranking']['priority'], -p['year']))
    for order, paper in enumerate(ordered):
        paper['publication_order'] = order
    news.sort(key=lambda n: n['month'], reverse=True)
    state['known_publications'] = sorted(seen)
    return papers, news, state, added, review
