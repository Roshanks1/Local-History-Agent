# Next phase: token visibility and a local reading UI

Project: `/Users/roshankatta/Projects/LocalAI/offline-history-ai`

This handoff describes future work. The terminal usage display and UI described below have **not** been implemented by this task.

## Objectives

1. Extend terminal answers to show the active model context window and tokens used.
2. Build a small local conversational UI.
3. Make each source open its complete article from the downloaded Wikipedia archive, using a verified local Wikipedia reader or server. No public Wikipedia links or internet dependency.

## Preserve the current foundation

The application uses local Ollama, local Wikipedia discovery, article/section expansion, cached embeddings, conversation state, and source-grounded generation. Reuse these components rather than rebuilding the pipeline.

- Archive: `data/wikipedia/wikipedia_en_all_nopic_2026-06.zim`. Keep this exact configured dataset path.
- Default model: `qwen3:14b`; alternate: `qwen3:8b`; embeddings: `nomic-embed-text`.
- Ollama endpoint: `http://127.0.0.1:11434`.
- Current generation context: `num_ctx=8192`; default output limit: `num_predict=600`.
- Python environment: `.venv`; installed dependencies are recorded in `requirements.txt`.
- Preserve original extraction/chunking, cached artifacts, and frozen benchmark results. This directory was not a Git repository at the earlier inspection; check current state before editing.

Useful files:

| Area | Existing implementation |
|---|---|
| Entry points, generation, answer records | `history_ai.py` |
| Terminal conversation loop | `main.py` |
| Terminal answer/source formatting | `terminal_output.py` |
| Session memory and query interpretation | `conversation_state.py`, `query_analysis.py` |
| Discovery and article expansion | `article_discovery.py`, `retrieval_expansion.py` |
| Original archive access | `wikipedia_local.py` |
| Structured extraction and timelines | `structured_wikipedia.py`, `timeline_utils.py` |
| Evidence budgets and settings | `answer_context.py`, `retrieval_config.py`, `retrieval_config.json` |
| Tests and live evaluation | `tests/`, `evaluate_assistant.py` |
| Current architecture and results | `ARCHITECTURE.md`, `artifacts/assistant-validation/` |

The last reported suite has 36 passing tests and six live conversation checks. Verify the current state before extending it. The benchmark has five provisionally labeled questions and 59 original chunks. Citation validity does not establish factual accuracy; this phase should not claim to solve existing historical interpretation or retrieval limitations.

## 1. Terminal model/token display

Add a compact usage block separated from the answer and sources. Include:

- Model name.
- Configured context window for this generation call.
- Actual prompt tokens reported by Ollama (`prompt_eval_count`).
- Actual generated tokens (`eval_count`).
- Total reported tokens for the call: prompt + generated, when both are available.
- Completion/truncation status where useful.

Example layout — values are illustrative:

```text
MODEL & USAGE
Model: Qwen3 14B          Context window: 8,192 tokens
Prompt: 2,400             Generated: 320
Total this answer: 2,720 tokens
```

`generate()` already saves `prompt_eval_count`, `eval_count`, `done_reason`, and `generation_options.num_ctx`. Reuse those values and centralize any new usage normalization so the terminal and UI consume the same record.

Accuracy requirements:

- The configured `num_ctx` is the active window, not necessarily the model's maximum supported context.
- `num_predict` is an output ceiling, not tokens actually generated.
- The evidence token budget in `answer_context.py` is an estimate, not actual prompt usage.
- Prompt tokens include instructions, dialogue context and supplied evidence. Label usage as belonging to the final answer-generation call; do not silently mix embedding/model calls into it.
- Missing counts mean “unavailable,” not zero. Distinguish a genuine zero from a missing value.
- Clarification or insufficient-evidence responses that skipped generation should say “model not called.” Do not display fabricated usage.
- If showing a percentage, explicitly label it as reported prompt/total tokens divided by the configured window. Do not imply an exact live KV-cache or memory measurement.
- Keep counts in saved JSON as well as the display. Preserve existing fields for compatibility.

