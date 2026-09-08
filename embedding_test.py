import ollama
import math


MODEL = "nomic-embed-text"


def embed(text):
    response = ollama.embed(
        model=MODEL,
        input=text,
    )

    return response["embeddings"][0]


def cosine_similarity(a, b):
    dot_product = sum(x * y for x, y in zip(a, b))

    magnitude_a = math.sqrt(
        sum(x * x for x in a)
    )

    magnitude_b = math.sqrt(
        sum(y * y for y in b)
    )

    return dot_product / (magnitude_a * magnitude_b)


question = "What caused the Thirty Years' War?"

sentence_a = (
    "Religious and political tensions between "
    "Catholics and Protestants contributed to the conflict."
)

sentence_b = (
    "The Thirty Years' War ended with the Peace of Westphalia in 1648."
)

sentence_c = (
    "Bananas are grown in tropical climates around the world."
)


question_embedding = embed(question)
a_embedding = embed(sentence_a)
b_embedding = embed(sentence_b)
c_embedding = embed(sentence_c)


print("Embedding dimensions:", len(question_embedding))

print("\nFirst 10 values of question embedding:")
print(question_embedding[:10])


print("\nCosine similarities:")

print(
    "Cause sentence:",
    cosine_similarity(question_embedding, a_embedding)
)

print(
    "End-of-war sentence:",
    cosine_similarity(question_embedding, b_embedding)
)

print(
    "Banana sentence:",
    cosine_similarity(question_embedding, c_embedding)
)