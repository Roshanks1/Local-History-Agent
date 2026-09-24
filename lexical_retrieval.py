"""Bounded, request-local SQLite FTS5 BM25. No persistent index or network I/O.

Each request builds a private generation from the complete discovered chunk pool.
The validated connection becomes visible only after its transaction commits.
There is no cross-request index to become stale or require a destructive rebuild.
"""
from copy import deepcopy
import hashlib
import json
import re
import sqlite3
import time
import unicodedata

SCHEMA = 1
TOKENIZER = 'unicode61 remove_diacritics 2'


def terms(text):
    # Normalize punctuation consistently; SQL MATCH operators remain literal tokens.
    return list(dict.fromkeys(re.findall(r'[^\W_]+', unicodedata.normalize('NFKC', text).casefold())))[:96]


def manifest_for(rows, corpus_version, chunker_version):
    identities = [r['retrieval']['candidate_id'] for r in rows]
    return dict(schema=SCHEMA, tokenizer=TOKENIZER, corpus_version=corpus_version,
                chunker_version=chunker_version, coverage='discovered article pool only',
                chunks=len(rows), articles=len({r['chunk']['article_path'] for r in rows}),
                pool_sha256=hashlib.sha256(json.dumps(identities).encode()).hexdigest())


def validate_manifest(actual, expected):
    if actual != expected:
        raise ValueError('Missing, stale or incompatible lexical manifest; retry to rebuild the request-local index')


def search(rows, query, *, corpus_version, chunker_version, limit=40, max_rows=480, check_cancel=None):
    if len(rows) > max_rows or limit < 1:
        raise ValueError('Lexical candidate bounds exceeded')
    expected = manifest_for(rows, corpus_version, chunker_version)
    started = time.perf_counter()
    connection = sqlite3.connect(':memory:')
    try:
        connection.execute("CREATE VIRTUAL TABLE evidence USING fts5(title, section, body, tokenize='unicode61 remove_diacritics 2')")
        connection.execute('CREATE TABLE manifest (value TEXT NOT NULL)')
        with connection:
            for number, row in enumerate(rows, 1):
                if check_cancel: check_cancel()
                c = row['chunk']
                connection.execute('INSERT INTO evidence(rowid,title,section,body) VALUES(?,?,?,?)',
                    (number, c['article_path'].replace('_', ' '),
                     ' '.join(filter(None, (c.get('section'), c.get('subsection')))), c['text']))
            connection.execute('INSERT INTO manifest VALUES(?)', (json.dumps(expected),))
        validate_manifest(json.loads(connection.execute('SELECT value FROM manifest').fetchone()[0]), expected)
        build_seconds = time.perf_counter()-started
        match = ' OR '.join('"' + t + '"' for t in terms(query))
        found = []
        if match:
            # Explicit, bounded field weights. FTS5 BM25 is lower-is-better.
            for number, score in connection.execute(
                    'SELECT rowid, bm25(evidence, 2.0, 1.5, 1.0) AS score FROM evidence '
                    'WHERE evidence MATCH ? ORDER BY score, rowid LIMIT ?', (match, limit)):
                if check_cancel: check_cancel()
                row = deepcopy(rows[number-1]); row['score'] = score; found.append(row)
        pages = connection.execute('PRAGMA page_count').fetchone()[0]
        page_size = connection.execute('PRAGMA page_size').fetchone()[0]
        return found, dict(manifest=expected, build_seconds=build_seconds,
                          search_seconds=time.perf_counter()-started-build_seconds,
                          index_bytes=pages*page_size, score_direction='lower',
                          field_weights={'title':2.0,'section':1.5,'body':1.0},
                          rebuild='Automatic private rebuild on the next request; no files to delete.')
    finally:
        connection.close()
