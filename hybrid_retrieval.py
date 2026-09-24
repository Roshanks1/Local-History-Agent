"""Independent dense/BM25 branches, deterministic fusion and bounded reranking."""
from copy import deepcopy
import math
import re
import sqlite3
from urllib.parse import quote
from types import SimpleNamespace
import time
import uuid

from retrieval_candidates import adapt_legacy, reciprocal_rank_fusion
from lexical_retrieval import search
from retrieval_ranking import rerank


def rerank_candidates(rows, plan, discovery, backend='deterministic', limit=40, check_cancel=None):
    fused_rows = deepcopy(rows[:limit])
    bounded = deepcopy(fused_rows)
    if check_cancel: check_cancel()
    fallback = None
    actual = backend
    try:
        if backend == 'deterministic':
            # The semantic signal remains cosine; fused rank is a separate bounded signal.
            for row in bounded:
                row['score'] = row['retrieval'].get('dense_pool_score', row['retrieval']['branches'].get('dense', {}).get('score', row['score']))
            ranked = rerank(bounded, plan, discovery)
            from retrieval_expansion import section_affinity
            intent = 'cause' if plan.intent == 'comparison' and re.search(r'caus', plan.resolved_question, re.I) else plan.intent
            analysis = SimpleNamespace(effective_type=intent, retrieval_query=plan.resolved_question)
            for row in ranked:
                c = row['chunk']
                affinity = max(-1., min(1., section_affinity(c, analysis)))
                title = c['article_path'].replace('_', ' ').casefold()
                dated_variant = bool(re.search(r'\b\d{3,4}\b', title) and not plan.date_or_period_hints and any(
                    title.startswith(e.normalized_name + ' ') for e in plan.entities))
                row['score'] = row['rerank_score'] = round(row['score'] + .10*((row['retrieval']['fused_score'] or 0)/(2/61)) + .18*affinity - .25*dated_variant, 8)
                row['score_components'].update(intent_section=affinity, dated_variant=dated_variant, fused_rank=(row['retrieval']['fused_score'] or 0)/(2/61))
                if re.search(r'references|bibliography|external links|literature about|gallery', c.get('section',''), re.I):
                    row['score'] -= .65
                    row['rerank_score'] = row['score']
            ranked.sort(key=lambda r:(-r['score'],r['retrieval']['candidate_id']))
            if (len(ranked) != len(bounded) or
                    {r['retrieval']['candidate_id'] for r in ranked} != {r['retrieval']['candidate_id'] for r in bounded} or
                    any(not math.isfinite(r['score']) for r in ranked)):
                raise ValueError('Invalid reranker output')
        elif backend == 'rrf':
            ranked = bounded
        else:
            raise ValueError('Unknown local reranker')
    except (ValueError, RuntimeError, TimeoutError) as error:
        if isinstance(error, InterruptedError): raise
        fallback = type(error).__name__
        actual = 'rrf'; ranked = fused_rows
    for rank, row in enumerate(ranked, 1):
        if check_cancel: check_cancel()
        # Passthrough ordering stays fused; normalized value is only for the packer floor.
        if actual == 'rrf': row['rerank_score'] = row['score'] / (2/61)
        row['retrieval'].update(rerank_method=actual, rerank_rank=rank,
                               rerank_score=row.get('rerank_score', row['score']))
    return ranked, {'backend':actual,'fallback_reason':fallback}


