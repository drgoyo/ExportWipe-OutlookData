# Agent entry point

This repository implements a dual-track Outlook RAG application. Read `.agent/status.md`,
`.agent/plan.md`, `.agent/decisions.md`, and relevant `.agent/rules/` before editing. Update memory
with actual verification evidence, decisions, and remaining limitations. Never record credentials
or real emails in memory.

## Canonical shape and boundaries

- `src/pipelines/vba_extraction/`: Outlook VBA and export-format assets.
- `src/pipelines/export_catalog/`: bounded DuckDB/Polars catalog and index generation.
- `src/pipelines/configuration_gui/`: configuration editor presentation.
- `src/pipelines/document_parsing/`: Office, table, text, and image-to-Markdown processing;
  native MSG parsing is the next Phase 2 integration task.
- `src/pipelines/data_ingestion/`: chunking and SQL/vector synchronization use cases.
- `src/pipelines/rag_agents/`: metadata-only and deep-retrieval agent behavior.
- `src/pipelines/analytics/`: dashboard and metrics presentation.
- `src/project_name/core/`: minimal shared typed records and ports.
- `src/project_name/infrastructure/`: SQLite, Chroma, embeddings, and LLM adapters.
- `src/project_name/`: application composition, CLI, GUI, API, MCP, and dashboard entry points.
- `config/`: typed central YAML configuration and secret environment settings.
- `tests/pipelines/`: tests mirroring each slice; infrastructure tests mirror project_name.

Slices are independent. Never import another slice or concrete infrastructure inside a slice.
Processing, ingestion, agents, and analytics receive ports and typed configuration through the outer
composition root. Core cannot depend on config, pipelines, adapters, Polars, or pydantic-settings.
Infrastructure cannot import pipelines. Config cannot import either application package. The five
import-linter contracts in pyproject.toml enforce these rules. Register new slices in the independence
contract. No global or nested horizontal models/services layers.

## Workflow

Use Python 3.12+, uv, absolute imports, Polars for tabular ETL, Ruff, pytest, and strict mypy.
Use `uv sync --locked --all-extras --group build` for full development. Change dependencies with
`uv add` or intentional pyproject edits followed by `uv lock`; never hand-edit uv.lock.
Run Ruff lint/format, mypy, lint-imports, pytest, and uv build before reporting a completed change.
Feature tests must exercise real parsing and database behavior, failure recovery, privacy boundaries,
and side effects. Never disable TLS, checksums, assertions, or architecture contracts for a pass.

## Operational rules

Track 1 only sees allowlisted metadata; email bodies and attachment contents must never reach its
LLM request. Track 2 may read content only when explicitly enabled. Do not treat the freemail domain
filter as a complete privacy classifier. All export defaults are copy-only. Destructive VBA modes
require explicit opt-in and an interactive confirmation; never run them as a setup or test step.
Secrets are supplied through .env/environment settings, never config.yaml or exported INI files.
MCP SQL is read-only, limited, and restricted to curated metadata views. SQL/vector writes use a
durable pending state with replay; never claim an atomic transaction across SQLite and Chroma.
VBA is strictly a physical-file extractor. It outputs only Unicode MSG files, qualifying by-value
attachments grouped by extension under each mail, and operational state: `export.lock`, per-mail
`_state/source_id.txt` and `_state/complete.txt`, and append-only `Processed_Cache.log`. Never add body
reads, `Email.txt`, `metadata.json`, JSONL/Markdown generation, RAG maps, domain schemas or track
routing to VBA. Property reads are limited to filenames, source identity and date/privacy filtering.
Track flags may remain in the generated INI for backward compatibility but VBA ignores them.
Python owns 100% of RAG modeling, text extraction, metadata handling, dual-track routing and output
generation. Phase 2 must natively parse MSG bodies, sender/recipients and metadata, for example with
`extract-msg`, and associate extracted attachments before building DuckDB/Polars indexes and feeding
SQLite/vector ingestion. That MSG-native parser is not yet implemented or installed. The current
catalog reads legacy `metadata.json` sidecars; never describe it as compatible with new MSG-only
exports or recommend catalog/ingest commands as a complete new-format workflow. Keep legacy support
separate and document this boundary until real MSG integration tests pass.
VBA writes only one email's files at a time; Python builds global indexes in bounded batches.
DuckDB catalogs stay local, outside OneDrive/SharePoint synchronization while open. Export and catalog
locks are mutual exclusion signals; an interrupted catalog publication must be repaired before ingest.
Model discovery must distinguish installed SDK support, live Hugging Face checks, downloaded files,
and successful runtime validation. Only explicit download/install actions fetch model weights.

Use the existing isolated checkout; do not create a worktree unless requested. Preserve user changes
and the MIT license. No live Outlook/mail access is needed for tests. Standalone binaries are built
natively on each OS; PyInstaller cannot cross-compile Windows/macOS from Linux. Record native build,
GUI, OCR, Docker, provider, and Outlook runtime validation separately.
