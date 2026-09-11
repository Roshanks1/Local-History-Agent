"""Deterministic local reranking and diversity-aware evidence selection."""
from collections import Counter
import math
import re

from answer_context import estimate_tokens
from retrieval_expansion import words


LOW_VALUE_HEADINGS = re.compile(r'^(?:references|external links|see also|bibliography|notes|sources)$', re.I)


def _minmax(values):
    if not values:
        return []
    low, high = min(values), max(values)
    if math.isclose(low, high):
        return [.5 for _ in values]
    return [(value-low)/(high-low) for value in values]


def _overlap(left, right):
    return len(left & right) / max(1, len(left))


def _date_score(text, hints):
    if not hints:
        return .5
    normalized = text.casefold()
    return max((1.0 if hint.casefold() in normalized else 0.0) for hint in hints)


def _density(text):
    tokens = re.findall(r'\w+', text)
    if len(tokens) < 18:
        return .1
    sentences = len(re.findall(r'[.!?](?:\s|$)', text))
    return min(1.0, .35 + sentences*.12 + min(len(tokens), 160)/400)


def rerank(candidates, plan, discovery=None):
    """Normalize incomparable signals and return a stable scored shortlist."""
    if not candidates:
        return []
    semantic = _minmax([float(hit.get('score', 0)) for hit in candidates])
    query_terms = words(' '.join(plan.seed_queries))
    entity_terms = [words(entity.display_name) for entity in plan.entities]
    reasons = (discovery or {}).get('article_reasons', {})
    rows = []
    for position, (hit, semantic_score) in enumerate(zip(candidates, semantic)):
        chunk = hit['chunk']
        title = chunk['article_path'].replace('_', ' ')
        heading = ' '.join(filter(None, (chunk.get('section'), chunk.get('subsection'))))
        text_terms = words(chunk.get('text', ''))
        title_terms, heading_terms = words(title), words(heading)
        lexical = _overlap(query_terms, text_terms | title_terms | heading_terms)
        title_score = _overlap(title_terms, query_terms)
        section_score = _overlap(heading_terms, query_terms)
        haystack = re.sub(r'[^\w ]+', ' ', ' '.join((title, heading, chunk.get('text', ''))).casefold())
        entity_scores = []
        for entity, entity_words in zip(plan.entities, entity_terms):
            phrase = re.sub(r'[^\w ]+', ' ', entity.display_name.casefold())
            entity_scores.append(1.0 if phrase in haystack else
                                 .35*_overlap(entity_words, title_terms | heading_terms | text_terms))
        entity_score = max(entity_scores, default=.5 if not entity_terms else 0)
        direct = 1.0 if any(reason in ('direct title', 'question search')
                            for reason in reasons.get(chunk['article_path'], [])) else .35
        completeness = _density(chunk.get('text', ''))
        low_value = 1.0 if (LOW_VALUE_HEADINGS.match((chunk.get('section') or '').strip()) or
                            re.search(r'\(disambiguation\)$', title, re.I)) else 0.0
        query_has_republic = 'republic' in query_terms
        topic_conflict = 1.0 if (query_has_republic and 'empire' in title_terms and 'republic' not in title_terms) else 0.0
        if (re.search(r'\(.*\d{3,4}', title) and not plan.date_or_period_hints and
                any(title.casefold().startswith(entity.display_name.casefold() + ' (')
                    for entity in plan.entities)):
            topic_conflict = 1.0
        components = dict(semantic=semantic_score, lexical=lexical, title=title_score,
                          section=section_score, entity=entity_score,
                          date=_date_score(' '.join((heading, chunk.get('text', ''))), plan.date_or_period_hints),
                          direct_title=direct, completeness=completeness, low_value=low_value,
                          topic_conflict=topic_conflict)
        score = (.39*components['semantic'] + .20*lexical + .10*title_score +
                 .08*section_score + .10*entity_score + .04*components['date'] +
                 .04*direct + .05*completeness - .65*low_value - .35*topic_conflict)
        rows.append(dict(hit, original_score=hit.get('score'), score=round(score, 8),
                         rerank_score=round(score, 8), score_components=components,
                         _input_position=position))
    rows.sort(key=lambda row: (-row['rerank_score'], row['chunk']['article_path'],
                               row['chunk']['chunk_id'], row['_input_position']))
    return rows


def _fingerprint(text):
    terms = re.findall(r'\w+', text.casefold())
    return set(zip(terms, terms[1:], terms[2:])) if len(terms) >= 3 else set(terms)


def redundancy(left, right):
    a, b = _fingerprint(left), _fingerprint(right)
    return len(a & b) / max(1, len(a | b))


def select_evidence(ranked, config):
    """MMR-style selection with whole-chunk token, article and redundancy bounds."""
    remaining = list(ranked)
    selected, diagnostics = [], []
    article_counts = Counter()
    used_tokens = 0
    while remaining and len(selected) < config.expanded_context_k:
        choices = []
        for row in remaining:
            article = row['chunk']['article_path']
            repeat_penalty = config.article_repeat_penalty * article_counts[article]
            duplicate = max((redundancy(row['chunk']['text'], prior['chunk']['text'])
                             for prior in selected), default=0.0)
            marginal = row['rerank_score'] - config.redundancy_penalty*duplicate - repeat_penalty
            choices.append((marginal, duplicate, row))
        marginal, duplicate, row = sorted(choices, key=lambda item: (
            -item[0], item[1], -item[2]['rerank_score'],
            item[2]['chunk']['article_path'], item[2]['chunk']['chunk_id']))[0]
        remaining.remove(row)
        article = row['chunk']['article_path']
        token_cost = estimate_tokens(row['chunk']['text']) + config.source_metadata_tokens
        reason = None
        if row['rerank_score'] < config.rerank_relevance_floor or marginal < config.rerank_relevance_floor:
            reason = 'below relevance floor'
        elif duplicate >= config.duplicate_overlap_threshold:
            reason = 'redundant'
        elif article_counts[article] >= config.selected_chunks_per_article:
            reason = 'article cap'
        elif used_tokens + token_cost > config.context_token_budget:
            reason = 'token budget'
        if reason:
            diagnostics.append(dict(chunk_id=row['chunk']['chunk_id'], article_path=article,
                                    rerank_score=row['rerank_score'], selection_reason=reason))
            continue
        chosen = dict(row, marginal_score=round(marginal, 8), selection_reason='selected',
                      token_estimate=token_cost)
        chosen.pop('_input_position', None)
        selected.append(chosen)
        article_counts[article] += 1
        used_tokens += token_cost
    selected_ids = {row['chunk']['chunk_id'] for row in selected}
    for row in remaining:
        if row['chunk']['chunk_id'] not in selected_ids:
            diagnostics.append(dict(chunk_id=row['chunk']['chunk_id'],
                                    article_path=row['chunk']['article_path'],
                                    rerank_score=row['rerank_score'], selection_reason='selection limit'))
    return selected, {'selected': selected, 'rejected': diagnostics,
                      'selected_tokens': used_tokens,
                      'distinct_articles': len(article_counts)}