def retrieve_hybrid(index, analysis, config, api, plan, discovery=None, check_cancel=None):
    from history_ai import retrieve, fingerprint
    from retrieval_expansion import expand
    meta = index.get('metadata', {})
    corpus = fingerprint({k:meta.get(k) for k in ('zim_path','zim_size','zim_mtime_ns')})
    chunker = meta.get('chunker_sha256', 'unknown')
    pool = adapt_legacy([{'score':0.,'chunk':c} for c in index['chunks']],
                        corpus_version=corpus, chunker_version=chunker)
    trace = dict(request_id=uuid.uuid4().hex, mode='hybrid', resolved_query=analysis.retrieval_query,
                 limits={'branch':config.hybrid_branch_k,'merged':config.hybrid_merge_k,
                         'rerank':config.hybrid_rerank_k,'packed':config.hybrid_pack_k},
                 fallback_reasons={}, timings={})
    started = time.perf_counter()
    try:
        lexical, info = search(pool, analysis.retrieval_query, corpus_version=corpus,
            chunker_version=chunker, limit=config.hybrid_branch_k,
            max_rows=config.candidate_chunks_total, check_cancel=check_cancel)
        trace['lexical_index'] = info
    except (ValueError, RuntimeError, OSError) as error:
        if isinstance(error, InterruptedError): raise
        trace['fallback_reasons']['bm25'] = type(error).__name__ + ': retry to rebuild request-local index'
        legacy, legacy_trace = expand(index, analysis, config, api, plan, discovery)
        legacy_trace.update(trace, mode='legacy_fallback')
        return legacy, legacy_trace
    except sqlite3.Error as error:
        legacy, legacy_trace = expand(index, analysis, config, api, plan, discovery)
        trace['fallback_reasons']['bm25'] = type(error).__name__ + ': SQLite FTS5 unavailable; check local Python SQLite support'
        legacy_trace.update(trace, mode='legacy_fallback')
        return legacy, legacy_trace
    trace['timings']['lexical_seconds'] = time.perf_counter()-started
    started = time.perf_counter()
    dense = []
    try:
        if index.get('dense_error'): raise ValueError(index['dense_error'])
        if check_cancel: check_cancel()
        dense = retrieve(index, analysis.retrieval_query, len(index['chunks']), api)
        if analysis.effective_type == 'cause':
            intent = retrieve(index, analysis.retrieval_query + ' Causes origins background immediate trigger outbreak', len(index['chunks']), api)
            scores = {r['chunk']['chunk_id']:r['score'] for r in intent}
            dense = [dict(r, score=.6*r['score']+.4*scores[r['chunk']['chunk_id']]) for r in dense]
        if analysis.effective_type in ('comparison', 'timeline'):
            # Consolidate the existing bounded side queries into ONE dense branch.
            # Max cosine retains each side's strongest match without extra RRF votes.
            scores = {r['chunk']['chunk_id']:r['score'] for r in dense}
            queries = plan.seed_queries[1:config.max_seed_queries]
            if analysis.effective_type == 'timeline':
                endpoints = re.search(r'\b(?:from|connected)\s+(.+?)\s+to\s+(.+)', analysis.question, re.I)
                queries = tuple(side + ' chronology events dates' for side in endpoints.groups()) if endpoints else (analysis.retrieval_query + ' chronology sequence of events dates declarations',)
            for query in queries:
                if check_cancel: check_cancel()
                for row in retrieve(index, query, len(index['chunks']), api):
                    key = row['chunk']['chunk_id']; scores[key] = max(scores[key],row['score'])
            dense = [dict(r,score=scores[r['chunk']['chunk_id']]) for r in dense]
        dense = adapt_legacy(dense, corpus_version=corpus, chunker_version=chunker)
    except Exception as error:
        if isinstance(error, (InterruptedError, KeyboardInterrupt)): raise
        # Embedding service may fail while the independent local lexical index remains usable.
        trace['fallback_reasons']['dense'] = type(error).__name__
    trace['timings']['dense_seconds'] = time.perf_counter()-started
    started = time.perf_counter()
    fused = reciprocal_rank_fusion({'dense':dense,'bm25':lexical},
        directions={'dense':'higher','bm25':'lower'}, branch_limit=config.hybrid_branch_k,
        output_limit=config.hybrid_merge_k, input_limit=config.candidate_chunks_total,
        check_cancel=check_cancel)
    dense_scores = {r['retrieval']['candidate_id']:r['score'] for r in dense}
    for row in fused:
        value = dense_scores.get(row['retrieval']['candidate_id'])
        if value is not None: row['retrieval']['dense_pool_score'] = value
    trace['timings']['fusion_seconds'] = time.perf_counter()-started
    started = time.perf_counter()
    ranked, backend = rerank_candidates(fused, plan, discovery, config.rerank_backend,
                                        config.hybrid_rerank_k, check_cancel)
    trace['timings']['rerank_seconds'] = time.perf_counter()-started
    trace.update(backend, counts={'pool':len(pool),'dense':min(len(dense),config.hybrid_branch_k),
        'bm25':len(lexical),'fused':len(fused),'reranked':len(ranked)},
        fused_candidates=fused, reranked_chunks=ranked, timeline_candidates=timeline_pool(ranked, config))
    # Generation performs final selection against the entire prompt, then assigns labels.
    return ranked, trace


