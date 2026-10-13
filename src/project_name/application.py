"""Composition root: instantiate adapters and inject ports without coupling vertical slices."""

from __future__ import annotations

from typing import TYPE_CHECKING

from config.application import AppConfig, RuntimeEnvironment
from project_name.core.records import IngestionOptions, ParseOptions
from project_name.infrastructure.llm import OpenAICompatibleLLM
from project_name.infrastructure.sqlite_store import SQLiteStore

if TYPE_CHECKING:
    from pathlib import Path

    from pipelines.data_ingestion.ingest import Ingestor
    from pipelines.document_parsing.parser import MarkdownParser
    from pipelines.rag_agents.agents import DeepRAGAgent, MetadataAgent
    from project_name.core.ports import Embedder, VectorStore


class Runtime:
    def __init__(self, config: AppConfig, config_path: Path) -> None:
        self.config = config
        self.environment = RuntimeEnvironment(env_file=config_path.resolve().parent / ".env")
        self.metadata = SQLiteStore(config.storage.sqlite_path)
        self._vectors: VectorStore | None = None
        self._vector_signature: str | None = None
        self._embedder: Embedder | None = None

    def llm(self) -> OpenAICompatibleLLM:
        config = self.config.llm
        return OpenAICompatibleLLM(
            config.base_url,
            config.model,
            self.environment.llm_api_key.get_secret_value(),
            config.timeout_seconds,
        )

    def require_deep(self) -> None:
        if not self.config.tracks.track2_enabled:
            raise ValueError("Track 2 is disabled in configuration")

    def embedding_signature(self) -> str:
        from project_name.infrastructure.model_catalog import installed_model_revision

        model = self.config.storage.embedding_model
        revision = installed_model_revision(model, self.config.storage.model_cache)
        return f"{model}@{revision}" if revision else model

    def vectors(self) -> VectorStore:
        self.require_deep()
        signature = self.embedding_signature()
        if self._vectors is not None and self._vector_signature != signature:
            raise ValueError(
                "Embedding installation changed; select a new collection and restart the backend"
            )
        if self._vectors is None:
            from project_name.infrastructure.vector_store import ChromaStore

            config = self.config.storage
            self._vectors = ChromaStore(
                config.chroma_directory,
                config.collection,
                signature,
                host=config.chroma_host,
                port=config.chroma_port,
                ssl=config.chroma_ssl,
            )
            self._vector_signature = signature
        return self._vectors

    def embedder(self) -> Embedder:
        self.require_deep()
        if self._embedder is None:
            from project_name.infrastructure.embeddings import FastEmbedder

            self._embedder = FastEmbedder(
                self.config.storage.embedding_model, self.config.storage.model_cache
            )
        return self._embedder

    def parser(self) -> MarkdownParser:
        from pipelines.document_parsing.parser import MarkdownParser

        config = self.config.parsing
        return MarkdownParser(
            ParseOptions(
                config.max_file_bytes,
                config.max_uncompressed_bytes,
                config.max_table_rows,
                config.ocr_language,
                config.tesseract_command,
                config.ocr_timeout_seconds,
            )
        )

    def ingestor(self) -> Ingestor:
        from pipelines.data_ingestion.ingest import Ingestor

        self.require_deep()
        options = IngestionOptions(
            self.config.extraction.output_directory,
            self.config.parsing.output_directory,
            self.config.storage.chunk_characters,
            self.config.storage.chunk_overlap,
            self.embedding_signature(),
        )
        return Ingestor(self.parser(), self.embedder(), self.metadata, self.vectors(), options)

    def metadata_agent(self) -> MetadataAgent:
        from pipelines.rag_agents.agents import MetadataAgent

        if not self.config.tracks.track1_enabled:
            raise ValueError("Track 1 is disabled in configuration")
        return MetadataAgent(self.llm(), self.config.llm.max_context_characters)

    def deep_agent(self) -> DeepRAGAgent:
        from pipelines.rag_agents.agents import DeepRAGAgent

        self.require_deep()
        return DeepRAGAgent(
            self.llm(),
            self.embedder(),
            self.vectors(),
            self.metadata,
            self.config.llm.max_context_characters,
        )
