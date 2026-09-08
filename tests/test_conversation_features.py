import unittest
from dataclasses import replace
from unittest.mock import Mock, patch
from conversation_state import ConversationState
from query_analysis import analyze, detect_type
from retrieval_config import RetrievalConfig
from retrieval_expansion import expand_ranked
from timeline_utils import normalize_date, extract_events
from answer_context import pack_context, estimate_tokens


def hit(identifier, section, text, score=.7, article='Thirty_Years_War'):
    return {'score': score, 'chunk': {'chunk_id': identifier, 'article_path': article,
                                     'section': section, 'subsection': None, 'text': text}}


def remember(state, question, titles, answer='The evidence identifies an immediate trigger.'):
    a = analyze(question, state)
    state.remember(a, {'answer': answer, 'sources': [], 'discovery': {'title_matches': titles}})
    return a


class QueryConversationTests(unittest.TestCase):
    def test_types(self):
        cases = {'What caused the Thirty Years War?': 'cause', 'Give me a timeline.': 'timeline',
                 'When did the major events of the French Revolution happen?': 'timeline',
                 'What happened between the fall of Constantinople and Columbus reaching America?': 'timeline',
                 'Compare France and Spain': 'comparison', 'Who was Napoleon?': 'lookup',
                 'Describe medieval trade': 'general'}
        for question, expected in cases.items():
            self.assertEqual(detect_type(question), expected)

    def test_three_turn_causal_followup(self):
        state = ConversationState()
        remember(state, "What caused the Thirty Years' War?", ['Thirty_Years_War'])
        second = remember(state, 'Which cause was the most immediate?', [],
                          'The Bohemian Revolt was an immediate trigger.')
        third = analyze('Why?', state)
        for analysis in (second, third):
            self.assertEqual(analysis.question_type, 'followup')
            self.assertIn('Thirty Years War', analysis.retrieval_query)
            self.assertEqual(analysis.effective_type, 'cause')
            self.assertFalse(analysis.clarification)
        self.assertIn('Bohemian Revolt', third.retrieval_query)

    def test_next_after_defenestration(self):
        state = ConversationState()
        remember(state, 'Tell me about the Defenestration of Prague.', ['Defenestration_of_Prague'])
        result = analyze('What happened next?', state)
        self.assertIn('Defenestration of Prague', result.retrieval_query)
        self.assertEqual(result.effective_type, 'timeline')
        self.assertFalse(result.clarification)

    def test_multiple_events_need_clarification(self):
        state = ConversationState()
        remember(state, 'Compare the fall of Constantinople and the French Revolution.',
                 ['Fall_of_Constantinople', 'French_Revolution'])
        self.assertTrue(analyze('What happened after that?', state).clarification)
        self.assertTrue(analyze('Why?', None).clarification)

    def test_bounded_state_and_reset(self):
        state = ConversationState(max_turns=2, max_chars=500)
        for n in range(10):
            remember(state, f'Question {n}', [], 'A'*2000)
        self.assertEqual(len(state.turns), 2)
        self.assertLessEqual(len(state.context()), 500)
        state.clear()
        self.assertTrue(analyze('Why?', state).clarification)


class ExpansionTests(unittest.TestCase):
    def test_article_expands_from_casualties_into_background(self):
        ranked = [hit('cost', 'Human and financial cost', 'Casualties.', .91),
                  hit('other', 'History', 'Other topic', .89, 'Other'),
                  hit('origin', 'Structural origins', 'Religious and political tensions.', .79),
                  hit('background', 'Background', 'Bohemian revolt and imperial authority.', .78)]
        config = replace(RetrievalConfig(), initial_top_k=2, article_top_k=1, chunks_per_article=2)
        selected, trace = expand_ranked(ranked, analyze("What caused the Thirty Years' War?"), config)
        self.assertEqual(selected[0]['chunk']['chunk_id'], 'origin')
        self.assertNotIn('cost', [h['chunk']['chunk_id'] for h in selected])
        self.assertEqual(trace['candidate_articles'][0]['article_path'], 'Thirty_Years_War')

    def test_threshold_and_duplicate_overlap(self):
        q = analyze('Explain the causes')
        ranked = [hit('a', 'Origins', 'Shared paragraph\n\nFirst.', .8),
                  hit('b', 'Origins', 'Shared paragraph\n\nSecond.', .7),
                  hit('c', 'Origins', 'Low quality', .01)]
        selected, _ = expand_ranked(ranked, q, RetrievalConfig())
        self.assertEqual(sum(h['chunk']['text'].count('Shared paragraph') for h in selected), 1)
        self.assertEqual(len(selected), 2)

    def test_budget_and_invalid_configuration(self):
        text, sources = pack_context([hit('a', 'Origins', 'évidence '*1000)], 500, 100)
        self.assertLessEqual(len(text), 500)
        self.assertLessEqual(estimate_tokens(text), 100)
        with self.assertRaises(ValueError):
            RetrievalConfig(initial_top_k=0)
        with self.assertRaises(ValueError):
            RetrievalConfig(similarity_threshold=float('nan'))


