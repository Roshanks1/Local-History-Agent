import math
import ollama

from wikipedia_local import LocalWikipedia
from chunking import chunk_article


ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"
EMBED_MODEL = "nomic-embed-text"

QUESTION = (
    "Causes and origins of the Thirty Years' War, including "
    "religious conflict, political tensions, and events leading to war"
)
TOP_K = 5


def embed(text):
    response = ollama.embed(
        model=EMBED_MODEL,
        input=text,
    )

    return response["embeddings"][0]


def cosine_similarity(a, b):
    dot_product = sum(
        x * y for x, y in zip(a, b)
    )

    magnitude_a = math.sqrt(
        sum(x * x for x in a)
    )

    magnitude_b = math.sqrt(
        sum(y * y for y in b)
    )

    return dot_product / (magnitude_a * magnitude_b)


# --------------------------------------------------
# 1. Load Wikipedia article
# --------------------------------------------------

wiki = LocalWikipedia(ZIM_PATH)

blocks = wiki.get_article("Thirty_Years_War")

chunks = chunk_article(
    blocks,
    article_path="Thirty_Years_War",
    max_chars=2000,
)


print(f"Total chunks: {len(chunks)}")
print(f"Question: {QUESTION}")

print("\nEmbedding question...")

question_embedding = embed(QUESTION)


# --------------------------------------------------
# 2. Embed every Wikipedia chunk
# --------------------------------------------------

results = []

print("Embedding chunks...")

for i, chunk in enumerate(chunks):

    chunk_embedding = embed(chunk["text"])

    similarity = cosine_similarity(
        question_embedding,
        chunk_embedding,
    )

    results.append({
        "score": similarity,
        "chunk": chunk,
    })

    print(
        f"\rEmbedded {i + 1}/{len(chunks)}",
        end="",
        flush=True,
    )


# --------------------------------------------------
# 3. Rank chunks
# --------------------------------------------------

results.sort(
    key=lambda result: result["score"],
    reverse=True,
)


# --------------------------------------------------
# 4. Print top results
# --------------------------------------------------

print("\n\n" + "=" * 80)
print(f"TOP {TOP_K} RESULTS")
print("=" * 80)


for rank, result in enumerate(
    results[:TOP_K],
    start=1,
):
    chunk = result["chunk"]

    print(f"\nRANK {rank}")
    print(f"Score: {result['score']:.4f}")
    print(f"Chunk: {chunk['chunk_id']}")
    print(f"Section: {chunk['section']}")
    print(f"Subsection: {chunk['subsection']}")

    print("\nText:")
    print(chunk["text"])

    print("\n" + "-" * 80)