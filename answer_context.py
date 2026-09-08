"""Evidence packing with explicit character and estimated-token limits."""
import math


def estimate_tokens(text):
    # Conservative for typical English prose; not the exact Qwen tokenizer.
    return math.ceil(len(text.encode('utf-8')) / 3)


def pack_context(hits, max_chars, token_budget):
    from history_ai import evidence_context
    low, high = 0, min(max_chars, token_budget*3)
    context, sources = evidence_context(hits, high)
    if estimate_tokens(context) <= token_budget:
        return context, sources
    # Non-ASCII text can use more bytes than characters; enforce the same estimate.
    best = ('', [])
    while low <= high:
        middle = (low+high)//2
        candidate = evidence_context(hits, middle)
        if estimate_tokens(candidate[0]) <= token_budget:
            best = candidate
            low = middle+1
        else:
            high = middle-1
    return best
