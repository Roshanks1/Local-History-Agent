"""Article-level candidate ranking and query-aware section expansion over existing vectors."""
from collections import defaultdict
import math
import re


INTENT_TERMS = {
    'cause': ('cause', 'origin', 'background', 'tension', 'religious', 'political', 'trigger', 'revolt'),
    'timeline': ('history', 'timeline', 'chronology', 'phase', 'battle', 'campaign', 'events'),
    'comparison': ('impact', 'consequence', 'political', 'econom', 'religio', 'difference'),
    'lookup': ('introduction', 'early life', 'background', 'history'),
    'general': (),
}


def words(text):
    return set(re.findall(r'\w+', text.casefold())) - {'the', 'of', 'a', 'and', 'to', 'in', 'what', 'why'}


def section_affinity(chunk, analysis):
    heading = ' '.join((chunk['section'], chunk.get('subsection') or '')).lower()
    terms = INTENT_TERMS.get(analysis.effective_type, ())
    affinity = min(1.0, sum(term in heading for term in terms) / 2)
    query = words(analysis.retrieval_query)
    affinity += .3 * len(query & words(heading)) / max(1, len(words(heading)))
    if analysis.effective_type == 'cause':
        if any(w in heading for w in ('cost', 'casualt', 'aftermath', 'consequence')) and not query & {'cost', 'costs', 'casualties', 'deaths', 'disease', 'famine'}:
            affinity -= 1
    return affinity


def deduplicate(hits, limit):
    selected, ids, paragraphs = [], set(), set()
    for hit in hits:
        chunk = hit['chunk']
        if chunk['chunk_id'] in ids:
            continue
        ids.add(chunk['chunk_id'])
        retained = []
        for p in chunk['text'].split('\n\n'):
            key = re.sub(r'\s+', ' ', p).strip().casefold()
            if key and key not in paragraphs:
                paragraphs.add(key)
                retained.append(p)
        if retained:
            selected.append(dict(hit, chunk=dict(chunk, text='\n\n'.join(retained))))
        if len(selected) >= limit:
            break
    return selected


