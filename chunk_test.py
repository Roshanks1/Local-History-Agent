from wikipedia_local import LocalWikipedia
from chunking import chunk_article


ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"


wiki = LocalWikipedia(ZIM_PATH)

blocks = wiki.get_article("Thirty_Years_War")

chunks = chunk_article(
    blocks,
    article_path="Thirty_Years_War",
    max_chars=2000,
    overlap_chars=300,
)


print(f"\nTotal blocks: {len(blocks)}")
print(f"Total chunks: {len(chunks)}\n")


for i, chunk in enumerate(chunks[:6]):
    print("=" * 80)

    print("Chunk:", chunk["chunk_id"])
    print("Length:", len(chunk["text"]))
    print("Section:", chunk["section"])
    print("Subsection:", chunk["subsection"])

    print("\nFIRST 300 CHARS:")
    print(chunk["text"][:300])

    print("\nLAST 300 CHARS:")
    print(chunk["text"][-300:])

    print()