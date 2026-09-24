"""Internal retrieval contracts; public chunk IDs and reader targets stay intact.

Discovery must resolve canonical article paths before adaptation. No redirect or
URL guessing happens here. Legacy chunks lack offsets, so content and section
identity provide the internal key until the chunker exposes original spans.
"""
from copy import deepcopy
import hashlib
import json
import math

from answer_context import estimate_tokens


def candidate_id(chunk, corpus_version, chunker_version):
    identity = [corpus_version, chunker_version,
                chunk.get('canonical_article_id', chunk['article_path']),
                chunk.get('section'), chunk.get('subsection'),
                chunk.get('start_offset'), chunk.get('end_offset'), chunk['text']]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def adapt_legacy(hits, *, corpus_version, chunker_version):
    """Copy evidence in existing order without changing its score or public IDs."""
    if not corpus_version or not chunker_version:
        raise ValueError('Corpus and chunker versions are required')
    rows = []
    for hit in hits:
        row = deepcopy(hit)
        chunk = row['chunk']
        if not all(isinstance(chunk.get(key), str) and chunk[key].strip()
                   for key in ('article_path', 'chunk_id', 'text')):
            raise ValueError('Evidence requires article path, public chunk ID and text')
        row['retrieval'] = dict(
            candidate_id=candidate_id(chunk, corpus_version, chunker_version),
            canonical_article_id=chunk.get('canonical_article_id', chunk['article_path']),
            corpus_version=corpus_version, chunker_version=chunker_version,
            origins=[], branches={}, fused_score=None, fused_rank=None,
            rerank_method=None, rerank_score=None, rerank_rank=None,
            estimated_text_tokens=estimate_tokens(chunk['text']))
        rows.append(row)
    return rows


def _positive_integer(name, value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(name + ' must be a positive integer')


def reciprocal_rank_fusion(branches, *, directions, k=60, branch_limit=40,
                           output_limit=80, input_limit=480, check_cancel=None):
    """Fuse one consolidated list per branch, never raw incomparable scores.

    directions maps dense/bm25 to 'higher' or 'lower'. Duplicate IDs receive
    only their best score in each branch. Inputs and outputs are bounded. A
    cancellation callback raises the caller's cancellation exception unchanged.
    """
    for name, value in [('k', k), ('branch_limit', branch_limit),
                        ('output_limit', output_limit), ('input_limit', input_limit)]:
        _positive_integer(name, value)
    if set(branches) - {'dense', 'bm25'} or set(directions) != set(branches):
        raise ValueError('Provide one score direction for each dense/bm25 branch')
    merged = {}
    for branch in sorted(branches):
        direction = directions[branch]
        if direction not in ('higher', 'lower'):
            raise ValueError('Score direction must be higher or lower')
        unique = {}
        sign = -1 if direction == 'higher' else 1
        for number, row in enumerate(branches[branch]):
            if check_cancel:
                check_cancel()
            if number >= input_limit:
                raise ValueError('Branch input exceeds bounded candidate universe')
            score = row['score']
            if isinstance(score, bool) or not isinstance(score, (int, float)) or not math.isfinite(score):
                raise ValueError('Branch scores must be finite numbers')
            identity = row['retrieval']['candidate_id']
            previous = unique.get(identity)
            if previous is None or sign * score < sign * previous['score']:
                unique[identity] = row
        ordered = sorted(unique.values(), key=lambda row: (
            sign * row['score'], row['retrieval']['candidate_id']))[:branch_limit]
        for rank, row in enumerate(ordered, 1):
            identity = row['retrieval']['candidate_id']
            if identity not in merged:
                result = deepcopy(row)
                result['retrieval'].update(origins=[], branches={}, fused_rank=None, fused_score=0.0)
                merged[identity] = result
            meta = merged[identity]['retrieval']
            meta['origins'].append(branch)
            meta['branches'][branch] = dict(score=row['score'], rank=rank, direction=direction)
            meta['fused_score'] += 1 / (k + rank)
    ordered = sorted(merged.values(), key=lambda row: (
        -row['retrieval']['fused_score'],
        min(value['rank'] for value in row['retrieval']['branches'].values()),
        row['retrieval']['candidate_id']))[:output_limit]
    for rank, row in enumerate(ordered, 1):
        if check_cancel:
            check_cancel()
        row['retrieval']['fused_rank'] = rank
        row['score'] = row['retrieval']['fused_score']
    return ordered
