# Local reading UI validation — 2026-09-06

The requested project was inspected before editing and is not a Git repository. No Git initialization or commit was performed. The referenced conversation contained only a truncated handoff; the current user's detailed implementation request supplied the remainder of the spec.

## Checks

- Before implementation: all 36 existing unit tests passed.
- Baseline local retrieval evaluation passed. A local Qwen3 14B terminal generation completed with an intentionally shortened 80-token smoke-test limit.
- Final suite: 47 tests, including real Ollama response-object normalization, missing/zero/partial/invalid token counts and durations, preserved legacy fields, skipped-call behavior, quiet automatic discovery, isolated session follow-ups/reset/error retry, redirect loops, Unicode/path encoding, invalid/missing articles, HTTP authorization, static assets and occupied ports.
- Live browser: default Qwen3 14B automatic discovery, loading state and disabled controls, error state, successful retry after correcting a quiet-output regression, answer/source cards, usage and debug-trace control.
- Successful UI generation: 3,338 prompt tokens + 299 output tokens = 3,637 total; context window 8,192; output limit 600. The answer is saved in `artifacts/ui/` with the existing trace format.
- Source card opened the actual local Thirty Years' War article in the browser. Verified title and rendered table layout. The alias `Thirty_Years_War` resolves to `/wiki/Thirty_Years%27_War`. Served HTML was 451,373 bytes with 20 tables and the References section; three sampled archived stylesheets returned HTTP 200 and text/css.
- Final terminal smoke: 2,186 prompt + 80 output = 2,266 total; context 8,192; output-limit notice displayed. This test-only output override does not change the default of 600.
- Before/after baseline and expanded retrieval metrics are identical on the five-question benchmark. The 59-chunk fixed index passes fingerprint validation and its corpus hash still matches the frozen benchmark.

Reports are under `artifacts/ui-validation/`. Existing frozen results, original extractor/chunker, archive path, model defaults, endpoint and requirements were not edited. Normal automatic discovery continues to use the existing embedding cache. Initial sandboxed Ollama checks failed due to restricted network access; authorized local checks subsequently confirmed all three installed models and completed successfully.

## Reader and limitations

Kiwix 3.16.1 was inspected through its bundle and UI. It registers `zim:` but no complete deep-link format was verified. Its Hotspot screen had no configured ZIM files; no standalone kiwix-serve was found on PATH or in the bundle. The application therefore uses the installed libzim 3.7.0 read-only fallback, not a guessed Kiwix URL or a LAN server. See README for exact routes and prerequisites.

The complete archived article content is preserved for reading, with active HTML features and external links disabled. Missing images in the no-picture archive remain unavailable. Source cards open article beginnings, not section anchors. Sessions are in memory, expire after 24 hours of inactivity and reset on reload/restart. There is no streamed generation or cancellation; requests are serialized. Tests establish integration behavior, not historical factual accuracy. The entire six-turn live evaluation suite was not rerun; live validation focused on the changed terminal/UI/reader paths.
