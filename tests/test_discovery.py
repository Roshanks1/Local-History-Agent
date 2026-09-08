import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch
from article_discovery import discover


class DiscoveryTests(unittest.TestCase):
    def wiki(self):
        wiki = Mock()
        wiki.zim.get_entry_by_path.side_effect = lambda path: SimpleNamespace(path=path, is_redirect=False)
        wiki.zim.has_fulltext_index = True
        def search(phrase, limit):
            return {'World War I': ['World_War_I'], 'World War': ['World_War'],
                    'caused': ['Caused'], 'French Revolution': ['French_Revolution']}.get(phrase, [])
        wiki.search.side_effect = search
        return wiki

    @patch('libzim.search.Searcher')
    def test_named_subject_and_fulltext_without_generic_subtopics(self, searcher):
        searcher.return_value.search.return_value.getResults.return_value = [
            'Causes_of_World_War_I', 'World_War_I', 'July_Crisis']
        result = discover(self.wiki(), 'What caused World War I?')
        self.assertEqual(result['articles'], ['World_War_I', 'Causes_of_World_War_I', 'July_Crisis'])
        self.assertEqual(result['fulltext_query'], 'caused World War I')

    def test_title_only_archive_and_no_results(self):
        wiki = self.wiki()
        wiki.zim.has_fulltext_index = False
        self.assertEqual(discover(wiki, 'Why did the French Revolution happen?')['articles'],
                         ['French_Revolution'])
        self.assertEqual(discover(wiki, 'unknown thing')['articles'], [])


class TimelineDiscoveryTests(unittest.TestCase):
    @patch('libzim.search.Searcher')
    def test_possessive_subject_and_prompt_words(self, searcher):
        wiki = Mock()
        wiki.zim.get_entry_by_path.side_effect = lambda path: SimpleNamespace(path=path, is_redirect=False)
        wiki.zim.has_fulltext_index = True
        wiki.search.side_effect = lambda phrase, limit: {
            'Napoleon': ['Napoleon'], "Napoleon's battles": ["Napoleon's_Battles"],
            'Give': ['Give'], 'timeline': ['Timeline']}.get(phrase, [])
        searcher.return_value.search.return_value.getResults.return_value = ['Military_career_of_Napoleon']
        result = discover(wiki, "Give me a timeline of Napoleon's battles")
        self.assertEqual(result['articles'], ['Napoleon', 'Military_career_of_Napoleon'])
        self.assertEqual(result['fulltext_query'], 'Napoleon battles')
