"""Render Streamlit and verify persisted metrics rather than checking only a server port."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from config.application import AppConfig, save_config
from project_name.core.records import Email
from project_name.infrastructure.sqlite_store import SQLiteStore


def test_dashboard_metrics_and_agent_controls_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    config = AppConfig.model_validate(
        {
            "tracks": {"track2_enabled": False},
            "storage": {"sqlite_path": str(tmp_path / "metadata.sqlite3")},
        }
    )
    save_config(path, config)
    sql = SQLiteStore(config.storage.sqlite_path)
    sql.upsert_email(
        Email("id", "sender@company.example", "Subject", "2026-01-01", "email.msg", "", ())
    )
    monkeypatch.setenv("EW_CONFIG_PATH", str(path))
    script = Path(__file__).resolve().parents[3] / "src/project_name/dashboard_app.py"
    app = AppTest.from_file(str(script)).run(timeout=20)
    assert not app.exception
    assert app.metric[0].label == "Emails"
    assert app.metric[0].value == "1"
    assert app.metric[3].value == "0"
    assert any("Metadata-only" in item.value for item in app.subheader)
    assert sql.statistics()["growth"]
