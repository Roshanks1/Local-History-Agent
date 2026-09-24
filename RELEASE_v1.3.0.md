# v1.3.0 — hybrid local retrieval

This release adds an independent SQLite FTS5 BM25 branch over the request's
bounded discovered Wikipedia article pool. It does **not** index the entire
archive and does not use an external search service. Existing title/full-text,
entity and related-article discovery supplies the common candidate pool.

## Retrieval and packing

- At most 480 chunks from up to 12 discovered articles (2 for narrow requests).
- Dense cosine and lexical BM25 each contribute up to 40 candidates. Their
  independent lists are deduplicated and fused using equal-weight reciprocal
  ranks, `1/(60 + rank)`, with deterministic ties.
- The deterministic local reranker considers all at most 80 fused candidates.
  The initial 40-candidate rerank bound discarded useful single-branch evidence
  in comparison questions; evaluation justified the final 80-candidate bound.
- Existing heuristic signals retain their weights: semantic .39, lexical .20,
  title .10, section .08, entity .10, date .04, discovery .04, completeness .05,
  low-value penalty .65 and topic-conflict penalty .35. Hybrid mode separately
  adds normalized fused rank .10, bounded intent/section affinity .18 and a .25
  penalty for unsolicited dated title variants. Scores are not probabilities.
  Semantic similarity remains available for BM25-recovered passages even if they
  missed the dense top 40; this does not fabricate a dense-branch rank or vote.
- Existing causal expansion consolidates its two cosine searches into one dense
  branch. Comparisons consolidate bounded subject queries by maximum cosine.
  Timeline endpoint searches are bounded to two derived queries. Extra queries
  never become extra RRF votes.
- The packer keeps at most 12 passages, discounts redundant evidence and repeated
  articles, reserves explicit comparison subjects, and skips oversized passages
  that cannot fit. Trimming retains an exact contiguous sentence-bounded excerpt and removes repeated full sentences without joining unrelated spans.
- The full request includes system instructions, question, bounded history,
  citation metadata, chat/schema overhead, the unchanged output reservation and
  a 384-token safety margin within the unchanged 8192-token context window.
  Token counts use the documented conservative UTF-8-byte estimate, not an exact
  Qwen tokenizer; observed Ollama usage is shown separately in debug mode.

## Local index lifecycle and failure behavior

The lexical index is a private in-memory SQLite database, rebuilt transactionally
for each request and closed afterward. There is no shared or persistent partial
index to become stale. This deliberately replaces the handoff's proposed
persistent-generation lifecycle with the smaller request-local equivalent.
The manifest records corpus/version identity, tokenizer, pool fingerprint,
coverage and schema; it is validated before querying. Interrupted builds are
closed and cannot be published or seen by another request. No archive-wide
extraction, database migration, new dependency or model download is required.

FTS5 uses `unicode61 remove_diacritics 2`, with title/section/body weights
2.0/1.5/1.0. Query tokens are literal quoted terms passed as SQL parameters.
Names, years and Roman numerals remain searchable; BM25's negative scores are
lower-is-better. Missing or failed lexical support restores the complete legacy
retrieval and packing path and reports a debug reason. Retry rebuilds the local
index; if FTS5 is unavailable, repair the local Python SQLite installation.
No cache deletion is necessary. An embedding failure can retain extracted chunks
and use local BM25; generation still requires the selected local Qwen model.
Reranker errors use RRF passthrough. Cancellation exceptions propagate without
starting fallback work; the existing UI has no streaming/Stop control to preserve.

## Compatibility and controls

`retrieval_mode` selects `hybrid` or `legacy`; `legacy` restores original query
interpretation, expansion, ranking and packing. `rerank_backend` accepts
`deterministic` or `rrf`. Existing settings files without the new keys still load.
The shipped configuration is the release control; library defaults remain legacy
for compatibility with existing scripts constructing `RetrievalConfig()`.

The debug checkbox uses the existing expandable trace panel. It adds a request
ID, candidate provenance and ranks, backend/fallback information, coverage,
index size, timings, previews/local URLs, packing decisions and prompt estimates.
Debug on/off does not change evidence. Content is rendered as text, not HTML.
Older saved answers have no new diagnostic trace and load normally.

Qwen3 14B remains the default, Qwen3 8B remains available, embeddings remain
nomic-embed-text, and the June 2026 Wikipedia archive is unchanged. Public source
IDs, citation labels, article URLs and existing chat storage remain compatible.
Opening saved chats never reretrieves their evidence.

## Operation and rollback

Start with `.venv/bin/python local_ui.py` as before. Set `retrieval_mode` to
`legacy` in `retrieval_config.json` and restart to restore the prior pipeline.
No conversation, model, archive or cache restoration is needed. Do not delete
user data. No remote release, tag or push is performed by this local build.

Run tests with `PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v`.
Run the frozen retrieval evaluation with `.venv/bin/python evaluate_v130.py`.
The original baseline artifacts live in `artifacts/v130`; do not recapture them
with changed code and call them an original baseline. Live local-only checks use
`.venv/bin/python validate_v130_live.py` and write to a separate validation chat
store. The validation process denies non-loopback connections without changing
system-wide network settings.

## Known limits

Search quality is limited by article discovery and the 480-chunk pool. The frozen
benchmark uses reviewed local supporting spans and is intentionally incomplete;
its nDCG is a partial-judgment estimate. Some chronology and Haitian-Revolution
questions still miss required evidence. General questions phrased as “sequence”
or “major events” retain the prior intent detection; ask explicitly for a timeline.
Newly supported named-subject questions previously stopped at a clarification,
so their new retrieval time has no meaningful ratio to the old skipped request.
No larger generation model, context increase, new UI streaming control, or
archive-wide lexical search is included.
