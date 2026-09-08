from libzim.reader import Archive
from bs4 import BeautifulSoup

ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"

zim = Archive(ZIM_PATH)

article_path = "Thirty_Years_War"

entry = zim.get_entry_by_path(article_path)
item = entry.get_item()

html = bytes(item.content).decode("utf-8")

soup = BeautifulSoup(html, "html.parser")

# Find the main Wikipedia article body
content = soup.find("div", id="mw-content-text")

if content is None:
    raise RuntimeError("Could not find article content")

# Remove things we don't want
for element in content.find_all([
    "script",
    "style",
    "table",
    "sup",
    "nav",
    "figure"
]):
    element.decompose()

# Pull out only useful prose elements
parts = []

for element in content.find_all(["h2", "h3", "p"]):
    text = element.get_text(" ", strip=True)

    if text:
        parts.append(text)

clean_text = "\n\n".join(parts)

print(clean_text[:12000])