def expand_ranked(ranked, analysis, config, plan=None, discovery=None):
    """Rank articles from initial scores/frequency, then revisit all their sections."""
    initial = [h for h in ranked[:config.initial_top_k] if h['score'] >= config.similarity_threshold]
    grouped = defaultdict(list)
    for hit in initial:
        grouped[hit['chunk']['article_path']].append(hit['score'])
    frequencies = {article: len(scores) for article, scores in grouped.items()}
    query_words = words(analysis.retrieval_query)
    for hit in ranked:
        article = hit['chunk']['article_path']
        title_words = words(article.replace('_', ' '))
        if article not in grouped and hit['score'] >= config.similarity_threshold and len(title_words & query_words)/max(1,len(title_words)) >= .3:
            grouped[article] = [hit['score']]
    articles = []
    for article, scores in grouped.items():
        title_words = words(article.replace('_', ' '))
        title_match = len(title_words & query_words)/max(1, len(title_words))
        score = .65*max(scores) + .25*sum(scores)/len(scores) + .10*frequencies.get(article, 0)/max(1,len(initial)) + config.article_boost*title_match
        articles.append({'article_path': article, 'score': score, 'initial_occurrences': frequencies.get(article, 0)})
    articles.sort(key=lambda a: (-a['score'], a['article_path']))
    articles = articles[:config.article_top_k]
    selected_articles = {a['article_path']: a['score'] for a in articles}
    by_article = defaultdict(list)
    for hit in ranked:
        c = hit['chunk']
        if c['article_path'] not in selected_articles or hit['score'] < config.similarity_threshold:
            continue
        affinity = section_affinity(c, analysis)
        score = hit['score'] + config.section_boost*affinity + config.article_boost*selected_articles[c['article_path']]
        by_article[c['article_path']].append(dict(hit, expansion_score=score, section_affinity=affinity))
    expanded = []
    for article in articles:
        hits = by_article[article['article_path']]
        hits.sort(key=lambda h: (-h['expansion_score'], h['chunk']['chunk_id']))
        section_counts = defaultdict(int)
        chosen = []
        if analysis.effective_type == 'cause':
            # Reserve evidence of a concrete trigger, so broad background sections
            # cannot consume every slot. These are event categories, not case-specific answers.
            triggers = [(sum(bool(re.search(pattern, h['chunk']['text'], re.I))*weight
                             for pattern, weight in ((r'defenestrat|assassinat|coup', 3),
                              (r'revolt|rebellion|uprising', 1), (r'war began|outbreak|trigger', 1))), h)
                        for h in hits]
            triggers = [(strength, h) for strength, h in triggers if strength]
            if triggers:
                trigger = max(triggers, key=lambda pair: pair[0]*.1+pair[1]['expansion_score'])[1]
                chosen.append(dict(trigger, trigger_evidence=True))
                c = trigger['chunk']
                section_counts[(c['section'], c.get('subsection'))] += 1
        for hit in hits:
            c = hit['chunk']
            section = (c['section'], c.get('subsection'))
            if len(chosen) >= config.chunks_per_article:
                break
            if any(h['chunk']['chunk_id'] == c['chunk_id'] for h in chosen):
                continue
            if section_counts[section] >= config.chunks_per_section:
                continue
            chosen.append(hit)
            section_counts[section] += 1
            if len(chosen) >= config.chunks_per_article:
                break
        expanded.extend(chosen)
    expanded.sort(key=lambda h: (-h['expansion_score'], h['chunk']['chunk_id']))
    priority = expanded
    if analysis.effective_type == 'cause':
        triggers = [h for h in expanded if h.get('trigger_evidence')]
        if re.search(r'immediate|trigger', analysis.retrieval_query, re.I):
            priority = triggers + expanded
        else:
            priority = expanded[:1] + triggers + expanded
    final = deduplicate(priority, config.expanded_context_k)
    # Comparison answers must retain evidence from more than the dominant article.
    if analysis.effective_type == 'comparison' and len(articles) > 1:
        leaders = [by_article[a['article_path']][0] for a in articles if by_article[a['article_path']]]
        final = deduplicate(leaders + expanded, config.expanded_context_k)
    timeline_pool = []
    if analysis.effective_type == 'timeline':
        # Include broader dated coverage from shortlisted articles, with query-type scores.
        pool = sorted([h for hits in by_article.values() for h in hits],
                      key=lambda h: (-h['expansion_score'], h['chunk']['chunk_id']))
        section_openings = {}
        for h in pool:
            c = h['chunk']
            key = (c['article_path'], c['section'], c.get('subsection'))
            if key not in section_openings or c['chunk_id'] < section_openings[key]['chunk']['chunk_id']:
                section_openings[key] = h
        leaders = sorted(section_openings.values(), key=lambda h: -h['expansion_score'])
        timeline_pool = deduplicate(leaders + pool, config.timeline_candidates)
    trace = {'initial_chunks': initial, 'candidate_articles': articles,
             'expanded_chunks': expanded, 'final_chunks': final,
             'timeline_candidates': timeline_pool}
    if plan is not None:
        from retrieval_ranking import rerank, select_evidence
        reranked = rerank(expanded, plan, discovery)
        final, selection = select_evidence(reranked, config)
        trace.update(reranked_chunks=reranked, final_chunks=final,
                     evidence_selection=selection)
    return final, trace


def expand(index, analysis, config, api, plan=None, discovery=None):
    from history_ai import retrieve
    ranked = retrieve(index, analysis.retrieval_query, len(index['chunks']), api)
    initial_ranked = ranked
    if analysis.effective_type == 'cause':
        intent_query = analysis.retrieval_query + ' Causes origins background immediate trigger outbreak'
        intent = retrieve(index, intent_query, len(index['chunks']), api)
        intent_scores = {h['chunk']['chunk_id']: h['score'] for h in intent}
        ranked = [dict(h, original_score=h['score'],
                       score=.6*h['score']+.4*intent_scores[h['chunk']['chunk_id']]) for h in ranked]
        ranked.sort(key=lambda h: (-h['score'], h['chunk']['chunk_id']))
    final, trace = expand_ranked(ranked, analysis, config, plan, discovery)
    trace['raw_initial_chunks'] = initial_ranked[:config.initial_top_k]
    return final, trace
