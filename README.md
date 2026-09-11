# Offline History AI

A conversational history assistant using your local Wikipedia archive and local Qwen models.

## Start a conversation

From this folder:

```sh
.venv/bin/python main.py
```

Try:

```text
What caused the Thirty Years' War?
Which cause was the most immediate?
Why?
```

The assistant automatically plans bounded local research, searches several relevant archive articles for broad questions, reranks nonredundant evidence, and keeps recent conversational context. Narrow questions stay focused, and unclear references can trigger clarification.

- `/new` — start a fresh conversation.
- `/debug` — toggle detailed retrieval traces saved with each answer.
- `exit` / `quit` / Ctrl+C / Ctrl+D — finish.

Ollama must already be running locally. The verified packages are in `requirements.txt`; models are `nomic-embed-text`, `qwen3:14b` (default), and `qwen3:8b`. No automatic model downloads or cloud calls are made. The client explicitly connects to `127.0.0.1:11434`.

The existing archive path remains **`data/wikipedia/wikipedia_en_all_nopic_2026-06.zim`**, resolved relative to the project. New topics can take longer initially while embeddings are cached.

## Single questions and tuning

```sh
.venv/bin/python history_ai.py ask "Give me a timeline of the Thirty Years' War." --debug
.venv/bin/python history_ai.py ask "Compare France and Spain during the Thirty Years' War." --model qwen3:8b
```

Each one-shot command starts without dialogue memory. Use the interactive program for follow-ups.

`retrieval_config.json` controls query/entity/article/chunk bounds, ranking weights, diversity and deduplication limits, estimated context-token and character budgets, history bounds, and timeline settings. `--config PATH` selects another configuration for a one-shot question. `--top-k` caps supplied passages and `--context-chars` tightens the character limit. See `ARCHITECTURE.md` for details and limitations.

Answers and source passages are saved under `artifacts/`. Debug mode additionally saves the interpreted query, initial/expanded retrieval, article ranking, dated records, and exact model context. Normal terminal output keeps these details hidden. Memory itself is session-local; `/new` and program restart clear it.

## Timeline behavior

Timeline questions collect dated evidence across relevant sections, preserve date precision and approximate labels, and sort records before generation. Qwen selects concise entries; the program uses the cited records' dates and sorts the final output. Answers are explicitly selected/partial timelines. Structured extraction retains lists and table rows without changing the original prose-only benchmark pipeline.

## Tests and evaluation

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python evaluate_assistant.py
.venv/bin/python evaluate_assistant.py --live --output artifacts/my-assistant-evaluation
```

The live evaluation uses your local models and saves per-turn JSON traces and readable transcripts. Unit tests cover retrieval planning, historical entities, one-hop local expansion, candidate provenance and bounds, deterministic reranking, diversity/redundancy selection, exact generation-source mapping, conversations, redirects, dates, and the source reader. The seven-question v1.2 acceptance properties are in `benchmarks/multi_source_retrieval.json`. Use `tests/` discovery: old exploratory `*_test.py` scripts at the project root perform live work on import.

Inspection found **five benchmark questions and 59 chunks**, not a 59-question dataset. Labels in `benchmarks/thirty_years_war.json` are provisional assistant-authored judgments, not independent ground truth. `BASELINE.md` preserves the earlier measured baseline. The new evaluation reports both raw and expanded results; gains in early relevance may trade off against labeled chunk recall.

## Preserved fixed-index tools

```sh
# Build/re-evaluate the original title-enriched corpus:
.venv/bin/python history_ai.py index
.venv/bin/python history_ai.py evaluate --output artifacts/retrieval-rerun.json
# Query that fixed corpus with the new answer pipeline:
.venv/bin/python history_ai.py ask "What caused the Thirty Years' War?" --index artifacts/index-title.json
# Original section-metadata baseline:
.venv/bin/python history_ai.py index --variant section --index artifacts/index-section.json
# Compare both Qwen models on identical fixed-index evidence:
.venv/bin/python history_ai.py benchmark-models --output artifacts/qwen-new.json
```

`evaluate` and `benchmark-models` preserve their original retrieval behavior. The newer article-expansion evaluation is `evaluate_assistant.py`. To provide a larger labeled question set to `evaluate`, use `--benchmark PATH`; the JSON has a `questions` array with unique `id`, `question`, and optional `relevant_chunk_ids`. Bind labels with `corpus_sha256` from the index metadata. Missing labels are unjudged; mismatched corpus hashes or unknown chunk IDs are rejected. Re-judge labels when changing chunks.

Metrics distinguish **hit rate@k** (any relevant labeled chunk found) from **recall@k** (fraction of labeled relevant chunks found) and **MRR@5** (first relevant rank). Saved configurations, model digests and hashes make comparisons reproducible. The original extractor, chunker, archive, exploratory scripts and baseline results are preserved; `main_legacy.py` retains the earliest main script.

## Reliability

Retrieval, coreference and date parsing use bounded heuristics. The assistant may miss relevant evidence or misinterpret a passage; valid citations alone do not establish factual support. The token budget is an estimate rather than exact Qwen tokenization. Date formatting prevents invented date fields but cannot repair source errors or validate every event description. Review important historical claims against the supplied sources.

See `ARCHITECTURE.md` for implementation details and `HANDOFF.md` for earlier work and the current handoff.

## Local reading UI

```sh
.venv/bin/python local_ui.py
# If 8765 is occupied, choose another port (0 selects a free port):
.venv/bin/python local_ui.py --port 0
```

Open the printed **http://127.0.0.1:PORT** address. The server binds only to IPv4 loopback; use that exact address, not localhost. Ctrl+C stops it. No extra packages, CDN, cloud service, or build step is required. Each tab can select its own conversation. Successful UI turns are saved locally, and reloading restores the current saved conversation. New conversation and `/new` start a fresh conversation without deleting earlier ones. Use the Saved conversations menu to reopen and continue earlier research. Requests are serialized because the existing embedding cache shares temporary filenames. A pending answer continues if its tab closes. Loading and retryable errors are shown; successful answers are saved under `artifacts/ui/`. Debug mode includes the existing retrieval and generation trace. These files are local and are not deleted by New conversation.

Terminal and UI usage show **final-generation** prompt, output, and total counts, plus the configured active 8192-token context window (not the model's advertised maximum). Counts come from Ollama, not text estimates or retrieval/embedding calls. Missing/invalid values remain unavailable; a zero count is valid. Total is shown only when both counts are available. Skipped generation and clarification do not call the model. Existing saved JSON fields retain their meanings; the new `usage` object is additive. The output limit remains 600 and both model defaults are unchanged.

### Exact offline reader integration

Inspection on 2026-09-06 found Kiwix macOS **3.16.1**, a registered `zim:` scheme, and a Hotspot UI displaying “No ZIM files found.” No `kiwix-serve` executable was on PATH or in the app bundle. The scheme registration does not establish a verified article URL format; no scheme was guessed and no LAN Hotspot was enabled. This implementation uses the already-installed **libzim 3.7.0** read-only fallback against exactly `data/wikipedia/wikipedia_en_all_nopic_2026-06.zim`.

Source cards resolve actual archive entries and redirects with `get_entry_by_path`, `get_redirect_entry`, and `get_item`. The application-owned URL is `/wiki/` plus the URL-encoded canonical item path. For example, the actual archive redirects `Thirty_Years_War` to `Thirty_Years'_War`, served as `/wiki/Thirty_Years%27_War`. Original full article HTML, tables, references, and locally archived styles/resources are served; extraction/chunking is not used for reading. Relative article and resource links stay within this route. Missing articles/resources return 404; invalid paths and redirect loops are rejected.

