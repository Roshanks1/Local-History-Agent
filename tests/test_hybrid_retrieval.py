import copy
from dataclasses import replace
import sqlite3
import unittest
from unittest.mock import Mock, patch
from pathlib import Path
import json

from retrieval_config import RetrievalConfig
from query_analysis import analyze
from retrieval_planning import build_plan
from retrieval_candidates import adapt_legacy
from lexical_retrieval import search, validate_manifest
from hybrid_retrieval import retrieve_hybrid, rerank_candidates, inspector
from evidence_packing import pack, prompt_estimate, normalize_text
from history_ai import generate, SYSTEM


def row(name,text,score=.7,article=None,section='History'):
    return {'score':score,'rerank_score':score,'chunk':{'article_path':article or name,'chunk_id':name,
             'section':section,'subsection':None,'text':text}}


def adapt(rows):
    return adapt_legacy(rows,corpus_version='test',chunker_version='v1')


class LexicalTests(unittest.TestCase):
    def test_literal_unicode_names_dates_and_independent_recovery(self):
        pool=adapt([row('dense','Other historical evidence.'),row('lexical','Lützen 1632 Gustavus Adolphus. Jean-Paul’s reign; Louis XIV.')])
        found,info=search(pool,'"Lützen" OR 1632 - Jean-Paul’s XIV',corpus_version='test',chunker_version='v1')
        self.assertEqual(found[0]['chunk']['chunk_id'],'lexical')
        self.assertLess(found[0]['score'],0)
        self.assertEqual(info['manifest']['chunks'],2)
        self.assertEqual(info['score_direction'],'lower')
        self.assertNotEqual(info['manifest']['coverage'],'archive-wide')
        self.assertEqual(search(pool,'***',corpus_version='test',chunker_version='v1')[0],[])
        self.assertEqual(search([],'date',corpus_version='test',chunker_version='v1')[0],[])

    def test_manifest_staleness_bounds_and_interrupted_generation(self):
        for actual in (None,{}, {'schema':2}):
            with self.assertRaises(ValueError):validate_manifest(actual,{'schema':1})
        rows=adapt([row('a','Historical evidence.')])
        with self.assertRaises(ValueError): search(rows,'history',corpus_version='x',chunker_version='y',max_rows=0)
        def cancel():raise InterruptedError('stop')
        with self.assertRaises(InterruptedError):search(rows,'history',corpus_version='x',chunker_version='y',check_cancel=cancel)
        self.assertTrue(search(rows,'Historical',corpus_version='x',chunker_version='y')[0])


class HybridTests(unittest.TestCase):
    def setUp(self):
        self.config=replace(RetrievalConfig(),retrieval_mode='hybrid',hybrid_branch_k=1)
        self.analysis=analyze('When was Magna Carta sealed?',enhanced=True)
        self.plan=build_plan(self.analysis,self.config)
        self.rows=[row('d','Distant unrelated semantic evidence.',.9),row('l','Magna Carta was sealed in 1215.',.01)]
        self.index={'chunks':[r['chunk'] for r in self.rows]}

    @patch('history_ai.retrieve')
    def test_real_lexical_branch_recovers_dense_miss_debug_is_bounded(self,retrieve):
        retrieve.return_value=self.rows
        first,trace=retrieve_hybrid(self.index,self.analysis,self.config,Mock(),self.plan)
        self.assertEqual({r['chunk']['chunk_id'] for r in first},{'d','l'})
        lexical=next(r for r in first if r['chunk']['chunk_id']=='l')
        self.assertEqual(lexical['retrieval']['origins'],['bm25'])
        _,other=retrieve_hybrid(self.index,self.analysis,self.config,Mock(),self.plan)
        self.assertNotEqual(trace['request_id'],other['request_id'])
        self.assertEqual([r['chunk'] for r in first],[r['chunk'] for r in other['reranked_chunks']])
        self.assertLessEqual(len(inspector(trace,[])['candidates']),80)

    @patch('history_ai.retrieve',side_effect=RuntimeError('embedding unavailable'))
    def test_dense_failure_keeps_lexical(self,_):
        found,trace=retrieve_hybrid(self.index,self.analysis,self.config,Mock(),self.plan)
        self.assertTrue(found)
        self.assertIn('dense',trace['fallback_reasons'])

    @patch('retrieval_expansion.expand',return_value=([],{}))
    @patch('hybrid_retrieval.search',side_effect=sqlite3.DatabaseError('corrupt'))
    def test_lexical_failure_restores_legacy(self,_,legacy):
        _,trace=retrieve_hybrid(self.index,self.analysis,self.config,Mock(),self.plan)
        self.assertEqual(trace['mode'],'legacy_fallback');legacy.assert_called_once()

    @patch('retrieval_expansion.expand')
    def test_cancellation_never_falls_back(self,legacy):
        def cancel():raise InterruptedError()
        with self.assertRaises(InterruptedError):retrieve_hybrid(self.index,self.analysis,self.config,Mock(),self.plan,check_cancel=cancel)
        legacy.assert_not_called()

    def test_reranker_failure_and_query_dependence(self):
        rows=adapt(self.rows)
        with patch('hybrid_retrieval.rerank',side_effect=TimeoutError()):
            found,meta=rerank_candidates(rows,self.plan,None)
        self.assertEqual(meta['backend'],'rrf');self.assertTrue(meta['fallback_reason'])
        self.assertEqual([r['chunk'] for r in found],[r['chunk'] for r in rows])
        equal=adapt([row('x','Magna Carta was sealed in 1215.',.5),row('y','French Revolution social economic political crisis.',.5)])
        a,_=rerank_candidates(equal,self.plan,None)
        other=build_plan(analyze('What caused the French Revolution?'),self.config)
        b,_=rerank_candidates(equal,other,None)
        self.assertNotEqual(a[0]['chunk']['chunk_id'],b[0]['chunk']['chunk_id'])


