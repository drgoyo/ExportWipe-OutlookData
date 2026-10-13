"""Verify inference never triggers an implicit mutable model download."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from config.application import AppConfig
from project_name.application import Runtime
from project_name.infrastructure import model_catalog
from project_name.infrastructure.embeddings import FastEmbedder

if TYPE_CHECKING:
    from pathlib import Path


def test_uninstalled_embedding_fails_before_engine_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import fastembed

    def forbidden_download(**_parameters: object) -> None:
        pytest.fail("Inference must never instantiate an unpinned/downloadable model")

    monkeypatch.setattr(fastembed, "TextEmbedding", forbidden_download)
    with pytest.raises(ValueError, match="models download"):
        FastEmbedder("BAAI/bge-small-en-v1.5", tmp_path).embed(["test"])


def test_live_runtime_rejects_model_installation_after_collection_initialization(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = AppConfig.model_validate(
        {
            "storage": {
                "sqlite_path": str(tmp_path / "metadata.sqlite3"),
                "chroma_directory": str(tmp_path / "chroma"),
                "model_cache": str(tmp_path / "models"),
            }
        }
    )
    runtime = Runtime(config, tmp_path / "config.yaml")
    assert runtime.vectors().count() == 0
    monkeypatch.setattr(model_catalog, "installed_model_revision", lambda _model, _cache: "a" * 40)
    with pytest.raises(ValueError, match="installation changed"):
        runtime.vectors()
