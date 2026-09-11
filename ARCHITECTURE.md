# Conversational history pipeline

The project still uses the same local Wikipedia ZIM, paragraph chunker, JSON vector indexes, cached `nomic-embed-text` embeddings, and local Ollama Qwen models. There are no cloud APIs or new runtime dependencies.

## Question → evidence → answer

1. **Interpret** (`query_analysis.py`): lightweight English rules detect general, cause, timeline, comparison, lookup, or follow-up questions. Follow-ups also have an effective answer type. Bounded conversation state resolves the topic and immediate prior question; short “Why?” queries additionally use a short previous-answer summary. Prior answers are marked unverified and never become source evidence.
2. **Plan** (`retrieval_planning.py`): classify narrow versus broad retrieval, generate up to four focused local-search queries, extract and normalize at most eight conservative historical entities, and retain date hints. Contextual entities come only from the current bounded conversation.
3. **Discover** (`article_discovery.py`, `wikipedia_local.py`): merge direct-title, local full-text, entity-title, and relevance-ranked one-hop local article links. Canonicalize redirects, retain discovery reasons, reject common disambiguation/content traps, and cap broad/narrow candidate pools separately. No recursive crawl or remote lookup is performed.
4. **Extract/index** (`history_ai.build`, `chunking.py`, `structured_wikipedia.py`): read candidate articles, including content lists/tables, and reuse cached embeddings. Per-article and total candidate-chunk limits bound cold work; deterministic sampling retains coverage across unusually long articles. Malformed candidates are skipped without failing valid articles.
5. **Retrieve, rerank, and select** (`retrieval_expansion.py`, `retrieval_ranking.py`): preserve semantic/section expansion for recall, then normalize semantic, lexical, title, heading, entity, date, direct-title, completeness, and low-value signals. A deterministic MMR-style pass applies redundancy and repeated-article penalties, per-article caps, a relevance floor, and a whole-chunk token budget. Raw components and selection/rejection reasons remain available in debug traces.
6. **Build chronology when needed** (`timeline_utils.py`): extract dated passages with date text, numeric sort key, precision, approximate flag, source article, section, and original chunk ID. Preserve dates and ranges; reject certain incomplete or misleading references. Use an explicit requested range, a relevant article's stated range, or a bounded continuation window when available. Sort and sample dated evidence before generation. Preceding source sentences remain available to resolve source pronouns.
7. **Pack evidence** (`answer_context.py`): honor the character cap and estimated-token budget. Each supplied passage retains traceable source metadata and records truncation. The token estimate is UTF-8 bytes / 3, rounded up, not the exact Qwen tokenizer. Configuration reserves space within the existing 8,192-token model context; actual `prompt_eval_count` is saved when Ollama reports it.
8. **Generate** (`history_ai.generate`): use the original user question, bounded dialogue context, and only the final selected evidence. Prompts distinguish facts/inferences, background/triggers, and parallel comparison criteria. Timeline generation selects source labels and short descriptions using a local JSON schema; code supplies source dates, drops unknown labels, caps ten entries and sorts them. Dates are not taken from model-generated date fields. Event summaries can still be inaccurate and need review.
9. **Remember/display** (`conversation_state.py`, `main.py`, `terminal_output.py`): remember only successful turns, print readable sources and citations, and continue prompting.

## Conversation and clarification

The interactive process keeps at most `history_turns` recent user questions and short answer summaries. It tracks the focus, referenced titles/articles, date mentions, and event candidates. Only two recent summarized turns, within `history_chars`, enter generation. Memory is held in the current process; it is not restored from saved answer files.

Use `/new` to reset memory. A new explicit topic updates the focus. Pronouns and short follow-ups inherit context; standalone unclear references ask a clarification question. “After that?” following multiple unresolved events asks which event. The user can name one of the offered events or say “the former”/“the latter.” Discourse resolution remains heuristic; it is not a complete coreference system.

A contextual “what happened next?” with an available anchor year examines the next `continuation_year_window` years (default 30). This is a retrieval scope, not a claim that consequences stop at that boundary. Ask for a specific range to control chronology more precisely.

## Configuration

`retrieval_config.json` contains validated limits for seed queries, entities, related-article expansion, candidate articles/chunks, first-stage retrieval, reranking, redundancy, per-article selection, context budgets, history, timelines, and chunking. Fields omitted from the JSON use dataclass defaults in `retrieval_config.py`.

`--config PATH` overrides this file for a one-shot `ask`. `--top-k` caps the final supplied passages; `--context-chars` can tighten the context character limit. Fixed-index questions use the same interpretation/expansion pipeline but skip article discovery. Historical `evaluate` and `benchmark-models` commands retain their original vector-retrieval interfaces for reproducibility.

## Debugging and evaluation

`/debug` toggles detailed saved traces in the interactive session; `ask --debug` enables them for a single question. Normal output does not print rewritten queries or score dumps. Debug answer JSON records:

- Query interpretation, question/effective type and bounded dialogue context.
- The versioned retrieval plan, entity resolutions, discovery provenance, canonical articles, bounds, fallbacks, and stage timings.
- Raw/intent-adjusted hits, article scores/frequency, normalized rerank components, expanded chunks, and selection/rejection reasons.
- Similarity/expansion scores, headings, source IDs, date records, token estimates, and bounds.
- Exact evidence/messages sent to Qwen and the raw model response.

Normal answer records still save basic interpretation, sources, timings and configuration. Debug traces can contain conversational text; they are written only to the local project.

Run `python -m unittest discover -s tests` in the existing environment for regression tests. `benchmarks/multi_source_retrieval.json` records deterministic acceptance properties for the seven v1.2 questions without brittle full rankings. `evaluate_assistant.py` retains the earlier fixed-corpus comparison. Frozen baseline artifacts are not overwritten.

## Limits

Article discovery and intent/section scoring are lexical heuristics supported by local embeddings. Candidate caps can miss articles; section bonuses can misrank passages. Date extraction is conservative but cannot reliably distinguish every incidental date from the event being narrated, and it does not understand every calendar, ancient period, or abbreviated date. Timelines are selected, incomplete evidence summaries, not exhaustive historical event databases.

Source-date formatting prevents model-generated date fields, but it cannot correct source errors, mistaken event/date associations, or unsupported generated descriptions. Citation syntax is not factual verification. Five provisional benchmark questions are a development check, not an independent quality estimate. Broader judgments and human review remain necessary.
