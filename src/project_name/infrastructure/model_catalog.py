"""Discover supported ONNX models, check the Hub, and install pinned CPU-validated weights."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

if TYPE_CHECKING:
    from project_name.core.records import JsonRow, JsonValue

_MAX_METADATA_BYTES = 2_000_000
_REPO_PATTERN = re.compile(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+\Z")
_REVISION_PATTERN = re.compile(r"[a-f0-9]{40}\Z")
_TOKENIZER_FILES = (
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "preprocessor_config.json",
)
_MULTILINGUAL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
_GERMAN_LONG = "jinaai/jina-embeddings-v2-base-de"
_ENGLISH_SMALL = "BAAI/bge-small-en-v1.5"


def _receipt_path(model: str, cache: Path) -> Path:
    key = hashlib.sha256(model.encode("utf-8")).hexdigest()
    return cache / "installed" / f"{key}.json"


def _read_receipt(model: str, cache: Path) -> JsonRow | None:
    receipt_path = _receipt_path(model, cache)
    try:
        if receipt_path.stat().st_size > _MAX_METADATA_BYTES:
            return None
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        if not isinstance(receipt, dict) or receipt.get("model") != model:
            return None
        if receipt.get("validated") is not True:
            return None
        revision = receipt.get("revision")
        repo = receipt.get("hf_repo")
        if not isinstance(revision, str) or not _REVISION_PATTERN.fullmatch(revision):
            return None
        if not isinstance(repo, str) or not _REPO_PATTERN.fullmatch(repo):
            return None
        path = receipt.get("relative_path")
        files = receipt.get("files")
        if not isinstance(path, str) or not isinstance(files, dict) or not files:
            return None
        snapshot = (cache / path).resolve()
        snapshot.relative_to(cache.resolve())
        if snapshot.name != revision or snapshot.parent.name != "snapshots":
            return None
        if snapshot.parent.parent.name != f"models--{repo.replace('/', '--')}":
            return None
        for name, size in files.items():
            if not isinstance(name, str) or not isinstance(size, int) or size <= 0:
                return None
            file = (snapshot / name).resolve()
            file.relative_to(cache.resolve())
            if file.stat().st_size != size:
                return None
        receipt["path"] = str(snapshot)
        return cast("JsonRow", receipt)
    except (OSError, ValueError, TypeError):
        return None


def installed_model_path(model: str, cache: Path) -> Path | None:
    """Return the validated pinned snapshot only while its recorded files remain present."""
    receipt = _read_receipt(model, cache)
    return Path(str(receipt["path"])) if receipt else None


def installed_model_revision(model: str, cache: Path) -> str | None:
    """Expose the installed revision for ingestion signatures and reproducible retrieval."""
    receipt = _read_receipt(model, cache)
    return str(receipt["revision"]) if receipt else None


def _write_receipt(path: Path, receipt: JsonRow) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as handle:
            temporary = Path(handle.name)
            json.dump(receipt, handle, indent=2, ensure_ascii=False, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _recommendation(model: str, language: str) -> tuple[int, str]:
    if model == _MULTILINGUAL:
        rank = 0 if language in {"de", "multilingual"} else 2
        return rank, (
            "Lightweight German/multilingual CPU option (~50 languages). "
            "128-token truncation: use short chunks; evaluate retrieval on your documents."
        )
    if model == _GERMAN_LONG:
        return 1, (
            "German/English alternative with 8192-token context. Larger CPU memory/download "
            "cost; FastEmbed 0.9 uses FP32 weights."
        )
    if model == _ENGLISH_SMALL:
        rank = 0 if language == "en" else 2
        return rank, "Small English CPU baseline; 512-token context. Not a German recommendation."
    return 100, ""


class ModelCatalog:
    """Use the installed SDK registry as the compatibility boundary, never arbitrary Hub code."""

    def __init__(self, cache: Path, *, client: httpx.Client | None = None) -> None:
        self.cache = cache.resolve()
        self._client = client

    def list_models(self, *, language: str = "de", online: bool = False) -> list[JsonRow]:
        if language not in {"de", "en", "multilingual"}:
            raise ValueError("Recommendation language must be de, en, or multilingual")
        from fastembed import TextEmbedding

        records = []
        for description in TextEmbedding.list_supported_models():
            model = str(description["model"])
            source = description.get("sources", {}).get("hf")
            if not isinstance(source, str) or not _REPO_PATTERN.fullmatch(source):
                continue
            model_file = str(description["model_file"])
            extra = description.get("additional_files", [])
            if not isinstance(extra, list) or any(not isinstance(name, str) for name in extra):
                raise ValueError(f"Unsupported file metadata for model {model}")
            rank, recommendation = _recommendation(model, language)
            receipt = _read_receipt(model, self.cache)
            record: JsonRow = {
                "model": model,
                "hf_repo": source,
                "dim": int(description["dim"]),
                "size_gb": float(description["size_in_GB"]),
                "license": str(description["license"]),
                "description": str(description["description"]),
                "model_file": model_file,
                "additional_files": list(extra),
                "recommendation": recommendation,
                "recommendation_rank": rank,
                "live_status": "not_checked",
                "installed": receipt is not None,
                "installed_revision": str(receipt["revision"]) if receipt else "",
            }
            records.append(record)
        records.sort(key=lambda row: (int(str(row["recommendation_rank"])), str(row["model"])))
        if online:
            with ThreadPoolExecutor(max_workers=4) as executor:
                return list(executor.map(self._verify, records))
        return records

    def _supported(self, model: str) -> JsonRow:
        for row in self.list_models():
            if row["model"] == model:
                return row
        raise ValueError(f"Model is not supported by the installed FastEmbed SDK: {model}")

    def check(self, model: str) -> JsonRow:
        """Verify the current repository, revision, license, and required ONNX filenames."""
        return self._verify(self._supported(model))

    def _verify(self, row: JsonRow) -> JsonRow:
        result = dict(row)
        url = f"https://huggingface.co/api/models/{row['hf_repo']}"
        try:
            if self._client is not None:
                payload = self._read_metadata(self._client, url)
            else:
                with httpx.Client(timeout=15, follow_redirects=False) as client:
                    payload = self._read_metadata(client, url)
            revision = payload.get("sha")
            siblings = payload.get("siblings")
            if str(payload.get("id", "")).casefold() != str(row["hf_repo"]).casefold():
                raise ValueError("Hub metadata repository does not match the requested model")
            if not isinstance(revision, str) or not _REVISION_PATTERN.fullmatch(revision):
                raise ValueError("Hub metadata did not provide a valid commit SHA")
            if not isinstance(siblings, list):
                raise ValueError("Hub metadata did not provide repository filenames")
            filenames = {
                item.get("rfilename")
                for item in siblings
                if isinstance(item, dict) and isinstance(item.get("rfilename"), str)
            }
            expected = [str(row["model_file"])]
            additional = row["additional_files"]
            if isinstance(additional, list):
                expected.extend(str(name) for name in additional)
            missing: list[JsonValue] = [name for name in expected if name not in filenames]
            restricted = bool(payload.get("gated")) or bool(payload.get("private"))
            result.update(
                live_status=(
                    "restricted" if restricted else "missing_files" if missing else "verified"
                ),
                revision=revision,
                gated=bool(payload.get("gated")),
                missing_files=missing,
                checked_at=datetime.now(UTC).isoformat(),
            )
            card = payload.get("cardData")
            if isinstance(card, dict) and isinstance(card.get("license"), str):
                result["hub_license"] = str(card["license"])
            if payload.get("disabled") is True:
                result.update(live_status="unavailable", live_error="Hub repository is disabled")
        except httpx.HTTPStatusError as exc:
            result.update(
                live_status="unavailable",
                live_error=f"Hugging Face returned HTTP {exc.response.status_code}",
            )
        except (httpx.HTTPError, ValueError, TypeError) as exc:
            result.update(
                live_status="unavailable", live_error=f"Hub check failed: {type(exc).__name__}"
            )
        return result

    @staticmethod
    def _read_metadata(client: httpx.Client, url: str) -> dict[str, object]:
        with client.stream("GET", url, timeout=15, follow_redirects=False) as response:
            response.raise_for_status()
            payload = bytearray()
            for block in response.iter_bytes():
                payload.extend(block)
                if len(payload) > _MAX_METADATA_BYTES:
                    raise ValueError("Hub metadata exceeds the size limit")
        value = json.loads(payload)
        if not isinstance(value, dict):
            raise ValueError("Hub metadata must be an object")
        return cast("dict[str, object]", value)

    def download(self, model: str, *, max_size_gb: float = 1.0) -> JsonRow:
        """Install verified compatible weights; publish a receipt after real CPU validation."""
        row = self.check(model)
        if row["live_status"] != "verified":
            raise ValueError(
                f"Model cannot be downloaded: {row['live_status']}; {row.get('live_error', '')}"
            )
        size = float(str(row["size_gb"]))
        if not math.isfinite(max_size_gb) or max_size_gb <= 0 or size > max_size_gb:
            raise ValueError(
                f"Model needs approximately {size:g} GB; increase the explicit size limit "
                f"from {max_size_gb:g} GB to accept this download"
            )
        self.cache.mkdir(parents=True, exist_ok=True)
        required_space = int(size * 1_000_000_000 * 2) + 100_000_000
        if shutil.disk_usage(self.cache).free < required_space:
            raise OSError(f"Model installation requires at least {required_space} free bytes")
        from fastembed import TextEmbedding
        from huggingface_hub import snapshot_download

        patterns = [*_TOKENIZER_FILES, str(row["model_file"])]
        additional = row["additional_files"]
        if isinstance(additional, list):
            patterns.extend(str(name) for name in additional)
        try:
            snapshot = Path(
                snapshot_download(
                    repo_id=str(row["hf_repo"]),
                    revision=str(row["revision"]),
                    allow_patterns=patterns,
                    cache_dir=str(self.cache),
                    max_workers=2,
                    etag_timeout=15,
                )
            ).resolve()
            snapshot.relative_to(self.cache)
            engine = TextEmbedding(
                model_name=model,
                cache_dir=str(self.cache),
                specific_model_path=str(snapshot),
                local_files_only=True,
                threads=2,
                cuda=False,
            )
            vectors = list(engine.embed(["Model installation validation."]))
            dimension = int(str(row["dim"]))
            if (
                len(vectors) != 1
                or len(vectors[0]) != dimension
                or any(not math.isfinite(float(value)) for value in vectors[0])
            ):
                raise ValueError("Downloaded model failed CPU embedding validation")
            required = [str(row["model_file"])]
            if isinstance(additional, list):
                required.extend(str(name) for name in additional)
            required.extend(name for name in _TOKENIZER_FILES if (snapshot / name).is_file())
            files: JsonRow = {}
            for name in required:
                file = (snapshot / name).resolve()
                file.relative_to(self.cache)
                size_bytes = file.stat().st_size
                if size_bytes <= 0:
                    raise ValueError("Downloaded model file is empty")
                files[name] = size_bytes
            receipt: JsonRow = {
                "model": model,
                "hf_repo": row["hf_repo"],
                "revision": row["revision"],
                "license": row.get("hub_license", row["license"]),
                "path": str(snapshot),
                "relative_path": snapshot.relative_to(self.cache).as_posix(),
                "dim": dimension,
                "files": files,
                "validated": True,
                "validated_at": datetime.now(UTC).isoformat(),
            }
            _write_receipt(_receipt_path(model, self.cache), receipt)
            return receipt
        except (OSError, ValueError):
            raise
        except httpx.ProxyError as exc:
            status = " (HTTP 403)" if "403" in str(exc) else ""
            raise RuntimeError(
                f"Model download was blocked by the network proxy{status}. "
                "Allow huggingface.co and its model-download CDN (such as us.aws.cdn.hf.co), "
                "then retry. No validated installation was published."
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Model download or validation failed: {type(exc).__name__}"
            ) from exc
