import json
import threading
import unittest
from types import SimpleNamespace
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import Mock
from usage import normalize_usage, format_usage
from offline_reader import OfflineReader, validate_path
from local_ui import Application, make_server


class UsageTests(unittest.TestCase):
    def test_missing_zero_partial_and_invalid(self):
        for bad in (None, -1, True, '10', float('nan'), float('inf'), 1.2):
            u = normalize_usage({'prompt_eval_count': bad, 'eval_count': 0})
            self.assertIsNone(u['prompt_tokens'])
            self.assertIsNone(u['total_tokens'])
            self.assertEqual(u['output_tokens'], 0)
        self.assertEqual(normalize_usage({'prompt_eval_count': 10, 'eval_count': 2, 'eval_duration': 1000000000})['tokens_per_second'], 2)
        self.assertEqual(normalize_usage({'prompt_eval_count': 0, 'eval_count': 0})['total_tokens'], 0)
        self.assertIsNone(normalize_usage({'eval_count': 1, 'eval_duration': 0})['tokens_per_second'])

    def test_skipped_and_display(self):
        u = normalize_usage({'eval_count': 10}, 'qwen3:14b', skipped=True)
        self.assertIsNone(u['output_tokens'])
        self.assertIn('skipped', format_usage(u))
        self.assertIn('unavailable', format_usage(normalize_usage(model='qwen3:14b')))


def reader_fixture():
    class Entry:
        def __init__(self, path, content=b'<html><body>Complete article<table><tr><td>Table</td></tr></table><a href="Other">Other</a><a href="https://example.com">external</a><script>alert(1)</script></body></html>', target=None):
            self.path, self.target = path, target
            self.is_redirect = target is not None
            self.item = SimpleNamespace(path=path, mimetype='text/html', content=content)
        def get_item(self):
            return self.item
        def get_redirect_entry(self):
            return entries[self.target]
    entries = {'Café / War': Entry('Café / War'), 'Alias': Entry('Alias', target='Café / War'), 'Loop': Entry('Loop', target='Loop')}
    return OfflineReader(SimpleNamespace(get_entry_by_path=lambda p: entries[p]))


class ReaderTests(unittest.TestCase):
    def test_encoding_redirect_and_complete_html(self):
        r = reader_fixture()
        self.assertEqual(r.link('Alias'), '/wiki/Caf%C3%A9%20/%20War')
        path, mime, body = r.read('Alias')
        self.assertIn(b'<table>', body)
        self.assertNotIn(b'<script', body)
        self.assertNotIn(b'https://', body)
        self.assertIn(b'/wiki/Caf%C3%A9%20/Other', body)

    def test_invalid_missing_and_loops(self):
        for path in ('', '../secret', 'a/../b', '/etc/passwd', 'a\\b', 'a\x00'):
            with self.assertRaises(ValueError):
                validate_path(path)
        with self.assertRaises(KeyError):
            reader_fixture().link('Missing')
        with self.assertRaises(ValueError):
            reader_fixture().link('Loop')

    def test_evidence_matching_normalizes_unicode_punctuation_and_whitespace(self):
        content = '''<html><head></head><body><p>Other text.</p><p>The people’s demands — including “liberty” — spread\nwidely across Europe.</p></body></html>'''.encode()
        item = SimpleNamespace(path='Revolutions', mimetype='text/html', content=content)
        reader = OfflineReader(SimpleNamespace(get_entry_by_path=lambda path: SimpleNamespace(is_redirect=False, get_item=lambda:item)))
        evidence = 'The people\'s demands - including "liberty" - spread widely across Europe.'
        self.assertTrue(reader.has_evidence('Revolutions', evidence))
        _, _, body = reader.read('Revolutions', evidence)
        self.assertIn(b'id="cited-evidence"', body)
        self.assertIn(b'Cited evidence', body)
        self.assertIn(b'prefers-color-scheme:dark', body)
        self.assertIn(b'color:#fff8df!important', body)
        self.assertNotIn(b'<script', body)
        self.assertFalse(reader.has_evidence('Revolutions', 'A passage that does not occur anywhere in this article.'))


