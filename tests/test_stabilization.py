"""Focused v1.2.1 error recovery and persisted-data regressions."""
import json
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from unittest.mock import Mock
import httpx
from local_ui import Application, make_server
from test_local_ui import reader_fixture


class StabilizationTests(unittest.TestCase):
    def setUp(self):
        self.app = Application(reader_fixture(), lambda args: dict(answer='Answer [S1]', sources=[dict(label='S1', article_path='Alias')]))
        self.addCleanup(self.app.store.close)

    def test_corrupt_saved_data_is_readable_error_and_preserved(self):
        sid = self.app.run({'question': 'Rome'})['session']
        for column, value in [('turns', '{'), ('turns', '{}'), ('turns', '[{}]'), ('state', '{"turns":null}'), ('state', '{"max_chars":"bad"}')]:
            with self.subTest(column=column, value=value):
                original = self.app.store.db.execute('SELECT state,turns FROM conversations WHERE id=?', (sid,)).fetchone()
                self.app.store.db.execute(f'UPDATE conversations SET {column}=? WHERE id=?', (value, sid))
                with self.assertRaisesRegex(ValueError, 'saved conversation could not be read'):
                    self.app.run({'action': 'open', 'session': sid})
                self.assertEqual(self.app.store.db.execute(f'SELECT {column} FROM conversations WHERE id=?', (sid,)).fetchone()[0], value)
                self.app.store.db.execute('UPDATE conversations SET state=?,turns=? WHERE id=?', (*original, sid))

    def test_http_failure_recovers_and_sources_open_locally(self):
        server = make_server(0, self.app)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def post(data):
            return urlopen(Request(base+'/api/chat', json.dumps(data).encode(), headers={'X-Local-Token': self.app.token}))
        answer = self.app.answer
        try:
            for error, expected in [(httpx.ConnectError('secret internal host'), 'Make sure Ollama'), (httpx.ReadTimeout('secret timeout'), 'too long'), (ValueError('secret index detail'), 'Answer failed')]:
                self.app.answer = Mock(side_effect=error)
                with self.assertRaises(HTTPError) as caught:
                    post({'question': 'Rome'})
                body = json.load(caught.exception)
                self.assertEqual(caught.exception.code, 503)
                self.assertIn(expected, body['error'])
                self.assertNotIn('secret', body['error'])
                self.assertEqual(self.app.store.list(), [])
            self.app.answer = answer
            with post({'question': 'Rome'}) as response:
                data = json.load(response)
            source = data['result']['sources'][0]
            self.assertEqual(source['article_title'], 'Alias')
            with urlopen(base+source['article_url']) as response:
                self.assertIn(b'Complete article', response.read())
            with post({'action': 'open', 'session': data['session']}) as response:
                self.assertEqual(json.load(response)['turns'][0]['question'], 'Rome')
        finally:
            server.shutdown(); server.server_close(); thread.join()
