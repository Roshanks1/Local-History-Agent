from libzim.reader import Archive
from libzim.suggestion import SuggestionSearcher

ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"

zim = Archive(ZIM_PATH)

query_text = input("Search Wikipedia: ")

searcher = SuggestionSearcher(zim)
search = searcher.suggest(query_text)

results = search.getResults(0, 10)

print("\nResults:\n")

for result in results:
    print(result)