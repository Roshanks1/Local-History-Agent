"""Resolve all final benchmark citations and measure repeated passage text locally."""
import json,sys,re,statistics
from pathlib import Path
import history_ai as h
from evaluate_v130 import covered
from evidence_packing import normalize_text
from offline_reader import OfflineReader
from libzim.reader import Archive
from retrieval_ranking import _fingerprint
out=h.ROOT/'artifacts/v130-verified';benchmark=h.read(h.ROOT/'benchmarks/v130_evidence.json');reader=OfflineReader(Archive(str(h.ZIM_PATH)))
checks=[]
for q in benchmark['questions']:
 f=h.read(out/(q['id']+'-final.json')); b=h.read(h.ROOT/'artifacts/v130'/(q['id']+'.json'))
 def duplication(sources):
  seen=set();dup=total=0
  for s in sources:
   tokens=re.findall(r'\w+',s['supplied_text'].casefold());grams=list(zip(tokens,tokens[1:],tokens[2:]));dup+=sum(g in seen for g in grams);total+=len(grams);seen.update(grams)
  return dup/max(1,total)
 lexical_only={c['chunk_id'] for c in f.get('retrieval_debug',{}).get('candidates',[]) if c['origins']==['bm25']}
 supporting=[s['chunk_id'] for s in f['sources'] if s['chunk_id'] in lexical_only and covered([s],q)]
 norms=[normalize_text(s['supplied_text']) for s in f['sources']]
 checks.append({'id':q['id'],'source_count':len(f['sources']),'valid_sources':sum(bool(reader.link(s['article_path'],s.get('section'),s.get('subsection'))) for s in f['sources']),
 'highlight_matches':sum(reader.has_evidence(s['article_path'],s['supplied_text']) for s in f['sources']),
 'exact_duplicates':len(norms)-len(set(norms)), 'baseline_repeated_trigram_share':duplication(b['sources']), 'final_repeated_trigram_share':duplication(f['sources']),
 'lexical_only_support':supporting,'prompt_with_reservation':f.get('generation_debug',{}).get('packing',{}).get('full_prompt_estimate',0)+984})
h.save(out/'source_checks.json',checks)
print(json.dumps({'sources':sum(r['source_count'] for r in checks),'valid':sum(r['valid_sources'] for r in checks),'highlights':sum(r['highlight_matches'] for r in checks),'duplicates':sum(r['exact_duplicates'] for r in checks),'baseline_repeated_trigram_share':statistics.mean(r['baseline_repeated_trigram_share'] for r in checks),'final_repeated_trigram_share':statistics.mean(r['final_repeated_trigram_share'] for r in checks),'lexical_only_support':[(r['id'],r['lexical_only_support']) for r in checks if r['lexical_only_support']]},indent=2))
