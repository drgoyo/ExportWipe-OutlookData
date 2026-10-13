"""Typed central YAML configuration, environment overrides, and VBA export settings."""

from __future__ import annotations

import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal, Self

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from config.settings import Settings


class ConfigurationModel(BaseModel):
    """Reject unknown keys and validate assignment at configuration boundaries."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class ExtractionConfig(ConfigurationModel):
    output_directory: Path = Path("data/raw")
    filter_date: date = date(2026, 1, 1)
    older_than_date: bool = True
    date_filter_mode: Literal[0, 1, 2] = 0
    process_all_subfolders: bool = True
    minimum_attachment_bytes: int = Field(default=0, ge=0, le=2_147_483_647)
    exclude_freemail: bool = True
    freemail_domains: list[str] = Field(
        default_factory=lambda: [
            "gmail.com",
            "googlemail.com",
            "outlook.com",
            "hotmail.com",
            "live.com",
            "web.de",
            "gmx.de",
            "gmx.net",
            "gmx.com",
            "yahoo.com",
            "yahoo.de",
            "icloud.com",
            "me.com",
            "mac.com",
            "t-online.de",
            "freenet.de",
            "aol.com",
        ]
    )
    archive_pst: Literal[False] = False
    deletion_mode: Literal[0, 1, 2] = 0
    allow_destructive: bool = False

    @field_validator("freemail_domains")
    @classmethod
    def validate_domains(cls, values: list[str]) -> list[str]:
        result = []
        for domain in values:
            domain = domain.strip().lower()
            if not domain or "." not in domain or any(c in domain for c in "@/\\,\r\n ="):
                raise ValueError("Freemail entries must be exact DNS domains")
            result.append(domain)
        return sorted(set(result))

    @field_validator("output_directory")
    @classmethod
    def validate_ini_path(cls, value: Path) -> Path:
        if any(c in str(value) for c in "\r\n"):
            raise ValueError("Output directory cannot contain a newline")
        return value


class TrackConfig(ConfigurationModel):
    track1_enabled: bool = True
    track2_enabled: bool = True


class ParsingConfig(ConfigurationModel):
    output_directory: Path = Path("data/processed")
    max_file_bytes: int = Field(default=50_000_000, gt=0)
    max_uncompressed_bytes: int = Field(default=250_000_000, gt=0)
    max_table_rows: int = Field(default=10_000, gt=0)
    ocr_language: str = "eng"
    tesseract_command: str = "tesseract"
    ocr_timeout_seconds: int = Field(default=120, gt=0, le=3600)

    @field_validator("ocr_language")
    @classmethod
    def validate_language(cls, value: str) -> str:
        if not value or not all(c.isalnum() or c in "+_" for c in value):
            raise ValueError("Use Tesseract language codes such as eng or eng+deu")
        return value


class StorageConfig(ConfigurationModel):
    sqlite_path: Path = Path("data/outlook.sqlite3")
    chroma_directory: Path = Path("data/chroma")
    chroma_host: str = ""
    chroma_port: int = Field(default=8000, ge=1, le=65535)
    chroma_ssl: bool = False
    collection: str = Field(
        default="outlook_documents", pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{1,60}[A-Za-z0-9]$"
    )
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    model_cache: Path = Path("data/models")
    chunk_characters: int = Field(default=1500, ge=100, le=10000)
    chunk_overlap: int = Field(default=200, ge=0)

    @model_validator(mode="after")
    def validate_overlap(self) -> Self:
        if self.chunk_overlap >= self.chunk_characters:
            raise ValueError("Chunk overlap must be smaller than the chunk size")
        return self


class LLMConfig(ConfigurationModel):
    base_url: str = "http://127.0.0.1:11434/v1"
    model: str = "llama3.2"
    timeout_seconds: int = Field(default=120, gt=0, le=3600)
    max_context_characters: int = Field(default=24000, ge=1000, le=500000)

    @field_validator("base_url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("LLM URL cannot contain credentials, query, or fragment")
        local = parsed.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal"}
        if parsed.scheme != "https" and not (parsed.scheme == "http" and local):
            raise ValueError("Use HTTPS for remote providers or HTTP for a local model")
        return value.rstrip("/")


class AppConfig(ConfigurationModel):
    schema_version: Literal[1] = 1
    extraction: ExtractionConfig = Field(default_factory=ExtractionConfig)
    tracks: TrackConfig = Field(default_factory=TrackConfig)
    parsing: ParsingConfig = Field(default_factory=ParsingConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)

    @model_validator(mode="after")
    def validate_routes(self) -> Self:
        if not (self.tracks.track1_enabled or self.tracks.track2_enabled):
            raise ValueError("Enable at least one track")
        if self.extraction.deletion_mode != 0:
            if not self.extraction.allow_destructive:
                raise ValueError("Cleanup requires allow_destructive=true")
            if not self.tracks.track2_enabled:
                raise ValueError("Cleanup requires Track 2 and a complete MSG backup")
        return self


class RuntimeEnvironment(Settings):
    """Optional overrides and credentials loaded only in the outer application boundary."""

    model_config = SettingsConfigDict(
        env_prefix="EW_", env_file=".env", extra="ignore", frozen=True
    )
    llm_api_key: SecretStr = SecretStr("")
    api_token: SecretStr = SecretStr("")
    raw_dir: Path | None = None
    processed_dir: Path | None = None
    sqlite_path: Path | None = None
    chroma_dir: Path | None = None
    chroma_host: str | None = None
    chroma_port: int | None = None
    model_cache: Path | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None

    def __init__(self, *, env_file: Path | None = None) -> None:
        BaseSettings.__init__(self, _env_file=env_file or ".env")


def load_config(path: Path, *, environment: bool = True) -> AppConfig:
    """Load safe YAML, apply environment overrides, and resolve paths to the YAML root."""
    if path.exists():
        if path.stat().st_size > 1_000_000:
            raise ValueError("Configuration exceeds 1 MB")
        payload = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
        if not isinstance(payload, dict):
            raise ValueError("Configuration must be a YAML mapping")
        config = AppConfig.model_validate(payload)
    else:
        raise FileNotFoundError(f"Configuration not found: {path}; run init-config first")
    data = config.model_dump(mode="json")
    if environment:
        overrides = RuntimeEnvironment(env_file=path.resolve().parent / ".env")
        for name, section, key in [
            ("raw_dir", "extraction", "output_directory"),
            ("processed_dir", "parsing", "output_directory"),
            ("sqlite_path", "storage", "sqlite_path"),
            ("chroma_dir", "storage", "chroma_directory"),
            ("chroma_host", "storage", "chroma_host"),
            ("chroma_port", "storage", "chroma_port"),
            ("model_cache", "storage", "model_cache"),
            ("llm_base_url", "llm", "base_url"),
            ("llm_model", "llm", "model"),
        ]:
            value = getattr(overrides, name)
            if value is not None:
                data[section][key] = str(value) if isinstance(value, Path) else value
    for section, key in [
        ("extraction", "output_directory"),
        ("parsing", "output_directory"),
        ("storage", "sqlite_path"),
        ("storage", "chroma_directory"),
        ("storage", "model_cache"),
    ]:
        value = Path(data[section][key]).expanduser()
        data[section][key] = str(
            value.resolve() if value.is_absolute() else (path.resolve().parent / value).resolve()
        )
    return AppConfig.model_validate(data)


def atomic_write(path: Path, text: str) -> None:
    """Replace only after a complete flushed write, without truncating an existing user file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def save_config(path: Path, config: AppConfig) -> None:
    atomic_write(
        path, yaml.safe_dump(config.model_dump(mode="json"), sort_keys=False, allow_unicode=True)
    )


def write_vba_ini(path: Path, config: AppConfig) -> None:
    """Export only macro settings, never provider secrets or content."""
    values = config.extraction.model_dump(mode="json")
    values["freemail_domains"] = ",".join(config.extraction.freemail_domains)
    values.update(config.tracks.model_dump())
    lines = ["# Generated by Outlook RAG. No credentials are included."]
    for key, value in values.items():
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        if "\n" in rendered or "\r" in rendered:
            raise ValueError(f"Newlines are forbidden in INI value {key}")
        lines.append(f"{key}={rendered}")
    atomic_write(path, "\n".join(lines) + "\n")