Archive HTML is read-only: scripts, forms, embedded active content, external links and event handlers are removed, with restrictive browser content policy preventing remote resource requests. This preserves the article content but disables interactive Wikipedia features and external references. The no-picture archive cannot supply absent images. This is a focused article reader, not Kiwix search/library functionality. Source links jump to a verified archived subsection heading when available, otherwise its section heading or the article beginning. Ambiguous or missing headings fall back without inventing a fragment. The server serves no arbitrary filesystem paths. Host checks, same-origin checks and a per-process request token protect chat mutations from unrelated web pages.

If answers fail, verify Ollama is running at `127.0.0.1:11434`, all three documented models are installed, the archive is present, and disk space is available. No model is downloaded automatically. If startup reports an occupied port, select another port; the application does not terminate other services. Restarting preserves saved UI conversations and answer JSON. Reopen a conversation from the Saved conversations menu after restarting. Terminal launch remains `.venv/bin/python main.py`.


## Saved conversations and source sections

UI conversations are saved automatically after each completed answer (including clarification and insufficient-evidence responses). They are titled from the first prompt and ordered by most recent update. Choose a saved conversation to restore its transcript, source cards and bounded follow-up context. The full transcript is retained for reading; model history remains bounded by the existing conversation settings. New conversation and `/new` preserve all previous conversations. Failed answers do not change the saved transcript or follow-up state.

Storage is `data/conversations.sqlite3`, using Python's built-in SQLite support; no new package is required. Stop the UI before copying that file for a backup. Use one UI server at a time for a project. The browser remembers the selected conversation per tab; saved conversations can also be reopened in another tab or after a server restart. Two tabs selecting the same conversation continue the same saved history; reload to see turns added by the other tab. Old per-answer JSON files from earlier versions remain untouched and are not automatically imported, since they do not reliably encode conversation boundaries. Saving applies to the UI; terminal conversation behavior is unchanged. This milestone does not include renaming or deleting conversations.

Source cards labeled **Read source section** point to IDs verified against the actual archived HTML. Matching prefers the subsection under its parent section, then the section. Unicode and punctuation in IDs are URL-encoded. Missing or ambiguous headings open the article beginning; the card then reads **Read complete offline article**. This jumps to a heading, not an exact passage highlight. The complete article and existing offline protections remain available.

In the prompt box, **Enter sends**, while **Command+Enter** (Mac) or **Ctrl+Enter** inserts a newline at the cursor, replacing any selected text. Composition input is left alone until completed. Restart an already-running UI server and reload the browser to load these changes; the launch command remains `.venv/bin/python local_ui.py`.
