from ollama import chat

from wikipedia_local import LocalWikipedia


ZIM_PATH = "data/wikipedia/wikipedia_en_all_nopic_2026-06.zim"

MODEL = "qwen3:14b"

wiki = LocalWikipedia(ZIM_PATH)


question = input("Ask a history question: ")

print("\nSearching offline Wikipedia...")

results = wiki.search(question, limit=5)

if not results:
    raise SystemExit("No Wikipedia results found.")

print("\nWikipedia results:")

for i, result in enumerate(results, start=1):
    print(f"{i}. {result}")

# For V1, simply use the highest-ranked article
article_path = results[0]

print(f"\nUsing article: {article_path}")

article_text = wiki.get_article(article_path)

# Temporary solution:
# limit how much article text we send to the model
context = article_text[:20000]

print("\nGenerating answer with Qwen3 14B...\n")

response = chat(
    model=MODEL,
    messages=[
        {
            "role": "system",
            "content": (
                "You are a historical research assistant. "
                "Answer the user's question using the supplied "
                "Wikipedia source material. "
                "Prioritize information supported by the source. "
                "If the supplied source does not contain enough "
                "information to answer something confidently, say so."
            ),
        },
        {
            "role": "user",
            "content": f"""
QUESTION:

{question}


WIKIPEDIA SOURCE:

Article: {article_path}

{context}
""",
        },
    ],
)

print("ANSWER:\n")

print(response.message.content)

print("\nSOURCE:")
print(article_path.replace("_", " "))