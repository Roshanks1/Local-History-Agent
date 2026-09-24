"""Frozen passage-level retrieval evaluation. Local ZIM + Ollama embeddings only.

No generation during retrieval evaluation. --smoke is a separate live answer check.
Baseline artifact directory must be captured before implementation (capture_v130.py).
"""
import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import re
import statistics
import time
from unittest.mock import patch, Mock

import history_ai as h
from retrieval_config import load_config
from evidence_packing import normalize_text


def covered(rows, question):
    text=[normalize_text(r.get('supplied_text',r.get('chunk',r).get('text',''))) for r in rows]
    return {f['name'] for f in question['facets'] if any(normalize_text(s) in t for s in f['accepted_spans'] for t in text)}


def metrics(rows, question, universe=None):
    gains=[2 if covered([r],question) else 0 for r in rows]
    # Partial judgments: no facet match means unjudged, not a verified negative.
    allgains=sorted([2 if covered([r],question) else 0 for r in (universe or rows)],reverse=True)[:10]
    dcg=sum((2**g-1)/math.log2(i+2) for i,g in enumerate(gains[:10]))
    ideal=sum((2**g-1)/math.log2(i+2) for i,g in enumerate(allgains))
    return {'recall40':len(covered(rows[:40],question))/len(question['facets']),
            'ndcg10_partial':dcg/ideal if ideal else 0,
            'mrr10':next((1/(i+1) for i,g in enumerate(gains[:10]) if g),0),
            'facets':sorted(covered(rows,question))}


def run(out, repeats=3):
    out.mkdir(parents=True,exist_ok=True)
    benchmark=h.read(h.ROOT/'benchmarks/v130_evidence.json')
    config=replace(load_config(),retrieval_mode='hybrid')
    configpath=out/'hybrid_config.json';h.save(configpath,config.to_dict())
    legacy=out/'legacy_config.json';h.save(legacy,replace(config,retrieval_mode='legacy').to_dict())
    fake=Mock();fake.list.return_value={'models':[{'model':'qwen3:14b','digest':'retrieval-only'}]}
    fake.chat.return_value={'message':{'content':'Evidence evaluation [S1].'}}
    original_generate=h.generate
    def generation(*args,**kwargs):
        args=list(args);args[3]=fake
        return original_generate(*args,**kwargs)
    report={'benchmark':benchmark['version'],'judgment_status':benchmark['judgment_status'],
            'config':config.to_dict(),'queries':[],'generation':'disabled; mock used solely to assemble actual prompt and sources'}
    for q in benchmark['questions']:
        ident=q['id']; baseline=h.read(h.ROOT/f'artifacts/v130/{ident}.json')
        args=argparse.Namespace(question=q['question'],model='qwen3:14b',config=configpath,index=None,
            top_k=None,context_chars=None,num_predict=600,debug=True,quiet=True,output=out/f'{ident}-final.json')
        started=time.perf_counter()
        with patch.object(h,'generate',generation):result=h.ask(args)
        cold=time.perf_counter()-started
        trace=result.get('retrieval_debug',{})
        # Replay frozen stage outputs from full request; candidate snippets aren't evidence for grading.
        articles=(result.get('discovery') or {}).get('articles',[])
        from query_analysis import analyze
        from retrieval_planning import build_plan
        from hybrid_retrieval import retrieve_hybrid
        if articles:
            index=h.read(h.ROOT/'.cache/article-indexes'/(h.fingerprint(articles)+'.json'))
            analysis=analyze(q['question'],enhanced=True)
            ranked,full=retrieve_hybrid(index,analysis,config,h.client(),build_plan(analysis,config),result['discovery'])
            fused=full.get('fused_candidates',[])
            universe=[{'chunk':c} for c in index['chunks']]
        else:ranked=[];fused=[];universe=[]
        baseline_ranked=baseline.get('retrieval_debug',{}).get('reranked_chunks',[])
        universe += baseline_ranked
        row={'id':ident,'category':q['category'],'baseline':metrics(baseline_ranked,q,universe),
            'rrf':metrics(fused,q,universe),'reranked':metrics(ranked,q,universe),
            'baseline_packed':len(covered(baseline['sources'],q))/len(q['facets']),
            'final_packed':len(covered(result['sources'],q))/len(q['facets']),
            'baseline_facets':sorted(covered(baseline['sources'],q)),
            'final_facets':sorted(covered(result['sources'],q)),
            'cold_with_existing_embedding_cache_seconds':cold,
            'lexical_index':trace.get('lexical_index'), 'packing':trace.get('packing'),
            'legacy_warm_seconds':[],'hybrid_warm_seconds':[]}
        for mode,path in [('legacy',legacy),('hybrid',configpath)]:
            args.config=path
            for _ in range(repeats):
                started=time.perf_counter()
                with patch.object(h,'generate',generation):h.ask(args)
                row[mode+'_warm_seconds'].append(time.perf_counter()-started)
        for mode in ('legacy','hybrid'):
            vals=row[mode+'_warm_seconds'];row[mode+'_warm_summary']={'median':statistics.median(vals),'min':min(vals),'max':max(vals)}
        # Restore first final artifact after repetitions.
        h.save(out/f'{ident}-final.json',result)
        report['queries'].append(row);h.save(out/'report.json',report)
        print(ident,round(row['baseline_packed'],3),'->',round(row['final_packed'],3),'facets',row['final_facets'],flush=True)
    qs=report['queries']
    report['aggregate']={name:statistics.mean(r[name] for r in qs) for name in ('baseline_packed','final_packed')}
    for stage in ('baseline','rrf','reranked'):
        report['aggregate'][stage]={m:statistics.mean(r[stage][m] for r in qs) for m in ('recall40','ndcg10_partial')}
    report['aggregate']['exact_mrr']={stage:statistics.mean(r[stage]['mrr10'] for r in qs if r['category']=='exact') for stage in ('baseline','rrf','reranked')}
    report['lost_facets']={r['id']:sorted(set(r['baseline_facets'])-set(r['final_facets'])) for r in qs if set(r['baseline_facets'])-set(r['final_facets'])}
    h.save(out/'report.json',report);print(json.dumps(report['aggregate'],indent=2),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=h.ROOT/'artifacts/v130-evaluation');p.add_argument('--repeats',type=int,default=3)
    args=p.parse_args();run(args.output,args.repeats)
