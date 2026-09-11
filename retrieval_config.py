"""Validated tuning settings shared by live chat and evaluation."""
from dataclasses import dataclass, asdict
import json
import math
from pathlib import Path


@dataclass(frozen=True)
class RetrievalConfig:
    candidate_articles: int = 12
    narrow_candidate_articles: int = 2
    max_seed_queries: int = 4
    max_entities: int = 8
    max_date_hints: int = 8
    articles_per_query: int = 4
    entity_title_candidates: int = 2
    related_seed_articles: int = 2
    related_articles_per_seed: int = 4
    candidate_chunks_per_article: int = 64
    candidate_chunks_total: int = 480
    max_discovery_seconds: int = 8
    initial_top_k: int = 24
    article_top_k: int = 6
    chunks_per_article: int = 6
    chunks_per_section: int = 3
    expanded_context_k: int = 10
    similarity_threshold: float = 0.15
    context_token_budget: int = 4800
    context_chars: int = 15000
    section_boost: float = 0.18
    article_boost: float = 0.08
    history_turns: int = 4
    history_chars: int = 1800
    timeline_events: int = 24
    timeline_candidates: int = 32
    continuation_year_window: int = 30
    max_chars: int = 2000
    overlap_chars: int = 300
    selected_chunks_per_article: int = 3
    source_metadata_tokens: int = 40
    rerank_relevance_floor: float = 0.25
    redundancy_penalty: float = 0.32
    article_repeat_penalty: float = 0.055
    duplicate_overlap_threshold: float = 0.72

    def __post_init__(self):
        for key, value in asdict(self).items():
            if key in ('similarity_threshold', 'section_boost', 'article_boost',
                       'rerank_relevance_floor', 'redundancy_penalty',
                       'article_repeat_penalty', 'duplicate_overlap_threshold'):
                if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 1:
                    raise ValueError(f'{key} must be between 0 and 1')
            elif not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f'{key} must be a positive integer')
        if self.context_token_budget > 5600:
            raise ValueError('context_token_budget must be <= 5600 to reserve generation/history space')
        if self.history_chars > 3000:
            raise ValueError('history_chars must be <= 3000')

    def to_dict(self):
        return asdict(self)


def load_config(path=None):
    if path is not None and not Path(path).exists():
        raise FileNotFoundError(f'Retrieval config not found: {path}')
    path = Path(path) if path else Path(__file__).resolve().parent/'retrieval_config.json'
    values = json.loads(path.read_text()) if path.exists() else {}
    unknown = set(values) - set(RetrievalConfig.__dataclass_fields__)
    if unknown:
        raise ValueError('Unknown retrieval settings: ' + ', '.join(sorted(unknown)))
    return RetrievalConfig(**values)
