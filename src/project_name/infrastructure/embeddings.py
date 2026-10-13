"""Lazy CPU ONNX semantic embeddings; no model download during import or GUI startup."""

from __future__ import annotations

from threading import Lock
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from fastembed import TextEmbedding


class FastEmbedder:
    def __init__(self, model: str, cache: Path) -> None:
        self.model = model
        self.cache = cache
        self._engine: TextEmbedding | None = None
        self._lock = Lock()

    def embed(self, texts: Sequence[str], *, query: bool = False) -> list[list[float]]:
        from fastembed import TextEmbedding

        from project_name.infrastructure.model_catalog import installed_model_path

        with self._lock:
            if self._engine is None:
                self.cache.mkdir(parents=True, exist_ok=True)
                pinned = installed_model_path(self.model, self.cache)
                if pinned is None:
                    raise ValueError(
                        "Install and validate the embedding model first: "
                        f"models download {self.model}"
                    )
                self._engine = TextEmbedding(
                    model_name=self.model,
                    cache_dir=str(self.cache),
                    threads=2,
                    local_files_only=True,
                    specific_model_path=str(pinned),
                )
            iterator = (
                self._engine.query_embed(list(texts)) if query else self._engine.embed(list(texts))
            )
            return [[float(value) for value in vector] for vector in iterator]
