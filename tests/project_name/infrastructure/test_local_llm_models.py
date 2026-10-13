"""Verify live-manifest selection, pinned weights, budgets, and explicit local installation."""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import httpx
import pytest

from project_name.infrastructure.local_llm_models import LocalLLMModelCatalog, install_ollama

if TYPE_CHECKING:
    from project_name.core.records import JsonRow

_WEIGHTS = b"GGUF" + b"synthetic weight bytes"
_REVISION = "a" * 40
_FILE = "qwen-Q4_K_M.gguf"


def _manifest() -> JsonRow:
    return {
        "sha": _REVISION,
        "pipeline_tag": "text-generation",
        "cardData": {"license": "apache-2.0"},
        "siblings": [
            {"rfilename": "qwen-Q8_0.gguf", "size": 2_000_000_000},
            {
                "rfilename": _FILE,
                "size": len(_WEIGHTS),
                "lfs": {"sha256": hashlib.sha256(_WEIGHTS).hexdigest()},
            },
            {"rfilename": "qwen-Q4_K_M-00001-of-00002.gguf", "size": 1},
        ],
    }


def _client(manifest: JsonRow | None = None) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "huggingface.co"
        if request.url.path == "/api/models":
            assert request.url.params["author"] == "Qwen"
            return httpx.Response(
                200,
                json=[
                    {"id": "Qwen/embedding", "pipeline_tag": "feature-extraction"},
                    {"id": "Other/model", "pipeline_tag": "text-generation"},
                    {"id": "Qwen/split", "pipeline_tag": "text-generation"},
                    {"id": "Qwen/model", "pipeline_tag": "text-generation"},
                ],
            )
        if request.url.path == "/api/models/Qwen/split":
            split_manifest = _manifest() | {
                "siblings": [{"rfilename": "split-00001-of-00002.gguf", "size": 100}]
            }
            return httpx.Response(200, json=split_manifest)
        assert request.url.path == "/api/models/Qwen/model"
        assert request.url.params["blobs"] == "true"
        return httpx.Response(200, json=manifest or _manifest())

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_live_catalog_selects_real_unsplit_q4_and_filters_non_generative(tmp_path: Path) -> None:
    with _client() as client:
        catalog = LocalLLMModelCatalog(tmp_path, client)
        models = catalog.list_models()
        assert len(models) == 1
        assert models[0]["repo_id"] == "Qwen/model"
        assert models[0]["recommended_filename"] == _FILE
        assert models[0]["revision"] == _REVISION
        assert models[0]["license"] == "apache-2.0"
        inventory = models[0]["files"]
        assert isinstance(inventory, list)
        assert len(inventory) == 2
        assert not list(tmp_path.iterdir())


