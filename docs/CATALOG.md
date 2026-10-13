# Legacy export catalogs and recovery

**Compatibility:** this catalog supports exports produced by the earlier sidecar-based VBA. The
current strict extractor writes only MSG files, physical attachments and operational state; it
does not write `metadata.json` or text. Native Python MSG parsing and its catalog integration are
the next Phase 2 task. Do not use these commands as a conversion workflow for a fresh MSG-only
export: without sidecars, the current catalog can publish an empty generation.

For an existing legacy export with completed per-email metadata and content files, Python owns all
mailbox-wide indexes. Run `outlook-rag --config config.yaml catalog --batch-size 256` after export finishes.
The raw directory comes from extraction.output_directory, resolved relative to the YAML file.

Polars validates/deduplicates batches, writes a temporary Parquet batch, and feeds a disk-backed
DuckDB catalog. The default batch contains at most 256 rows; batches also have a 4 MB byte budget.
DuckDB has a 128 MB memory limit and can spill intermediate operations to its local staging directory.
Index output uses fetchmany and streamed writes; neither all filenames nor all emails are held in a
Python list/dictionary. Only the current directory iterators and batch remain in Python memory.

Published outputs are:

- Master_Index.jsonl: UTF-8 metadata, relative content-file pointers, and original Outlook folder.
- Master_Context.md: the same metadata in readable JSON sections; no email body/attachment contents.
- _rag/catalog.duckdb: persistent emails table and metadata_emails view.
- _rag/catalog_generation.json: generation ID, counts, date and completeness state.

Track 1 strips body_file and other non-allowlisted fields again before constructing a prompt. DuckDB
is the export catalog; SQLite remains the authoritative application metadata/outbox/MCP database.
Keep open DuckDB and SQLite files outside synchronized OneDrive/SharePoint libraries.

## Completion and duplicate handling

Legacy email directories require _rag/complete.txt before their sidecar is read. Incomplete exports are
counted and excluded, the Markdown contains a visible warning, and the CLI returns status 1. Restore
incomplete legacy artifacts from a verified backup before rebuilding; the current MSG-only macro
cannot regenerate their metadata sidecars. A missing/invalid referenced artifact,
malformed metadata, path escape, or conflicting identity aborts publication and preserves the previous
catalog. Symbolic-link traversal is rejected. The old per-email layout and UTF-16 sidecars are supported.

Equal duplicate records collapse into one email. A shared email ID with different source identity or
different metadata is an error; the catalog never chooses an arbitrary copy. When moving from the old
extension-separated layout, use a fresh export root to avoid mixing different paths for the same mail.
Existing global UTF-16 master files from the supplied older macro are not a source for this catalog.
Only compatible per-email sidecars are inputs. Reexporting with the current MSG-only macro does not
restore this legacy format; preserve older exports separately.

## New MSG-only extraction contract

VBA saves `Mail/YYYY/MM/<readable-mail-folder>/Email.msg` plus
`Attachments/Type_<extension>/...` (or `Other/`) and `_state/source_id.txt`/`complete.txt`. Root state
is `export.lock` and append-only `Processed_Cache.log`. These are operational files, not email
metadata sources. A fresh root is required to avoid retaining older sidecars and text files.

Python Phase 2 must parse MSG bodies, sender/recipients and metadata natively, for example through
`extract-msg`, associate physical attachments, and create all RAG records. It will connect those
records to bounded Polars/DuckDB batches and streamed JSONL/Markdown publication. Track routing and
metadata-only privacy remain Python responsibilities. Native MSG parsing is not implemented in the
current refactor; the disk-backed generation/recovery machinery below remains legacy-only for now.

## Locks and interrupted publication

VBA owns export.lock; catalog/recovery own _rag/catalog.lock. Each writer checks the other writer's
lock before and after acquiring its own. Export, catalog and ingestion must not overlap. The
publication journal _rag/catalog_publication.json blocks export/ingestion when a multi-file replacement
was interrupted. Handled errors restore prior outputs; a killed process leaves recoverable backups.

To recover a hard interruption:

1. Stop only the export/catalog process you started and confirm it is no longer running. Keep a copy
   of the raw directory and journal/backups if investigating a production failure.
2. Remove a stale export.lock or _rag/catalog.lock only after that check. Neither tool guesses that
   a lock is stale. Do not delete the publication journal or its .bak files.
3. Run `outlook-rag --config config.yaml catalog-recover`. It validates all expected destinations and
   backups before writing, restores the previous generation, and removes the journal after success.
4. Run catalog again, check complete=true/counts, then ingest the regenerated manifest.

Recovery keeps backups until all restorations succeed and can be retried if it is itself interrupted.
It refuses unexpected destinations, symbolic links, duplicate entries, or missing backups. Do not
manually point a journal at another database or arbitrary file. A no-journal recovery is a no-op.

The generation marker is a publication record, not a mailbox retention policy. Changing filters or
deleting raw exports does not purge previously ingested SQLite/Chroma data.
