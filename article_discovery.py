"""Discover candidate articles using the local ZIM's title and full-text indexes."""
import re
import time

STOPWORDS = set('what why how when where who which did does do was were is are the a an of to in on for and or about tell me explain describe please give show create make provide construct build list timeline chronology chronological happen happened next most immediate those that these their they them he she his her it one latter former'.split())
GENERIC_ARTICLE_TITLES = {'cause', 'causes', 'caused', 'effects', 'impact', 'begin',
    'start', 'end', 'ended', 'role', 'result', 'results', 'consequences', 'war',
    'history', 'battle', 'battles', 'events', 'collapse', 'collapsed', 'spread',
    'comparison', 'european', 'year', 'beyond', 'revolution'}


def title_key(text):
    return re.sub(r"[^\w ]", '', text.replace('_', ' ').casefold()).strip()


def discover(wiki, question, limit=3):
    from libzim.search import Searcher, Query
    # Phrase matching anchors broad full-text results to named subjects.
    question = re.sub(r"[’']s\b", '', question)
    words = re.findall(r"[\w’']+", question)
    phrases = []
    for size in range(min(6, len(words)), 0, -1):
        for start in range(len(words)-size+1):
            part = words[start:start+size]
            if part[0].casefold() in STOPWORDS or part[-1].casefold() in STOPWORDS:
                continue
            phrase = ' '.join(part)
            if phrase not in phrases:
                phrases.append(phrase)
    titles = []
    generic_titles = GENERIC_ARTICLE_TITLES
    for phrase in phrases[:48]:
        if title_key(phrase) in generic_titles:
            continue
        if any(title_key(phrase) in title_key(path) for path in titles):
            continue
        for path in wiki.search(phrase, limit=5):
            if title_key(path) == title_key(phrase) and path not in titles:
                titles.append(path)
                break
        if len(titles) >= 2:
            break
    query_text = ' '.join(word for word in words if word.casefold() not in STOPWORDS)
    fulltext = []
    if wiki.zim.has_fulltext_index and query_text:
        result = Searcher(wiki.zim).search(Query().set_query(query_text))
        fulltext = list(result.getResults(0, limit*2))
    # Battle chronology benefits from campaign/battle records, not product-title matches.
    if wiki.zim.has_fulltext_index and re.search(r'\bbattles?\b', question, re.I):
        result = Searcher(wiki.zim).search(Query().set_query(query_text + ' military career'))
        fulltext = list(dict.fromkeys(list(result.getResults(0, 1)) + fulltext))
    def canonical(path):
        entry = wiki.zim.get_entry_by_path(path)
        seen = set()
        while entry.is_redirect and entry.path not in seen:
            seen.add(entry.path)
            entry = entry.get_redirect_entry()
        return entry.path
    articles = []
    for path in titles + fulltext:
        resolved = canonical(path)
        if ('%' in resolved or title_key(resolved) in GENERIC_ARTICLE_TITLES or
                (not re.search(r'game|novel|film|album|song', question, re.I) and
                 re.search(r'\((?:wargame|board.game|video.game|novel|film|album|song|disambiguation)\)', resolved, re.I))):
            continue
        if resolved not in articles:
            articles.append(resolved)
        if len(articles) == limit:
            break
    return {'articles': articles, 'title_matches': titles, 'matched_articles': list(dict.fromkeys(canonical(p) for p in titles)), 'fulltext_query': query_text,
            'fulltext_candidates': fulltext, 'fulltext_available': wiki.zim.has_fulltext_index}


def _canonical(wiki, path):
    entry = wiki.zim.get_entry_by_path(path)
    seen = set()
    while entry.is_redirect is True:
        entry_path = entry.path if isinstance(entry.path, str) else path
        if entry_path in seen:
            raise ValueError('Redirect loop')
        seen.add(entry_path)
        entry = entry.get_redirect_entry()
    resolved = entry.path if isinstance(entry.path, str) else path
    return resolved.split('#', 1)[0]


