import math
import ollama

from wikipedia_local import LocalWikipedia
from chunking import chunk_article


ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"

EMBED_MODEL = "nomic-embed-text"

TOP_K = 5


QUESTIONS = [
    "What caused the Thirty Years' War?",
    "How did the Thirty Years' War begin?",
    "Why did France enter the Thirty Years' War?",
    "How did the Thirty Years' War end?",
    "What were the human costs of the Thirty Years' War?",
]


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
# Load and chunk the article once
# --------------------------------------------------

wiki = LocalWikipedia(ZIM_PATH)

blocks = wiki.get_article("Thirty_Years_War")

chunks = chunk_article(
    blocks,
    article_path="Thirty_Years_War",
    max_chars=2000,
)


print(f"Total chunks: {len(chunks)}")
print("Embedding all chunks once...\n")


# --------------------------------------------------
# Embed all chunks once
#
# NEW:
# Include section/subsection metadata in the text
# that gets embedded.
# --------------------------------------------------

chunk_embeddings = []

for i, chunk in enumerate(chunks):

    embedding_text = (
        f"Section: {chunk['section']}\n"
    )

    if chunk["subsection"]:
        embedding_text += (
            f"Subsection: {chunk['subsection']}\n"
        )

    embedding_text += (
        f"\n{chunk['text']}"
    )

    embedding = embed(embedding_text)

    chunk_embeddings.append(embedding)

    print(
        f"\rEmbedded chunk {i + 1}/{len(chunks)}",
        end="",
        flush=True,
    )


print("\n")


# --------------------------------------------------
# Run every benchmark question
# --------------------------------------------------

for question_number, question in enumerate(
    QUESTIONS,
    start=1,
):

    print("=" * 90)
    print(f"QUESTION {question_number}")
    print("=" * 90)

    print(question)

    # Embed the user's actual question directly
    question_embedding = embed(question)

    results = []

    for chunk, chunk_embedding in zip(
        chunks,
        chunk_embeddings,
    ):

        score = cosine_similarity(
            question_embedding,
            chunk_embedding,
        )

        results.append({
            "score": score,
            "chunk": chunk,
        })


    # --------------------------------------------------
    # Sort highest similarity -> lowest similarity
    # --------------------------------------------------

    results.sort(
        key=lambda result: result["score"],
        reverse=True,
    )


    # --------------------------------------------------
    # Print top-k
    # --------------------------------------------------

    print(f"\nTOP {TOP_K} RESULTS\n")


    for rank, result in enumerate(
        results[:TOP_K],
        start=1,
    ):
        chunk = result["chunk"]

        section = chunk["section"]
        subsection = chunk["subsection"]

        if subsection is None:
            subsection = "-"

        print(
            f"{rank}. "
            f"{chunk['chunk_id']} | "
            f"{result['score']:.4f} | "
            f"{section} | "
            f"{subsection}"
        )


    print()