"""Build metadata-only master files without collecting an entire mailbox in memory."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PureWindowsPath
from typing import TYPE_CHECKING, cast

import duckdb
import polars as pl

from project_name.core.records import Email

if TYPE_CHECKING:
    from collections.abc import Iterator

    from duckdb import DuckDBPyConnection

    from project_name.core.records import JsonRow, JsonValue

_MAX_METADATA_BYTES = 2_000_000
_MAX_BATCH_BYTES = 4_000_000
_COLUMNS = (
    "email_id",
    "sender",
    "subject",
    "date",
    "msg_file",
    "body_file",
    "extracted_attachments",
    "source_folder",
    "source_key",
    "metadata_hash",
    "sidecar_file",
)
_SCHEMA = {
    key: pl.List(pl.String) if key == "extracted_attachments" else pl.String for key in _COLUMNS
}


class CatalogError(ValueError):
    """An export cannot be safely cataloged; existing published outputs remain usable."""


@dataclass(frozen=True)
class CatalogReport:
    records: int
    emails: int
    duplicates: int
    incomplete: int
    max_batch_rows: int
    index_file: Path
    context_file: Path
    database_file: Path
    generation_file: Path
    generation: str

    @property
    def complete(self) -> bool:
        return self.incomplete == 0


@dataclass(frozen=True)
class CatalogRecoveryReport:
    recovered: bool
    restored: int
    removed: int
    generation_file: Path


def _metadata_paths(directory: Path, *, depth: int = 0) -> Iterator[Path]:
    """Keep only one directory iterator per depth; never collect every export path."""
    if depth > 64:
        raise CatalogError("Export directory nesting exceeds the supported depth of 64")
    with os.scandir(directory) as entries:
        for entry in entries:
            if entry.is_symlink():
                continue
            path = Path(entry.path)
            if entry.is_dir(follow_symlinks=False):
                yield from _metadata_paths(path, depth=depth + 1)
            elif entry.is_file(follow_symlinks=False) and entry.name == "metadata.json":
                yield path


def _read_bounded(path: Path, limit: int) -> str:
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise CatalogError(f"{path.name} exceeds the maximum metadata size")
    # Older exports sometimes use FSO UTF-16; current VBA emits UTF-8.
    encoding = "utf-16" if raw.startswith((b"\xff\xfe", b"\xfe\xff")) else "utf-8-sig"
    return raw.decode(encoding)


def _relative_artifact(root: Path, value: str) -> str:
    normalized = value.replace("\\", "/")
    if not value:
        return ""
    if PureWindowsPath(value).drive or normalized.startswith("/") or "\x00" in value:
        raise CatalogError("Artifact paths must be relative to the export directory")
    unresolved = root / normalized
    candidate = unresolved.resolve()
    if not candidate.is_relative_to(root):
        raise CatalogError("Artifact path escapes the export directory")
    if any(part.is_symlink() for part in (unresolved, *unresolved.parents) if part != root):
        raise CatalogError("Artifact paths must not traverse symbolic links")
    if not candidate.is_file():
        raise CatalogError(f"Export artifact is missing: {normalized}")
    return candidate.relative_to(root).as_posix()


def _text_field(payload: JsonRow, name: str, default: str = "") -> str:
    value = payload.get(name, default)
    if not isinstance(value, str):
        raise CatalogError(f"{name} must be a string")
    return value


def _read_row(root: Path, sidecar: Path) -> tuple[JsonRow, int] | None:
    completion = sidecar.parent / "complete.txt"
    if completion.is_symlink():
        raise CatalogError("Export completion marker must not be a symbolic link")
    if sidecar.parent.name == "_rag" and not completion.is_file():
        return None
    payload = json.loads(_read_bounded(sidecar, _MAX_METADATA_BYTES))
    if not isinstance(payload, dict):
        raise CatalogError("Metadata must contain a JSON object")
    row = cast("JsonRow", payload)
    version = row.get("schema_version", 1)
    if not isinstance(version, int) or isinstance(version, bool) or not 1 <= version <= 3:
        raise CatalogError("Unsupported metadata schema_version; expected 1, 2, or 3")
    if version >= 2 and not completion.is_file():
        return None
    email = Email.from_mapping(row)
    metadata = email.metadata()
    metadata["msg_file"] = _relative_artifact(root, email.msg_file)
    metadata["body_file"] = _relative_artifact(root, email.body_file)
    metadata["extracted_attachments"] = [
        _relative_artifact(root, path) for path in email.attachments
    ]
    metadata["source_folder"] = _text_field(
        row, "outlook_folder", _text_field(row, "source_folder")
    )
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True).encode("utf-8")
    metadata["metadata_hash"] = hashlib.sha256(encoded).hexdigest()
    source_key = _text_field(row, "source_key", _text_field(row, "source_id"))
    source_file = sidecar.parent / "source_id.txt"
    if not source_key and source_file.is_file():
        if source_file.is_symlink():
            raise CatalogError("Source identity must not be a symbolic link")
        source_key = _read_bounded(source_file, 65536).strip()
    metadata["source_key"] = source_key
    metadata["sidecar_file"] = sidecar.relative_to(root).as_posix()
    return metadata, len(encoded) + len(source_key.encode("utf-8")) + len(str(sidecar))


def _write_batch(connection: DuckDBPyConnection, rows: list[JsonRow], batch_file: Path) -> None:
    frame = pl.DataFrame(rows, schema=_SCHEMA)
    source_conflicts = (
        frame.filter(pl.col("source_key") != "")
        .group_by("email_id")
        .agg(pl.col("source_key").n_unique().alias("count"))
        .filter(pl.col("count") > 1)
    )
    metadata_conflicts = (
        frame.group_by("email_id")
        .agg(pl.col("metadata_hash").n_unique().alias("count"))
        .filter(pl.col("count") > 1)
    )
    if source_conflicts.height or metadata_conflicts.height:
        conflicts = source_conflicts if source_conflicts.height else metadata_conflicts
        raise CatalogError(f"Conflicting export identity: {conflicts.item(0, 'email_id')}")
    # Equal records are collapsed deterministically. Preserve a known source identity even
    # when an older duplicate has no source_id. Native Parquet avoids requiring PyArrow.
    aggregations = [
        pl.col(key).max()
        if key == "source_key"
        else pl.col(key).min()
        if key == "sidecar_file"
        else pl.col(key).first()
        for key in _COLUMNS
        if key != "email_id"
    ]
    frame.group_by("email_id").agg(aggregations).select(_COLUMNS).write_parquet(batch_file)
    conflict = connection.execute(
        """
        SELECT incoming.email_id FROM read_parquet(?) incoming JOIN emails existing
        USING (email_id) WHERE incoming.metadata_hash != existing.metadata_hash
          OR (incoming.source_key != '' AND existing.source_key != ''
              AND incoming.source_key != existing.source_key) LIMIT 1
        """,
        [str(batch_file)],
    ).fetchone()
    if conflict:
        raise CatalogError(f"Conflicting export identity: {conflict[0]}")
    connection.execute(
        """
        INSERT INTO emails SELECT * FROM read_parquet(?)
        ON CONFLICT(email_id) DO UPDATE SET
          source_key = greatest(emails.source_key, excluded.source_key),
          sidecar_file = least(emails.sidecar_file, excluded.sidecar_file)
        """,
        [str(batch_file)],
    )


def _write_master_files(
    connection: DuckDBPyConnection,
    index_file: Path,
    context_file: Path,
    batch_size: int,
    *,
    incomplete: int,
) -> int:
    result = connection.execute(
        """
        SELECT email_id, sender, subject, date, msg_file, body_file,
               extracted_attachments, source_folder
        FROM emails ORDER BY date, email_id
        """
    )
    count = 0
    with (
        index_file.open("w", encoding="utf-8", newline="\n") as index,
        context_file.open("w", encoding="utf-8", newline="\n") as context,
    ):
        context.write(
            "# Outlook metadata context\n\n"
            "Generated by Python from completed exports. Email bodies and attachment "
            "contents are excluded. File paths identify local artifacts for Track 2.\n"
        )
        if incomplete:
            context.write(
                f"\n**Partial export: {incomplete} unfinished email export(s) were excluded.**\n"
            )
        while batch := result.fetchmany(batch_size):
            for values in batch:
                metadata: JsonRow = {
                    "schema_version": 3,
                    "doc_type": "email_metadata",
                    **dict(zip(_COLUMNS[:8], cast("tuple[JsonValue, ...]", values), strict=True)),
                }
                line = json.dumps(metadata, ensure_ascii=False)
                index.write(line + "\n")
                count += 1
                context.write(f"\n## Email {count}\n\n```json\n{line}\n```\n")
        for stream in [index, context]:
            stream.flush()
            os.fsync(stream.fileno())
    return count


def _restore_outputs(entries: Iterator[tuple[Path, Path | None]]) -> tuple[int, int]:
    """Retain every backup until all restores succeed, allowing an interrupted retry."""
    restored = removed = 0
    for destination, backup in entries:
        if backup is None:
            if destination.exists():
                destination.unlink()
                removed += 1
            continue
        with tempfile.NamedTemporaryFile(
            prefix=f".{destination.name}.recover-",
            suffix=".tmp",
            dir=destination.parent,
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
        try:
            shutil.copy2(backup, temporary)
            with temporary.open("rb") as saved:
                os.fsync(saved.fileno())
            temporary.replace(destination)
            restored += 1
        finally:
            temporary.unlink(missing_ok=True)
    return restored, removed


def _publish(staged: tuple[tuple[Path, Path], ...], publication_marker: Path) -> None:
    """Rollback handled failures; a journal blocks consumers after a hard interruption."""
    backups: list[tuple[Path, Path | None]] = []
    replaced: list[tuple[Path, Path | None]] = []
    cleanup_backups = False
    journal_owned = False
    backup: Path | None
    try:
        for _, destination in staged:
            if destination.is_symlink():
                raise CatalogError("Published catalog outputs must not be symbolic links")
            backup = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.bak")
            if destination.exists():
                try:
                    backup.hardlink_to(destination)
                except OSError:
                    shutil.copyfile(destination, backup)
                backups.append((destination, backup))
            else:
                backups.append((destination, None))
        if publication_marker.exists() or publication_marker.is_symlink():
            raise CatalogError("A catalog publication journal already exists")
        journal_file = staged[0][0].parent / "catalog_publication.json"
        with journal_file.open("x", encoding="utf-8") as journal:
            json.dump(
                {
                    "state": "publishing",
                    "backups": [
                        {"destination": str(destination), "backup": str(backup) if backup else None}
                        for destination, backup in backups
                    ],
                },
                journal,
            )
            journal.flush()
            os.fsync(journal.fileno())
        journal_owned = True
        journal_file.replace(publication_marker)
        for (source, destination), (_, backup) in zip(staged, backups, strict=True):
            replaced.append((destination, backup))
            source.replace(destination)
    except BaseException:
        _restore_outputs(reversed(replaced))
        if journal_owned:
            publication_marker.unlink(missing_ok=True)
        cleanup_backups = True
        raise
    else:
        publication_marker.unlink()
        cleanup_backups = True
    finally:
        if cleanup_backups:
            for _, backup in backups:
                if backup is not None:
                    backup.unlink(missing_ok=True)


def _recovery_entries(root: Path, publication_marker: Path) -> list[tuple[Path, Path | None]]:
    """Validate the complete journal before any file can be restored or deleted."""
    if publication_marker.is_symlink():
        raise CatalogError("The publication journal must not be a symbolic link")
    try:
        payload = json.loads(_read_bounded(publication_marker, 65536))
    except (ValueError, OSError) as exc:
        raise CatalogError(f"Cannot read the catalog publication journal: {exc}") from exc
    if not isinstance(payload, dict) or set(payload) != {"state", "backups"}:
        raise CatalogError("Invalid catalog publication journal")
    if payload.get("state") != "publishing":
        raise CatalogError("Unsupported catalog publication state")
    raw_entries = payload.get("backups")
    if not isinstance(raw_entries, list) or len(raw_entries) != 4:
        raise CatalogError("Publication journal must list exactly four catalog outputs")
    expected = {
        root / "Master_Index.jsonl",
        root / "Master_Context.md",
        root / "_rag/catalog.duckdb",
        root / "_rag/catalog_generation.json",
    }
    seen: set[Path] = set()
    entries: list[tuple[Path, Path | None]] = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or set(entry) != {"destination", "backup"}:
            raise CatalogError("Invalid publication journal entry")
        value = entry.get("destination")
        if not isinstance(value, str) or "\x00" in value:
            raise CatalogError("Invalid catalog recovery destination")
        destination = Path(value)
        if destination not in expected or destination in seen:
            raise CatalogError("Recovery destination is outside the exact catalog output allowlist")
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise CatalogError("Recovery destinations must be regular files without symbolic links")
        seen.add(destination)
        backup_value = entry.get("backup")
        backup: Path | None = None
        if backup_value is not None:
            if not isinstance(backup_value, str) or "\x00" in backup_value:
                raise CatalogError("Invalid catalog recovery backup")
            candidate = Path(backup_value)
            prefix = f".{destination.name}."
            name = candidate.name
            identity = (
                name[len(prefix) : -4] if name.startswith(prefix) and name.endswith(".bak") else ""
            )
            if (
                candidate.parent != destination.parent
                or len(identity) != 32
                or any(character not in "0123456789abcdef" for character in identity)
            ):
                raise CatalogError("Recovery backup must be a generated sibling catalog backup")
            if candidate.is_symlink() or not candidate.is_file():
                raise CatalogError("Recovery backup is missing or is a symbolic link")
            backup = candidate
        entries.append((destination, backup))
    if seen != expected:
        raise CatalogError("Publication journal omits a required catalog output")
    return entries


def recover_catalog(raw_directory: Path) -> CatalogRecoveryReport:
    """Restore the last published generation after an interrupted multi-file publication."""
    if raw_directory.is_symlink():
        raise CatalogError("The Outlook export directory must not be a symbolic link")
    root = raw_directory.resolve()
    if not root.is_dir():
        raise CatalogError("The Outlook export directory does not exist")
    technical = root / "_rag"
    if technical.is_symlink():
        raise CatalogError("The catalog directory must not be a symbolic link")
    if (root / "export.lock").exists():
        raise CatalogError("Outlook export is still running (export.lock exists)")
    lock = technical / "catalog.lock"
    if lock.exists() or lock.is_symlink():
        raise CatalogError("Catalog lock exists; check the process before removing a stale lock")
    publication_marker = technical / "catalog_publication.json"
    generation_file = technical / "catalog_generation.json"
    if not publication_marker.exists() and not publication_marker.is_symlink():
        return CatalogRecoveryReport(False, 0, 0, generation_file)
    entries = _recovery_entries(root, publication_marker)
    try:
        lock_stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise CatalogError("Catalog started while recovery was acquiring the lock") from exc
    try:
        with lock_stream:
            lock_stream.write(f"{os.getpid()}\n")
        if (root / "export.lock").exists():
            raise CatalogError("Outlook export started while recovery was acquiring the lock")
        restored, removed = _restore_outputs(iter(entries))
        # Keep the journal and every original backup until all replacements have completed.
        publication_marker.unlink()
        for _, backup in entries:
            if backup is not None:
                backup.unlink(missing_ok=True)
        return CatalogRecoveryReport(True, restored, removed, generation_file)
    finally:
        lock.unlink(missing_ok=True)


def build_catalog(raw_directory: Path, *, batch_size: int = 256) -> CatalogReport:
    """Rebuild DuckDB, JSONL, and Markdown in bounded batches; fail on invalid exports."""
    if not 1 <= batch_size <= 256:
        raise CatalogError("Catalog batch_size must be between 1 and 256")
    if raw_directory.is_symlink():
        raise CatalogError("The Outlook export directory must not be a symbolic link")
    root = raw_directory.resolve()
    if not root.is_dir():
        raise CatalogError("The Outlook export directory does not exist")
    if (root / "export.lock").exists():
        raise CatalogError("Outlook export is still running (export.lock exists)")
    technical = root / "_rag"
    if technical.is_symlink():
        raise CatalogError("The catalog directory must not be a symbolic link")
    technical.mkdir(exist_ok=True)
    publication_marker = technical / "catalog_publication.json"
    if publication_marker.exists():
        raise CatalogError("Interrupted catalog publication requires recovery before indexing")
    lock = technical / "catalog.lock"
    try:
        lock_stream = lock.open("x", encoding="utf-8")
    except FileExistsError as exc:
        raise CatalogError(
            "Catalog is already running (or catalog.lock needs stale-lock recovery)"
        ) from exc
    try:
        work = Path(tempfile.mkdtemp(prefix=".catalog-", dir=technical))
    except BaseException:
        lock_stream.close()
        lock.unlink(missing_ok=True)
        raise
    generation = uuid.uuid4().hex
    database = work / "catalog.duckdb"
    connection: DuckDBPyConnection | None = None
    records = incomplete = max_batch_rows = 0
    try:
        with lock_stream:
            lock_stream.write(f"{os.getpid()}\n")
        if (root / "export.lock").exists():
            raise CatalogError("Outlook export started while the catalog lock was acquired")
        connection = duckdb.connect(
            str(database),
            config={"memory_limit": "128MB", "threads": "2", "temp_directory": str(work / "spill")},
        )
        connection.execute(
            """
            CREATE TABLE emails (
              email_id VARCHAR PRIMARY KEY, sender VARCHAR NOT NULL, subject VARCHAR NOT NULL,
              date VARCHAR NOT NULL, msg_file VARCHAR NOT NULL, body_file VARCHAR NOT NULL,
              extracted_attachments VARCHAR[] NOT NULL, source_folder VARCHAR NOT NULL,
              source_key VARCHAR NOT NULL, metadata_hash VARCHAR NOT NULL,
              sidecar_file VARCHAR NOT NULL
            )
            """
        )
        batch: list[JsonRow] = []
        batch_bytes = 0
        batch_file = work / "batch.parquet"
        for sidecar in _metadata_paths(root):
            try:
                record = _read_row(root, sidecar)
                if record is None:
                    incomplete += 1
                    continue
                row, row_bytes = record
                if batch and (
                    len(batch) >= batch_size or batch_bytes + row_bytes > _MAX_BATCH_BYTES
                ):
                    max_batch_rows = max(max_batch_rows, len(batch))
                    _write_batch(connection, batch, batch_file)
                    batch.clear()
                    batch_bytes = 0
                batch.append(row)
                batch_bytes += row_bytes
                records += 1
            except (ValueError, OSError) as exc:
                raise CatalogError(f"Invalid export {sidecar.relative_to(root)}: {exc}") from exc
        if batch:
            max_batch_rows = max(max_batch_rows, len(batch))
            _write_batch(connection, batch, batch_file)
        index = work / "Master_Index.jsonl"
        context = work / "Master_Context.md"
        emails = _write_master_files(connection, index, context, batch_size, incomplete=incomplete)
        connection.execute(
            "CREATE VIEW metadata_emails AS SELECT email_id, sender, subject, date, msg_file, "
            "extracted_attachments, source_folder FROM emails"
        )
        connection.close()
        connection = None
        if (root / "export.lock").exists():
            raise CatalogError(
                "Outlook export started while cataloging; outputs were not published"
            )
        marker = work / "catalog_generation.json"
        marker.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "generation": generation,
                    "created_at": datetime.now(UTC).isoformat(),
                    "records": records,
                    "emails": emails,
                    "duplicates": records - emails,
                    "incomplete": incomplete,
                    "complete": incomplete == 0,
                    "index_file": "Master_Index.jsonl",
                    "context_file": "Master_Context.md",
                    "database_file": "_rag/catalog.duckdb",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        index_output = root / index.name
        context_output = root / context.name
        database_output = technical / database.name
        generation_output = technical / marker.name
        _publish(
            (
                (database, database_output),
                (index, index_output),
                (context, context_output),
                (marker, generation_output),
            ),
            publication_marker,
        )
        return CatalogReport(
            records,
            emails,
            records - emails,
            incomplete,
            max_batch_rows,
            index_output,
            context_output,
            database_output,
            generation_output,
            generation,
        )
    finally:
        if connection is not None:
            connection.close()
        shutil.rmtree(work)
        lock.unlink(missing_ok=True)
