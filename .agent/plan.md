# Implementation roadmap

The user authorized actual application code, replacing the scaffold-only scope.

1. Project and memory: dependency groups, current architecture, and end-to-end instructions.
2. Phase 1 extraction: English VBA, stable identifiers, safe defaults, split exports, Outlook guide.
3. Phase 1 GUI: central typed YAML, environment secrets, form validation, generated VBA INI.
4. Phases 2–4: Office/CSV/text/OCR parsing, chunking, Chroma+SQLite with durable replay, metadata-only
   and deep-retrieval agents, read-only MCP SQL tools, CLI and authenticated backend API.
5. Phase 5: Streamlit metrics, database growth, top senders/file types, and agent file-upload UI.
6. Phase 6: hardened Docker stack, native PyInstaller builds, OS CI, integrated validation.

Each step must be implemented and verified before the next. Outlook requires classic Outlook on
Windows. Native OS build execution and real LLM availability depend on external environments.
Do not replace those validations with a claim of success.

## Completion evidence

Steps 1–6 are implemented. The 36-test suite, architecture/type/lint gates, Linux builds, and Docker
integration passed; see status.md for exact evidence. The remaining actions are to apply model weight-download network
access, configure a real LLM, compile/test VBA in classic Outlook, and run native Windows/macOS CI.
Those external checks are not presented as completed application validation.

## Authorized follow-up: updated large-mailbox extractor and GitHub publication

1. Review updated VBA and permission failure paths: complete.
2. Replace master-file writing with DuckDB/Polars export catalog: complete.
3. Friendly mail-centered folders, bounded checkpoints, recipient privacy filtering: complete.
4. Live embedding/GGUF discovery and explicit download/install GUI/CLI: complete.
5. Safe catalog crash recovery, full documentation and deployment integration: complete.
6. Final gates and Linux/container rebuilds: complete; user-authorized GitHub publication is verified
   separately against the remote commit. Keep publication evidence separate from runtime readiness.

The current follow-up suite has 89 passing tests. Actual model weight download remains blocked by
HTTP 403 at us.aws.cdn.hf.co despite successful live metadata checks. Model/provider/Outlook/native OS
runtime prerequisites remain separate from code publication. User explicitly authorized GitHub push.
