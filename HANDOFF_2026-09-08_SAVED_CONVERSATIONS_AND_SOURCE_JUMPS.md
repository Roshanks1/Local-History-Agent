# Fresh-session handoff — saved conversations and source jumps

Date: 2026-09-08  
Project: `/Users/roshankatta/Projects/LocalAI/offline-history-ai`

## Current state

This is a local, offline historical research assistant. It uses local Ollama generation and embeddings, local Wikipedia discovery from a ZIM archive, article/section expansion, cached embeddings, bounded conversational context, and source-grounded answers. It now has both a conversational terminal interface and a loopback-only browser UI.

The project directory is **not a Git repository**. Do not assume commits, branches, or a clean working tree are available. Preserve the original extraction/chunking pipeline, cached artifacts, benchmark results, and existing per-answer JSON files.

Fixed configuration that must remain unchanged unless the user explicitly requests otherwise:

- Wikipedia archive: `data/wikipedia/wikipedia_en_all_nopic_2026-06.zim`
- Default generation model: `qwen3:14b`
- Alternate generation model: `qwen3:8b`
- Embedding model: `nomic-embed-text`
- Ollama endpoint: `http://127.0.0.1:11434`
- Generation context: `num_ctx=8192`
- Default output limit: `num_predict=600`
- Python environment: `.venv`

## Work completed

### Retrieval and conversation foundation

The application already supported automatic archive-wide topic discovery, structured Wikipedia extraction, semantic retrieval, article/section expansion, context packing, timelines, cached embeddings, clarification prompts, and bounded follow-up state. The terminal entry point remains `main.py`; the pipeline and CLI live primarily in `history_ai.py`.

Relevant modules include:

- `history_ai.py` — CLI, retrieval/generation orchestration, saved answer records
- `conversation_state.py` — bounded follow-up context
- `query_analysis.py` — query type and follow-up interpretation
- `retrieval_expansion.py`, `answer_context.py`, `timeline_utils.py` — retrieval and evidence handling
- `wikipedia_local.py`, `structured_wikipedia.py` — ZIM access and extraction
- `main.py`, `terminal_output.py` — terminal conversation and presentation

### Centralized generation usage

`usage.py` normalizes the final Ollama generation call's usage. Terminal and browser answers show:

- active model
- configured 8,192-token context window
- final-call prompt, output, and total tokens
- unavailable values without inventing estimates
- explicit skipped-generation semantics

Existing JSON usage/timing fields retain their prior meanings; the `usage` object is additive. Retrieval and embedding calls are not included in final-generation token totals.

### Local browser UI

The UI is implemented with the Python standard library and local static files:

- `local_ui.py` — loopback HTTP application and API
- `ui.html`, `ui.css`, `ui.js` — browser interface
- `offline_reader.py` — read-only archive article server and source-link resolution

It binds only to `127.0.0.1`, uses no CDN or cloud dependency, and includes loading/error states, model selection, optional debug traces, source cards, and New conversation behavior. Chat mutations require the same loopback Host/Origin and a per-process token.

Requests are serialized because the existing embedding cache uses shared temporary filenames. There is currently no streaming or cancellation; closing a tab does not cancel a pending answer.

### Complete offline Wikipedia reading

Kiwix macOS 3.16.1 was inspected. It registers a `zim:` URL scheme, but no complete article deep-link format was verified. Its Hotspot had no configured archive, and no standalone `kiwix-serve` executable was found. No Kiwix URL scheme was guessed.

The verified fallback uses installed `libzim==3.7.0` against the exact configured archive. `offline_reader.py` resolves archive entries and redirects, serves complete archived HTML and local resources, and keeps links inside `/wiki/...`. It removes scripts, forms, embedded active content, event handlers, and external resource links, with a restrictive content policy.

The archive is the `nopic` edition, so absent images remain unavailable. Interactive Wikipedia features and public external links are intentionally disabled.

### Saved conversations

Browser conversations are persisted in `data/conversations.sqlite3` by `conversation_store.py`, using Python's built-in SQLite support.

Behavior:

- A successful answer saves the transcript, source records, and bounded `ConversationState` together.
- Conversations are titled from their first prompt and ordered by latest update.
- The Saved conversations menu restores the transcript and follow-up context.
- A restored conversation can continue with natural follow-ups after a server restart.
- New conversation and `/new` start a blank conversation without deleting earlier conversations.
- Failed generation does not commit a partially mutated transcript or follow-up state.
- The selected conversation ID is remembered per browser tab with `sessionStorage`.
- The full transcript is retained for reading, while model history remains bounded by the existing conversation settings.

Old per-answer JSON files are preserved but are not imported into SQLite because older records do not reliably encode conversation boundaries. Renaming and deleting conversations have not been implemented.

Use one UI server per project. Stop the UI before copying `data/conversations.sqlite3` for backup. Two tabs can deliberately open the same saved conversation, but one tab must reload to see turns added by another.

### Source-section jumps

Source cards now inspect the actual archived article headings and use verified HTML IDs. Resolution prefers:

