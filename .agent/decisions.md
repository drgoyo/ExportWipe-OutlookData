# Architectural decisions

## ADR-0001: Independent vertical slices and uv

- Date: 2026-10-13
- Status: Accepted
- Scope: Repository infrastructure

### Context

RAG/ETL workflows combine distinct extraction, OCR, and embedding concerns. Horizontal models and
service layers scatter each use case, increasing the context agents must load. Dependency setup
also needs one repeatable workflow.

### Decision

Use independent bounded contexts under `src/project_name/pipelines/`. Keep each use case together;
reserve core for shared ports and infrastructure for concrete adapters. Inject dependencies from
an outer composition root when requested. Enforce direction and independence with import-linter.

Use uv instead of Poetry or direct pip workflows. Commit `uv.lock`; use `uv sync --locked` for normal
setup and development dependency groups. Target Python 3.12+, default to 3.12, and use Ruff, strict
mypy, pytest, pydantic-settings, and Polars.

### Consequences

A change normally loads one context and its tests. Cross-context behavior requires an explicit
shared contract. New contexts must join the independence contract. Dependency changes regenerate
the lockfile. Empty slices establish no behavior; negative probes verify that contracts reject
forbidden imports instead of relying on vacuously passing checks.

## ADR-0002: External memory and outer configuration

- Date: 2026-10-13
- Status: Accepted

AGENTS.md is the entry point; `.agent/` is the canonical memory bank. Native Cursor rules reference
directory rules rather than copying their contents. `.cursorrules` instructs legacy readers to
select rules; its frontmatter does not imply an automatic conditional loader in legacy clients.

Install `project_name` and `config` in the wheel. `config/settings.py` provides shared settings policy
without domain fields or credentials. Domain code receives typed values instead of reading runtime
environment directly. Ignore `.env` and datasets; scaffold checks require no external services.

## ADR-0003: Authorized implementation and top-level pipeline namespace

Date: 2026-10-13. Status: Accepted; updates the namespace in ADR-0001.
The user explicitly requested actual behavior and paths beneath src/pipelines. Install an independent
pipelines package beside project_name. Keep shared contracts/adapters in project_name and orchestration
outside slices. The GUI is an outer-facing editor; processing slices never load config themselves.

Track 1 consumes allowlisted metadata only. Track 2 uses ONNX semantic embeddings (FastEmbed), Chroma,
and SQLite. SQLite is the source of truth and maintains a durable outbox/pending state. Vector writes
are idempotent and replayable; ready-only SQL views and retrieval validation prevent partial/stale
content from being exposed. This is recoverable synchronization, not a distributed atomic transaction.

Use SQLite initially; PostgreSQL is an alternative future adapter, not a second unimplemented backend
presented as working. Use a configurable OpenAI-compatible HTTP LLM endpoint, supporting local Ollama
and hosted providers. Provider keys stay in environment secrets. GUI uses standard-library Tkinter;
containers run the headless backend and Streamlit, while native desktops run the GUI.

## ADR-0004: Read-only SQL defense and deployable consistency

Date: 2026-10-13. Status: Accepted.
SQLite authorizer source names alone cannot distinguish a real view from a CTE impersonating that
view. Parse SQL with SQLGlot, require one SELECT query, reject CTEs/non-curated tables, then enforce
SQLite authorizer and execution budgets. Include SQLGlot's dynamically loaded dialects in native
bundles. Metadata-only SQL never exposes Markdown, raw tables, or durable job payloads.

A vector index lost during restore cannot be repaired by skipping unchanged SQL revisions. Provide
an explicit force-reingestion path, tested by deleting/recreating a derived test collection. It
rebuilds from preserved raw exports; it does not delete mail or source files. Docker backup/restore
instructions distinguish durable state, derived vectors, and runtime processes.

## ADR-0005: Bounded Outlook exports, local catalogs, and explicit model installation

Date: 2026-10-13. Status: Accepted.
The user's updated macro removes PST creation after permission failures. Export independent Unicode
MSG backups without mail.Copy or source modification in copy mode; cleanup remains explicit and
confirmed. VBA uses Long counters and one-email completion markers, never a mailbox-wide dictionary,
JSONL stream, or master Markdown stream. Group each email with its attachments in a readable date/
subject/sender folder; preserve original Outlook folder information in metadata.

Python owns the export_catalog bounded context. Polars feeds at most 256 rows/4 MB per batch into
local DuckDB with a 128 MB memory budget and disk spill. Stream both master files and exclude all
body/content fields. Reject conflicting identities and path escapes. Multi-file publication uses a
journal plus retained backups; handled failures roll back and hard interruptions require validated,
retryable catalog-recover before consumption. Locks coordinate extraction/catalog/recovery/ingestion.
Keep databases local; synchronize completed Mail folders and master files to OneDrive/SharePoint.

Model discovery starts from the installed FastEmbed registry, then verifies live Hugging Face metadata.
Download/install are explicit actions, pin immutable revisions and validate actual CPU embeddings
before publishing portable receipts. Inference requires that receipt and never downloads implicitly.
Include the installed revision in Chroma/ingestion signatures and reject a running backend's cached
adapter if installation changes. Generative GGUF discovery/download is separate; validate files and
only import into an existing local Ollama when explicitly requested. GUI workers do network work off
Tk's main thread and apply configuration only through user selection/save. Never equate live metadata,
downloaded files, successful inference, or model answer quality.

## ADR-0006: VBA is a dumb physical-file extractor

Date: 2026-10-13. Status: Accepted; supersedes VBA sidecar/text responsibilities in ADR-0005.
The user explicitly requires Phase 1 to output only Unicode MSG archives, physical attachments
separated by file type, and internal idempotency state. Remove body access, Email.txt, metadata.json,
JSON helpers, relative RAG maps and Track 1/2 routing from VBA. Preserve export filters and readable
physical names; address/date/subject reads for filtering/naming do not establish a RAG schema.

Use Attachments/Type_<validated extension> or Other within each mail directory. Operational files are
export.lock, append-only Processed_Cache.log, and per-mail _state/source_id.txt plus complete.txt.
Never load the global log into memory; the per-mail checkpoint is authoritative. The raw-msg-v1
checkpoint includes the threshold and full source identity. Legacy completion markers cannot skip the
new format. Preserve copy-only defaults and explicitly confirmed cleanup after physical backups.

Python Phase 2 owns 100% of RAG modeling: native MSG parsing (extract-msg is a candidate), bodies,
headers/structured metadata, attachment association, Markdown/JSONL, DuckDB/Polars cataloging and
SQL/vector data. Native MSG parsing is the next implementation task; it is not present in the current
Python parser/catalog. The existing sidecar-based pipeline is retained for legacy exports only.
Do not claim that catalog/ingest already consumes fresh MSG-only exports. Use a fresh raw root when
migrating; no automatic removal of historical user artifacts is authorized by this refactor.
