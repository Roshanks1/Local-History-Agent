# Retrieval baseline V1 — 2026-09-06

Corpus: 59 chunks of `Thirty_Years_War`, extracted from `data/wikipedia/wikipedia_en_all_nopic_2026-06.zim`. Existing chunker: target 2,000 characters, whole-paragraph overlap target 300. Embedding: `nomic-embed-text`, local digest recorded in the JSON artifacts. Raw user questions, cosine similarity, top five; no query rewriting or reranking.

Dataset: the existing **five** questions. Judgments are provisional, assistant-authored and potentially incomplete. Scores apply only to these labels and this small development set.

| Metric | Existing section metadata | Article + section metadata |
|---|---:|---:|
| Hit rate@1 | 20% | 60% |
| Hit rate@3 | 80% | 100% |
| Hit rate@5 | 80% | 100% |
| Recall@1 | 3.33% | 13.33% |
| Recall@3 | 33.33% | 35.67% |
| Recall@5 | 48.33% | 49.00% |
| MRR@5 | 0.50 | 0.80 |

Saved runs: `artifacts/baseline-section.json`, `artifacts/experiment-title.json`. Both contain full ranked evidence and fingerprints. The title experiment uses the same labels and chunk corpus; only embedded metadata changes. It is the V1 default because it improves early relevant hits on this development set.

The baseline puts “Human and financial cost of the war” first for all five questions and misses all labeled ending-of-war evidence within the top five. Title enrichment retrieves labeled evidence for every question within the top three, but still ranks human-cost material first for the causal question. For the ending question it ranks political consequences first, ahead of the labeled introductory passage. Better hit rate does not mean complete evidence coverage: recall@5 remains 49% against the provisional labels.

Do not tune a complex reranker on these five questions. First independently review and expand the labels, add out-of-corpus questions and hold out a test set. Then compare a hybrid lexical/vector method, query/document embedding prefixes, or a local reranker against this frozen baseline. Chunk-size experiments require new judgments because chunk IDs encode positions.
