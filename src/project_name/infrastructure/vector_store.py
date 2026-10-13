"""Chroma adapter with explicit embeddings and idempotent revision replacement."""

from __future__ import annotations

from typing import TYPE_CHECKING

import chromadb
from chromadb.config import Settings as ChromaSettings

from project_name.core.records import VectorHit

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from project_name.core.records import Chunk, Document


class ChromaStore:
    def __init__(
        self,
        directory: Path,
        collection: str,
        signature: str,
        *,
        host: str = "",
        port: int = 8000,
        ssl: bool = False,
    ) -> None:
        settings = ChromaSettings(anonymized_telemetry=False)
        self.client = (
            chromadb.HttpClient(host=host, port=port, ssl=ssl, settings=settings)
            if host
            else chromadb.PersistentClient(path=str(directory), settings=settings)
        )
        self.client.heartbeat()
        self.collection = self.client.get_or_create_collection(
            collection,
            embedding_function=None,
            metadata={"embedding_signature": signature},
            configuration={"hnsw": {"space": "cosine"}},
        )
        if (
            self.collection.metadata is None
            or self.collection.metadata.get("embedding_signature") != signature
        ):
            raise ValueError(
                "Embedding model differs from this collection; choose a new collection"
            )

    def replace_document(
        self, document: Document, chunks: Sequence[Chunk], embeddings: Sequence[Sequence[float]]
    ) -> None:
        ids = [chunk.chunk_id for chunk in chunks]
        # Batches respect remote/local Chroma limits; a crash remains replayable in the SQL outbox.
        maximum = self.client.get_max_batch_size()
        for start in range(0, len(chunks), maximum):
            batch = chunks[start : start + maximum]
            batch_embeddings: list[Sequence[float] | Sequence[int]] = [
                list(vector) for vector in embeddings[start : start + maximum]
            ]
            self.collection.upsert(
                ids=ids[start : start + maximum],
                embeddings=batch_embeddings,
                documents=[chunk.text for chunk in batch],
                metadatas=[
                    {
                        "document_id": document.document_id,
                        "email_id": document.email_id,
                        "source_path": document.source_path,
                        "revision": document.revision,
                    }
                    for _ in batch
                ],
            )
        existing = self.collection.get(where={"document_id": document.document_id}, include=[])[
            "ids"
        ]
        stale = list(set(existing) - set(ids))
        if stale:
            self.collection.delete(ids=stale)

    def search(self, embedding: Sequence[float], limit: int) -> list[VectorHit]:
        count = self.count()
        if not count:
            return []
        query_embeddings: list[Sequence[float] | Sequence[int]] = [list(embedding)]
        result = self.collection.query(
            query_embeddings=query_embeddings, n_results=min(limit, count), include=["distances"]
        )
        distances = result["distances"]
        if distances is None:
            return []
        return [
            VectorHit(chunk_id, float(distance))
            for chunk_id, distance in zip(result["ids"][0], distances[0], strict=True)
        ]

    def count(self) -> int:
        return self.collection.count()
