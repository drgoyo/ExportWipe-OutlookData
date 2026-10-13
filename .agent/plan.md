# Implementation roadmap

The user authorized actual application code, replacing the scaffold-only scope.

1. Project and memory: dependency groups, current architecture, and end-to-end instructions.
2. Phase 1 extraction: English VBA as a strict physical-file extractor, stable checkpoint identities,
   safe defaults, MSG files and attachments grouped by type, Outlook guide.
3. Phase 1 GUI: central typed YAML, environment secrets, form validation, generated VBA INI.
4. Phases 2–4: Python-native MSG parsing for body, sender/recipients and metadata; Python owns all
   RAG modeling and DuckDB/Polars JSONL/Markdown generation. Office/CSV/text/OCR parsing, chunking,
   Chroma+SQLite with durable replay, metadata-only and deep-retrieval agents, read-only MCP SQL tools,
   CLI and authenticated backend API.
5. Phase 5: Streamlit metrics, database growth, top senders/file types, and agent file-upload UI.
6. Phase 6: hardened Docker stack, native PyInstaller builds, OS CI, integrated validation.

Each step must be implemented and verified before the next. Outlook requires classic Outlook on
Windows. Native OS build execution and real LLM availability depend on external environments.
Do not replace those validations with a claim of success.

## Completion evidence

The earlier sidecar-based implementation of Steps 1–6 passed the initial 36-test suite, architecture/
type/lint gates, Linux builds, and Docker integration; see status.md for exact evidence. Native MSG
integration is pending following the new extraction contract. Other remaining actions are to apply
model weight-download network access, configure a real LLM, compile/test VBA in classic Outlook,
and run native Windows/macOS CI.
Those external checks are not presented as completed application validation.

## Authorized follow-up: updated large-mailbox extractor and GitHub publication

1. Review updated VBA and permission failure paths: complete.
2. Replace master-file writing with DuckDB/Polars export catalog: complete.
3. Friendly mail-centered folders, bounded checkpoints, recipient privacy filtering: complete.
4. Live embedding/GGUF discovery and explicit download/install GUI/CLI: complete.
5. Safe catalog crash recovery, full documentation and deployment integration: complete.
6. Final gates and Linux/container rebuilds: complete; user-authorized GitHub publication is verified
   separately against the remote commit. Keep publication evidence separate from runtime readiness.

That published follow-up suite had 89 passing tests. Actual model weight download remains blocked by
HTTP 403 at us.aws.cdn.hf.co despite successful live metadata checks. Model/provider/Outlook/native OS
runtime prerequisites remain separate from code publication. User explicitly authorized GitHub push.

## Authorized follow-up: strict physical extraction

1. Refactor VBA to save only `.msg`, attachments in type folders, and internal operational state:
   implemented. Remove all body extraction, metadata sidecars and RAG-map logic. Track flags no
   longer affect physical extraction; per-mail checkpoints, not a global in-memory cache, govern
   idempotency. Use a fresh output directory because legacy files are not purged or migrated.
2. Update architecture and operational docs to make Python responsible for 100% of text extraction,
   metadata, RAG records, JSONL/Markdown and dual-track routing: documented. Phase 2 must parse MSG
   natively, with `extract-msg` as a candidate, and connect those records to bounded DuckDB/Polars
   catalog generation. This parser is not implemented; existing catalog/ingest commands support
   legacy sidecar exports only.
3. Verify the refactor and documentation, then commit with the user's specified message and push
   to origin: publication and final gate evidence are recorded separately in status.md.

Do not claim that a fresh MSG-only export is ingestible until native MSG parsing and attachment
association have been implemented and tested. The new macro is in source; existing binaries/images
contain their earlier bundled macro until rebuilt.
