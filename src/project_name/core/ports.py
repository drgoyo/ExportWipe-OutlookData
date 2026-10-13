"""Shared ports allow contexts to collaborate without importing one another."""

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from project_name.core.records import (
    Chunk,
    Document,
    Email,
    JsonRow,
    JsonValue,
    RetrievedChunk,
    VectorHit,
)


class Parser(Protocol):
    def parse(self, path: Path) -> str: ...


class Embedder(Protocol):
    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]: ...


class VectorStore(Protocol):
    def replace_document(
        self, document: Document, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None: ...
    def search(self, embedding: Sequence[float], limit: int) -> list[VectorHit]: ...
    def count(self) -> int: ...


class MetadataStore(Protocol):
    def upsert_email(self, email: Email) -> None: ...
    def revision(self, document_id: str) -> str | None: ...
    def stage(
        self, document: Document, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None: ...
    def synchronize(self, vectors: VectorStore) -> int: ...
    def resolve_hit(self, hit: VectorHit) -> RetrievedChunk | None: ...
    def statistics(self) -> JsonRow: ...
    def query(
        self, sql: str, parameters: Sequence[JsonValue] = (), limit: int = 200
    ) -> list[JsonRow]: ...


class LanguageModel(Protocol):
    def complete(self, system: str, context: str, question: str) -> str: ...
