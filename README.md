# Outlook Dual-Track RAG

Export Outlook mail into readable folders and let Python own the RAG data model: message parsing,
metadata, Markdown, JSONL, semantic retrieval, SQL/MCP, and analytics. Python 3.12+,
uv, Polars, DuckDB, SQLite, Chroma, FastEmbed, and Streamlit form the implementation. The project is
licensed under [MIT](LICENSE); downloaded models keep their own licenses.

Classic Outlook for Windows runs the VBA extractor. Python runs on Windows, Linux, and macOS.
The desktop configuration GUI runs on the host; Docker runs the backend, Chroma, and dashboard.

**Current integration boundary:** the VBA now exports only MSG files, physical attachments and its
operational checkpoints. Native Python MSG parsing is the next Phase 2 task; `extract-msg` is a
candidate, not an installed or implemented parser. The existing Python catalog consumes the earlier
`metadata.json` sidecars and cannot process a fresh MSG-only export. The extraction refactor does not
claim that the new format already works end to end.

## Dual-track architecture

```mermaid
flowchart LR
    O[Classic Outlook] --> V[VBA: physical-file extractor]
    V --> F[Mail folders: MSG and attachments by type]
    F --> MP[Python Phase 2: native MSG parsing - pending]
    MP --> C[Python catalog: bounded Polars batches and DuckDB]
    C --> I[Master_Index.jsonl and Master_Context.md]
    I --> T1[Track 1: metadata-only LLM]
    I --> P[Track 2: Office parsing and OCR]
    P --> E[Markdown, chunks and ONNX embeddings]
    E --> SQL[SQLite metadata and durable sync jobs]
    SQL --> VC[Chroma semantic index]
    SQL --> MCP[Read-only MCP SQL]
    VC --> T2[Track 2: deep RAG with citations]
    SQL --> A[Streamlit analytics]
    VC --> A
```

| Component | Responsibility |
| --- | --- |
| VBA / Phase 1 | Export Unicode MSG files and qualifying attachments; maintain only extraction state |
| Python / Phase 2 | Natively parse MSG bodies, sender/recipients and metadata; associate attachments; own every RAG record |
| Track 1 | Allowlisted sender, subject, date, IDs and filenames; bounded metadata sent to an LLM |
| Track 2 | Email text and attachments parsed into Markdown, embedded and retrieved with citations |
| DuckDB + Polars | Disk-backed export catalog and streamed global index generation |
| SQLite | Relational metadata, document revisions, synchronization jobs and analytics |
| Chroma | Semantic vectors for ready document revisions |
| MCP | Deterministic, bounded, read-only queries against curated metadata views |

All text extraction, metadata schemas, Track 1/Track 2 routing, JSONL and Markdown generation belong
to Python. VBA reads message properties only for physical filenames, date/privacy filters and stable
checkpoint identity; it never reads the body or writes a RAG sidecar. Track flags in an older INI do
not alter physical extraction.

Track 1 strips legacy body/content fields before sending data to the provider. MSG archives still
contain the full original message, so treat the export folder as sensitive. The freemail filter checks
sender and To/CC/BCC against exact domains and subdomains; it is not a general privacy classifier.

## Install and configure

