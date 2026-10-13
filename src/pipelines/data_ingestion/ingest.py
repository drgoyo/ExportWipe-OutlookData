"""Chunk and stage documents; durable SQL jobs recover interrupted vector synchronization."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from project_name.core.records import Chunk, Document, Email, IngestionOptions

if TYPE_CHECKING:
    from pathlib import Path

    from project_name.core.ports import Embedder, MetadataStore, Parser, VectorStore


@dataclass
class IngestionReport:
    emails: int = 0
    documents: int = 0
    unchanged: int = 0
    synchronized: int = 0
    errors: list[str] = field(default_factory=list)


def resolve_export_path(root: Path, value: str) -> Path:
    candidate = (root / value.replace("\\", "/")).resolve()
    if not value or not candidate.is_relative_to(root.resolve()):
        raise ValueError("Export path must stay within the configured raw directory")
    return candidate


def chunk_markdown(document: Document, size: int, overlap: int) -> list[Chunk]:
    if size < 1 or not 0 <= overlap < size:
        raise ValueError("Require 0 <= overlap < chunk size")
    text = document.markdown
    chunks: list[Chunk] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        # Prefer paragraph/line boundaries without breaking overlap coverage.
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start + overlap:
                end = boundary + 1
        content = text[start:end]
        if content.strip():
            ordinal = len(chunks)
            chunk_id = hashlib.sha256(
                f"{document.document_id}:{document.revision}:{ordinal}".encode()
            ).hexdigest()
            chunks.append(
                Chunk(chunk_id, document.document_id, document.revision, ordinal, content)
            )
        if end == len(text):
            break
        start = end - overlap
    return chunks


class Ingestor:
    def __init__(
        self,
        parser: Parser,
        embedder: Embedder,
        metadata: MetadataStore,
        vectors: VectorStore,
        options: IngestionOptions,
    ) -> None:
        self.parser = parser
        self.embedder = embedder
        self.metadata = metadata
        self.vectors = vectors
        self.options = options

    def ingest(self, manifest: Path, *, force: bool = False) -> IngestionReport:
        root = self.options.raw_directory.resolve()
        manifest = manifest.resolve()
        if not manifest.is_relative_to(root):
            raise ValueError("Manifest must be within the raw directory")
        if (root / "export.lock").exists():
            raise ValueError("Outlook export is still running (export.lock exists)")
        if (root / "_rag/catalog_publication.json").exists():
            raise ValueError("Catalog publication was interrupted; repair before ingestion")
        if (root / "_rag/catalog.lock").exists():
            raise ValueError("Catalog generation is still running (catalog.lock exists)")
        report = IngestionReport()
        with manifest.open(encoding="utf-8-sig") as stream:
            for number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    if len(line) > 2_000_000:
                        raise ValueError("Manifest record exceeds 2 MB")
                    payload = json.loads(line)
                    if not isinstance(payload, dict):
                        raise ValueError("Manifest records must be JSON objects")
                    email = Email.from_mapping(payload)
                    self.metadata.upsert_email(email)
                    report.emails += 1
                    paths = ([email.body_file] if email.body_file else []) + list(email.attachments)
                    for relative in dict.fromkeys(paths):
                        try:
                            if self.ingest_document(email, relative, force=force):
                                report.documents += 1
                            else:
                                report.unchanged += 1
                        except (ValueError, OSError, RuntimeError) as exc:
                            report.errors.append(f"{email.email_id} / {relative}: {exc}")
                except (ValueError, OSError) as exc:
                    report.errors.append(f"Manifest line {number}: {exc}")
        # Failures here leave committed SQL jobs pending for an explicit sync or next run.
        report.synchronized = self.metadata.synchronize(self.vectors)
        return report

    def ingest_document(self, email: Email, relative: str, *, force: bool = False) -> bool:
        path = resolve_export_path(self.options.raw_directory, relative)
        markdown = self.parser.parse(path)
        content_hash = hashlib.sha256(markdown.encode()).hexdigest()
        document_id = hashlib.sha256(f"{email.email_id}:{relative}".encode()).hexdigest()
        revision = hashlib.sha256(
            f"{content_hash}:{self.options.embedding_signature}:{self.options.chunk_characters}:{self.options.chunk_overlap}".encode()
        ).hexdigest()
        if not force and self.metadata.revision(document_id) == revision:
            return False
        document = Document(
            document_id,
            email.email_id,
            relative,
            path.suffix.lower(),
            content_hash,
            revision,
            markdown,
        )
        chunks = chunk_markdown(document, self.options.chunk_characters, self.options.chunk_overlap)
        if not chunks:
            raise ValueError("No nonempty chunks")
        embeddings = self.embedder.embed([chunk.text for chunk in chunks])
        if len(embeddings) != len(chunks) or not embeddings or not embeddings[0]:
            raise ValueError("Embedding count or dimension is invalid")
        dimension = len(embeddings[0])
        if any(
            len(vector) != dimension or not all(math.isfinite(value) for value in vector)
            for vector in embeddings
        ):
            raise ValueError("Embeddings must have equal dimensions and finite values")
        self.options.processed_directory.mkdir(parents=True, exist_ok=True)
        output = self.options.processed_directory / f"{document_id}.md"
        temporary = output.with_suffix(".md.tmp")
        temporary.write_text(markdown, encoding="utf-8")
        temporary.replace(output)
        self.metadata.stage(document, chunks, embeddings)
        return True