## 2. Minimal local UI

Build a focused first version, not a redesign of the backend. Suggested scope:

- Conversation transcript and multiline input with Send/Enter behavior.
- Visible “searching / preparing answer” status; disable duplicate submissions during a run.
- Readable answers and citations, source cards, and the model/token usage block.
- New conversation action corresponding to `/new`.
- Optional development panel exposing the existing debug trace.
- Clear errors when Ollama or the archive reader is unavailable.

Separate reusable answer execution from terminal printing as necessary. Share the existing retrieval/generation code and keep independent conversation state per UI session. Avoid blocking the UI while indexing or generating. Streaming is optional for this first version.

Run the UI/backend on loopback. Bundle its scripts, styles, fonts and icons locally. Do not use hosted model APIs, CDNs, external analytics, or cloud deployment. The terminal program must continue working.

## 3. Clickable sources that open full offline Wikipedia articles

The user wants a source click to open the correct downloaded Wikipedia article in the appropriate local viewing tool. Opening the cleaned RAG excerpt, a source-code file, or public `en.wikipedia.org` does not satisfy this requirement.

### First inspect reader availability

Identify whether Kiwix or another suitable ZIM reader/server is already installed. Verify its actual supported article-opening mechanism; installation and deep-link support have **not** been established by this handoff. Do not invent a `kiwix://` scheme or assume that an article identifier equals a guessed URL.

Preferred integration:

1. Reuse the installed local reader's verified article-opening interface when available.
2. If it has no usable deep link, use a local Kiwix serving process to expose this same ZIM archive and open its article URLs in the browser. This should display the complete offline article through the local Wikipedia reader, not a web search.
3. If neither is available, implement a narrowly scoped local ZIM viewing route using the existing archive library, or document the reader prerequisite. A custom route must serve original article HTML and required archive resources; the text-cleaning functions are unsuitable for full-page viewing.

### Source-to-article mapping

- Resolve sources from their stored `article_path` and archive identity; retain `chunk_id`/section for citation traceability.
- Canonicalize redirects and use the reader/server's verified URL format and archive identifier.
- Encode apostrophes, spaces, Unicode and other path characters correctly.
- Open the full article. A verified section anchor is a useful enhancement, but missing anchors must still open the article.
- Relative images, styles, internal links and redirects should resolve through the same local archive service. Never silently fetch missing content online. This is a `nopic` archive, so unavailable images are expected.
- Prefer a new reader tab/window so the chat remains available. Clearly mark source cards as offline articles.
- Start/reuse the reader service cleanly, bind it to loopback, handle port conflicts, and explain readiness failures in the UI. Avoid duplicate or orphaned server processes.
- Restrict any custom serving route to archive content; do not expose arbitrary local filesystem paths.

Provide one reusable source-link resolver for all source cards. Optional terminal links can use the same URLs, but terminal hyperlinks are not required for this phase.

## Acceptance checks

### Usage

Verify correct display with reported counts, missing values, zero tokens, a skipped model call and a length-limited answer. Confirm that UI, terminal and saved JSON agree and that estimates are clearly distinguished from measured counts.

### UI and conversation

Complete the existing three-turn sequence: “What caused the Thirty Years' War?” → “Which cause was the most immediate?” → “Why?” Verify new-conversation reset and session isolation, readable sources, loading/error states, and no regression to terminal operation.

### Offline source opening

With external network access disabled, click sources for the Thirty Years' War, World War I and Napoleon. Verify that each opens the correct **full local article**, including redirects and a title containing punctuation/Unicode. Follow an internal article link and check local assets. Also test a missing reader/service, invalid article and port conflict.

## Deliverables for the next agent

Inspect the repository first, then implement incrementally. Deliver the usage display, runnable local UI, working offline article links, focused tests, and updated launch/troubleshooting instructions. Report the exact local reader integration used, any prerequisite installation, checks performed, and remaining limitations. Preserve the current ZIM path and the terminal workflow throughout.