class SessionTests(unittest.TestCase):
    def setUp(self):
        def answer(args):
            previous = args.conversation.focus
            args.conversation.focus = args.question
            return dict(answer=previous or args.question, sources=[dict(article_path='Alias')])
        self.app = Application(reader_fixture(), answer)

    def test_isolation_followup_and_reset(self):
        a = self.app.run({'question': 'Rome'})
        b = self.app.run({'question': 'France'})
        self.assertNotEqual(a['session'], b['session'])
        result = self.app.run({'session': a['session'], 'question': 'Why?'})
        self.assertEqual(result['result']['answer'], 'Rome')
        self.assertTrue(result['result']['sources'][0]['article_url'].startswith('/wiki/'))
        reset = self.app.run({'session': a['session'], 'question': '/new'})
        self.assertIsNone(reset['session'])
        self.assertEqual(self.app.store.load(a['session'])['state'].focus, 'Why?')
        self.assertEqual(self.app.store.load(b['session'])['state'].focus, 'France')

    def test_validation_and_error_retry(self):
        sid = self.app.run({'new': True})['session']
        for bad in ({'question': ''}, {'question': 'a'*4001}, {'question': 'x', 'model': 'remote'}, {'session': 'unknown', 'question': 'x'}):
            with self.assertRaises(ValueError):
                self.app.run(dict({'session': sid}, **bad))
        original = self.app.answer
        self.app.answer = Mock(side_effect=ConnectionError('offline'))
        with self.assertRaises(ConnectionError):
            self.app.run({'session': sid, 'question': 'x'})
        self.app.answer = original
        self.assertIn('result', self.app.run({'session': sid, 'question': 'retry'}))

    def test_sources_get_independent_exact_citation_links(self):
        content = b'<html><body><p>Complete archived article evidence appears in this paragraph.</p></body></html>'
        item = SimpleNamespace(path='Article', mimetype='text/html', content=content)
        reader = OfflineReader(SimpleNamespace(get_entry_by_path=lambda path: SimpleNamespace(is_redirect=False, get_item=lambda:item)))
        app = Application(reader, self.app.answer)
        self.addCleanup(app.store.close)
        result = app.source_links({'sources': [
            {'label':'S1','article_path':'Article','supplied_text':'Complete archived article evidence appears in this paragraph.'},
            {'label':'S2','article_path':'Article','supplied_text':'Missing evidence','section':'Missing'},
        ]})
        self.assertIn('?citation=', result['sources'][0]['article_url'])
        self.assertTrue(result['sources'][0]['article_url'].endswith('#cited-evidence'))
        self.assertEqual(result['sources'][1]['article_url'], '/wiki/Article')


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(reader_fixture(), lambda args: dict(answer='ok', sources=[]))
        self.server = make_server(0, self.app)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f'http://127.0.0.1:{self.server.server_port}'
    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
    def test_static_and_port_conflict(self):
        for path in ('/', '/ui.js', '/ui.css'):
            with urlopen(self.base+path) as response:
                self.assertEqual(response.status, 200)
                self.assertIn("'self'", response.headers['Content-Security-Policy'])
        with self.assertRaises(OSError):
            make_server(self.server.server_port, self.app)
    def test_article_redirect_and_invalid(self):
        with urlopen(self.base+'/wiki/Alias') as response:
            self.assertTrue(response.url.endswith('/wiki/Caf%C3%A9%20/%20War'))
            self.assertIn('sandbox', response.headers['Content-Security-Policy'])
            self.assertIn(b'Complete article', response.read())
        for path in ('/wiki/Missing', '/wiki/%2E%2E/secret', '/wiki/Loop'):
            with self.assertRaises(HTTPError) as caught:
                urlopen(self.base+path)
            self.assertEqual(caught.exception.code, 404)
    def test_authorization_validation_and_errors(self):
        for headers in ({}, {'X-Local-Token': self.app.token, 'Origin': 'https://evil.example'}, {'X-Local-Token': self.app.token, 'Host': 'evil.example'}):
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(self.base+'/api/chat', b'{"new":true}', headers=headers))
            self.assertEqual(caught.exception.code, 403)
        headers = {'X-Local-Token': self.app.token}
        with urlopen(Request(self.base+'/api/chat', b'{"new":true}', headers=headers)) as response:
            self.assertIn('session', json.load(response))
        for data, code in ((b'[]', 400), (b'bad', 400)):
            with self.assertRaises(HTTPError) as caught:
                urlopen(Request(self.base+'/api/chat', data, headers=headers))
            self.assertEqual(caught.exception.code, code)
        self.app.answer = Mock(side_effect=ConnectionError())
        with self.assertRaises(HTTPError) as caught:
            urlopen(Request(self.base+'/api/chat', b'{"question":"Rome"}', headers=headers))
        self.assertEqual(caught.exception.code, 503)


class GenerationUsageTests(unittest.TestCase):
    def test_real_response_type_and_legacy_fields(self):
        import history_ai
        from ollama import ChatResponse
        from test_history_ai import hit
        api = Mock()
        api.list.return_value = {'models': [{'model': 'qwen3:14b', 'digest': 'd'}]}
        api.chat.return_value = ChatResponse(message={'role': 'assistant', 'content': 'Claim [S1]'}, prompt_eval_count=23, eval_count=7, eval_duration=1000000000)
        result = history_ai.generate('Question', [hit('a')], 'qwen3:14b', api)
        self.assertEqual(result['usage']['total_tokens'], 30)
        self.assertEqual(result['eval_count'], 7)
        self.assertEqual(result['prompt_eval_count'], 23)
        self.assertEqual(result['eval_duration_ns'], 1000000000)
        self.assertEqual(result['generation_options']['num_ctx'], result['usage']['context_window'])
        api.chat.return_value = {'message': {'content': 'Claim [S1]'}, 'eval_count': 'bad', 'eval_duration': -1}
        self.assertIsNone(history_ai.generate('Question', [hit('a')], 'qwen3:14b', api)['usage']['output_tokens'])
        api.reset_mock()
        result = history_ai.generate('Question', [], 'qwen3:14b', api)
        self.assertTrue(result['usage']['skipped'])
        self.assertNotIn('eval_count', result)
        api.list.assert_not_called()
        api.chat.assert_not_called()

class QuietDiscoveryTests(unittest.TestCase):
    def test_quiet_automatic_discovery_reuses_pipeline(self):
        import argparse
        import io
        import tempfile
        from pathlib import Path
        from contextlib import redirect_stdout
        from unittest.mock import patch
        import history_ai
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(question='What caused the Thirty Years War?', model='qwen3:14b', conversation=None, config=None, index=None, top_k=None, context_chars=None, num_predict=600, debug=False, quiet=True, output=Path(directory)/'answer.json')
            with patch('wikipedia_local.LocalWikipedia'), patch('article_discovery.discover', return_value={'articles':['Thirty_Years_War']}), patch('history_ai.build') as build, patch('history_ai.read', return_value={}), patch('history_ai.load_index_value', return_value={'index_id':'test'}), patch('history_ai.client'), patch('retrieval_expansion.expand', return_value=([],{})):
                output=io.StringIO()
                with redirect_stdout(output):
                    result=history_ai.ask(args)
                self.assertEqual(output.getvalue(), '')
                self.assertTrue(result['usage']['skipped'])
                self.assertEqual(build.call_count, 1)
                self.assertTrue(args.output.exists())
