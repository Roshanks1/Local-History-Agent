# v1.3.0 implementation and validation — September 24, 2026

## Status and revision

The v1.3.0 application implementation is complete and configured for hybrid
retrieval. Automated regression, retrieval, local-model and persistence checks
were run. **Visual browser acceptance remains unverified:** the browser tool
could not verify the administrator-enforced access policy. It denied access to
the temporary localhost UI; no alternate browser-control method was used.
This is not a claim that every manual acceptance gate passed.

Repository: `/Users/roshankatta/Projects/LocalAI/offline-history-ai`.
Starting HEAD: `e3f9d83beaadbb123f606fc8b838fbf0a02ba6f1` (v1.2.0).
No v1.2.1 revision was present. Ending HEAD is unchanged: this is a local working
build, with no new commit, tag, push or remote release. Existing changes to
conversation_store.py, local_ui.py, ui.css, ui.js and test_stabilization.py were
preserved. No original conversation database, archive, embedding cache or model
was deleted, migrated or replaced. Synced ChatGPT project reference files were
not edited.

## Implemented components

- `lexical_retrieval.py`: independent request-local SQLite FTS5 BM25, manifest,
  literal queries, bounded construction, coverage and footprint diagnostics.
- `retrieval_candidates.py`: stable internal evidence identity and deterministic
  RRF, preserving public source IDs and original reader targets.
- `hybrid_retrieval.py`: independent branches, fusion, modular deterministic/RRF
  reranking, explicit fallbacks, cancellation propagation and bounded inspector.
- `evidence_packing.py`: exact contiguous excerpts, duplicate-sentence removal,
  comparison subject reservations, diversity/relevance selection and complete
  estimated prompt budgeting. It skips unusably tiny truncated fragments.
- `history_ai.py`: live pipeline integration, lexical survival of embedding
  failures, strict context recount, and concise hybrid answer guidance. Later
  successes must not be inferred to be earlier motives. Model limitations remain.
- `query_analysis.py`: a named subject before a pronoun can make a question
  self-contained; true pronoun-led follow-ups retain bounded conversation context.
- Configuration, frozen evidence benchmark, evaluation/live/source-validation
  tools, regression tests and release/rollback documentation.

The normal UI layout was not changed. The existing debug disclosure renders the
new inspector as escaped text. It reports candidate origins/ranks, local URLs,
selection reasons, request identity, stage timings, index scope and footprint,
prompt estimates and observed usage. Existing old-chat source metadata remains
valid and opening a saved answer does not retrieve it again.

## Chosen design and bounds

The common searchable universe is a discovered pool, not all Wikipedia: up to
12 articles (2 for narrow requests), 64 chunks per article and 480 total.
Both branches independently rank that pool; each contributes 40 hits. RRF uses
k=60, equal weights, one-based ranks and stable identity ties. The reranker
considers all at most 80 fused candidates; the initial 40 limit dropped useful
single-branch comparison evidence. Final packing allows at most 12 excerpts.
The deterministic heuristic reuses the existing ranking signals and adds explicit
fused-rank and intent signals; see RELEASE_v1.3.0.md for weights and tie policy.

FTS5 indexes are private in-memory transactional generations. They are validated
before use and closed after each request. This smaller lifecycle avoids a stale
shared/persistent index and the need for cache deletion or disk rebuild commands.
The manifest still records corpus, chunker, tokenizer, schema and exact coverage.
No optional reranker model, new package, hosted service or automatic download was
introduced. SQLite FTS5 is available in the existing Python environment.

The generation defaults remain qwen3:14b, qwen3:8b alternate, nomic-embed-text,
8192 context tokens, 600 output tokens in the UI and think=false. The evidence
cap remains 4800 estimated tokens, reduced when complete prompt overhead requires
it. Estimates include UTF-8 bytes/3, chat/schema overhead and a 384-token margin.
These are estimates, explicitly separated from observed Ollama token usage.

## Frozen retrieval results

The benchmark was frozen before new ranking scores were examined: 13 questions,
26 locally reviewed supporting facets, covering exact facts, people, causes,
comparisons, chronology, explicit contextual questions and two held-out questions.
Full pronoun follow-ups and topic-switch/isolation are additionally exercised by
regression and live tests. Gold is **partial**: matching a supporting span counts,
but an unmatched passage is not proved irrelevant. nDCG below is consequently a
partial-judgment metric; it is not a comprehensive accuracy score.

| Metric | Baseline | Final |
| --- | ---: | ---: |
| Mean packed facet coverage | 51.3% | 70.5% |
| Candidate facet recall at 40 | 53.8% | 84.6% |
| Partial nDCG at 10 | 0.255 | 0.370 |
| Exact-question MRR at 10 | 0.500 | 0.556 |

