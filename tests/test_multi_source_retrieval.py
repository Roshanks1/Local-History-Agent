import unittest
from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from article_discovery import discover_plan
from query_analysis import analyze
from retrieval_config import RetrievalConfig
from retrieval_planning import build_plan, extract_entities, normalize_entity
from retrieval_ranking import rerank, select_evidence
from retrieval_expansion import expand
from history_ai import generate
from wikipedia_local import LocalWikipedia


def hit(identifier, article, text, score=.7, section='History'):
    return {'score': score, 'chunk': {'chunk_id': identifier, 'article_path': article,
            'section': section, 'subsection': None, 'text': text}}


class PlanningTests(unittest.TestCase):
    def test_checked_in_benchmark_plans_are_deterministic(self):
        benchmark = json.loads((Path(__file__).parents[1]/'benchmarks/multi_source_retrieval.json').read_text())
        config = RetrievalConfig()
        for question in benchmark['questions']:
            first = build_plan(analyze(question['question']), config).to_dict()
            second = build_plan(analyze(question['question']), config).to_dict()
            self.assertEqual(first, second)
            self.assertEqual(first['breadth'], question['breadth'])

    def test_breadth_queries_entities_and_narrow_control(self):
        config = RetrievalConfig()
        broad = build_plan(analyze('Why did the Roman Republic collapse?'), config)
        self.assertEqual(broad.breadth, 'broad')
        self.assertGreater(len(broad.seed_queries), 1)
        self.assertIn('roman republic', [entity.normalized_name for entity in broad.entities])
        narrow = build_plan(analyze('In what year was Magna Carta sealed?'), config)
        self.assertEqual(narrow.breadth, 'narrow')
        self.assertEqual(len(narrow.seed_queries), 1)
        self.assertEqual(narrow.article_limit, config.narrow_candidate_articles)

    def test_comparison_expands_both_sides_and_bounds(self):
        plan = build_plan(analyze('Compare the causes of the French and Russian Revolutions.'),
                          replace(RetrievalConfig(), max_entities=3, max_seed_queries=3))
        names = [entity.normalized_name for entity in plan.entities]
        self.assertIn('french revolution', names)
        self.assertIn('russian revolution', names)
        self.assertLessEqual(len(plan.entities), 3)
        self.assertLessEqual(len(plan.seed_queries), 3)

    def test_normalization_and_bounded_followup_entities(self):
        self.assertEqual(normalize_entity('Sulla_(Roman_general)'), 'sulla')
        entities = extract_entities('How did his reforms affect the Republic afterward?',
                                    ['Sulla', 'Roman Republic'], limit=1)
        self.assertEqual([entity.display_name for entity in entities], ['Sulla'])


class DiscoveryPlanTests(unittest.TestCase):
    @patch('article_discovery.time.monotonic', side_effect=[0] + [2]*20)
    @patch('article_discovery.discover')
    def test_discovery_time_bound_returns_collected_candidates(self, discover, _clock):
        config = replace(RetrievalConfig(), max_discovery_seconds=1)
        result = discover_plan(Mock(), build_plan(analyze('Why did Rome collapse?'), config), config)
        self.assertEqual(result['articles'], [])
        self.assertTrue(result['bounds']['time_limit_reached'])
        discover.assert_not_called()

    @patch('article_discovery.discover')
    def test_merges_provenance_redirects_and_enforces_bound(self, discover):
        config = replace(RetrievalConfig(), candidate_articles=3, articles_per_query=2)
        plan = build_plan(analyze('Why did the Roman Republic collapse?'), config)
        discover.side_effect = [
            {'articles': ['Roman_Republic', 'Roman_Republic_alias'], 'title_matches': ['Roman_Republic'],
             'matched_articles': ['Roman_Republic'], 'fulltext_available': True},
            {'articles': ['Social_War'], 'title_matches': [], 'matched_articles': [], 'fulltext_available': True},
        ] + [{'articles': [], 'title_matches': [], 'matched_articles': [], 'fulltext_available': True}]*2
        wiki = Mock()
        wiki.zim.has_fulltext_index = True
        wiki.zim.get_entry_by_path.side_effect = lambda path: (
            SimpleNamespace(path=path, is_redirect=True,
                get_redirect_entry=lambda: SimpleNamespace(path='Roman_Republic', is_redirect=False))
            if path == 'Roman_Republic_alias' else SimpleNamespace(path=path, is_redirect=False))
        wiki.search.return_value = []
        result = discover_plan(wiki, plan, config)
        self.assertEqual(result['articles'], ['Roman_Republic', 'Social_War'])
        self.assertIn('direct title', result['article_reasons']['Roman_Republic'])
        self.assertIn('seed query 2', result['article_reasons']['Social_War'])
        self.assertLessEqual(len(result['articles']), plan.article_limit)

    def test_one_hop_related_links_are_local_bounded_and_relevant(self):
        html = b'''<div id="mw-content-text"><p>Political crisis and civil war empowered
          <a href="Sulla">Sulla</a> and preceded the <a href="Julius_Caesar">rise of Caesar</a>.
          <a href="https://example.com">remote</a><a href="#note">note</a></p>
          <p><a href="Roman_pottery">Pottery</a> was manufactured.</p></div>'''
        wiki = LocalWikipedia.__new__(LocalWikipedia)
        entry = SimpleNamespace(path='Roman_Republic', is_redirect=False,
                                get_item=lambda: SimpleNamespace(content=html))
        wiki.zim = Mock()
        wiki.zim.get_entry_by_path.return_value = entry
        related = wiki.related_articles('Roman_Republic', 'Roman Republic political crisis civil war', 2)
        self.assertEqual(related, ['Sulla', 'Julius_Caesar'])
        self.assertNotIn('https://example.com', related)


