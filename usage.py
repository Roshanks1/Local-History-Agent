"""Final generation accounting only; never infer unavailable counts."""
import math


def number(value):
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) and value >= 0 else None


def normalize_usage(response=None, model=None, num_ctx=8192, skipped=False):
    response = response or {}
    def count(key):
        value = number(response.get(key))
        return int(value) if value is not None and value == int(value) else None
    prompt = None if skipped else count('prompt_eval_count')
    output = None if skipped else count('eval_count')
    duration = None if skipped else number(response.get('eval_duration'))
    total = prompt + output if prompt is not None and output is not None else None
    return dict(model=model, context_window=num_ctx, skipped=skipped,
                prompt_tokens=prompt, output_tokens=output, total_tokens=total,
                tokens_per_second=output / (duration / 1e9) if output is not None and duration else None)


def format_usage(usage):
    if usage['skipped']:
        return 'Generation skipped; no final model call.'
    show = lambda value: 'unavailable' if value is None else str(value)
    return (f"Model: {usage['model']} | Context window: {usage['context_window']} tokens\n"
            f"Final call tokens — prompt: {show(usage['prompt_tokens'])}; output: {show(usage['output_tokens'])}; total: {show(usage['total_tokens'])}")