class PackingTests(unittest.TestCase):
    def setUp(self):self.config=replace(RetrievalConfig(),retrieval_mode='hybrid')
    def test_duplicate_overlap_oversized_and_exact_prefix(self):
        a=row('a','Distinct first fact. '*1000,.9)
        b=row('b','A second useful short historical fact.',.8)
        dup=row('dup',b['chunk']['text'],.7)
        context,sources,trace=pack('Facts?', [a,b,dup],None,replace(self.config,context_token_budget=120),1000,600,SYSTEM)
        self.assertTrue(sources)
        self.assertLessEqual(trace['selected_tokens'],120)
        self.assertTrue(all(s['supplied_text'] in s['text'] for s in sources))
        self.assertEqual(len({normalize_text(s['supplied_text']) for s in sources}),len(sources))
        # Oversized unbreakable passage does not block smaller useful evidence.
        a['chunk']['text']='x'*20000
        _,sources,_=pack('Facts?', [a,b],None,replace(self.config,context_token_budget=120),1000,600,SYSTEM)
        self.assertEqual([s['chunk_id'] for s in sources],['b'])

    def test_no_budget_skips_model_and_full_prompt_counted(self):
        api=Mock();r=generate('x'*25000,[row('a','Useful evidence.')],'qwen3:14b',api,config=self.config,debug=True)
        api.chat.assert_not_called();self.assertTrue(r['skipped_generation'])
        self.assertEqual(r['generation_debug']['packing']['evidence_budget'],0)

    def test_comparison_subjects_and_distinct_facts(self):
        analysis=analyze('Compare the causes of the French and Russian Revolutions.')
        rows=[row('f','The French fiscal crisis concerned tax collection.',.9,'French_Revolution'),
              row('f2','The French monarchy opposed institutional reform.',.89,'French_Revolution'),
              row('r','Russian workers protested wartime shortages.',.6,'Russian_Revolution')]
        _,sources,_=pack(analysis.question,rows,analysis,self.config,15000,600,SYSTEM)
        self.assertEqual({s['article_path'] for s in sources},{'French_Revolution','Russian_Revolution'})
        self.assertEqual(len(sources),3)

    def test_debug_equality_and_prompt_source_correspondence(self):
        api=Mock();api.list.return_value={'models':[{'model':'qwen3:14b','digest':'d'}]}
        api.chat.return_value={'message':{'content':'Fact [S1].'}}
        rows=[row('a','A historically supported sentence.')]
        a=generate('Fact?',rows,'qwen3:14b',api,config=self.config)
        b=generate('Fact?',rows,'qwen3:14b',api,config=self.config,debug=True)
        self.assertEqual(a['sources'],b['sources'])
        self.assertIn(b['sources'][0]['supplied_text'],b['generation_debug']['messages'][1]['content'])
        self.assertLessEqual(b['generation_debug']['packing']['full_prompt_estimate']+600+384,8192)

    def test_named_subject_and_new_chat_isolation(self):
        self.assertFalse(analyze('How did Sulla’s reforms affect the Republic after his death?',enhanced=True).clarification)
        self.assertTrue(analyze('How did he die?',enhanced=True).clarification)
        self.assertTrue(analyze('Why did he intervene in the Thirty Years War?',enhanced=True).clarification)
        self.assertEqual(analyze('Outline the sequence from the Estates-General to the abolition of the French monarchy.',enhanced=True).effective_type,'general')
        self.assertTrue(analyze('How did Sulla’s reforms affect the Republic after his death?').clarification)


if __name__=='__main__':unittest.main()