class TimelineTests(unittest.TestCase):
    def test_precision_and_sorting(self):
        dates = [('23 May 1618', [1618, 5, 23], 'day'), ('circa 1619', [1619, 0, 0], 'year'),
                 ('1618–1648', [1618, 0, 0], 'range'), ('500 BCE', [-500, 0, 0], 'year')]
        for text, expected, precision in dates:
            result = normalize_date(text)
            self.assertEqual(result['sortable_date'], expected)
            self.assertEqual(result['precision'], precision)
        self.assertTrue(normalize_date('circa 1619')['approximate'])
        self.assertIsNone(normalize_date('31 February 1618'))

    def test_event_chronology_preserves_sources(self):
        hits = [hit('peace', 'History', 'In 1648, the Peace of Westphalia ended the war.'),
                hit('start', 'History', 'On 23 May 1618, the Defenestration occurred.'),
                hit('approx', 'History', 'Around 1620 a revolt occurred.')]
        events = extract_events(hits)
        self.assertEqual([e['sortable_date'][0] for e in events], [1618, 1620, 1648])
        self.assertEqual(events[0]['chunk_id'], 'start')
        self.assertTrue(events[1]['approximate'])

    def test_year_heading_does_not_invent_day(self):
        events = extract_events([hit('x', '1618', 'A revolt occurred.')])
        self.assertEqual(events[0]['sortable_date'], [1618, 0, 0])
        self.assertTrue(events[0]['heading_date'])


class AdditionalRegressionTests(unittest.TestCase):
    def test_date_counts_decades_and_partial_reference(self):
        events = extract_events([hit('x', 'History',
           "Talks began in 1642, with 109 delegations. In the 1620s tensions rose. On 19 August, he rescinded the 1617 election.")])
        self.assertNotIn(109, [e['sortable_date'][0] for e in events])
        self.assertNotIn(1617, [e['sortable_date'][0] for e in events])
        self.assertEqual(normalize_date('1620s')['precision'], 'decade')

    def test_clarification_can_be_answered(self):
        state = ConversationState()
        remember(state, 'Compare the fall of Constantinople and the French Revolution.',
                 ['Fall_of_Constantinople', 'French_Revolution'])
        self.assertTrue(analyze('What happened after that?', state).clarification)
        result = analyze('the latter', state)
        self.assertFalse(result.clarification)
        self.assertIn('French Revolution', result.retrieval_query)

    def test_trigger_passage_survives_background_expansion(self):
        ranked = [hit('origins', 'Structural origins', 'Religious tensions.', .88),
                  hit('background', 'Background', 'Political tensions.', .87),
                  hit('trigger', 'Phase I', 'A defenestration triggered a revolt.', .70)]
        selected, _ = expand_ranked(ranked, analyze('What caused the war?'),
                                    replace(RetrievalConfig(), chunks_per_article=2))
        self.assertIn('trigger', [h['chunk']['chunk_id'] for h in selected])


class StructuredTimelineGenerationTests(unittest.TestCase):
    def test_model_entries_sorted_using_source_dates(self):
        import json
        from history_ai import generate
        from timeline_utils import event_hits
        events = extract_events([hit('end', 'History', 'In 1648 the war ended.'),
                                 hit('start', 'History', 'In 1618 the war began.')])
        api = Mock()
        api.list.return_value = {'models': [{'model': 'qwen3:14b', 'digest': 'd'}]}
        api.chat.return_value = {'message': {'content': json.dumps({'entries': [
            {'source_label': '[S2]', 'summary': 'The war ended.'},
            {'source_label': 'S99', 'summary': 'An unsupported event.'},
            {'source_label': 'S1', 'summary': 'The war began.'}]})}}
        result = generate('Give a timeline', event_hits(events), 'qwen3:14b', api,
                          analysis=analyze('Give a timeline'), config=RetrievalConfig())
        self.assertLess(result['answer'].index('1618'), result['answer'].index('1648'))
        self.assertNotIn('unsupported', result['answer'])
        self.assertIn('format', api.chat.call_args.kwargs)

    def test_full_date_range_and_bce(self):
        date = normalize_date('August 29, 1793 – December 19, 1793')
        self.assertEqual(date['precision'], 'range')
        self.assertIn('December 19', date['date_text'])
        self.assertEqual(normalize_date('15 March 44 BCE')['sortable_date'], [-44, 3, 15])


class ClarificationIntegrationTests(unittest.TestCase):
    def test_unclear_first_question_never_calls_model(self):
        import contextlib
        import io
        import tempfile
        from pathlib import Path
        from history_ai import main
        with tempfile.TemporaryDirectory() as directory, patch('history_ai.client') as client:
            with contextlib.redirect_stdout(io.StringIO()):
                result = main(['ask', 'What happened after that?', '--output', str(Path(directory)/'answer.json')])
            self.assertTrue(result['clarification'])
            client.assert_not_called()


class TimelineExpansionRegressionTests(unittest.TestCase):
    def test_section_opening_survives_low_similarity(self):
        ranked = [hit('section_009', 'History', 'In 1648 the war ended.', .9),
                  hit('section_001', 'History', 'In 1618 a revolt began.', .6)]
        config = replace(RetrievalConfig(), timeline_candidates=1)
        _, trace = expand_ranked(ranked, analyze('Give a timeline'), config)
        self.assertEqual(trace['timeline_candidates'][0]['chunk']['chunk_id'], 'section_001')
