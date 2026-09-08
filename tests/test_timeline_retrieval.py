import unittest
from unittest.mock import patch
from history_ai import retrieve_timeline


class TimelineRetrievalTests(unittest.TestCase):
    @patch('history_ai.retrieve')
    def test_covers_record_endpoints_in_source_order(self, retrieve):
        chunks = [{'chunk_id': str(n), 'article_path': 'Commander', 'section': 'Battles',
                   'text': 'Date: 1800; Battle: Example', 'subsection': None} for n in range(15)]
        retrieve.return_value = [{'chunk': c, 'score': n/20} for n, c in reversed(list(enumerate(chunks)))]
        result = retrieve_timeline({'chunks': chunks}, 'timeline', None)
        ids = [int(h['chunk']['chunk_id']) for h in result]
        self.assertEqual(len(ids), 10)
        self.assertEqual(ids, sorted(ids))
        self.assertEqual((ids[0], ids[-1]), (0, 14))

    @patch('history_ai.retrieve')
    def test_prose_fallback(self, retrieve):
        hits = [{'chunk': {'text': 'Prose evidence'}, 'score': .5} for _ in range(12)]
        retrieve.return_value = hits
        self.assertEqual(retrieve_timeline({'chunks': [None]*12}, 'timeline', None), hits[:8])