1. the source subsection scoped to its parent section;
2. the source section;
3. the article beginning when a match is missing or ambiguous.

Fragments are URL-encoded, including Unicode and punctuation. Verified examples from the current archive:

- `/wiki/Thirty_Years%27_War#Structural_origins`
- `/wiki/Thirty_Years%27_War#Bohemian_Revolt`

This feature jumps to a heading. It does not yet highlight the exact evidence passage.

### Prompt keyboard behavior

In the browser prompt field:

- Enter submits the prompt.
- Command+Enter on macOS inserts a newline.
- Ctrl+Enter also inserts a newline.
- Composition input is left alone until composition completes.

The UI includes a visible keyboard hint.

## Launch instructions

From VS Code's integrated terminal or another terminal:

```sh
cd /Users/roshankatta/Projects/LocalAI/offline-history-ai
.venv/bin/python local_ui.py
```

Open the printed `http://127.0.0.1:PORT` address. The default is:

```text
http://127.0.0.1:8765
```

If that port is occupied:

```sh
.venv/bin/python local_ui.py --port 0
```

Ollama must already be running locally with `nomic-embed-text`, `qwen3:14b`, and optionally `qwen3:8b` installed. Press Ctrl+C in the server terminal to stop it. Restart any older running UI server and reload the browser after code changes.

Terminal conversation remains:

```sh
.venv/bin/python main.py
```

## Validation status

As of 2026-09-08:

- All **50 unit/integration tests pass** with `.venv/bin/python -m unittest discover -s tests -v`.
- Tests cover token accounting, skipped calls, terminal compatibility, UI HTTP protections, invalid paths, redirects and redirect loops, Unicode URL encoding, occupied ports, session isolation, saved-conversation restart/continuation, failure rollback, new-conversation preservation, and heading resolution/fallback.
- A live Qwen3 14B browser answer was generated and saved.
- Enter submitted; Command+Enter and Ctrl+Enter inserted newlines.
- New conversation preserved the prior saved conversation.
- Selecting and reloading restored the saved transcript.
- A source link visibly landed at the archived `Bohemian Revolt` heading.
- Earlier retrieval before/after checks were unchanged, and the original 59-chunk benchmark corpus remained fingerprint-compatible.

Validation details:

- `SAVED_CONVERSATIONS_VALIDATION.md`
- `UI_VALIDATION.md`
- `artifacts/saved-conversation-validation/tests.txt`
- `artifacts/ui-validation/`

The tests validate application behavior, not the historical accuracy of generated claims. The full multi-turn live evaluation was not rerun for the latest saved-conversation milestone.

## Important limitations

- Conversation titles are derived from the first prompt; they cannot be renamed.
- Saved conversations cannot be deleted or archived from the UI.
- There is no schema-version/migration framework for the SQLite record format.
- There is no streaming response, Stop button, or request cancellation.
- Source links jump to headings rather than highlighting the exact cited passage.
- Citation syntax validation does not establish claim-level factual support.
- Multiple UI server processes should not write the same project database concurrently.
- Simultaneous tabs editing the same conversation do not receive live updates or conflict detection.
- Browser keyboard behavior was live-tested, but there is no dedicated automated JavaScript browser test suite.
- The benchmark contains five provisionally labeled questions and 59 chunks; it is not a 59-question evaluation set.

## Suggested next steps

Recommended order:

1. **Conversation management:** add rename, archive/delete with a recoverable confirmation flow, search, and an explicit export/backup option. Add SQLite schema versioning and migrations before expanding stored metadata.
2. **Exact citation inspection:** make inline `[S1]` citations open the precise supplied passage, and highlight or scroll to the closest archived article text. Keep a safe fallback when archive prose differs from extracted text.
3. **Streaming and cancellation:** stream model output, add a Stop button, and define what gets saved when a request is cancelled or fails midway.
4. **Concurrency hardening:** add per-conversation revision checks or optimistic locking so two tabs cannot silently overwrite each other's state. Decide whether multiple server processes should be rejected with a lock file or supported through database-level coordination.
5. **Automated browser coverage:** add focused tests for Enter/Command+Enter/Ctrl+Enter, reload restore, menu switching, source-card fragments, loading/error recovery, and narrow/mobile layouts.
6. **Conversation portability:** export a saved conversation with answers, citations, and source passages as Markdown; optionally support a local import format with validation.
7. **Evaluation expansion:** build an independently reviewed held-out set with answerable, unanswerable, ambiguous, timeline, comparison, and multi-turn questions before changing retrieval weights.
8. **Evidence quality:** add exact citation previews and warnings for uncited claims, unknown labels, incomplete coverage, and conflicting retrieved passages.
9. **Local health panel:** report archive availability, Ollama connectivity, required model presence, disk/write errors, and current database path in plain language.

For the next session, inspect the current files and rerun the 50-test suite before editing. Do not run the exploratory root-level `*_test.py` files through broad discovery because several perform live work on import; use `tests/` discovery exactly as documented.
