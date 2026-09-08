"""Loopback-only conversation UI and read-only offline Wikipedia viewer."""
import argparse
from collections import OrderedDict
import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit
from conversation_state import ConversationState
from history_ai import ROOT, ZIM_PATH, ask
from offline_reader import OfflineReader
from retrieval_config import load_config


PREVIEW_MAX_CHARS = 280


def preview_excerpt(value, limit=PREVIEW_MAX_CHARS):
    """Return a compact plain-text excerpt without changing persisted evidence."""
    if not isinstance(value, str):
        return None
    text = ' '.join(value.split()).strip()
    if not text:
        return None
    if len(text) <= limit:
        return text
    clipped = text[:limit + 1]
    sentence_end = max(clipped.rfind('. '), clipped.rfind('? '), clipped.rfind('! '))
    if sentence_end >= max(80, limit // 2):
        return clipped[:sentence_end + 1] + '…'
    word_end = clipped.rfind(' ', 0, limit + 1)
    return clipped[:word_end if word_end >= 80 else limit].rstrip() + '…'


class Application:
    def __init__(self, reader, answer=ask, store_path=None):
        from conversation_store import ConversationStore
        self.reader, self.answer = reader, answer
        self.store = ConversationStore(store_path)
        # Keep each read/modify/write and shared embedding-cache operation serialized.
        self.generation_lock = threading.Lock()
        self.token = secrets.token_urlsafe(32)
        self.citations = OrderedDict()

    def source_links(self, result):
        result = dict(result)
        result['sources'] = [dict(source) for source in result.get('sources') or []]
        for source in result['sources']:
            evidence = source.get('supplied_text')
            source['article_title'] = str(source.get('article_title') or
                                          source.get('article_path', '')).replace('_', ' ')
            source['preview_excerpt'] = preview_excerpt(evidence)
            try:
                fallback = self.reader.link(source['article_path'], source.get('section'), source.get('subsection'))
                if evidence and self.reader.has_evidence(source['article_path'], evidence):
                    citation = secrets.token_urlsafe(18)
                    article_path = urlsplit(fallback).path
                    self.citations[citation] = (article_path, evidence)
                    if len(self.citations) > 512:
                        self.citations.popitem(last=False)
                    source['article_url'] = article_path + '?citation=' + citation + '#cited-evidence'
                    source['evidence_status'] = 'exact'
                else:
                    source['article_url'] = fallback
                    source['evidence_status'] = 'section' if urlsplit(fallback).fragment else 'article'
            except (KeyError, ValueError, RuntimeError):
                source['article_url'] = None
                source['evidence_status'] = 'unavailable'
            # The UI needs only the bounded excerpt, not the full generation chunk.
            source.pop('supplied_text', None)
            source.pop('text', None)
        return result

    def run(self, data):
        if not isinstance(data, dict):
            raise ValueError('Expected a JSON object')
        with self.generation_lock:
            action = data.get('action')
            if action == 'list':
                return dict(conversations=self.store.list(data.get('search', '')))
            sid = data.get('session')
            if action == 'rename':
                saved = self.store.rename(sid, data.get('title'))
                return dict(id=sid, title=saved['title'])
            if action == 'archive':
                if data.get('confirmed') is not True:
                    raise ValueError('Archive confirmation is required')
                self.store.archive(sid)
                return dict(archived=sid)
            if action == 'export':
                saved = self.store.load(sid)
                return dict(filename=self._export_filename(saved['title']),
                            markdown=self.store.export_markdown(sid))
            question = data.get('question', '')
            if not isinstance(question, str) or len(question) > 4000:
                raise ValueError('Question must be at most 4000 characters')
            if action == 'open':
                saved = self.store.load(sid)
                return dict(session=sid, title=saved['title'],
                    turns=[dict(question=t['question'], result=self.source_links(t['result'])) for t in saved['turns']])
            if data.get('new') or question.strip() == '/new':
                # A new conversation never erases a saved one.
                return dict(session=None, reset=True)
            if not question.strip():
                raise ValueError('Enter a question')
            model = data.get('model', 'qwen3:14b')
            if model not in ('qwen3:14b', 'qwen3:8b'):
                raise ValueError('Unsupported local model')
            if sid is None:
                sid = secrets.token_urlsafe(24)
                config = load_config()
                saved = dict(id=sid, title=question.strip()[:80], turns=[],
                    state=ConversationState(max_turns=config.history_turns, max_chars=config.history_chars))
            else:
                saved = self.store.load(sid)
            result = self.answer(argparse.Namespace(question=question.strip(), model=model,
                conversation=saved['state'], config=None, index=None, top_k=None, context_chars=None,
                num_predict=600, debug=data.get('debug') is True, quiet=True,
                output=ROOT/'artifacts'/'ui'/f'{time.time_ns()}-{secrets.token_hex(4)}.json'))
            saved['turns'].append(dict(question=question.strip(), result=result))
            self.store.save(saved)
            return dict(session=sid, result=self.source_links(result))

    @staticmethod
    def _export_filename(title):
        safe = ''.join(character if character.isalnum() or character in ' -_' else '-'
                       for character in title).strip(' .-_')[:80]
        return (safe or 'conversation') + '.md'


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, code, content, mime='application/json', headers=None, archive=False):
        if not isinstance(content, bytes):
            content = json.dumps(content).encode()
        self.send_response(code)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(content)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        csp = ("default-src 'none'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; sandbox allow-same-origin" if archive else
               "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('Content-Security-Policy', csp)
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(content)

    def valid_host(self):
        return self.headers.get('Host') == f'127.0.0.1:{self.server.server_port}'

    def do_GET(self):
        if not self.valid_host():
            return self.reply(403, {'error': 'Loopback host required'})
        path = urlsplit(self.path).path
        if path == '/api/bootstrap':
            return self.reply(200, {'token': self.server.app.token})
        assets = {'/': ('ui.html', 'text/html; charset=utf-8'), '/ui.js': ('ui.js', 'text/javascript'), '/ui.css': ('ui.css', 'text/css')}
        if path in assets:
            filename, mime = assets[path]
            return self.reply(200, (Path(__file__).parent/filename).read_bytes(), mime)
        if path.startswith('/wiki/'):
            try:
                citation = parse_qs(urlsplit(self.path).query).get('citation', [None])[0]
                saved = self.server.app.citations.get(citation)
                evidence = saved[1] if saved and saved[0] == path else None
                canonical, mime, content = self.server.app.reader.read(unquote(path[6:], errors='strict'), evidence)
                if canonical != path:
                    return self.reply(302, b'', headers={'Location': canonical}, archive=True)
                return self.reply(200, content, mime, archive=True)
            except (KeyError, ValueError, RuntimeError, UnicodeError):
                return self.reply(404, {'error': 'Article or resource unavailable in this archive'}, archive=True)
        return self.reply(404, {'error': 'Not found'})

    def do_POST(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        if not self.valid_host() or self.headers.get('Origin') not in (None, origin) or self.headers.get('X-Local-Token') != self.server.app.token:
            return self.reply(403, {'error': 'Local session authorization required'})
        if self.path != '/api/chat':
            return self.reply(404, {'error': 'Not found'})
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 20000:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            result = self.server.app.run(data)
            self.reply(200, result)
        except (ValueError, UnicodeError) as error:
            self.reply(400, {'error': str(error)})
        except Exception:
            self.reply(503, {'error': 'Answer failed. Check local Ollama at 127.0.0.1:11434, installed models, archive, and available disk space. You can retry.'})


def make_server(port, app):
    server = ThreadingHTTPServer(('127.0.0.1', port), Handler)
    server.app = app
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('Port must be 0–65535')
    from libzim.reader import Archive
    try:
        server = make_server(args.port, Application(OfflineReader(Archive(str(ZIM_PATH))), store_path=ROOT/'data'/'conversations.sqlite3'))
    except (OSError, RuntimeError) as error:
        parser.exit(1, f'Cannot start local UI: {error}. Check the archive or choose another --port.\n')
    print(f'Open http://127.0.0.1:{server.server_port} — Ctrl+C stops the server.', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        server.app.store.close()


if __name__ == '__main__':
    main()
