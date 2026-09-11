from libzim.reader import Archive
from libzim.suggestion import SuggestionSearcher
from bs4 import BeautifulSoup
from urllib.parse import unquote
import re


class LocalWikipedia:
    def __init__(self, zim_path):
        self.zim = Archive(zim_path)

    def search(self, query, limit=10):
        searcher = SuggestionSearcher(self.zim)
        search = searcher.suggest(query)

        return list(search.getResults(0, limit))

    def get_article(self, article_path):
        entry = self.zim.get_entry_by_path(article_path)
        item = entry.get_item()

        html = bytes(item.content).decode("utf-8")
        soup = BeautifulSoup(html, "html.parser")

        content = soup.find("div", id="mw-content-text")

        if content is None:
            raise RuntimeError(
                f"Could not find article content for: {article_path}"
            )

        for element in content.find_all([
            "script",
            "style",
            "table",
            "sup",
            "nav",
            "figure",
        ]):
            element.decompose()

        blocks = []

        for element in content.find_all(["h2", "h3", "p"]):
            text = element.get_text(" ", strip=True)

            if not text:
                continue

            if element.name == "h2":
                block_type = "h2"
            elif element.name == "h3":
                block_type = "h3"
            else:
                block_type = "p"

            blocks.append({
                "type": block_type,
                "text": text,
            })

        return blocks

    def related_articles(self, article_path, query, limit=6):
        """Return a bounded, relevance-ranked set of one-hop local article links."""
        if limit < 1:
            return []
        entry = self.zim.get_entry_by_path(article_path)
        seen_redirects = set()
        while entry.is_redirect:
            if entry.path in seen_redirects:
                return []
            seen_redirects.add(entry.path)
            entry = entry.get_redirect_entry()
        soup = BeautifulSoup(bytes(entry.get_item().content).decode('utf-8'), 'html.parser')
        content = soup.find('div', id='mw-content-text')
        if content is None:
            return []
        query_words = set(re.findall(r'\w+', query.casefold())) - {
            'the', 'a', 'an', 'of', 'to', 'in', 'what', 'why', 'how', 'did', 'does',
            'cause', 'caused', 'causes', 'after', 'before', 'and', 'or'}
        cue_words = {'crisis', 'conflict', 'reform', 'revolution', 'war', 'treaty',
                     'political', 'military', 'social', 'economic', 'collapse',
                     'assassination', 'aftermath', 'consequence', 'revolt'}
        ranked = {}
        for position, link in enumerate(content.find_all('a', href=True)[:600]):
            href = unquote(link.get('href', '')).split('#', 1)[0]
            if (not href or href.startswith(('/', '.', '?')) or ':' in href or
                    not re.fullmatch(r"[\w%()'\u2019,.-]+", href)):
                continue
            anchor = link.get_text(' ', strip=True)
            if not anchor or re.fullmatch(r'\[?\s*\d+\s*\]?', anchor):
                continue
            parent = link.find_parent('p')
            if parent is None:
                continue
            context = parent.get_text(' ', strip=True)[:900]
            terms = set(re.findall(r'\w+', (anchor + ' ' + context).casefold()))
            anchor_terms = set(re.findall(r'\w+', anchor.casefold()))
            overlap = len(query_words & terms) / max(1, len(query_words))
            cues = len(cue_words & terms) / max(1, len(cue_words))
            anchor_relevance = min(1.0, (len(query_words & anchor_terms) +
                                        len(cue_words & anchor_terms)) / 2)
            lead = max(0.0, 1.0-position/180)
            score = .48*overlap + .27*anchor_relevance + .15*cues + .10*lead
            prior = ranked.get(href)
            if prior is None or score > prior[0]:
                ranked[href] = (score, position)
        return [path for path, _ in sorted(ranked.items(), key=lambda item: (
            -item[1][0], item[1][1], item[0]))[:limit]]
