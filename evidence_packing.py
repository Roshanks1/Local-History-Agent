"""Conservative full-prompt budgeting and exact, sentence-bounded excerpts."""
from collections import Counter
from functools import lru_cache
from copy import deepcopy
import re

from answer_context import estimate_tokens

CONTEXT_LIMIT = 8192
SAFETY_MARGIN = 384
CHAT_OVERHEAD = 128


def messages_for(question, context, analysis, system):
    dialogue = ''
    if analysis is not None:
        dialogue = f'\nANSWER TYPE: {analysis.effective_type}\n'
        if analysis.context_summary:
            dialogue += 'CONVERSATION CONTEXT (unverified, only for resolving references):\n' + analysis.context_summary + '\n'
    return [{'role':'system','content':system},
            {'role':'user','content':f'QUESTION:\n{question}\n{dialogue}\nEVIDENCE:\n{context}'}]


def prompt_estimate(messages, extra=None):
    import json
    return sum(estimate_tokens(m['content']) for m in messages) + CHAT_OVERHEAD + (
        estimate_tokens(json.dumps(extra,ensure_ascii=False)) if extra else 0)


def normalize_text(text):
    return ' '.join(re.findall(r'\w+',text.casefold()))


def trim_sentence(text, max_tokens, max_chars):
    if estimate_tokens(text) <= max_tokens and len(text) <= max_chars: return text
    # Preserve an exact prefix ending at a sentence or paragraph; no fabricated joins.
    ends = [m.end() for m in re.finditer(r'[.!?](?=\s|$)|\n\n',text)]
    fits = [n for n in ends if n <= max_chars and estimate_tokens(text[:n]) <= max_tokens]
    return text[:max(fits)].rstrip() if fits else ''



def novel_span(text, sources):
    """Keep a contiguous run of sentences, excluding already supplied full sentences."""
    previous=[normalize_text(s['supplied_text']) for s in sources]
    if not previous: return text
    spans=list(re.finditer(r'.+?(?:[.!?](?=\s|$)|\n\n|$)',text,re.S))
    runs=[];start=None;end=None
    for match in spans:
        sentence=normalize_text(match.group())
        repeated=len(sentence)>=60 and any(sentence in prior for prior in previous)
        if repeated:
            if start is not None:runs.append((start,end));start=None
        else:
            if start is None:start=match.start()
            end=match.end()
    if start is not None:runs.append((start,end))
    if not runs:return ''
    start,end=max(runs,key=lambda span:span[1]-span[0])
    return text[start:end].strip()

def pack(question, hits, analysis, config, max_chars, num_predict, system, extra_reserve=0):
    fixed = prompt_estimate(messages_for(question,'',analysis,system)) + extra_reserve
    budget = min(config.context_token_budget, CONTEXT_LIMIT-num_predict-SAFETY_MARGIN-fixed)
    trace = dict(estimator='UTF-8 bytes / 3, rounded up; estimated, not Qwen tokenizer',
        context_limit=CONTEXT_LIMIT, reserved_output_tokens=num_predict, safety_margin=SAFETY_MARGIN,
        fixed_prompt_tokens=fixed, evidence_budget=max(0,budget), selected_tokens=0, rejected=[])
    if budget <= 0:
        trace['reason']='fixed prompt and output reservation leave no evidence budget'
        return '',[],trace
    selected=[]; parts=[]; counts=Counter(); remaining=deepcopy(hits)
    from retrieval_ranking import _fingerprint
    @lru_cache(maxsize=192)
    def fingerprint(text): return _fingerprint(text)
    @lru_cache(maxsize=4096)
    def overlap(left,right):
        a,b=fingerprint(left),fingerprint(right)
        return len(a & b)/max(1,len(a | b))
    # Explicit subject reservations use the existing shared planner, never new aliases.
    subjects=[]
    if analysis is not None and analysis.effective_type=='comparison':
        from retrieval_planning import build_plan
        subjects=[e.normalized_name for e in build_plan(analysis,config).entities if e.reason=='comparison subject']
    covered=set()
    while remaining and len(selected)<config.hybrid_pack_k:
        def priority(row):
            c=row['chunk']; title=normalize_text(c['article_path'].replace('_',' '))
            reservation=any(s not in covered and normalize_text(s)==title for s in subjects)
            duplication=max((overlap(c['text'],s['supplied_text']) for s in selected),default=0.)
            score=row.get('rerank_score',row['score'])
            return (-int(reservation),-(score-config.redundancy_penalty*duplication-config.article_repeat_penalty*counts[c['article_path']]),c['article_path'],c['chunk_id'])
        remaining.sort(key=priority); row=remaining.pop(0); c=row['chunk']; key=[c['article_path'],c['chunk_id']]
        reason=None; original_text=c['text']; text=novel_span(original_text,selected); norm=normalize_text(text)
        if not norm: reason='empty evidence'
        elif any(norm==normalize_text(s['supplied_text']) or norm in normalize_text(s['supplied_text']) or normalize_text(s['supplied_text']) in norm for s in selected): reason='duplicate'
        elif any(overlap(text,s['supplied_text'])>=config.duplicate_overlap_threshold for s in selected): reason='overlap'
        elif any(c['article_path']==s['article_path'] and c.get('start_offset') is not None and s.get('start_offset') is not None and
                 max(c['start_offset'],s['start_offset'])<min(c['end_offset'],s['end_offset']) for s in selected): reason='overlap'
        elif row.get('rerank_score',1)<config.rerank_relevance_floor: reason='lower relevance'
        if not reason:
            label=f'S{len(selected)+1}'
            header=f"[{label}] {c['article_path']} | {c['section']} | {c.get('subsection') or '-'}\n"
            prefix='\n\n'.join(parts)+ ('\n\n' if parts else '')+header
            tokens_left=budget-estimate_tokens(prefix)
            chars_left=min(max_chars,config.context_chars)-len(prefix)
            excerpt=trim_sentence(text,tokens_left,chars_left)
            if not excerpt or (len(excerpt)<80 and len(original_text)>80): reason='token budget'
            else:
                source=dict(label=label,score=row['score'],**c,supplied_text=excerpt,truncated=excerpt!=original_text)
                if c.get('start_offset') is not None:
                    source['start_offset']=c['start_offset']+original_text.index(excerpt)
                    source['end_offset']=source['start_offset']+len(excerpt)
                selected.append(source); parts.append(header+excerpt); counts[c['article_path']]+=1
                covered.add(normalize_text(c['article_path'].replace('_',' ')))
        if reason: trace['rejected'].append({'key':key,'reason':reason})
    trace['rejected'].extend({'key':[r['chunk']['article_path'],r['chunk']['chunk_id']],'reason':'cap'} for r in remaining)
    context='\n\n'.join(parts)
    trace.update(selected_tokens=estimate_tokens(context),full_prompt_estimate=prompt_estimate(messages_for(question,context,analysis,system))+extra_reserve,
                 selected_count=len(selected),distinct_articles=len(counts))
    return context,selected,trace