class PersistenceIntegrationTests(unittest.TestCase):
    def test_hybrid_evidence_survives_save_restart_and_reader_links(self):
        import tempfile
        from local_ui import Application
        from conversation_store import ConversationStore
        config=replace(RetrievalConfig(),retrieval_mode='hybrid')
        api=Mock();api.list.return_value={'models':[{'model':'qwen3:14b','digest':'d'}]}
        api.chat.return_value={'message':{'content':'The charter was sealed in 1215 [S1].'}}
        reader=Mock();reader.link.return_value='/wiki/Magna_Carta';reader.has_evidence.return_value=True
        def answer(args):
            return generate(args.question,[row('Magna_Carta_000','Magna Carta was sealed in 1215.',article='Magna_Carta')],
                            'qwen3:14b',api,config=config,debug=True)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'chats.sqlite3'
            app=Application(reader,answer,path)
            result=app.run({'question':'When was Magna Carta sealed?'})
            stored=app.store.load(result['session'])['turns'][0]['result']['sources']
            app.store.close()
            reopened=Application(reader,answer,path)
            loaded=reopened.run({'action':'open','session':result['session']})
            self.assertEqual(reopened.store.load(result['session'])['turns'][0]['result']['sources'],stored)
            self.assertEqual(loaded['turns'][0]['result']['sources'][0]['label'],'S1')
            self.assertTrue(loaded['turns'][0]['result']['sources'][0]['article_url'].startswith('/wiki/'))
            self.assertEqual(api.chat.call_count,1)
            reopened.store.close()

    def test_build_can_retain_chunks_when_embedding_service_fails(self):
        import tempfile
        import argparse
        import history_ai as h
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory);zim=path/'archive.zim';zim.write_bytes(b'fixture')
            args=argparse.Namespace(zim=zim,articles=['A'],max_chars=2000,overlap_chars=300,
                embed_model='nomic-embed-text',variant='title',index=path/'index.json',quiet=True,allow_dense_failure=True)
            with patch('wikipedia_local.LocalWikipedia'),patch('chunking.chunk_article',return_value=[row('A','Evidence.')['chunk']]),patch('history_ai.client') as client:
                client.return_value.list.side_effect=ConnectionError('offline model service')
                h.build(args)
            index=h.load_index_value(h.read(args.index))
            self.assertTrue(index['dense_error']);self.assertEqual(index['vectors'],[])
            self.assertEqual(index['chunks'][0]['text'],'Evidence.')


class TimelineBoundsTests(unittest.TestCase):
    def test_bounds_come_from_source_not_invented_dates(self):
        from hybrid_retrieval import endpoint_period
        analysis=analyze('Outline the sequence from the Assembly to the abolition of the monarchy.',enhanced=True)
        index={'chunks':[row('Revolution_000','The Assembly began the abolition of the monarchy from 1800 to 1810.',section='Introduction')['chunk']]}
        self.assertEqual(endpoint_period(index,analysis),(1800,1810))
        index['chunks'][0]['text']='The Assembly changed the monarchy.'
        self.assertIsNone(endpoint_period(index,analysis))

class TimelineGenerationTests(unittest.TestCase):
    def test_hybrid_timeline_schema_budget_and_labels(self):
        api=Mock();api.list.return_value={'models':[{'model':'qwen3:14b','digest':'d'}]}
        api.chat.return_value={'message':{'content':'{"entries":[{"source_label":"S1","summary":"The assembly convened."}]}'}}
        evidence=row('a','Dated passage: In 1789 the assembly convened.',article='Assembly')
        evidence['chunk'].update(sortable_date=[1789,1,1],date_text='1789',date_precision='year',approximate=False)
        result=generate('Give a timeline of the assembly.',[evidence],'qwen3:14b',api,
            analysis=analyze('Give a timeline of the assembly.'),
            config=replace(RetrievalConfig(),retrieval_mode='hybrid'),debug=True)
        self.assertIn('1789',result['answer'])
        self.assertEqual(result['citation_check']['unknown_labels'],[])
        self.assertLessEqual(result['generation_debug']['packing']['full_prompt_estimate']+984,8192)
        self.assertIn('format',api.chat.call_args.kwargs)


class FallbackScoreTests(unittest.TestCase):
    def test_failure_restores_fused_scores_not_mutated_semantic_scores(self):
        rows=adapt([row('a','A factual historical sentence.',1/61)])
        rows[0]['retrieval'].update(fused_score=1/61,dense_pool_score=.9)
        plan=build_plan(analyze('Historical sentence?'),RetrievalConfig())
        with patch('hybrid_retrieval.rerank',side_effect=RuntimeError('failed')):
            result,meta=rerank_candidates(rows,plan,None)
        self.assertEqual(result[0]['score'],1/61)
        self.assertEqual(result[0]['rerank_score'],.5)
        self.assertEqual(meta['backend'],'rrf')

    def test_repeated_sentence_trim_keeps_original_contiguous_evidence(self):
        from evidence_packing import novel_span
        repeated='This is a sufficiently long historical sentence about a treaty and its consequences.'
        fresh='A different sentence supplies a distinct date and event.'
        original=repeated+' '+fresh
        excerpt=novel_span(original,[{'supplied_text':repeated}])
        self.assertEqual(excerpt,fresh)
        self.assertIn(excerpt,original)
