"""Discover verified GGUF files and explicitly provision a local generative model."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
    from project_name.core.records import JsonRow, JsonValue

_HF_API = "https://huggingface.co/api/models"
_MAX_METADATA_BYTES = 4_000_000
_REPOSITORY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}/[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
_COMMIT = re.compile(r"^[0-9a-f]{40}$")
_HASH = re.compile(r"^[0-9a-f]{64}$")
_OLLAMA_NAME = re.compile(r"^[a-z][a-z0-9_.-]{0,60}$")


class _NoSingleGGUFError(ValueError):
    """A listed repository has only split weights, which this importer does not assemble."""


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError("Hugging Face returned an invalid object")
    return cast("dict[str, object]", value)


def _string(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Missing or invalid model {field}")
    return value


def _positive_size(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError("GGUF download requires a verified, positive file size")
    return value


def _safe_filename(value: str) -> str:
    path = PurePosixPath(value)
    if (
        not value
        or len(value) > 500
        or path.is_absolute()
        or ".." in path.parts
        or "\\" in value
        or any(ord(character) < 32 for character in value)
        or path.suffix.lower() != ".gguf"
        or re.search(r"-\d+-of-\d+\.gguf$", value, flags=re.IGNORECASE)
    ):
        raise ValueError("Select a single, unsplit GGUF file inside the model repository")
    return value


def _recommendation(repo_id: str) -> str:
    if "0.6B" in repo_id:
        return "Small CPU smoke-test model; limited answer quality."
    if "1.7B" in repo_id:
        return "Lightweight multilingual CPU option; evaluate answers on your own documents."
    if "4B" in repo_id and "14B" not in repo_id:
        return (
            "Balanced multilingual option; prefer available Q4_K_M and at least 8 GiB system RAM."
        )
    return "Larger model: check available RAM, context memory, and measured answer quality."


class LocalLLMModelCatalog:
    """Live official-model discovery; downloads and Ollama installation are separate actions."""

    def __init__(self, cache: Path, client: httpx.Client | None = None) -> None:
        self.cache = cache
        self._client = client

    def _get(self, suffix: str, parameters: dict[str, str | int]) -> object:
        def request(client: httpx.Client) -> object:
            with client.stream(
                "GET", _HF_API + suffix, params=parameters, timeout=30, follow_redirects=False
            ) as response:
                response.raise_for_status()
                payload = bytearray()
                for block in response.iter_bytes(chunk_size=65_536):
                    payload.extend(block)
                    if len(payload) > _MAX_METADATA_BYTES:
                        raise ValueError("Hugging Face metadata exceeds the size limit")
            return cast("object", json.loads(payload))

        try:
            if self._client is None:
                with httpx.Client(timeout=30, follow_redirects=False) as client:
                    return request(client)
            return request(self._client)
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"Hugging Face live model check failed with HTTP {exc.response.status_code}"
            ) from None
        except (httpx.HTTPError, ValueError) as exc:
            raise RuntimeError(
                f"Hugging Face live model check failed ({type(exc).__name__})"
            ) from None

    def list_models(self, search: str = "Qwen", limit: int = 8) -> list[JsonRow]:
        """Check current official Qwen text-generation GGUF repositories and file sizes."""
        if not 1 <= limit <= 20 or not search.strip() or len(search) > 100:
            raise ValueError("Use a non-empty search up to 100 characters and limit 1..20")
        data = self._get(
            "",
            {
                "author": "Qwen",
                "filter": "gguf",
                "search": search,
                "limit": min(limit * 2, 40),
                "sort": "downloads",
                "direction": -1,
            },
        )
        if not isinstance(data, list):
            raise ValueError("Hugging Face returned an invalid model list")
        results: list[JsonRow] = []
        for entry in cast("list[object]", data):
            model = _mapping(entry)
            if model.get("pipeline_tag") != "text-generation":
                continue
            repo_id = _string(model.get("id"), "repository")
            if not repo_id.startswith("Qwen/"):
                continue
            try:
                results.append(self.check(repo_id))
            except _NoSingleGGUFError:
                continue
            if len(results) >= limit:
                break
        return results

    def check(self, repo_id: str) -> JsonRow:
        """Resolve a live immutable revision, license, actual GGUF files, and memory estimate."""
        if not _REPOSITORY.fullmatch(repo_id):
            raise ValueError("Model repository must be a Hugging Face owner/name")
        data = _mapping(self._get("/" + repo_id, {"blobs": "true"}))
        revision = _string(data.get("sha"), "revision")
        if not _COMMIT.fullmatch(revision):
            raise ValueError("Hugging Face did not return an immutable commit revision")
        if data.get("pipeline_tag") != "text-generation":
            raise ValueError(
                "Select a text-generation model, rather than an embedding/vision model"
            )
        siblings = data.get("siblings")
        if not isinstance(siblings, list):
            raise ValueError("Hugging Face returned no model file inventory")
        files: list[JsonValue] = []
        for entry in cast("list[object]", siblings):
            sibling = _mapping(entry)
            filename = sibling.get("rfilename")
            if not isinstance(filename, str) or not filename.lower().endswith(".gguf"):
                continue
            try:
                _safe_filename(filename)
            except ValueError:
                continue
            lfs_value = sibling.get("lfs", {})
            lfs = _mapping(lfs_value)
            size = _positive_size(sibling.get("size", lfs.get("size")))
            digest_value = lfs.get("sha256")
            digest = digest_value if isinstance(digest_value, str) else ""
            if digest and not _HASH.fullmatch(digest):
                raise ValueError("Invalid Hugging Face LFS checksum")
            files.append({"filename": filename, "size_bytes": size, "sha256": digest})
        if not files:
            raise _NoSingleGGUFError(
                "No verified single-file GGUF weights are available in this repository"
            )
        file_rows = [_mapping(file) for file in files]
        preferred = min(
            file_rows,
            key=lambda file: (
                "q4_k_m" not in _string(file["filename"], "filename").lower(),
                _positive_size(file["size_bytes"]),
            ),
        )
        size = _positive_size(preferred["size_bytes"])
        card_value = data.get("cardData", {})
        card = _mapping(card_value) if card_value is not None else {}
        license_value = card.get("license", "unknown")
        license_name = license_value if isinstance(license_value, str) else "unknown"
        return {
            "repo_id": repo_id,
            "revision": revision,
            "license": license_name,
            "live_status": "verified",
            "checked_at": datetime.now(UTC).isoformat(),
            "recommended_filename": _string(preferred["filename"], "filename"),
            "size_gb": round(size / 1_000_000_000, 3),
            "minimum_ram_gib": math.ceil(size / (1024**3) * 1.5 + 2),
            "ram_note": "Estimate only: context/KV cache and application memory require extra RAM.",
            "recommendation": _recommendation(repo_id),
            "source_url": "https://huggingface.co/" + repo_id,
            "files": files,
        }

    def download(
        self, repo_id: str, filename: str | None = None, *, max_size_gb: float = 5.0
    ) -> JsonRow:
        """Download selected GGUF weights; verify size, format, and available LFS checksum."""
        if not math.isfinite(max_size_gb) or max_size_gb <= 0:
            raise ValueError("Download size budget must be finite and positive")
        model = self.check(repo_id)
        selected = _safe_filename(
            filename or _string(model["recommended_filename"], "recommended filename")
        )
        inventory = model["files"]
        if not isinstance(inventory, list):
            raise ValueError("Invalid model file inventory")
        file = next(
            (_mapping(entry) for entry in inventory if _mapping(entry).get("filename") == selected),
            None,
        )
        if file is None:
            raise ValueError("Selected GGUF file is absent from the verified repository revision")
        size = _positive_size(file["size_bytes"])
        if size > max_size_gb * 1_000_000_000:
            raise ValueError(
                "Model exceeds the download size budget; explicitly increase the limit"
            )
        self.cache.mkdir(parents=True, exist_ok=True)
        from huggingface_hub import hf_hub_download, try_to_load_from_cache

        cached = try_to_load_from_cache(
            repo_id, selected, cache_dir=str(self.cache), revision=str(model["revision"])
        )
        cached_file = isinstance(cached, str) and Path(cached).is_file()
        if not cached_file and shutil.disk_usage(self.cache).free < size + 100_000_000:
            raise ValueError("Insufficient free disk space for the model and download staging")

        try:
            local = Path(
                hf_hub_download(
                    repo_id=repo_id,
                    filename=selected,
                    revision=_string(model["revision"], "revision"),
                    cache_dir=str(self.cache),
                    local_files_only=cached_file,
                )
            ).resolve()
        except httpx.ProxyError as exc:
            status = " (HTTP 403)" if "403" in str(exc) else ""
            raise RuntimeError(
                f"GGUF download was blocked by the network proxy{status}; "
                "allow Hugging Face model CDN access and retry"
            ) from None
        except httpx.HTTPStatusError as exc:
            raise RuntimeError(
                f"GGUF download failed with HTTP {exc.response.status_code}; "
                "check repository access and network availability"
            ) from None
        except Exception as exc:
            raise RuntimeError(
                f"GGUF download failed ({type(exc).__name__}); check network and cache permissions"
            ) from None
        if not local.is_relative_to(self.cache.resolve()) or not local.is_file():
            raise ValueError("Downloaded GGUF file is outside the configured model cache")
        if local.stat().st_size != size:
            raise ValueError("Downloaded GGUF size differs from the pinned model manifest")
        digest = hashlib.sha256()
        with local.open("rb") as stream:
            if stream.read(4) != b"GGUF":
                raise ValueError("Downloaded file does not have a GGUF format header")
            stream.seek(0)
            for block in iter(lambda: stream.read(1_048_576), b""):
                digest.update(block)
        expected = _string(file["sha256"], "checksum") if file["sha256"] else ""
        if expected and digest.hexdigest() != expected:
            raise ValueError("Downloaded GGUF SHA-256 differs from the pinned LFS checksum")
        return model | {
            "filename": selected,
            "size_gb": round(size / 1_000_000_000, 3),
            "cache_path": str(local),
            "downloaded": True,
            "sha256": digest.hexdigest(),
            "checksum_verified": bool(expected),
        }


def install_ollama(download: JsonRow, name: str = "outlook-rag") -> JsonRow:
    """Explicitly import downloaded GGUF into an already-installed, running local Ollama."""
    if not _OLLAMA_NAME.fullmatch(name):
        raise ValueError("Ollama model name must start with a letter and use letters/digits/._-")
    executable = shutil.which("ollama")
    if executable is None:
        raise ValueError("Install and start Ollama before importing the downloaded GGUF")
    model_path = Path(_string(download.get("cache_path"), "cache path")).resolve()
    _safe_filename(_string(download.get("filename", model_path.name), "filename"))
    if not model_path.is_file() or any(character in str(model_path) for character in '\r\n"'):
        raise ValueError("Downloaded GGUF path is invalid for an Ollama Modelfile")
    with model_path.open("rb") as stream:
        if stream.read(4) != b"GGUF":
            raise ValueError("Ollama import requires a verified GGUF file")
    # Forward slashes avoid escape sequences in quoted Windows Modelfile paths.
    with tempfile.TemporaryDirectory(prefix="outlook-rag-ollama-") as directory:
        modelfile = Path(directory) / "Modelfile"
        modelfile.write_text(f'FROM "{model_path.as_posix()}"\n', encoding="utf-8")
        try:
            result = subprocess.run(  # noqa: S603 -- resolved executable and fixed argument list.
                [executable, "create", name, "--file", str(modelfile)],
                check=False,
                capture_output=True,
                text=True,
                timeout=1800,
                env=os.environ | {"OLLAMA_HOST": "127.0.0.1:11434"},
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(f"Ollama model import failed ({type(exc).__name__})") from None
    if result.returncode:
        raise RuntimeError("Ollama rejected the GGUF import; check the running Ollama service")
    return download | {
        "installed_provider_model": name,
        "base_url": "http://127.0.0.1:11434/v1",
        "installed": True,
    }
