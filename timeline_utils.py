"""Conservative dated evidence extraction. Sort keys never replace source precision."""
import calendar
import re

MONTHS = {name.lower(): i for i, name in enumerate(calendar.month_name) if name}
MONTH_PATTERN = '(?:' + '|'.join(calendar.month_name[1:]) + ')'
YEAR = r'(?<![\d,])(?:\d{1,4}\s*(?:BCE|BC|CE|AD)\b|[12]\d{3}s?|(?<=in )\d{3})(?!\d|,\d)'
DATE_RE = re.compile(r'(?:c\.\s*|circa\s+|about\s+|around\s+|approximately\s+)?(?:'
                     + MONTH_PATTERN + r'\s+\d{1,2}(?:st|nd|rd|th)?,?\s+\d{1,4}(?:\s*(?:BCE|BC|CE|AD))?'
                     + r'|\d{1,2}(?:st|nd|rd|th)?\s+' + MONTH_PATTERN + r',?\s+\d{1,4}(?:\s*(?:BCE|BC|CE|AD))?'
                     + r'|' + MONTH_PATTERN + r'\s+\d{3,4}'
                     + r'|' + YEAR + r'(?:\s*[–−-]\s*\d{3,4}(?:\s*(?:BCE|BC|CE|AD))?)?'
                     + r')', re.I)


def normalize_date(text):
    match = DATE_RE.search(text)
    if not match:
        return None
    date_text = match.group().strip()
    numbers = re.findall(r'\d+', date_text)
    month_match = re.search(MONTH_PATTERN, date_text, re.I)
    year = int(numbers[-1] if month_match else numbers[0])
    if not year:
        return None
    if re.search(r'\b(?:BCE|BC)\b', date_text, re.I):
        year = -year
    month = MONTHS[month_match.group().lower()] if month_match else 0
    day = int(numbers[0]) if month_match and len(numbers) > 1 else 0
    if day and not 1 <= day <= calendar.monthrange(abs(year), month)[1]:
        return None
    approx = bool(re.match(r'c\.|circa|about|around|approximately', date_text, re.I))
    precision = 'day' if day else 'month' if month else 'year'
    if date_text.endswith('s'):
        precision = 'decade'
    if not month and len(numbers) > 1:
        precision = 'range'
    tail = text[match.end():]
    separator = re.match(r'\s*[–−-]\s*', tail)
    if separator:
        end_date = DATE_RE.match(tail[separator.end():])
        if end_date:
            date_text += tail[:separator.end()] + end_date.group()
            precision = 'range'
    return {'date_text': date_text, 'sortable_date': [year, month, day],
            'precision': precision, 'approximate': approx}


def extract_events(hits, max_events=24, bounds=None):
    events, seen = [], set()
    for hit in hits:
        c = hit['chunk']
        heading = c.get('subsection') or c.get('section', '')
        heading_date = normalize_date(heading) if re.fullmatch(r'\d{3,4}', heading.strip()) else None
        for paragraph in c['text'].split('\n'):
            previous = ''
            sentences = re.split(r'(?<=[.!?])\s+(?=[A-Z])', paragraph.strip())
            for number, sentence in enumerate(sentences):
                if not sentence:
                    continue
                supporting_context = previous
                previous = sentence
                date_input = sentence.split(';', 1)[0] if sentence.startswith('Date:') else sentence
                # A partial day/month followed by a historical reference year is not
                # a dated event (e.g. 'On 19 August ... his 1617 election').
                partial = re.match(r'(?:On |By )?\d{1,2}\s+' + MONTH_PATTERN + r',', sentence, re.I)
                if partial:
                    continue
                date = normalize_date(date_input)
                inherited = False
                if date is None and heading_date:
                    # A dated section gives a year, not an invented month/day.
                    date = dict(heading_date)
                    inherited = True
                if date is None:
                    continue
                if bounds and not bounds[0] <= date['sortable_date'][0] <= bounds[1]:
                    continue
                event_text = sentence
                if number+1 < len(sentences) and normalize_date(sentences[number+1]) is None:
                    event_text += ' ' + sentences[number+1]
                key = re.sub(r'\s+', ' ', event_text).casefold()
                if key in seen:
                    continue
                seen.add(key)
                events.append(dict(date, event=event_text, source_article=c['article_path'],
                                   section=c['section'], subsection=c.get('subsection'),
                                   chunk_id=c['chunk_id'], score=hit['score'], heading_date=inherited,
                                   supporting_context=supporting_context))
    events.sort(key=lambda e: (*e['sortable_date'], e['source_article'], e['chunk_id']))
    if len(events) > max_events:
        def salience(event):
            text = event['event'].lower()
            milestones = sum(bool(re.search(pattern, text)) for pattern in (
                r'defenestrat|assassinat|outbreak|revolt|rebellion',
                r'war began|war ended|ending the war|peace|treaty|signed',
                r'battle|siege|invad|landed|interven|surrender'))
            return event['score'] + .12*milestones
        # Reserve the strongest passage per year, then fill the remaining budget.
        # This retains dated milestones instead of uniformly sampling incidental dates.
        by_year = {}
        for event in events:
            year = event['sortable_date'][0]
            if year not in by_year or salience(event) > salience(by_year[year]):
                by_year[year] = event
        candidates = sorted(by_year.values(), key=salience, reverse=True)
        chosen = candidates[:max_events]
        chosen_ids = {id(event) for event in chosen}
        rest = sorted((e for e in events if id(e) not in chosen_ids), key=salience, reverse=True)
        chosen.extend(rest[:max_events-len(chosen)])
        events = sorted(chosen, key=lambda e: (*e['sortable_date'], e['source_article'], e['chunk_id']))
    return events


def event_hits(events):
    """Each event retains its parent chunk ID; provenance survives chronological sorting."""
    return [{'score': e['score'], 'chunk': {'chunk_id': e['chunk_id'], 'article_path': e['source_article'],
             'section': e['section'], 'subsection': e.get('subsection'),
             'text': (('Preceding source sentence: ' + e.get('supporting_context', '') + '\n') if e.get('supporting_context') else '') +
                     ('Dated passage: ' + e['event'] if not e['heading_date'] else e['date_text'] + ' — ' + e['event']),
             'date_text': e['date_text'], 'date_precision': e['precision'],
             'approximate': e['approximate'], 'sortable_date': e['sortable_date']}}
            for e in events]


def infer_period(index, analysis, config):
    """Use explicit query dates or an article's stated span; never invent event dates."""
    if analysis.anchor_year is not None:
        return (analysis.anchor_year, analysis.anchor_year + config.continuation_year_window)
    pattern = r'(?:between|from)\s+(\d{3,4})\s+(?:and|to|[–-])\s+(\d{3,4})'
    match = re.search(pattern, analysis.question, re.I)
    if match:
        return tuple(map(int, match.groups()))
    query_words = set(re.findall(r'\w+', analysis.retrieval_query.lower()))
    for c in index['chunks']:
        title_words = set(re.findall(r'\w+', c['article_path'].replace('_', ' ').lower()))
        if c['section'] == 'Introduction' and title_words <= query_words:
            match = re.search(pattern, c['text'][:1000], re.I)
            if match:
                return tuple(map(int, match.groups()))
    return None
