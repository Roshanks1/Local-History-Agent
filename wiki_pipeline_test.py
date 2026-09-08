from wikipedia_local import LocalWikipedia


ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"

wiki = LocalWikipedia(ZIM_PATH)

query = input("Search Wikipedia: ")

results = wiki.search(query, limit=5)

print("\nResults:\n")

for i, result in enumerate(results, start=1):
    print(f"{i}. {result}")

if not results:
    raise SystemExit("No results found.")

article_path = results[0]

print(f"\nOpening: {article_path}\n")

article_text = wiki.get_article(article_path)

print(article_text[:5000])