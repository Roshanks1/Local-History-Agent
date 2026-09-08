import math
import ollama

from wikipedia_local import LocalWikipedia
from chunking import chunk_article


ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"

EMBED_MODEL = "nomic-embed-text"
LLM_MODEL = "qwen3:14b"

QUESTION = "What caused the Thirty Years' War?"

RETRIEVAL_QUERY = (
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
# Load and chunk article
# --------------------------------------------------

wiki = LocalWikipedia(ZIM_PATH)

blocks = wiki.get_article("Thirty_Years_War")

chunks = chunk_article(
    blocks,
    article_path="Thirty_Years_War",
    max_chars=2000,
)


# --------------------------------------------------
# Embed retrieval query
# --------------------------------------------------

query_embedding = embed(RETRIEVAL_QUERY)

results = []


# --------------------------------------------------
# Embed chunks and score them
# --------------------------------------------------

for chunk in chunks:

    chunk_embedding = embed(chunk["text"])

    score = cosine_similarity(
        query_embedding,
        chunk_embedding,
    )

    results.append({
        "score": score,
        "chunk": chunk,
    })


results.sort(
    key=lambda result: result["score"],
    reverse=True,
)

top_results = results[:TOP_K]


# --------------------------------------------------
# Build evidence context
# --------------------------------------------------

context_parts = []

for result in top_results:

    chunk = result["chunk"]

    source_label = (
        f"[{chunk['chunk_id']} | "
        f"Section: {chunk['section']} | "
        f"Subsection: {chunk['subsection']}]"
    )

    context_parts.append(
        source_label + "\n" + chunk["text"]
    )


context = "\n\n".join(context_parts)


# --------------------------------------------------
# Ask Qwen using ONLY retrieved evidence
# --------------------------------------------------

system_prompt = """
You are an offline historical research assistant.

Answer the user's question using ONLY the evidence supplied
in the context.

Rules:

1. Do not use outside knowledge.
2. Do not invent facts that are not explicitly supported
   by the supplied evidence.
3. If the evidence is insufficient, clearly say so.
4. Cite supporting chunks using their chunk IDs.
5. Every major factual claim should have a citation.
6. Do not cite a chunk unless it actually supports the claim.
7. Prefer a concise, direct answer.
"""


user_prompt = f"""
QUESTION:
{QUESTION}

EVIDENCE:
{context}

Answer the question using only the evidence above.
"""


response = ollama.chat(
    model=LLM_MODEL,
    messages=[
        {
            "role": "system",
            "content": system_prompt,
        },
        {
            "role": "user",
            "content": user_prompt,
        },
    ],
)


print("\n" + "=" * 80)
print("RETRIEVED CHUNKS")
print("=" * 80)

for rank, result in enumerate(top_results, start=1):
    chunk = result["chunk"]

    print(
        f"{rank}. "
        f"{chunk['chunk_id']} "
        f"({result['score']:.4f}) "
        f"- {chunk['section']} / "
        f"{chunk['subsection']}"
    )


print("\n" + "=" * 80)
print("QWEN ANSWER")
print("=" * 80)

print(response["message"]["content"])