def discover_plan(wiki, plan, config):
    """Merge bounded seed and entity searches while retaining discovery provenance."""
    articles, reasons, title_matches, matched, searches = [], {}, [], [], []
    deadline = time.monotonic() + config.max_discovery_seconds

    def expired():
        return time.monotonic() >= deadline

    def retain(path, reason):
        try:
            canonical = _canonical(wiki, path)
        except (KeyError, RuntimeError, ValueError):
            return None
        normalized_title = title_key(canonical)
        ambiguous_dated_alias = (not plan.date_or_period_hints and re.search(r'\(.*\d{3,4}', canonical) and
            any(normalized_title.startswith(title_key(entity.normalized_name) + ' ')
                for entity in plan.entities))
        if ('%' in canonical or re.sub(r'\s+\d+$', '', normalized_title) in GENERIC_ARTICLE_TITLES or
                ambiguous_dated_alias or
                re.search(r'\((?:wargame|board.game|video.game|novel|film|album|song|disambiguation)\)', canonical, re.I)):
            return None
        reasons.setdefault(canonical, [])
        if reason not in reasons[canonical]:
            reasons[canonical].append(reason)
        if canonical not in articles and len(articles) < plan.article_limit:
            articles.append(canonical)
        return canonical

    # Reserve a small part of a broad pool for explicit entity resolution, so
    # full-text seed results cannot consume the entire fan-out before that stage.
    entity_reserve = min(2, len(plan.entities))
    related_reserve = (min(3, max(0, plan.article_limit-entity_reserve-1))
                       if plan.breadth == 'broad' and plan.article_limit >= 6 else 0)
    seed_limit = plan.article_limit - entity_reserve - related_reserve
    seed_limit = max(1, seed_limit)
    for query_number, query in enumerate(plan.seed_queries):
        if len(articles) >= seed_limit or expired():
            break
        try:
            result = discover(wiki, query, limit=config.articles_per_query)
        except (KeyError, RuntimeError, ValueError):
            searches.append({'query': query, 'error': 'local search unavailable'})
            continue
        searches.append({'query': query, 'articles': result['articles']})
        title_matches.extend(result.get('title_matches', []))
        matched.extend(result.get('matched_articles', []))
        for path in result['articles']:
            if len(articles) >= seed_limit:
                break
            direct = path in result.get('matched_articles', [])
            reason = 'direct title' if direct else ('question search' if query_number == 0 else f'seed query {query_number + 1}')
            retain(path, reason)

    related_expansions = []
    related_limit = plan.article_limit - entity_reserve
    if plan.breadth == 'broad' and hasattr(wiki, 'related_articles'):
        for seed in list(dict.fromkeys(matched + articles))[:config.related_seed_articles]:
            if len(articles) >= related_limit or expired():
                break
            try:
                related = wiki.related_articles(seed, ' '.join(plan.seed_queries),
                                                limit=config.related_articles_per_seed)
            except (KeyError, RuntimeError, ValueError, UnicodeError):
                related = []
            record = {'seed_article': seed, 'candidates': list(related)}
            related_expansions.append(record)
            for path in related:
                if len(articles) >= related_limit:
                    break
                retain(path, f'related from: {seed}')

    entity_resolutions = []
    for entity in plan.entities:
        if len(articles) >= plan.article_limit or expired():
            break
        record = {'entity': entity.to_dict(), 'accepted': [], 'rejected': []}
        try:
            paths = wiki.search(entity.display_name, limit=config.entity_title_candidates)
        except (KeyError, RuntimeError, ValueError):
            paths = []
        for path in paths[:config.entity_title_candidates]:
            canonical = retain(path, f'entity: {entity.display_name}')
            if canonical:
                record['accepted'].append(canonical)
            else:
                record['rejected'].append(str(path))
        entity_resolutions.append(record)

    return {'articles': articles, 'title_matches': list(dict.fromkeys(title_matches)),
            'matched_articles': list(dict.fromkeys(matched)), 'article_reasons': reasons,
            'searches': searches, 'related_expansions': related_expansions,
            'entity_resolutions': entity_resolutions,
            'bounds': {'seed_queries': len(searches), 'entities': len(entity_resolutions),
                       'candidate_articles': len(articles), 'article_limit': plan.article_limit,
                       'time_limit_reached': expired()},
            'fulltext_available': bool(wiki.zim.has_fulltext_index)}
