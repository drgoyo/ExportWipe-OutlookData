# Current implementation state

Updated: 2026-10-13. Version: 0.3.0. The latest user request changes the extraction boundary to a
strict physical-file exporter. Phase 1 is refactored; native Python MSG parsing is the next Phase-2
implementation task. Earlier sidecar-based application/deployment verification is historical evidence,
not evidence that the current Python pipeline consumes the new raw exports.

## Existing application and historical baseline

- English classic-Outlook VBA based on the updated source: Long counters, per-email completion
  markers, no mailbox-sized checkpoint dictionary and no global JSONL/Markdown generation. Copy-only
  export requires no PST or mail.Copy. Sender and To/CC/BCC filtering resolves SMTP addresses, matches
  exact domains/subdomains and fails closed for unknown contacts when enabled. Recursive folder/item
  failures are isolated. Unicode MSG backup and all exported artifacts precede explicit cleanup.
- Readable Mail/year/month/date_subject_sender_identity folders group each email and attachments.
  Sanitized, extension-preserving bounded names, full identity collision checks, original folder
  metadata, local write preflight and export/catalog locking. Installation/permissions guide included.
- Polars/DuckDB export_catalog slice: batches at most 256 rows/4 MB, DuckDB 128 MB limit and disk spill,
  streamed UTF-8 metadata-only master files, persistent queryable catalog, deduplication and containment.
  Publication journal/backups, rollback and catalog-recover survive genuine process interruption.
- Validated central YAML, environment-only credentials, native configuration GUI and generated INI.
  Explicit embedding/GGUF model dialogs use background workers and separate apply/save steps.
- FastEmbed-supported model discovery, live HF repository/revision/license checks, CPU/resource
  recommendations, explicit pinned installation and portable receipts. Inference requires a validated
  receipt. Revision signatures reject model changes against existing/cached Chroma adapters.
- Live official GGUF discovery with actual filenames/sizes, explicit pinned download, GGUF/size/LFS
  checksums, cache reuse and optional import into an existing local Ollama. No remote model code runs.
- DOCX/XLSX/PPTX/CSV/text and Tesseract image parsing to bounded Markdown; overlapping chunks;
  SQLite metadata/durable synchronization jobs, local/HTTP Chroma, ready-only retrieval and replay.
- Metadata-only agent, deep RAG agent, configurable OpenAI-compatible LLM, CLI/API/stdio MCP and
  Streamlit analytics. Curated read-only SQL has AST/authorizer/row/time defenses. Track 1 CLI reads
  at most 20 MB before prompting. Raw data/credentials stay out of Git.
- Digest-pinned Docker app/Chroma stack with non-root/read-only app services, private storage network,
  persisted volumes and isolated writable/no-network catalog tool. Native PyInstaller GUI/backend/
  dashboard bundles and Linux/Windows/macOS CI, full README and MIT license preserved.

## Historical verification at commit 85fcf36

- Python 3.12.14, uv 0.12.23: 89 pytest tests passed, none failed or skipped, including real Tk tests
  under Xvfb. Ruff lint/format passed; strict mypy passed for 62 source files; five architecture
  contracts kept with rejection probes. Wheel and source distribution 0.3.0 built; assets verified.
- Real DuckDB/Polars catalog tests, Unicode/legacy UTF-16 handling, bounded batches, privacy stripping,
  path/symlink rejection, deduplication/conflicts and CLI catalog-to-SQL/Chroma ingestion passed.
- Genuine child-process termination during publication, previous DuckDB/JSONL/Markdown restoration,
  interrupted-recovery retry, tampered journals and mutual locks passed. Existing parser/OCR,
  SQLite/Chroma consistency/replay/force rebuild, HTTP/MCP and dashboard checks still pass.
- All 41 SDK-compatible Hugging Face repositories verified against current live metadata (HTTP 200).
  Multilingual MiniLM and German Jina are actual supported choices. Current Qwen GGUF inventories
  checked; Qwen3-4B Q4_K_M is 2,497,280,256 bytes at bc640142c66e1fdd12af0bd68f40445458f3869b.
