"""Verify the exported catalog feeds the actual CLI ingestion composition."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from config.application import AppConfig, save_config
from project_name.application import Runtime
from project_name.cli import build_parser, execute
from project_name.infrastructure.sqlite_store import SQLiteStore
from tests.support import TestEmbedder

if TYPE_CHECKING:
    from pathlib import Path


def test_catalog_to_ingestion_cli_preserves_metadata_privacy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    raw = tmp_path / "data/raw"
    email = raw / "Mail/2026/01/2026-01-01_Renewal_company_12345678"
    technical = email / "_rag"
    technical.mkdir(parents=True)
    (email / "Email.msg").write_bytes(b"synthetic archival fixture")
    (email / "Email.txt").write_text("Confidential contract renewal details.")
    relative = email.relative_to(raw).as_posix()
    (technical / "metadata.json").write_text(
        json.dumps(
            {
                "schema_version": 3,
                "email_id": "20260101_100000_12345678",
                "source_key": "synthetic-store:synthetic-entry",
                "sender": "client@company.example",
                "subject": "Verlängerung",
                "date": "2026-01-01T10:00:00",
                "msg_file": f"{relative}/Email.msg",
                "body_file": f"{relative}/Email.txt",
                "extracted_attachments": [],
                "outlook_folder": "\\Mailbox\\Projects",
                "body": "Legacy confidential body must never enter metadata indexes.",
            }
        )
    )
    (technical / "complete.txt").write_text("completed synthetic export")
    config = tmp_path / "config.yaml"
    save_config(config, AppConfig())
    parser = build_parser()
    execute(parser.parse_args(["--config", str(config), "catalog", "--batch-size", "1"]))
    report = json.loads(capsys.readouterr().out)
    assert report["emails"] == 1
    assert report["max_batch_rows"] == 1
    manifest = raw / "Master_Index.jsonl"
    assert "confidential" not in manifest.read_text().lower()
    assert "confidential" not in (raw / "Master_Context.md").read_text().lower()
    monkeypatch.setattr(Runtime, "embedder", lambda _runtime: TestEmbedder())
    execute(parser.parse_args(["--config", str(config), "ingest", "--manifest", str(manifest)]))
    ingestion = json.loads(capsys.readouterr().out)
    assert ingestion["synchronized"] == 1
    assert ingestion["errors"] == []
    sql = SQLiteStore(tmp_path / "data/outlook.sqlite3")
    assert sql.query("SELECT count(*) AS count FROM mcp_documents") == [{"count": 1}]
    execute(parser.parse_args(["--config", str(config), "ingest", "--manifest", str(manifest)]))
    assert json.loads(capsys.readouterr().out)["unchanged"] == 1
    (technical / "complete.txt").unlink()
    with pytest.raises(SystemExit) as exception:
        execute(parser.parse_args(["--config", str(config), "catalog"]))
    assert exception.value.code == 1
    assert json.loads(capsys.readouterr().out)["incomplete"] == 1


def test_metadata_cli_rejects_large_mailbox_manifest_before_provider_access(tmp_path: Path) -> None:
    config = tmp_path / "config.yaml"
    save_config(config, AppConfig())
    manifest = tmp_path / "huge.jsonl"
    with manifest.open("wb") as stream:
        stream.truncate(20_000_001)
    args = build_parser().parse_args(
        [
            "--config",
            str(config),
            "ask",
            "Count emails",
            "--track",
            "1",
            "--metadata-file",
            str(manifest),
        ]
    )
    with pytest.raises(ValueError, match="20 MB"):
        execute(args)
