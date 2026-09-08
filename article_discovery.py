"""Discover candidate articles using the local ZIM's title and full-text indexes."""
import re

STOPWORDS = set('what why how when where who which did does do was were is are the a an of to in on for and or about tell me explain describe please give show create make provide construct build list timeline chronology chronological happen happened next most immediate those that these their they them he she his her it one latter former'.split())


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
    generic_titles = {'cause', 'causes', 'caused', 'effects', 'impact', 'begin', 'start', 'end', 'ended', 'role', 'result', 'results', 'consequences', 'war', 'history', 'battle', 'battles', 'events'}
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
        if not re.search(r'game|novel|film|album|song', question, re.I) and re.search(r'\((?:wargame|board.game|video.game|novel|film|album|song|disambiguation)\)', resolved, re.I):
            continue
        if resolved not in articles:
            articles.append(resolved)
        if len(articles) == limit:
            break
    return {'articles': articles, 'title_matches': titles, 'matched_articles': list(dict.fromkeys(canonical(p) for p in titles)), 'fulltext_query': query_text,
            'fulltext_candidates': fulltext, 'fulltext_available': wiki.zim.has_fulltext_index}
