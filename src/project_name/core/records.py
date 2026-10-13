"""Shared immutable records; no runtime configuration or adapter dependencies."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from pathlib import Path

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None
type JsonRow = dict[str, JsonValue]


@dataclass(frozen=True)
class Email:
    email_id: str
    sender: str
    subject: str
    received_at: str
    msg_file: str
    body_file: str
    attachments: tuple[str, ...]

    @classmethod
    def from_mapping(cls, row: dict[str, JsonValue]) -> Email:
        required = ["email_id", "sender", "date"]
        if any(not isinstance(row.get(key), str) or not row[key] for key in required):
            raise ValueError("Each email requires string email_id, sender, and ISO date")
        received_at = str(row["date"])
        datetime.fromisoformat(received_at.replace("Z", "+00:00"))
        attachments = row.get("extracted_attachments", [])
        if not isinstance(attachments, list) or any(
            not isinstance(item, str) for item in attachments
        ):
            raise ValueError("extracted_attachments must be a list of relative paths")
        for key in ["subject", "msg_file", "body_file"]:
            if key in row and not isinstance(row[key], str):
                raise ValueError(f"{key} must be a string")
        return cls(
            str(row["email_id"]),
            str(row["sender"]),
            str(row.get("subject", "")),
            received_at,
            str(row.get("msg_file", "")),
            str(row.get("body_file", "")),
            tuple(cast("list[str]", attachments)),
        )

    def metadata(self) -> JsonRow:
        """Strict Track 1 allowlist; legacy body/content fields are never copied."""
        return {
            "email_id": self.email_id,
            "sender": self.sender,
            "subject": self.subject,
            "date": self.received_at,
            "msg_file": self.msg_file,
            "extracted_attachments": list(self.attachments),
        }


@dataclass(frozen=True)
class Document:
    document_id: str
    email_id: str
    source_path: str
    file_type: str
    content_hash: str
    revision: str
    markdown: str


@dataclass(frozen=True)
class Chunk:
    chunk_id: str
    document_id: str
    revision: str
    ordinal: int
    text: str


@dataclass(frozen=True)
class VectorHit:
    chunk_id: str
    distance: float


@dataclass(frozen=True)
class RetrievedChunk:
    chunk: Chunk
    source_path: str
    distance: float


@dataclass(frozen=True)
class Answer:
    text: str
    citations: tuple[str, ...] = ()


@dataclass(frozen=True)
class ParseOptions:
    max_file_bytes: int = 50_000_000
    max_uncompressed_bytes: int = 250_000_000
    max_table_rows: int = 10000
    ocr_language: str = "eng"
    tesseract_command: str = "tesseract"
    ocr_timeout_seconds: int = 120


@dataclass(frozen=True)
class IngestionOptions:
    raw_directory: Path
    processed_directory: Path
    chunk_characters: int = 1500
    chunk_overlap: int = 200
    embedding_signature: str = ""
