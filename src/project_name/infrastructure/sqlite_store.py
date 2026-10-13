"""SQLite metadata, ready-only MCP views, and transactionally serialized vector replay."""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING, cast

import sqlglot
from sqlglot import exp

from project_name.core.records import (
    Chunk,
    Document,
    Email,
    JsonRow,
    JsonValue,
    RetrievedChunk,
    VectorHit,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from project_name.core.ports import VectorStore

SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_version(version INTEGER NOT NULL);
INSERT INTO schema_version SELECT 1 WHERE NOT EXISTS(SELECT 1 FROM schema_version);
CREATE TABLE IF NOT EXISTS emails(
 email_id TEXT PRIMARY KEY, sender TEXT NOT NULL, subject TEXT NOT NULL,
 received_at TEXT NOT NULL, msg_file TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS emails_sender ON emails(sender);
CREATE INDEX IF NOT EXISTS emails_received ON emails(received_at);
CREATE TABLE IF NOT EXISTS attachments(
 email_id TEXT NOT NULL REFERENCES emails(email_id), source_path TEXT NOT NULL,
 file_type TEXT NOT NULL, PRIMARY KEY(email_id, source_path)
);
CREATE TABLE IF NOT EXISTS documents(
 document_id TEXT PRIMARY KEY, email_id TEXT NOT NULL REFERENCES emails(email_id),
 source_path TEXT NOT NULL, file_type TEXT NOT NULL, content_hash TEXT NOT NULL,
 revision TEXT NOT NULL, markdown TEXT NOT NULL,
 state TEXT NOT NULL CHECK(state IN ('pending','ready')),
 updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
);
CREATE INDEX IF NOT EXISTS documents_state ON documents(state);
CREATE INDEX IF NOT EXISTS documents_email ON documents(email_id);
CREATE TABLE IF NOT EXISTS chunks(
 chunk_id TEXT PRIMARY KEY,
 document_id TEXT NOT NULL REFERENCES documents(document_id) ON DELETE CASCADE,
 revision TEXT NOT NULL, ordinal INTEGER NOT NULL, text TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS chunks_document ON chunks(document_id);
CREATE TABLE IF NOT EXISTS sync_jobs(
 document_id TEXT PRIMARY KEY REFERENCES documents(document_id) ON DELETE CASCADE,
 payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS analytics_snapshots(
 day TEXT PRIMARY KEY, documents INTEGER NOT NULL,
 emails INTEGER NOT NULL, sqlite_bytes INTEGER NOT NULL
);
CREATE VIEW IF NOT EXISTS mcp_emails AS
 SELECT e.* FROM emails e WHERE NOT EXISTS(
 SELECT 1 FROM documents d WHERE d.email_id=e.email_id AND d.state='pending');
CREATE VIEW IF NOT EXISTS mcp_documents AS
 SELECT document_id,email_id,source_path,file_type,content_hash,revision,updated_at
 FROM documents WHERE state='ready';
CREATE VIEW IF NOT EXISTS mcp_attachments AS
 SELECT a.* FROM attachments a JOIN mcp_emails e ON e.email_id=a.email_id;
"""
MCP_SCHEMA: JsonRow = {
    "mcp_emails": ["email_id", "sender", "subject", "received_at", "msg_file"],
    "mcp_documents": [
        "document_id",
        "email_id",
        "source_path",
        "file_type",
        "content_hash",
        "revision",
        "updated_at",
    ],
    "mcp_attachments": ["email_id", "source_path", "file_type"],
}
SAFE_FUNCTIONS = {
    "count",
    "sum",
    "total",
    "min",
    "max",
    "avg",
    "lower",
    "upper",
    "length",
    "coalesce",
    "ifnull",
    "nullif",
    "like",
    "glob",
    "substr",
    "substring",
    "date",
    "datetime",
    "strftime",
    "julianday",
    "round",
    "abs",
    "trim",
    "ltrim",
    "rtrim",
    "replace",
}


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.executescript(SCHEMA)
            if connection.execute("SELECT version FROM schema_version").fetchone()[0] != 1:
                raise RuntimeError("Unsupported SQLite schema version")

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=30000")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def upsert_email(self, email: Email) -> None:
        with self.connect() as connection:
            connection.execute(
                (
                    "INSERT INTO emails VALUES(?,?,?,?,?) ON CONFLICT(email_id) DO "
                    "UPDATE SET "
                    "sender=excluded.sender,subject=excluded.subject,received_at=excluded.received_at,msg_file=excluded.msg_file"
                ),
                (email.email_id, email.sender, email.subject, email.received_at, email.msg_file),
            )
            connection.execute("DELETE FROM attachments WHERE email_id=?", (email.email_id,))
            connection.executemany(
                "INSERT INTO attachments VALUES(?,?,?)",
                [(email.email_id, path, Path(path).suffix.lower()) for path in email.attachments],
            )

    def revision(self, document_id: str) -> str | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT revision FROM documents WHERE document_id=? AND state='ready'",
                (document_id,),
            ).fetchone()
            return str(row[0]) if row else None

    def stage(
        self, document: Document, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        payload = json.dumps(
            {
                "document": asdict(document),
                "chunks": [asdict(chunk) for chunk in chunks],
                "embeddings": [list(vector) for vector in embeddings],
            },
            allow_nan=False,
        )
        with self.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                (
                    "INSERT INTO "
                    """
                    documents(document_id,
                    email_id,
                    source_path,
                    file_type,
                    content_hash,
                    revision,
                    markdown,
                    state) VALUES(?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    ?,
                    'pending') ON CONFLICT(document_id) DO UPDATE SET email_id=excluded.email_id,
                    source_path=excluded.source_path,
                    file_type=excluded.file_type,
                    content_hash=excluded.content_hash,
                    revision=excluded.revision,
                    markdown=excluded.markdown,
                    state='pending',
                    updated_at=strftime('%Y-%m-%dT%H:%M:%fZ',
                    'now')
                    """
                ),
                (
                    document.document_id,
                    document.email_id,
                    document.source_path,
                    document.file_type,
                    document.content_hash,
                    document.revision,
                    document.markdown,
                ),
            )
            connection.execute("DELETE FROM chunks WHERE document_id=?", (document.document_id,))
            connection.executemany(
                "INSERT INTO chunks VALUES(?,?,?,?,?)",
                [
                    (chunk.chunk_id, chunk.document_id, chunk.revision, chunk.ordinal, chunk.text)
                    for chunk in chunks
                ],
            )
            connection.execute(
                (
                    "INSERT INTO sync_jobs VALUES(?,?) ON CONFLICT(document_id) DO "
                    "UPDATE SET payload=excluded.payload"
                ),
                (document.document_id, payload),
            )

    def synchronize(self, vectors: VectorStore) -> int:
        count = 0
        # Hold a SQLite writer lock during each vector replacement: concurrent replay cannot mark
        # Older revisions cannot become ready. A crash rolls SQL back; vector writes can replay.
        while True:
            with self.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                row = connection.execute(
                    "SELECT document_id,payload FROM sync_jobs ORDER BY document_id LIMIT 1"
                ).fetchone()
                if row is None:
                    return count
                payload = json.loads(row["payload"])
                document = Document(**payload["document"])
                chunks = [Chunk(**chunk) for chunk in payload["chunks"]]
                vectors.replace_document(document, chunks, payload["embeddings"])
                connection.execute(
                    "UPDATE documents SET state='ready' WHERE document_id=? AND revision=?",
                    (document.document_id, document.revision),
                )
                connection.execute(
                    "DELETE FROM sync_jobs WHERE document_id=?", (document.document_id,)
                )
            count += 1

    def resolve_hit(self, hit: VectorHit) -> RetrievedChunk | None:
        with self.connect() as connection:
            row = connection.execute(
                (
                    "SELECT c.*,d.source_path FROM chunks c JOIN documents d ON "
                    "d.document_id=c.document_id WHERE c.chunk_id=? AND "
                    "c.revision=d.revision AND d.state='ready'"
                ),
                (hit.chunk_id,),
            ).fetchone()
            if row is None:
                return None
            return RetrievedChunk(
                Chunk(
                    row["chunk_id"],
                    row["document_id"],
                    row["revision"],
                    row["ordinal"],
                    row["text"],
                ),
                row["source_path"],
                hit.distance,
            )

    def query(
        self, sql: str, parameters: Sequence[JsonValue] = (), limit: int = 200
    ) -> list[JsonRow]:
        if not 1 <= limit <= 1000 or len(sql) > 16000:
            raise ValueError("SQL is limited to 16 KB and 1-1000 rows")
        if any(isinstance(value, (dict, list)) for value in parameters):
            raise ValueError("SQL parameters must be scalar")
        statements = sqlglot.parse(sql, read="sqlite")
        if len(statements) != 1 or not isinstance(statements[0], exp.Query):
            raise ValueError("Exactly one SELECT query is supported")
        statement = statements[0]
        if statement.find(exp.With) is not None:
            raise ValueError("CTEs are disabled to prevent curated-view impersonation")
        for table in statement.find_all(exp.Table):
            if table.name not in MCP_SCHEMA or table.db not in {"", "main"}:
                raise ValueError("Queries may only read curated MCP views")
        started = time.monotonic()
        connection = sqlite3.connect(f"{self.path.as_uri()}?mode=ro", uri=True, timeout=3)
        connection.row_factory = sqlite3.Row

        def authorize(
            action: int,
            arg1: str | None,
            arg2: str | None,
            database: str | None,
            source: str | None,
        ) -> int:
            if action == sqlite3.SQLITE_SELECT:
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_READ and database == "main":  # noqa: SIM102
                if arg1 in MCP_SCHEMA or (
                    source in MCP_SCHEMA and arg1 in {"emails", "documents", "attachments"}
                ):
                    return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION and str(arg2).lower() in SAFE_FUNCTIONS:
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        connection.set_authorizer(authorize)
        connection.set_progress_handler(lambda: int(time.monotonic() - started > 3), 1000)
        try:
            cursor = connection.execute(sql, tuple(parameters))
            if cursor.description is None:
                raise ValueError("Only read-only queries are supported")
            return [cast("JsonRow", dict(row)) for row in cursor.fetchmany(limit)]
        finally:
            connection.close()

    def statistics(self) -> JsonRow:
        with self.connect() as connection:

            def scalar(sql: str) -> int:
                return int(connection.execute(sql).fetchone()[0])

            def rows(sql: str) -> list[JsonValue]:
                return [cast("JsonValue", dict(row)) for row in connection.execute(sql)]

            size = sum(
                path.stat().st_size
                for path in [self.path, Path(str(self.path) + "-wal")]
                if path.exists()
            )
            connection.execute(
                "INSERT INTO analytics_snapshots VALUES(date('now'),?,?,?) "
                "ON CONFLICT(day) DO UPDATE SET documents=excluded.documents,"
                "emails=excluded.emails,sqlite_bytes=excluded.sqlite_bytes",
                (
                    scalar("SELECT count(*) FROM documents WHERE state='ready'"),
                    scalar("SELECT count(*) FROM emails"),
                    size,
                ),
            )
            return {
                "email_count": scalar("SELECT count(*) FROM emails"),
                "document_count": scalar("SELECT count(*) FROM documents WHERE state='ready'"),
                "pending_count": scalar("SELECT count(*) FROM sync_jobs"),
                "chunk_count": scalar(
                    "SELECT count(*) FROM chunks c JOIN documents d ON "
                    "d.document_id=c.document_id WHERE d.state='ready'"
                ),
                "sqlite_bytes": size,
                "top_senders": rows(
                    "SELECT sender,count(*) AS count FROM emails GROUP BY sender "
                    "ORDER BY count DESC,sender LIMIT 20"
                ),
                "file_types": rows(
                    "SELECT file_type,count(*) AS count FROM documents WHERE "
                    "state='ready' GROUP BY file_type ORDER BY count DESC"
                ),
                "email_volumes": rows(
                    "SELECT substr(received_at,1,10) AS day,count(*) AS count FROM "
                    "emails GROUP BY day ORDER BY day"
                ),
                "growth": rows("SELECT * FROM analytics_snapshots ORDER BY day"),
            }
