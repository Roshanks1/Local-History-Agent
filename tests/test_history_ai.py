import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock
import history_ai as h


def hit(identifier, text='evidence '*100):
    return {'score': .8, 'chunk': {'chunk_id': identifier, 'article_path': 'Article',
            'section': 'Intro', 'subsection': None, 'text': text}}


class HistoryTests(unittest.TestCase):
    def test_metric_denominators_and_unjudged(self):
        rows = [dict(relevant_chunk_ids=['a', 'b'], results=[hit('x'), hit('a'), hit('b')]),
                dict(relevant_chunk_ids=['z'], results=[hit('x')]), dict(results=[hit('a')])]
        m = h.metrics(rows)
        self.assertEqual(m['hit_rate@1'], 0)
        self.assertEqual(m['hit_rate@3'], .5)
        self.assertEqual(m['recall@3'], .5)
        self.assertEqual(m['mrr@5'], .25)
        self.assertEqual(m['unjudged_questions'], 1)
        self.assertIsNone(h.metrics([dict(results=[])])['recall@1'])

    def test_duplicate_hits_cannot_inflate_recall(self):
        m = h.metrics([dict(relevant_chunk_ids=['a', 'b'], results=[hit('a'), hit('a')])])
        self.assertEqual(m['recall@3'], .5)

    def test_bad_vectors(self):
        for a, b in [([0], [1]), ([1], [1, 2]), ([float('nan')], [1])]:
            with self.assertRaises(ValueError):
                h.cosine(a, b)
        self.assertAlmostEqual(h.cosine([1, 2], [2, 4]), 1)

    def test_context_budget_and_citation_mapping(self):
        text, sources = h.evidence_context([hit('a'), hit('b')], 500)
        self.assertLessEqual(len(text), 500)
        self.assertEqual(sources[0]['label'], 'S1')
        self.assertTrue(sources[0]['truncated'])
        self.assertIn(sources[0]['supplied_text'], text)

    def test_generation_unknown_citation_and_options(self):
        api = Mock()
        api.list.return_value = {'models': [{'model': 'qwen3:14b', 'digest': 'd'}]}
        api.chat.return_value = {'message': {'content': 'Claim [S1]. False [S9].'},
                                 'eval_count': 10, 'eval_duration': 1000000000}
        answer = h.generate('Question?', [hit('a')], 'qwen3:14b', api)
        self.assertEqual(answer['citation_check']['unknown_labels'], ['S9'])
        self.assertEqual(answer['tokens_per_second'], 10)
        self.assertFalse(api.chat.call_args.kwargs['think'])
        self.assertEqual(api.chat.call_args.kwargs['keep_alive'], 0)

    def test_empty_evidence_does_not_call_model(self):
        api = Mock()
        answer = h.generate('Question?', [], 'qwen3:14b', api)
        self.assertTrue(answer['skipped_generation'])
        api.chat.assert_not_called()

    def test_retrieval_and_model_mismatch(self):
        api = Mock()
        api.list.return_value = {'models': [{'model': 'embed:latest', 'digest': 'd'}]}
        api.embed.return_value = {'embeddings': [[1, 0]]}
        index = {'metadata': {'embedding_model': 'embed', 'model_digest': 'd'},
                 'chunks': [hit('b')['chunk'], hit('a')['chunk']], 'vectors': [[0, 1], [1, 0]]}
        self.assertEqual(h.retrieve(index, 'query', 1, api)[0]['chunk']['chunk_id'], 'a')
        index['metadata']['model_digest'] = 'old'
        with self.assertRaises(ValueError):
            h.retrieve(index, 'query', 1, api)

    def test_stale_labels_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'q.json'
            h.save(path, {'corpus_sha256': 'old', 'questions': [
                {'id': 'q', 'question': '?', 'relevant_chunk_ids': ['a']}]})
            with self.assertRaises(ValueError):
                h.load_benchmark(path, {'chunks': [hit('a')['chunk']],
                                       'metadata': {'corpus_sha256': 'new'}})


if __name__ == '__main__':
    unittest.main()