def inspector(trace, sources):
    """Bounded safe data; the UI renders JSON via textContent, never innerHTML."""
    final = {(s['article_path'],s['chunk_id']):s for s in sources}
    rankings = {r['retrieval']['candidate_id']:r for r in trace.get('reranked_chunks',[])}
    reasons = {tuple(r['key']):r['reason'] for r in trace.get('packing',{}).get('rejected',[])}
    candidates = []
    for row in trace.get('fused_candidates',[]):
        row = rankings.get(row['retrieval']['candidate_id'], row)
        c = row['chunk']; key = (c['article_path'],c['chunk_id']); source = final.get(key)
        candidates.append(dict(row['retrieval'], article=c['article_path'], section=c.get('section'),
            chunk_id=c['chunk_id'], selected=source is not None,
            selection_reason='selected' if source else reasons.get(key,'rerank or timeline limit'),
            preview=(source['supplied_text'] if source else c['text'])[:240],
            local_article_path=c['article_path'],
            local_url='/wiki/'+quote(c['article_path'],safe='/')))
    compact = {k:v for k,v in trace.items() if k not in ('fused_candidates','reranked_chunks','timeline_candidates')}
    compact['candidates'] = candidates
    compact.setdefault('counts', {})['packed_sources'] = len(sources)
    return compact


def timeline_pool(ranked, config):
    """Retain relevant section openings as in the legacy timeline expansion."""
    rows=[r for r in ranked if r.get('rerank_score',0)>=config.rerank_relevance_floor]
    openings={}
    for row in rows:
        c=row['chunk'];key=(c['article_path'],c['section'],c.get('subsection'))
        if key not in openings or c['chunk_id']<openings[key]['chunk']['chunk_id']:
            openings[key]=row
    leads=[r for r in rows if r['chunk']['section']=='Introduction'][:12]
    ordered=leads+sorted(openings.values(),key=lambda r:-r['rerank_score'])+rows
    seen=set();result=[]
    for row in ordered:
        key=row['retrieval']['candidate_id']
        if key not in seen:seen.add(key);result.append(row)
        if len(result)>=config.timeline_candidates:break
    return result


def endpoint_period(index, analysis):
    """For endpoint sequences, bound incidental dates using a matching local lead.

Only dates explicitly present in that lead sentence are used. General timelines
and follow-ups keep the legacy explicit/anchor-year policy.
"""
    if not re.search(r'\b(?:sequence\s+from|events\s+connected)\b', analysis.question, re.I):
        return None
    from retrieval_expansion import words
    query=words(analysis.question)-set('outline sequence from major events connected outbreak beyond between'.split())
    candidates=[]
    for c in index['chunks']:
        if c['section']!='Introduction' or not c['chunk_id'].endswith('_000'):continue
        sentence=re.split(r'(?<=[.!?])\s+',c['text'])[0]
        overlap=len(query & words(sentence))
        dates=[int(y) for y in re.findall(r'\b\d{4}\b',sentence)]
        if overlap>=3 and dates:
            candidates.append((overlap,c['article_path'],min(dates),max(dates)))
    if not candidates:return None
    best=sorted(candidates,key=lambda c:(-c[0],c[1]))[0]
    return (best[2],best[3])
