"""Model compatibility, live metadata, pinned installation, and real validation boundaries."""

from __future__ import annotations

import shutil
from typing import TYPE_CHECKING
from unittest.mock import patch

import httpx
import pytest

from project_name.infrastructure.model_catalog import (
    ModelCatalog,
    installed_model_path,
    installed_model_revision,
)

if TYPE_CHECKING:
    from pathlib import Path

    from project_name.core.records import JsonRow

_MODEL = "BAAI/bge-small-en-v1.5"
_REPO = "Qdrant/bge-small-en-v1.5-onnx-Q"
_REVISION = "a" * 40


def _metadata(**changes: object) -> dict[str, object]:
    return {
        "id": _REPO,
        "sha": _REVISION,
        "gated": False,
        "private": False,
        "cardData": {"license": "mit"},
        "siblings": [{"rfilename": "model_optimized.onnx"}],
        **changes,
    }


def _client(payload: dict[str, object], *, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"https://huggingface.co/api/models/{_REPO}"
        return httpx.Response(status, json=payload)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_registry_recommends_actual_supported_models_without_network(tmp_path: Path) -> None:
    catalog = ModelCatalog(tmp_path)
    with patch("httpx.Client", side_effect=AssertionError("Offline discovery made a request")):
        models = catalog.list_models(language="de")
        assert models[0]["model"] == ("sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
        assert all(row["live_status"] == "not_checked" for row in models)
        assert not any(row["installed"] for row in models)
        assert catalog.list_models(language="en")[0]["model"] == _MODEL
        with pytest.raises(ValueError, match="not supported"):
            catalog.check("arbitrary/remote-code-model")


def test_live_check_verifies_commit_filenames_and_license(tmp_path: Path) -> None:
    with _client(_metadata()) as client:
        row = ModelCatalog(tmp_path, client=client).check(_MODEL)
    assert row["live_status"] == "verified"
    assert row["revision"] == _REVISION
    assert row["hub_license"] == "mit"
    assert row["installed"] is False
    assert not tmp_path.exists() or not list(tmp_path.iterdir())


@pytest.mark.parametrize(
    ("changes", "status", "expected"),
    [
        ({"siblings": []}, 200, "missing_files"),
        ({"gated": "manual"}, 200, "restricted"),
        ({"id": "different/repository"}, 200, "unavailable"),
        ({"sha": "main"}, 200, "unavailable"),
        ({}, 403, "unavailable"),
    ],
)
def test_unavailable_or_incompatible_hub_models_are_not_downloadable(
    tmp_path: Path, changes: dict[str, object], status: int, expected: str
) -> None:
    with _client(_metadata(**changes), status=status) as client:
        catalog = ModelCatalog(tmp_path, client=client)
        assert catalog.check(_MODEL)["live_status"] == expected
        with patch("huggingface_hub.snapshot_download") as download:
            with pytest.raises(ValueError, match="cannot be downloaded"):
                catalog.download(_MODEL)
            download.assert_not_called()


def test_install_pins_revision_and_only_publishes_validated_portable_receipt(
    tmp_path: Path,
) -> None:
    from fastembed import TextEmbedding

    registry = TextEmbedding.list_supported_models()
    cache = tmp_path / "models"
    snapshot = cache / "models--Qdrant--bge-small-en-v1.5-onnx-Q" / "snapshots" / _REVISION
    snapshot.mkdir(parents=True)
    (snapshot / "model_optimized.onnx").write_bytes(b"model-fixture")
    (snapshot / "tokenizer.json").write_text("{}")
    with (
        _client(_metadata()) as client,
        patch("huggingface_hub.snapshot_download", return_value=str(snapshot)) as download,
        patch("fastembed.TextEmbedding") as embedding,
    ):
        embedding.list_supported_models.return_value = registry
        embedding.return_value.embed.return_value = [[0.25] * 384]
        receipt = ModelCatalog(cache, client=client).download(_MODEL)
        assert download.call_args.kwargs["revision"] == _REVISION
        assert download.call_args.kwargs["allow_patterns"][-1] == "model_optimized.onnx"
        assert embedding.call_args.kwargs["specific_model_path"] == str(snapshot)
        assert embedding.call_args.kwargs["local_files_only"] is True
        assert embedding.call_args.kwargs["cuda"] is False
    assert receipt["validated"] is True
    assert installed_model_path(_MODEL, cache) == snapshot
    assert installed_model_revision(_MODEL, cache) == _REVISION
    moved = tmp_path / "moved"
    shutil.copytree(cache, moved)
    assert installed_model_path(_MODEL, moved) == moved / snapshot.relative_to(cache)
    (moved / snapshot.relative_to(cache) / "tokenizer.json").unlink()
    assert installed_model_path(_MODEL, moved) is None
    assert installed_model_revision(_MODEL, moved) is None


@pytest.mark.parametrize("vector", [[float("nan")] * 384, [0.25] * 8])
def test_failed_embedding_validation_never_creates_ready_receipt(
    tmp_path: Path, vector: list[float]
) -> None:
    from fastembed import TextEmbedding

    registry = TextEmbedding.list_supported_models()
    snapshot = tmp_path / "snapshot"
    snapshot.mkdir()
    (snapshot / "model_optimized.onnx").write_bytes(b"model-fixture")
    with (
        _client(_metadata()) as client,
        patch("huggingface_hub.snapshot_download", return_value=str(snapshot)),
        patch("fastembed.TextEmbedding") as embedding,
    ):
        embedding.list_supported_models.return_value = registry
        embedding.return_value.embed.return_value = [vector]
        with pytest.raises(ValueError, match="CPU embedding validation"):
            ModelCatalog(tmp_path, client=client).download(_MODEL)
    assert installed_model_path(_MODEL, tmp_path) is None
    assert not (tmp_path / "installed").exists()


def test_explicit_size_limit_blocks_download_before_network_weights(tmp_path: Path) -> None:
    with _client(_metadata()) as client, patch("huggingface_hub.snapshot_download") as download:
        with pytest.raises(ValueError, match="size limit"):
            ModelCatalog(tmp_path, client=client).download(_MODEL, max_size_gb=0.01)
        download.assert_not_called()


def test_blocked_download_explains_proxy_failure_without_publishing_or_leaking_details(
    tmp_path: Path,
) -> None:
    with (
        _client(_metadata()) as client,
        patch(
            "huggingface_hub.snapshot_download",
            side_effect=httpx.ProxyError("403 Forbidden; sensitive-proxy-credential"),
        ),
        pytest.raises(RuntimeError, match="HTTP 403") as error,
    ):
        ModelCatalog(tmp_path, client=client).download(_MODEL)
    assert "us.aws.cdn.hf.co" in str(error.value)
    assert "sensitive-proxy-credential" not in str(error.value)
    assert installed_model_path(_MODEL, tmp_path) is None


def test_live_metadata_size_limit_rejects_false_availability(tmp_path: Path) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"x" * 2_000_001)

    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        row = ModelCatalog(tmp_path, client=client).check(_MODEL)
    assert row["live_status"] == "unavailable"


def test_receipt_cannot_point_outside_configured_cache(tmp_path: Path) -> None:
    import hashlib
    import json

    cache = tmp_path / "models"
    receipt = cache / "installed" / f"{hashlib.sha256(_MODEL.encode()).hexdigest()}.json"
    receipt.parent.mkdir(parents=True)
    (tmp_path / "outside.onnx").write_bytes(b"model")
    row: JsonRow = {
        "model": _MODEL,
        "hf_repo": _REPO,
        "revision": _REVISION,
        "validated": True,
        "relative_path": "..",
        "files": {"outside.onnx": 5},
    }
    receipt.write_text(json.dumps(row))
    assert installed_model_path(_MODEL, cache) is None
