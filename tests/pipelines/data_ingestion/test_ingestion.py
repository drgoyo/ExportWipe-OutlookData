"""Real SQLite/Chroma consistency, revision replacement, failure replay, and containment."""

import json
import sqlite3
from collections.abc import Sequence
from pathlib import Path

import pytest

from pipelines.data_ingestion.ingest import Ingestor, resolve_export_path
from pipelines.document_parsing.parser import MarkdownParser
from pipelines.rag_agents.agents import DeepRAGAgent
from project_name.core.records import Chunk, Document, IngestionOptions, VectorHit
from project_name.infrastructure.sqlite_store import SQLiteStore
from project_name.infrastructure.vector_store import ChromaStore
from tests.support import RecordingLLM, TestEmbedder


class FailAfterWrite:
    def __init__(self, real: ChromaStore) -> None:
        self.real = real

    def replace_document(
        self, document: Document, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        self.real.replace_document(document, chunks, embeddings)
        raise RuntimeError("Simulated interruption after Chroma write")

    def search(self, embedding: Sequence[float], limit: int) -> list[VectorHit]:
        return self.real.search(embedding, limit)

    def count(self) -> int:
        return self.real.count()


def make_export(root: Path) -> Path:
    root.mkdir()
    (root / "body.txt").write_text("Contract renewal is scheduled for January 2026.")
    (root / "table.csv").write_text("name,amount\nService,1200\n")
    manifest = root / "Master_Index.jsonl"
    manifest.write_text(
        json.dumps(
            {
                "email_id": "email-1",
                "sender": "client@company.example",
                "subject": "Renewal",
                "date": "2026-01-01T10:00:00",
                "msg_file": "email.msg",
                "body_file": "body.txt",
                "extracted_attachments": ["table.csv"],
            }
        )
        + "\n"
    )
    return manifest


def test_ingestion_replay_idempotency_and_stale_chunk_removal(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    manifest = make_export(raw)
    sql = SQLiteStore(tmp_path / "metadata.sqlite3")
    vectors = ChromaStore(tmp_path / "chroma", "test_documents", "test-model")
    options = IngestionOptions(raw, tmp_path / "processed", 100, 10, "test-model")
    ingestor = Ingestor(MarkdownParser(), TestEmbedder(), sql, vectors, options)
    first = ingestor.ingest(manifest)
    assert first.documents == 2
    assert first.synchronized == 2
    assert first.errors == []
    assert sql.statistics()["email_count"] == 1
    assert vectors.count() == 2
    second = ingestor.ingest(manifest)
    assert second.unchanged == 2
    assert vectors.count() == 2
    agent = DeepRAGAgent(RecordingLLM(), TestEmbedder(), vectors, sql)
    original_ids = {hit.chunk.chunk_id for hit in agent.search("contract", 5)}
    (raw / "body.txt").write_text("Updated contract renewal terms.")
    failing = Ingestor(MarkdownParser(), TestEmbedder(), sql, FailAfterWrite(vectors), options)
    with pytest.raises(RuntimeError, match="Simulated"):
        failing.ingest(manifest)
    assert sql.statistics()["pending_count"] == 1
    assert sql.query("SELECT count(*) AS count FROM mcp_documents")[0]["count"] == 1
    assert all("Updated" not in hit.chunk.text for hit in agent.search("contract", 5))
    assert sql.synchronize(vectors) == 1
    assert sql.statistics()["pending_count"] == 0
    assert vectors.count() == 2
    final_hits = agent.search("contract", 5)
    assert any("Updated" in hit.chunk.text for hit in final_hits)
    assert {hit.chunk.chunk_id for hit in final_hits} != original_ids
    with pytest.raises(ValueError, match="differs"):
        ChromaStore(tmp_path / "chroma", "test_documents", "different-model")


def test_mcp_sql_rejects_writes_raw_tables_and_functions(tmp_path: Path) -> None:
    sql = SQLiteStore(tmp_path / "metadata.sqlite3")
    assert sql.query("SELECT count(*) AS count FROM mcp_emails") == [{"count": 0}]
    for statement in [
        "DELETE FROM emails",
        "SELECT * FROM documents",
        "PRAGMA database_list",
        "ATTACH DATABASE ':memory:' AS other",
        "SELECT load_extension('unsafe')",
        "SELECT * FROM sqlite_master",
        "WITH mcp_documents AS (SELECT * FROM documents) SELECT * FROM mcp_documents",
    ]:
        with pytest.raises((sqlite3.DatabaseError, ValueError)):
            sql.query(statement)


def test_path_escape_and_export_lock_are_rejected(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    manifest = make_export(raw)
    with pytest.raises(ValueError, match="within"):
        resolve_export_path(raw, "../outside.txt")
    (raw / "export.lock").touch()
    sql = SQLiteStore(tmp_path / "metadata.sqlite3")
    vectors = ChromaStore(tmp_path / "chroma", "test_documents", "test-model")
    with pytest.raises(ValueError, match="still running"):
        Ingestor(
            MarkdownParser(),
            TestEmbedder(),
            sql,
            vectors,
            IngestionOptions(raw, tmp_path / "processed"),
        ).ingest(manifest)
    (raw / "export.lock").unlink()
    (raw / "_rag").mkdir()
    publication = raw / "_rag/catalog_publication.json"
    publication.write_text("{}")
    with pytest.raises(ValueError, match="publication was interrupted"):
        Ingestor(
            MarkdownParser(),
            TestEmbedder(),
            sql,
            vectors,
            IngestionOptions(raw, tmp_path / "processed"),
        ).ingest(manifest)


def test_force_reingestion_rebuilds_an_empty_vector_index(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    manifest = make_export(raw)
    sql = SQLiteStore(tmp_path / "metadata.sqlite3")
    original = ChromaStore(tmp_path / "chroma", "test_documents", "test-model")
    options = IngestionOptions(raw, tmp_path / "processed", 100, 10, "test-model")
    Ingestor(MarkdownParser(), TestEmbedder(), sql, original, options).ingest(manifest)
    original.client.delete_collection("test_documents")
    restored = ChromaStore(tmp_path / "chroma", "test_documents", "test-model")
    ingestor = Ingestor(MarkdownParser(), TestEmbedder(), sql, restored, options)
    report = ingestor.ingest(manifest, force=True)
    assert report.documents == 2
    assert report.synchronized == 2
    assert restored.count() == 2
    assert sql.query("SELECT count(*) AS count FROM mcp_documents") == [{"count": 2}]
