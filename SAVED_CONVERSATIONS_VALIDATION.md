# Saved conversations milestone — 2026-09-08

Implemented automatic UI conversation persistence, reopening/continuation, verified archive section fragments, and Enter-to-send with Command/Ctrl+Enter for newlines.

Validation:

- Baseline: 47 tests passed before editing; final suite: 50 tests passed. Report: `artifacts/saved-conversation-validation/tests.txt`.
- Restart test closes the SQLite connection and constructs a new application against the same database, then restores transcript and clarification options and continues the saved focus.
- Tests cover independent conversations, New preserving earlier turns, failed generation leaving stored context untouched, invalid saved IDs, section/subsection hierarchy, Unicode fragment encoding, missing and ambiguous heading fallback, and existing terminal/HTTP/reader behavior.
- Live browser generation through Enter: Qwen3 14B, 3,323 prompt and 162 output tokens. Both Command+Enter and Ctrl+Enter inserted newlines without submitting. Disabled/loading state appeared on plain Enter.
- Browser New cleared the view while retaining the saved entry. Selecting it restored the answer and source cards. Browser reload restored the selected conversation.
- Actual archive paths verified: `/wiki/Thirty_Years%27_War#Structural_origins` and `/wiki/Thirty_Years%27_War#Bohemian_Revolt`. Browser screenshot confirmed the latter landed at the Bohemian Revolt heading.

Conversation history is in `data/conversations.sqlite3`. The original answer JSON files remain in place and new per-answer files continue to be written. Old answers are not automatically grouped/imported; their prior session boundaries were not stored. Titles use the first prompt; rename/delete and passage highlighting are outside this milestone. Full transcripts are saved for reading, while generation continues using bounded conversation context. Run one UI server per project, and stop it before copying the SQLite file for backup. The saved list is shared locally; different tabs may select separate conversations or intentionally continue the same one.

No model defaults, generation options, Ollama endpoint, ZIM path, retrieval/chunking implementation or frozen benchmark reports were changed. The directory remains outside Git. Launch is unchanged; restart existing server processes and reload the page to apply the milestone.
