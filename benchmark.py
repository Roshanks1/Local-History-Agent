import time
from ollama import chat


MODELS = [
    "qwen3:8b",
    "qwen3:14b",
]

PROMPT = """
Explain the major causes of the Thirty Years' War.
Keep the answer between 400 and 600 words.
"""


def ns_to_seconds(ns):
    return ns / 1_000_000_000


for model in MODELS:
    print("\n" + "=" * 70)
    print(f"BENCHMARKING: {model}")
    print("=" * 70)

    start = time.perf_counter()

    response = chat(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a historical research assistant. "
                    "Give clear and factual historical explanations."
                ),
            },
            {
                "role": "user",
                "content": PROMPT,
            },
        ],
    )

    wall_time = time.perf_counter() - start

    total_duration = ns_to_seconds(response.total_duration)
    load_duration = ns_to_seconds(response.load_duration)
    prompt_eval_duration = ns_to_seconds(response.prompt_eval_duration)
    eval_duration = ns_to_seconds(response.eval_duration)

    prompt_tokens = response.prompt_eval_count
    output_tokens = response.eval_count

    prompt_tokens_per_second = (
        prompt_tokens / prompt_eval_duration
        if prompt_eval_duration > 0
        else 0
    )

    generation_tokens_per_second = (
        output_tokens / eval_duration
        if eval_duration > 0
        else 0
    )

    print("\nRESULTS")
    print(f"Model:                     {model}")
    print(f"Wall-clock time:           {wall_time:.2f} sec")
    print(f"Ollama total duration:     {total_duration:.2f} sec")
    print(f"Model load duration:       {load_duration:.2f} sec")
    print(f"Prompt eval duration:      {prompt_eval_duration:.2f} sec")
    print(f"Generation duration:       {eval_duration:.2f} sec")
    print(f"Prompt tokens:             {prompt_tokens}")
    print(f"Generated tokens:          {output_tokens}")
    print(f"Prompt processing speed:   {prompt_tokens_per_second:.2f} tok/s")
    print(f"Generation speed:          {generation_tokens_per_second:.2f} tok/s")

    print("\nMODEL OUTPUT\n")
    print(response.message.content)