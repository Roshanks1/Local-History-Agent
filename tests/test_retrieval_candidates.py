import copy
import unittest

from retrieval_candidates import adapt_legacy, reciprocal_rank_fusion


def rows(*values):
    return adapt_legacy([dict(score=score, chunk=dict(article_path=name,
        chunk_id=name + '_000', section='Introduction', text=name + ' evidence'))
        for name, score in values], corpus_version='corpus-1', chunker_version='chunker-1')


class CandidateTests(unittest.TestCase):
    def test_adapter_preserves_public_contract_and_order_without_mutation(self):
        original = rows(('B', .2), ('A', .8))
        snapshot = copy.deepcopy(original)
        adapted = adapt_legacy(original, corpus_version='corpus-1', chunker_version='chunker-1')
        self.assertEqual([r['chunk'] for r in adapted], [r['chunk'] for r in original])
        self.assertEqual([r['score'] for r in adapted], [.2, .8])
        adapted[0]['chunk']['text'] = 'changed'
        self.assertEqual(original, snapshot)
        self.assertIsNone(original[0]['retrieval']['rerank_score'])

    def test_identity_separates_versions_and_preserves_reader_target(self):
        first = rows(('A', 1))[0]
        changed = copy.deepcopy(first)
        changed['chunk']['article_path'] = 'Alias'
        changed['chunk']['canonical_article_id'] = 'A'
        alias = adapt_legacy([changed], corpus_version='corpus-1', chunker_version='chunker-1')[0]
        self.assertEqual(first['retrieval']['candidate_id'], alias['retrieval']['candidate_id'])
        self.assertEqual(alias['chunk']['article_path'], 'Alias')
        newer = adapt_legacy([first], corpus_version='corpus-2', chunker_version='chunker-1')[0]
        self.assertNotEqual(first['retrieval']['candidate_id'], newer['retrieval']['candidate_id'])

    def test_hand_computed_duplicates_and_score_directions(self):
        dense = rows(('A', .9), ('A', .1), ('B', .8))
        lexical = rows(('B', -5), ('C', -2))
        before = copy.deepcopy(dense)
        result = reciprocal_rank_fusion(dict(dense=dense, bm25=lexical),
                                        directions=dict(dense='higher', bm25='lower'))
        self.assertEqual([r['chunk']['article_path'] for r in result], ['B', 'A', 'C'])
        self.assertAlmostEqual(result[0]['score'], 1/62 + 1/61)
        self.assertAlmostEqual(result[1]['score'], 1/61)
        self.assertEqual(result[0]['retrieval']['origins'], ['bm25', 'dense'])
        self.assertNotIn('bm25', result[1]['retrieval']['branches'])
        self.assertEqual(dense, before)

    def test_ties_stable_across_input_order_and_single_empty_branches(self):
        candidates = rows(('A', 1), ('B', 1))
        def fuse(values):
            return reciprocal_rank_fusion({'dense': values}, directions={'dense': 'higher'})
        self.assertEqual(fuse(candidates), fuse(list(reversed(candidates))))
        self.assertEqual(fuse([]), [])
        self.assertEqual(reciprocal_rank_fusion({}, directions={}), [])

    def test_limits_invalid_scores_and_cancellation(self):
        candidates = rows(('A', 1), ('B', .5))
        def fuse(**kwargs):
            return reciprocal_rank_fusion({'dense': candidates}, directions={'dense': 'higher'}, **kwargs)
        self.assertEqual(len(fuse(branch_limit=1)), 1)
        self.assertEqual(len(fuse(output_limit=1)), 1)
        for kwargs in ({'input_limit': 1}, {'k': 0}, {'output_limit': True}):
            with self.assertRaises(ValueError):
                fuse(**kwargs)
        def cancel():
            raise InterruptedError('cancelled')
        with self.assertRaises(InterruptedError):
            fuse(check_cancel=cancel)
        candidates[0]['score'] = float('nan')
        with self.assertRaises(ValueError):
            fuse()


if __name__ == '__main__':
    unittest.main()