def test_download_pins_commit_and_verifies_content(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def download(**kwargs: object) -> str:
        calls.append(kwargs)
        path = Path(str(kwargs["cache_dir"])) / _FILE
        path.write_bytes(_WEIGHTS)
        return str(path)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    with _client() as client:
        result = LocalLLMModelCatalog(tmp_path, client).download("Qwen/model")
    assert calls == [
        {
            "repo_id": "Qwen/model",
            "filename": _FILE,
            "revision": _REVISION,
            "cache_dir": str(tmp_path),
            "local_files_only": False,
        }
    ]
    assert result["checksum_verified"] is True
    assert result["downloaded"] is True
    assert result["cache_path"] == str(tmp_path / _FILE)
    assert "installed_provider_model" not in result


def test_budgets_unknown_files_and_untrusted_paths_prevent_download(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_download(**kwargs: object) -> str:
        pytest.fail("An invalid selection or insufficient budget must not download weights")

    monkeypatch.setattr("huggingface_hub.hf_hub_download", unexpected_download)
    with _client() as client:
        catalog = LocalLLMModelCatalog(tmp_path, client)
        with pytest.raises(ValueError, match="budget"):
            catalog.download("Qwen/model", "qwen-Q8_0.gguf", max_size_gb=0.1)
        with pytest.raises(ValueError, match="absent"):
            catalog.download("Qwen/model", "other.gguf")
        for filename in ("../model.gguf", "/model.gguf", "model-00001-of-00002.gguf"):
            with pytest.raises(ValueError, match="single"):
                catalog.download("Qwen/model", filename)
        for repository in ("https://evil.example/model", "Qwen/../model", "Qwen/model?token=abc"):
            with pytest.raises(ValueError, match="owner/name"):
                catalog.check(repository)
    assert not list(tmp_path.iterdir())


def test_download_rejects_checksum_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def download(**kwargs: object) -> str:
        path = tmp_path / _FILE
        path.write_bytes(b"GGUF" + b"X" * (len(_WEIGHTS) - 4))
        return str(path)

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    with _client() as client, pytest.raises(ValueError, match="SHA-256"):
        LocalLLMModelCatalog(tmp_path, client).download("Qwen/model")


@pytest.mark.parametrize("failure", ["proxy", "status"])
def test_download_denial_reports_http_status_without_provider_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    def download(**kwargs: object) -> str:
        if failure == "proxy":
            raise httpx.ProxyError("403 authorization-secret")
        request = httpx.Request("GET", "https://huggingface.co/model?token=authorization-secret")
        raise httpx.HTTPStatusError(
            "authorization-secret", request=request, response=httpx.Response(403, request=request)
        )

    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    with _client() as client, pytest.raises(RuntimeError) as error:
        LocalLLMModelCatalog(tmp_path, client).download("Qwen/model")
    assert "HTTP 403" in str(error.value)
    assert "authorization-secret" not in str(error.value)


def test_cached_hf_blob_reuses_space_and_preserves_pinned_filename(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    blob = tmp_path / "blobs" / ("c" * 64)
    blob.parent.mkdir()
    blob.write_bytes(_WEIGHTS)
    snapshot = tmp_path / _FILE
    snapshot.symlink_to(blob)

    def cached(*args: object, **kwargs: object) -> str:
        return str(snapshot)

    def download(**kwargs: object) -> str:
        assert kwargs["local_files_only"] is True
        assert kwargs["revision"] == _REVISION
        return str(snapshot)

    monkeypatch.setattr("huggingface_hub.try_to_load_from_cache", cached)
    monkeypatch.setattr("huggingface_hub.hf_hub_download", download)
    monkeypatch.setattr("shutil.disk_usage", lambda path: SimpleNamespace(free=0))
    with _client() as client:
        result = LocalLLMModelCatalog(tmp_path, client).download("Qwen/model")
    assert result["cache_path"] == str(blob)
    assert result["filename"] == _FILE
    assert result["checksum_verified"] is True


def test_ollama_install_is_explicit_uses_literal_args_and_quotes_space_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "folder with spaces" / ("c" * 64)
    model.parent.mkdir()
    model.write_bytes(_WEIGHTS)
    captured: list[list[str]] = []
    monkeypatch.setattr("shutil.which", lambda executable: "/usr/bin/ollama")

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        captured.append(command)
        assert kwargs["timeout"] == 1800
        assert kwargs.get("shell", False) is False
        environment = kwargs["env"]
        assert isinstance(environment, dict)
        assert environment["OLLAMA_HOST"] == "127.0.0.1:11434"
        assert Path(command[-1]).read_text(encoding="utf-8") == f'FROM "{model.as_posix()}"\n'
        return subprocess.CompletedProcess(command, 0, "ok", "")

    monkeypatch.setattr("subprocess.run", run)
    result = install_ollama({"cache_path": str(model), "filename": _FILE}, "outlook-test")
    assert captured[0][:4] == ["/usr/bin/ollama", "create", "outlook-test", "--file"]
    assert result["installed_provider_model"] == "outlook-test"
    assert result["base_url"] == "http://127.0.0.1:11434/v1"
    with pytest.raises(ValueError, match="model name"):
        install_ollama({"cache_path": str(model), "filename": _FILE}, "--untrusted")


def test_live_failure_reports_status_without_claiming_offline_verification(tmp_path: Path) -> None:
    with (
        httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(403))) as client,
        pytest.raises(RuntimeError, match="HTTP 403"),
    ):
        LocalLLMModelCatalog(tmp_path, client).list_models()


def test_provider_metadata_is_bounded_before_json_decoding(tmp_path: Path) -> None:
    with (
        httpx.Client(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(200, content=b" " * 4_000_001)
            )
        ) as client,
        pytest.raises(RuntimeError, match="ValueError"),
    ):
        LocalLLMModelCatalog(tmp_path, client).list_models()
