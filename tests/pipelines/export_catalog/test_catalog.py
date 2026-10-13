"""Exercise disk cataloging, bounded batches, identity, privacy, and publication recovery."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import duckdb
import pytest

from pipelines.export_catalog.catalog import CatalogError, build_catalog, recover_catalog

_CRASH_PUBLICATION = """
import os
import sys
from pathlib import Path
from pipelines.export_catalog.catalog import build_catalog

replace = Path.replace
def crashing_replace(source, destination):
    result = replace(source, destination)
    if source.parent.name.startswith('.catalog-') and source.name == sys.argv[2]:
        os._exit(77)
    return result
Path.replace = crashing_replace
build_catalog(Path(sys.argv[1]))
"""


def crash_publication(root: Path, after: str = "Master_Index.jsonl") -> None:
    process = subprocess.run(  # noqa: S603 - fixed local test program; no shell or untrusted code.
        [sys.executable, "-c", _CRASH_PUBLICATION, str(root), after],
        check=False,
        timeout=30,
        capture_output=True,
        text=True,
    )
    assert process.returncode == 77, process.stderr
    # The child has exited, so its PID lock is now demonstrably stale.
    (root / "_rag/catalog.lock").unlink()


def make_sidecar(
    root: Path,
    email_id: str,
    *,
    legacy: bool = False,
    complete: bool = True,
    source_key: str = "store:entry",
) -> Path:
    folder = root / (f"2026/01/{email_id}" if legacy else f"Mail/2026/01/{email_id}")
    technical = folder if legacy else folder / "_rag"
    technical.mkdir(parents=True)
    (folder / "Email.msg").write_bytes(b"fixture message")
    (folder / "Email.txt").write_text("PRIVATE_BODY_SECRET", encoding="utf-8")
    attachments = folder / "Attachments"
    attachments.mkdir()
    (attachments / "001 Bericht.txt").write_text("PRIVATE_ATTACHMENT_SECRET", encoding="utf-8")
    prefix = folder.relative_to(root).as_posix()
    payload = {
        "schema_version": 2 if legacy else 3,
        "email_id": email_id,
        "sender": "büro@company.example",
        "subject": "Angebot München \u2013 更新",
        "date": "2026-01-01T10:00:00",
        "msg_file": f"{prefix}/Email.msg",
        "body_file": f"{prefix}/Email.txt",
        "extracted_attachments": [f"{prefix}/Attachments/001 Bericht.txt"],
        "outlook_folder": "Mailbox/Customers/München",
        "source_key": source_key,
        "body": "PRIVATE_LEGACY_BODY_SECRET",
        "attachment_contents": "PRIVATE_LEGACY_ATTACHMENT_SECRET",
    }
    sidecar = technical / "metadata.json"
    sidecar.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    if complete:
        (technical / "complete.txt").write_text("done", encoding="utf-8")
    return sidecar


def test_unicode_privacy_catalog_and_deterministic_repeat(tmp_path: Path) -> None:
    make_sidecar(tmp_path, "email-b")
    make_sidecar(tmp_path, "email-a", legacy=True, source_key="legacy:entry")
    report = build_catalog(tmp_path, batch_size=1)
    assert (report.records, report.emails, report.duplicates, report.incomplete) == (2, 2, 0, 0)
    assert report.max_batch_rows == 1
    first_index = report.index_file.read_bytes()
    first_context = report.context_file.read_bytes()
    assert b"PRIVATE_" not in first_index + first_context
    payloads = [json.loads(line) for line in first_index.decode().splitlines()]
    assert [row["email_id"] for row in payloads] == ["email-a", "email-b"]
    assert payloads[0]["subject"] == "Angebot München \u2013 更新"
    assert payloads[0]["body_file"].endswith("Email.txt")
    assert "source_key" not in payloads[0]
    assert payloads[0]["source_folder"] == "Mailbox/Customers/München"
    with duckdb.connect(str(report.database_file), read_only=True) as catalog:
        result = catalog.execute("SELECT count(*) FROM metadata_emails").fetchone()
        assert result is not None
        assert result[0] == 2
        columns = {row[0] for row in catalog.execute("DESCRIBE metadata_emails").fetchmany(20)}
        assert "body" not in columns
        assert "source_key" not in columns
    repeat = build_catalog(tmp_path, batch_size=2)
    assert repeat.generation != report.generation
    assert repeat.index_file.read_bytes() == first_index
    assert repeat.context_file.read_bytes() == first_context


def test_duplicate_identity_across_batches_and_conflict_preserves_outputs(tmp_path: Path) -> None:
    original = make_sidecar(tmp_path, "same-email")
    duplicate = tmp_path / "copied-sidecar"
    duplicate.mkdir()
    shutil.copyfile(original, duplicate / "metadata.json")
    shutil.copyfile(original.parent / "complete.txt", duplicate / "complete.txt")
    report = build_catalog(tmp_path, batch_size=1)
    assert (report.records, report.emails, report.duplicates) == (2, 1, 1)
    before = report.index_file.read_bytes()
    payload = json.loads((duplicate / "metadata.json").read_text(encoding="utf-8"))
    payload["source_key"] = "another-store:another-entry"
    (duplicate / "metadata.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CatalogError, match="Conflicting export identity"):
        build_catalog(tmp_path, batch_size=1)
    assert report.index_file.read_bytes() == before
    assert not (tmp_path / "_rag/catalog.lock").exists()
    with duckdb.connect(str(report.database_file), read_only=True) as catalog:
        row = catalog.execute("SELECT source_key FROM emails").fetchone()
        assert row is not None
        assert row[0] == "store:entry"


def test_incomplete_exports_are_reported_and_never_read(tmp_path: Path) -> None:
    make_sidecar(tmp_path, "ready")
    incomplete = make_sidecar(tmp_path, "unfinished", complete=False)
    incomplete.write_text("invalid unfinished JSON", encoding="utf-8")
    # Marker must be checked before parsing unfinished JSON written by a running export.
    report = build_catalog(tmp_path)
    assert report.incomplete == 1
    assert not report.complete
    assert report.emails == 1
    generation = json.loads(report.generation_file.read_text(encoding="utf-8"))
    assert generation["complete"] is False
    assert generation["incomplete"] == 1
    assert "Partial export: 1 unfinished" in report.context_file.read_text(encoding="utf-8")


@pytest.mark.parametrize("bad_path", ["../secret.txt", "C:\\secret.txt", "/secret.txt"])
def test_unsafe_artifact_paths_do_not_replace_outputs(tmp_path: Path, bad_path: str) -> None:
    sidecar = make_sidecar(tmp_path, "one")
    report = build_catalog(tmp_path)
    previous = report.index_file.read_bytes()
    payload = json.loads(sidecar.read_text(encoding="utf-8"))
    payload["body_file"] = bad_path
    sidecar.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(CatalogError, match="Artifact path"):
        build_catalog(tmp_path)
    assert report.index_file.read_bytes() == previous


def test_export_lock_publication_marker_and_symlink_guards(tmp_path: Path) -> None:
    make_sidecar(tmp_path, "one")
    (tmp_path / "export.lock").write_text("locked")
    with pytest.raises(CatalogError, match=r"export\.lock"):
        build_catalog(tmp_path)
    (tmp_path / "export.lock").unlink()
    technical = tmp_path / "_rag"
    technical.mkdir()
    (technical / "catalog_publication.json").write_text("interrupted")
    with pytest.raises(CatalogError, match="Interrupted catalog"):
        build_catalog(tmp_path)
    (technical / "catalog_publication.json").unlink()
    root_alias = tmp_path / "alias"
    root_alias.symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(CatalogError, match="symbolic link"):
        build_catalog(root_alias)
    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()
    make_sidecar(outside, "outside")
    (tmp_path / "linked-folder").symlink_to(outside, target_is_directory=True)
    assert build_catalog(tmp_path).emails == 1


def test_large_catalog_uses_bounded_batches(tmp_path: Path) -> None:
    for number in range(67):
        make_sidecar(tmp_path, f"email-{number:04}", source_key=f"store:{number}")
    report = build_catalog(tmp_path, batch_size=8)
    assert report.emails == report.records == 67
    assert report.max_batch_rows == 8
    with duckdb.connect(str(report.database_file), read_only=True) as catalog:
        result = catalog.execute("SELECT sum(len(extracted_attachments)) FROM emails").fetchone()
        assert result is not None
        assert result[0] == 67
    assert len(report.index_file.read_text(encoding="utf-8").splitlines()) == 67


def test_failed_publication_rolls_back_database_index_context_and_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_sidecar(tmp_path, "old-email")
    report = build_catalog(tmp_path)
    old_index = report.index_file.read_bytes()
    old_context = report.context_file.read_bytes()
    old_generation = report.generation_file.read_bytes()
    make_sidecar(tmp_path, "new-email", source_key="store:new")
    real_replace = Path.replace

    def interrupted_replace(source: Path, target: str | Path) -> Path:
        if source.name == "Master_Context.md" and source.parent.name.startswith(".catalog-"):
            raise OSError("Simulated publication failure")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", interrupted_replace)
    with pytest.raises(OSError, match="Simulated publication failure"):
        build_catalog(tmp_path)
    assert report.index_file.read_bytes() == old_index
    assert report.context_file.read_bytes() == old_context
    assert report.generation_file.read_bytes() == old_generation
    with duckdb.connect(str(report.database_file), read_only=True) as catalog:
        result = catalog.execute("SELECT email_id FROM emails").fetchone()
        assert result is not None
        assert result[0] == "old-email"
    assert not (tmp_path / "_rag/catalog_publication.json").exists()
    assert not (tmp_path / "_rag/catalog.lock").exists()


def test_actual_killed_publisher_recovers_previous_generation(tmp_path: Path) -> None:
    make_sidecar(tmp_path, "old-email")
    previous = build_catalog(tmp_path)
    old_index = previous.index_file.read_bytes()
    old_context = previous.context_file.read_bytes()
    old_generation = previous.generation_file.read_bytes()
    old_mode = previous.index_file.stat().st_mode
    make_sidecar(tmp_path, "new-email", source_key="store:new")
    crash_publication(tmp_path)
    assert previous.index_file.read_bytes() != old_index
    with pytest.raises(CatalogError, match="Interrupted catalog"):
        build_catalog(tmp_path)
    recovered = recover_catalog(tmp_path)
    assert recovered.recovered
    assert recovered.restored == 4
    assert recovered.removed == 0
    assert previous.index_file.read_bytes() == old_index
    assert previous.context_file.read_bytes() == old_context
    assert previous.generation_file.read_bytes() == old_generation
    assert previous.index_file.stat().st_mode == old_mode
    with duckdb.connect(str(previous.database_file), read_only=True) as catalog:
        result = catalog.execute("SELECT email_id FROM emails").fetchone()
        assert result is not None
        assert result[0] == "old-email"
    assert not (tmp_path / "_rag/catalog_publication.json").exists()
    assert not recover_catalog(tmp_path).recovered
    assert not list(tmp_path.glob(".*.bak"))
    assert not list((tmp_path / "_rag").glob(".*.bak"))


def test_journal_publication_failure_cannot_publish_any_new_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_sidecar(tmp_path, "old-email")
    previous = build_catalog(tmp_path)
    old_index = previous.index_file.read_bytes()
    old_generation = previous.generation_file.read_bytes()
    make_sidecar(tmp_path, "new-email", source_key="store:new")
    real_replace = Path.replace

    def fail_journal_publication(source: Path, target: str | Path) -> Path:
        if source.name == "catalog_publication.json":
            raise OSError("Journal could not be atomically published")
        return real_replace(source, target)

    monkeypatch.setattr(Path, "replace", fail_journal_publication)
    with pytest.raises(OSError, match="Journal could not be atomically published"):
        build_catalog(tmp_path)
    assert previous.index_file.read_bytes() == old_index
    assert previous.generation_file.read_bytes() == old_generation
    assert not (tmp_path / "_rag/catalog_publication.json").exists()
    assert not recover_catalog(tmp_path).recovered


def test_recovery_interrupted_halfway_retries_from_preserved_backups(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_sidecar(tmp_path, "old-email")
    previous = build_catalog(tmp_path)
    old_index = previous.index_file.read_bytes()
    old_context = previous.context_file.read_bytes()
    old_generation = previous.generation_file.read_bytes()
    make_sidecar(tmp_path, "new-email", source_key="store:new")
    crash_publication(tmp_path, after="Master_Context.md")
    real_replace = Path.replace

    def fail_second_restore(source: Path, target: str | Path) -> Path:
        if source.name.startswith(".Master_Index.jsonl.recover-"):
            raise OSError("Simulated interruption during recovery")
        return real_replace(source, target)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "replace", fail_second_restore)
        with pytest.raises(OSError, match="Simulated interruption during recovery"):
            recover_catalog(tmp_path)
    marker = tmp_path / "_rag/catalog_publication.json"
    assert marker.exists()
    backups = json.loads(marker.read_text())["backups"]
    assert all(Path(entry["backup"]).is_file() for entry in backups)
    assert previous.index_file.read_bytes() != old_index
    assert recover_catalog(tmp_path).restored == 4
    assert previous.index_file.read_bytes() == old_index
    assert previous.context_file.read_bytes() == old_context
    assert previous.generation_file.read_bytes() == old_generation


@pytest.mark.parametrize("tamper", ["destination", "backup", "duplicate", "link"])
def test_recovery_rejects_tampered_journal_before_any_output_write(
    tmp_path: Path, tamper: str
) -> None:
    make_sidecar(tmp_path, "one")
    previous = build_catalog(tmp_path)
    destinations = [
        previous.database_file,
        previous.index_file,
        previous.context_file,
        previous.generation_file,
    ]
    before = {path: path.read_bytes() for path in destinations}
    entries = []
    for destination in destinations:
        backup = destination.with_name(f".{destination.name}.{'0' * 32}.bak")
        shutil.copyfile(destination, backup)
        entries.append({"destination": str(destination), "backup": str(backup)})
    victim = tmp_path.parent / f"{tmp_path.name}-victim"
    victim.write_text("do not touch")
    if tamper == "destination":
        entries[3]["destination"] = str(victim)
    elif tamper == "backup":
        entries[3]["backup"] = str(victim)
    elif tamper == "duplicate":
        entries[3] = entries[0].copy()
    else:
        backup = Path(entries[3]["backup"])
        backup.unlink()
        backup.symlink_to(victim)
    marker = tmp_path / "_rag/catalog_publication.json"
    marker.write_text(json.dumps({"state": "publishing", "backups": entries}))
    with pytest.raises(CatalogError):
        recover_catalog(tmp_path)
    assert marker.exists()
    assert victim.read_text() == "do not touch"
    assert all(path.read_bytes() == before[path] for path in destinations)
    assert not (tmp_path / "_rag/catalog.lock").exists()


def test_recovery_of_initial_publication_removes_only_known_catalog_outputs(tmp_path: Path) -> None:
    make_sidecar(tmp_path, "one")
    retained = tmp_path / "user-notes.txt"
    retained.write_text("keep me")
    crash_publication(tmp_path)
    assert (tmp_path / "Master_Index.jsonl").is_file()
    recovered = recover_catalog(tmp_path)
    assert recovered.recovered
    assert recovered.restored == 0
    assert recovered.removed == 2
    assert retained.read_text() == "keep me"
    assert not (tmp_path / "Master_Index.jsonl").exists()
    assert not (tmp_path / "_rag/catalog.duckdb").exists()
    assert not (tmp_path / "_rag/catalog_publication.json").exists()


def test_recovery_refuses_export_or_catalog_lock(tmp_path: Path) -> None:
    make_sidecar(tmp_path, "one")
    report = build_catalog(tmp_path)
    previous = report.index_file.read_bytes()
    export_lock = tmp_path / "export.lock"
    export_lock.write_text("active")
    with pytest.raises(CatalogError, match=r"export\.lock"):
        recover_catalog(tmp_path)
    export_lock.unlink()
    catalog_lock = tmp_path / "_rag/catalog.lock"
    catalog_lock.write_text("active or stale - operator must check")
    with pytest.raises(CatalogError, match="Catalog lock exists"):
        recover_catalog(tmp_path)
    assert catalog_lock.exists()
    assert report.index_file.read_bytes() == previous