The RRF-only ablation has recall 71.8% and partial nDCG 0.278. Final coverage
improves by 19.2 percentage points; no previously covered required facet is lost.
Comparison coverage increases from 83.3% to 100%. Category packed coverage does
not decline. Deterministic lexical-challenge tests recover a relevant candidate
absent from the dense shortlist. Real-ZIM BM25-only candidates also enter the
final context, but none matches the benchmark's narrowly frozen supporting spans;
we do not claim the entire measured gain is specifically attributable to BM25.

Three warm runs were measured per configuration and question. Across comparable
requests, median-of-query-medians is about 0.724 seconds legacy versus 0.786
seconds hybrid. The largest per-query median ratio is about 1.165. B02 and F02
previously returned clarification without retrieval; they now retrieve in about
1.36 and 2.18 seconds, respectively. Ratios to those skipped requests are not
meaningful and are disclosed rather than counted as timing passes.

The private lexical indexes measured 28,672–1,425,408 bytes and built in roughly
0.26–6.40 ms. A separate genuinely empty embedding cache for 64 Magna Carta chunks
built in 1.57 s; rebuilding with the now-warm cache took 0.42 s. Existing user
caches were untouched. First-request benchmark timings used existing embeddings
and are labeled accordingly. The minimum-excerpt guard and fallback-only score
fix were followed by a complete quality refresh; the three-run timings precede
those small fixes, as recorded in the report.

## Tests and local/offline validation

- 93 automated tests pass, including the prior suite, real FTS5 scoring, fusion,
  bounds, failure/cancellation paths, contextual isolation, prompt budgets,
  exact source correspondence, timeline schemas and saved-chat restart behavior.
- The tests use temporary localhost HTTP servers; the suite requires loopback
  permission. A sandbox socket-bind denial is not an application test failure.
- Final live checks use both Qwen3 14B and 8B, baseline/final exact/comparison/
  chronology questions, a real multi-turn Gustavus Adolphus conversation, an
  explicit switch to Magna Carta, and exact saved-evidence comparison after restart.
- Non-loopback socket connections are denied inside the live validation process.
  No external connection attempt occurred. This is application-process offline
  enforcement, not a claim that system networking was disabled.
- All tested benchmark source URLs resolve locally; exact duplicate excerpts are
  zero. Some reader matches fall back to the section/article, which is existing
  supported behavior. Repeated selected trigram share drops from about 3.80% to
  2.38%; this is a disclosed overlap proxy, not a precise duplicated-token metric.
- Full estimated prompt plus output and safety reservation remains within 8192.
  Observed live prompt counts stay below the conservative estimates.
- The initial live comparison truncated at 600 tokens; concise-answer instructions
  fixed that in the final rerun without increasing output or context settings.
- Validation memory remained below the recorded 2 GiB process / 20 GiB model
  targets, and system swap use remained unchanged during the live run.

Commands:

```text
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evaluate_v130.py
.venv/bin/python validate_v130_live.py
.venv/bin/python validate_v130_sources.py
```

Reports are in `artifacts/v130` (original baseline), `artifacts/v130-verified`
(frozen evaluation, source checks, cold-cache measurement) and
`artifacts/v130-live-final` (live answers, usage, memory and restart checks).
Raw results and failed/intermediate attempts are not presented as passes.

## Remaining limits and acceptance items

Visual checks of narrow windows, scrolling, composer and hover previews remain
blocked by browser policy. Automated HTTP/static layout/reader regression tests
pass, and this release makes no layout changes. The existing application has no
streaming or Stop/Cancel UI; none is claimed here.

T01/T02 and the held-out Haitian causal question still miss the benchmark's
supporting facets. Discovery and the bounded pool remain limiting factors.
Expanding generic “sequence”/“major events” into timeline intent was tried and
removed because it increased request cost substantially. Existing explicit
timeline behavior is retained.

Live answers are not guaranteed fully grounded. Review still found causal
inference from subsequent military accomplishments in a follow-up, and the
comparison can blur 1905 background with 1917 causes even after explicit prompt
guidance. Citation labels remain valid, but valid labels alone do not establish
claim support. Claim-level validation and broader held-out judgments remain
future work; they were explicit non-goals for this release.

Rollback: set `retrieval_mode` to `legacy` in retrieval_config.json and restart.
This restores original query interpretation, expansion, selection and packing,
without restoring or modifying any saved-chat data. See RELEASE_v1.3.0.md.