class RankingTests(unittest.TestCase):
    def plan(self):
        return build_plan(analyze('Why did the Roman Republic collapse?'), RetrievalConfig())

    def test_components_determinism_diversity_and_budget(self):
        candidates = [
            hit('a1', 'Roman_Republic', 'Political institutions and conflict weakened the republic. '*8, .9, 'Political institutions'),
            hit('a2', 'Roman_Republic', 'Political institutions and conflict weakened the republic. '*8, .89, 'Political institutions'),
            hit('b1', 'Social_War', 'The Social War changed citizenship and intensified social conflict. '*8, .8, 'Consequences'),
            hit('c1', 'Sulla', 'Civil war and military power changed republican politics. '*8, .78, 'Dictatorship'),
        ]
        discovery = {'article_reasons': {'Roman_Republic': ['direct title'],
                                         'Social_War': ['seed query 2'], 'Sulla': ['entity: Sulla']}}
        first = rerank(candidates, self.plan(), discovery)
        second = rerank(candidates, self.plan(), discovery)
        self.assertEqual([(r['chunk']['chunk_id'], r['score']) for r in first],
                         [(r['chunk']['chunk_id'], r['score']) for r in second])
        self.assertIn('semantic', first[0]['score_components'])
        config = replace(RetrievalConfig(), context_token_budget=900,
                         selected_chunks_per_article=1, duplicate_overlap_threshold=.5)
        selected, trace = select_evidence(first, config)
        self.assertLessEqual(trace['selected_tokens'], 900)
        self.assertEqual(len({row['chunk']['article_path'] for row in selected}), len(selected))
        reasons = {row['selection_reason'] for row in trace['rejected']}
        self.assertTrue(reasons & {'article cap', 'redundant'})

    def test_low_value_chunk_loses_and_source_provenance_survives(self):
        candidates = [hit('refs', 'Roman_Republic', 'Roman Republic '*50, .99, 'References'),
                      hit('good', 'Social_War', 'The conflict widened citizenship and political tensions. '*5,
                          .75, 'Political consequences')]
        ranked = rerank(candidates, self.plan())
        self.assertEqual(ranked[0]['chunk']['chunk_id'], 'good')
        selected, _ = select_evidence(ranked, RetrievalConfig())
        self.assertEqual(selected[0]['chunk']['article_path'], 'Social_War')
        self.assertEqual(selected[0]['chunk']['section'], 'Political consequences')


class PipelineIntegrationTests(unittest.TestCase):
    @patch('history_ai.retrieve')
    def test_selected_evidence_is_exact_generation_source_set(self, retrieve):
        candidates = [
            hit('roman', 'Roman_Republic', 'Political institutions entered a prolonged crisis. '*8, .92, 'Political crisis'),
            hit('social', 'Social_War', 'The Social War widened citizenship after armed conflict. '*8, .82, 'Aftermath'),
            hit('sulla', 'Sulla', 'Civil war tied armies more closely to individual commanders. '*8, .78, 'Civil war'),
            hit('duplicate', 'Roman_Republic', 'Political institutions entered a prolonged crisis. '*8, .77, 'Political crisis'),
        ]
        retrieve.return_value = candidates
        analysis = analyze('Why did the Roman Republic collapse?')
        config = replace(RetrievalConfig(), context_token_budget=1200,
                         selected_chunks_per_article=1, duplicate_overlap_threshold=.5)
        plan = build_plan(analysis, config)
        selected, trace = expand({'chunks': [row['chunk'] for row in candidates]}, analysis,
                                 config, Mock(), plan,
                                 {'article_reasons': {'Roman_Republic': ['direct title']}})
        self.assertGreaterEqual(len({row['chunk']['article_path'] for row in selected}), 2)
        self.assertNotIn('duplicate', [row['chunk']['chunk_id'] for row in selected])
        api = Mock()
        api.list.return_value = {'models': [{'model': 'qwen3:14b', 'digest': 'd'}]}
        api.chat.return_value = {'message': {'content': 'Supported synthesis [S1] [S2].'}}
        result = generate(analysis.question, selected, 'qwen3:14b', api,
                          analysis=analysis, config=config)
        self.assertEqual([source['chunk_id'] for source in result['sources']],
                         [row['chunk']['chunk_id'] for row in selected])
        self.assertTrue(all(source['supplied_text'] for source in result['sources']))
        self.assertFalse(result['citation_check']['unknown_labels'])
        self.assertLessEqual(trace['evidence_selection']['selected_tokens'], config.context_token_budget)


if __name__ == '__main__':
    unittest.main()