Install [uv](https://docs.astral.sh/uv/getting-started/installation/) and Tesseract with the OCR language
packs you need. From the checkout:

```sh
uv sync --locked --all-extras --group build
uv run --no-sync outlook-rag init-config --output config.yaml
uv run --no-sync outlook-rag-config --config config.yaml
```

On this cloud workspace set `UV_CACHE_DIR=/workspace/.cache/uv` before uv commands because the home
cache is read-only. Windows users can run the same uv commands in PowerShell without that setting.
`init-config` preserves an existing configuration; use the GUI to edit it. Tk/Tcl must be available in
your Python installation. The base dependencies support configuration editing; model management needs
the `rag` extra. The web dashboard needs the `dashboard` extra.

The GUI saves validated `config.yaml` and a credential-free `extractor.ini`. Secrets belong in an
untracked `.env` or environment variables; see [.env.example](.env.example). `EW_LLM_API_KEY` is needed
only for providers requiring authentication. The HTTP backend requires a strong `EW_API_TOKEN`.
Default answer generation uses Ollama at `http://127.0.0.1:11434/v1`; start Ollama and install a model,
or configure an HTTPS OpenAI-compatible provider. Physical extraction and legacy catalog generation
require no LLM.

## Export from Outlook

Follow [the Outlook installation guide](docs/VBA_INSTALL_GUIDE.md) for the Developer tab, importing the
English [.bas module](src/pipelines/vba_extraction/Outlook_RAG_Extractor.bas), compiling it and running
`ExtractOutlookForRAG`. Select the generated INI when prompted. Start with a small copy-only folder.

Defaults process all dates and subfolders, exclude configured freemail domains and delete nothing.
No PST creation, Outlook item copying or item modification is required in copy mode. Cleanup requires
explicit opt-in, a complete Unicode MSG backup, and a default-No confirmation. The central GUI/config
also retains its Track 2 cleanup guard. Python never deletes mail. Outlook policies can still restrict
macros/programmatic access; the guide separates
those cases from filesystem permission failures.

Mail and its attachments remain together for browsing in Explorer, OneDrive or SharePoint:

```text
data/raw/
├── extractor.ini            # Written by the Python GUI, not VBA
├── Processed_Cache.log       # Append-only extraction history; never loaded as a global cache
├── Mail/
│   └── 2026/01/
│       └── 2026-01-15_09-30_Contract renewal_client_7A2B3C4D/
│           ├── Email.msg
│           ├── Attachments/
│           │   ├── Type_docx/001 Contract.docx
│           │   ├── Type_pdf/002 Terms.pdf
│           │   └── Other/003 attachment
│           └── _state/
│               ├── source_id.txt
│               └── complete.txt
└── export.lock              # Exists only while the VBA export is running
```

Readable date, subject and sender labels accompany a stable identity suffix. Attachment numbering
prevents duplicate names from overwriting each other. Extension folders group physical attachments
inside each email. No email text, metadata JSON, RAG map or master file is produced by VBA.
The macro checks path length, recursively creates directories, tests write access, and records failures
without aborting the entire mailbox. `Long` counters and per-email completion markers replace the
mailbox-sized in-memory cache. Attachment-threshold changes trigger a refreshed export; track selection
does not change raw extraction.

Prefer a short local path such as `C:\OutlookRAG`. After extraction finishes, copy the complete `Mail/`
snapshot into your approved OneDrive/SharePoint library. Keep live DuckDB, SQLite, Chroma
and model caches local; do not synchronize open databases. MSG opens in Outlook from Explorer;
SharePoint/OneDrive browser previews depend on their supported formats.

## Phase 2 integration to implement

Python must open the native `.msg` files, for example with `extract-msg`, to obtain the body, sender,
recipients, subject, dates and metadata. It must associate the adjacent type-grouped attachments,
enforce parser/path/size limits, and build its own typed records. Polars batches and a disk-backed
DuckDB catalog then feed streamed `Master_Index.jsonl` and `Master_Context.md` generation; ingestion
writes relational metadata and vectors through the existing SQLite/Chroma synchronization layer.
Track 1 receives allowlisted metadata only, and Track 2 processes content only when enabled in Python.
Operational `_state` files and `Processed_Cache.log` are not RAG metadata sources.

This MSG-native integration is not implemented in the current refactor. Do not run the existing
`catalog` command against a new MSG-only export expecting populated indexes: it requires legacy
sidecars and may otherwise publish an empty catalog. Retain raw files until Phase 2 support is added.

## Existing Python pipeline for legacy sidecar exports

The following commands remain supported **only for exports from the earlier VBA containing
`metadata.json` and content-file references**, or an already valid manifest with preserved content
files. They do not convert the new MSG-only format:

```sh
uv run --no-sync outlook-rag --config config.yaml catalog --batch-size 256
# Install the configured English embedding once; use model selection below for German mail.
uv run --no-sync outlook-rag --config config.yaml models download BAAI/bge-small-en-v1.5
uv run --no-sync outlook-rag --config config.yaml ingest --manifest data/raw/Master_Index.jsonl
uv run --no-sync outlook-rag --config config.yaml sync
uv run --no-sync outlook-rag --config config.yaml search "Vertragsverlängerung" --limit 5
uv run --no-sync outlook-rag --config config.yaml ask "Which contracts expire?" --track 2
uv run --no-sync outlook-rag --config config.yaml ask "Who sent these emails?" --track 1 --metadata-file data/raw/Master_Index.jsonl
uv run --no-sync outlook-rag-dashboard --config config.yaml
```

The legacy `catalog` scans complete per-email sidecars, validates contained paths, strips content
fields, loads bounded Polars batches into DuckDB, deduplicates identities and streams both master files. It supports
the previous per-email export layout too. Incomplete exports are counted and return a nonzero status;
invalid metadata/colliding identities leave the prior published catalog intact. Interrupted publication
blocks ingestion until repaired. See [catalog recovery](docs/CATALOG.md).

Supported parsing formats: `.docx`, `.xlsx`, `.pptx`, `.csv`, `.txt`, `.md`, `.jpg`/`.jpeg` and `.png`.
Earlier exports supplied `Email.txt` for bodies; the new VBA does not. Python does not yet parse
`.msg` or legacy binary Office formats.
Tesseract performs image OCR. Size, expanded ZIP and table-row limits are enforced; document macros
are never executed. Track 2 must be enabled to ingest content; raw VBA attachment extraction is
independent of track selection.

SQLite first records pending revisions and durable synchronization jobs. Chroma writes are replayable;
successful sync promotes revisions to ready. SQL views/retrieval exclude pending and stale revisions.
This provides recoverable consistency across stores. Rebuild a lost vector index with
`ingest --force --manifest ...` against preserved raw files. Changing filters does not purge previously
indexed data; retention is a separate operation.

## Discover, download and install models

The GUI has separate Hugging Face dialogs for embeddings and generative LLMs. Discovery fetches
metadata only; weights download only on explicit request. Network work runs in background workers.
Downloads have size budgets and use checked immutable revisions. See [model details](docs/MODELS.md).

```sh
uv run --no-sync outlook-rag models list --language de --online
uv run --no-sync outlook-rag models check sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
uv run --no-sync outlook-rag models download sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
uv run --no-sync outlook-rag llm-models list --search Qwen3 --limit 5
uv run --no-sync outlook-rag llm-models check Qwen/Qwen3-4B-GGUF
uv run --no-sync outlook-rag llm-models download Qwen/Qwen3-4B-GGUF --install-ollama --name outlook-rag
```

For German/mixed-language embeddings, supported multilingual MiniLM is a small CPU option
(approximately 0.22 GB in the SDK registry). BGE-small-en remains the English default; Jina's German
model is a larger alternative. Availability, licenses and actual files are checked live. Recommendations
describe resource tradeoffs without claiming benchmark superiority.

Embedding installation validates a real finite CPU vector before marking the cache ready. Pinned
revisions enter the Chroma/ingestion signature. Selecting a different embedding in the GUI creates a
new collection name; reingest raw data. Collections with earlier unpinned signatures also need a new
name after explicit model installation. GGUF downloads verify headers, sizes and available LFS SHA-256
checksums. Ollama import requires an installed, running Ollama service. After import save
`llm.model: outlook-rag` and the indicated local `/v1` URL in GUI/YAML.

## MCP and authenticated API

Configure your MCP client to execute `outlook-rag --config /absolute/path/config.yaml mcp` over stdio.
Tools expose schema, bounded read-only SQL and semantic search. Use only `mcp_emails`, `mcp_documents`
and `mcp_attachments`. SQL AST checks, SQLite authorizer, row limits and time budgets reject writes,
raw tables, CTE view impersonation, extension loading and file access.

```sh
uv run --no-sync outlook-rag --config config.yaml mcp
uv run --no-sync outlook-rag --config config.yaml serve --host 127.0.0.1 --port 8000
```

The API exposes `/health`, `/stats`, `/ingest`, `/search` and `/ask`. Protected requests require
`Authorization: Bearer <your token>`. Ingestion accepts manifests inside the raw root and respects
extraction/catalog locks. Streamlit shows email/document counts, physical vector counts, database
bytes, daily growth, top senders, file types and separate agent controls.

## Docker and standalone deployment

```sh
# First put a strong random EW_API_TOKEN in an untracked .env.
docker compose config --quiet
docker compose up --build -d
# Legacy sidecar exports only; the raw mount must be writable by its configured UID/GID.
docker compose run --rm --no-deps catalog
docker compose exec backend outlook-rag --config /app/config.yaml ingest --manifest /data/raw/Master_Index.jsonl
```

Digest-pinned images, private Chroma networking, non-root containers, read-only application filesystems,
persistent state/model volumes and health checks are included. Ports bind localhost. The catalog tool
has a writable raw mount and no network. On Linux set `EW_CATALOG_UID` and `EW_CATALOG_GID` to the
export directory owner if needed. Backend/dashboard raw mounts remain read-only. Use an authenticated
TLS reverse proxy for remote access.

```sh
uv sync --locked --all-extras --group build
uv run --no-sync python build.py --target all
```

PyInstaller creates GUI, backend/CLI and dashboard bundles under `artifacts/<platform>-<architecture>`.
Distribute the entire bundle, including `_internal`. Build natively on Windows, Linux and macOS;
PyInstaller does not cross-compile. CI builds all three OSes. Tk/Tcl, DuckDB, ONNX and required assets
are collected. Tesseract/language packs and a running LLM remain external prerequisites.
Signing/notarization need your release credentials. See [deployment and backups](docs/DEPLOYMENT.md).

Upgrading from the earlier export layout: use a fresh export directory. The macro does not purge old
`Email.txt`, `_rag/metadata.json`, master files or attachment folders, and does not reuse old RAG
completion markers. Existing packaged binaries/images retain the asset from their build; rebuild
before distributing this updated macro. In older YAML set `extraction.archive_pst: false`; the extractor
uses independent MSG backups. Choose `date_filter_mode: 0` (all), `1` (before), or `2` (from).

## Repository and verification

[AGENTS.md](AGENTS.md) and `.agent/` define the canonical shape, decisions and current evidence.
Independent slices live in `src/pipelines/`; shared records/ports and adapters in `src/project_name/`.
Composition roots wire components. Five import-linter contracts enforce independence and dependency
direction; there are no global models/services layers.

```sh
uv run --no-sync ruff check
uv run --no-sync ruff format --check
uv run --no-sync mypy
uv run --no-sync lint-imports
uv run --no-sync pytest
uv build
```

Tests use generated mail metadata/documents, real parsers/databases and failure recovery. They never
access or delete a mailbox. [.agent/status.md](.agent/status.md) distinguishes automated checks,
executed model/native/container tests, and external Outlook/OS/provider validation still required.