- Explicit BGE-small installation was attempted; model weights hit proxy HTTP 403 at us.aws.cdn.hf.co.
  No validated receipt or successful semantic inference was claimed. Required CDN domain saved in
  the cloud draft; draft persistence does not apply networking to the running task.
- Updated Linux x86_64 GUI/backend/dashboard bundles built. Compiled GUI rendered; compiled backend
  generated real DuckDB/master files and listed 41 compatible models. The frozen dashboard rendered
  all five metrics through a real WebSocket session. Windows/macOS execution remains external.
- Docker app/Chroma images built. Catalog-user test exposed private template permissions; Dockerfile
  now copies non-secret config with explicit read permissions. Final images rebuilt successfully.
  Container catalog ran as the export-directory owner; Chroma/backend/dashboard were healthy. Real
  parsing and two SQL/Chroma documents synchronized using explicit synthetic384-dimensional vectors.
  Authenticated API statistics and the container dashboard agreed (1email,2documents,2vectors).
  Synthetic vectors prove deployment wiring, not model inference or semantic quality.
- Builds reached the 32 GB disk limit. Only generated Docker build cache and known obsolete images
  from this task were removed; retained bundles and source data were preserved. Build retry uses the
  freed storage and unchanged TLS/package verification.

## External validation and configuration

Classic Outlook/VBA COM compilation and live mailbox behavior cannot run on this Linux host. Source
review and three guard tests passed; use Debug > Compile and a small copy-only folder before rollout.
No real mail or destructive mode was accessed. Actual semantic inference requires model weight access;
real generative answers require a running local model/HTTPS provider. No real LLM responds at the
current default Ollama endpoint. Existing EW_LLM_API_KEY/EW_API_TOKEN were absent; no secrets recorded.
Windows/macOS jobs are configured; signing/notarization is not supplied. Model quality is unmeasured.
Cloud draft save is separate from publication/restoration in a new task; neither is claimed verified.

## Current refactor and handoff

The VBA writes only Email.msg, qualifying physical attachments separated into Type_<extension>/Other,
and internal export.lock/Processed_Cache.log/_state/source_id.txt/complete.txt. It never reads message
body text or emits Email.txt, metadata.json, JSONL, Markdown or RAG maps. Track flags are ignored by
the exporter; Python owns routing and all RAG data modeling. Existing GUI cleanup validation still
adds a Track-2 guard, while macro cleanup requires its own explicit opt-in/default-No confirmation.

The append-only log is operational history, never loaded as a mailbox-sized cache. Versioned raw-msg-v1
markers cannot reuse old sidecar checkpoints. Full identity/MSG presence are checked before skips;
all physical writes and completion precede source cleanup. Use a fresh export root: legacy files are
never deleted automatically. Read-only legacy source identity and Python lock checks preserve safety.

Four focused VBA guard tests passed and an independent source review found no blocking syntax/safety
issue. Classic Outlook compilation/runtime remains unexecuted on Linux. Final verification:90 pytest tests passed (none skipped under Xvfb), strict mypy62files, Ruff
lint/format,5architecturecontracts and wheel/source builds passed. The new .bas asset is in the wheel.
Existing native bundles/Docker images contain the previous VBA asset and were not rebuilt for this
VBA/documentation-only change. Rebuild from the updated checkout to distribute the current macro.

Native MSG extraction (extract-msg is a candidate), header/body metadata, attachment association and
integration with bounded DuckDB/Polars JSONL/Markdown remain pending Python Phase 2. The current catalog
still accepts legacy metadata.json sidecars only. Do not run it against fresh MSG-only exports or
claim that pipeline is complete; an unguarded raw-only run could publish an empty catalog.

The cloud startup draft explicitly marks catalog/ingest as legacy-only until native MSG parsing is
implemented. Saving is separate from environment publication. The user authorized the exact refactor
commit message and GitHub push. Preserve ignored config.yaml,
.env, data and MIT license; no mailbox actions or unrelated user-data cleanup were performed.
