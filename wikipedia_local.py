from libzim.reader import Archive
from libzim.suggestion import SuggestionSearcher
from bs4 import BeautifulSoup


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