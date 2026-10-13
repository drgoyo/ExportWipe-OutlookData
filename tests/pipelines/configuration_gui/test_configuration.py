"""Central settings and editor conversion tests independent of a graphical display."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from config.application import AppConfig, load_config, save_config, write_vba_ini
from pipelines.configuration_gui.editor import FIELDS, apply_form, flatten_values


def test_yaml_roundtrip_paths_and_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = tmp_path / "config.yaml"
    save_config(path, AppConfig())
    assert (
        load_config(path, environment=False).storage.sqlite_path
        == tmp_path / "data/outlook.sqlite3"
    )
    monkeypatch.setenv("EW_CHROMA_HOST", "chroma")
    monkeypatch.setenv("EW_LLM_API_KEY", "test-secret-never-export")
    config = load_config(path)
    assert config.storage.chroma_host == "chroma"
    write_vba_ini(tmp_path / "extractor.ini", config)
    text = (tmp_path / "extractor.ini").read_text()
    assert "deletion_mode=0" in text
    assert "track2_enabled=true" in text
    assert "test-secret" not in text
    assert "test-secret" not in path.read_text()


def test_invalid_cleanup_and_routing_are_rejected() -> None:
    payload = AppConfig().model_dump(mode="json")
    payload["extraction"]["deletion_mode"] = 2
    with pytest.raises(ValidationError, match="allow_destructive"):
        AppConfig.model_validate(payload)
    payload["extraction"]["allow_destructive"] = True
    assert AppConfig.model_validate(payload).extraction.archive_pst is False
    payload["tracks"]["track2_enabled"] = False
    with pytest.raises(ValidationError, match="Track 2"):
        AppConfig.model_validate(payload)
    payload["tracks"]["track2_enabled"] = True
    payload["extraction"]["archive_pst"] = True
    with pytest.raises(ValidationError):
        AppConfig.model_validate(payload)
    payload["extraction"]["archive_pst"] = False
    payload["extraction"]["deletion_mode"] = 0
    payload["tracks"] = {"track1_enabled": False, "track2_enabled": False}
    with pytest.raises(ValidationError, match="at least one"):
        AppConfig.model_validate(payload)


def test_form_conversion_preserves_unedited_fields() -> None:
    payload = AppConfig().model_dump(mode="json")
    flat = flatten_values(payload)
    form: dict[str, str | bool] = {}
    for name, _label, kind in FIELDS:
        value = flat[name]
        if kind == "bool":
            form[name] = bool(value)
        elif isinstance(value, list):
            form[name] = ",".join(str(item) for item in value)
        else:
            form[name] = str(value)
    form["storage.chunk_characters"] = "2500"
    form["tracks.track2_enabled"] = False
    candidate = AppConfig.model_validate(apply_form(payload, form))
    assert candidate.storage.chunk_characters == 2500
    assert candidate.tracks.track2_enabled is False
    assert candidate.parsing.max_file_bytes == 50_000_000


def test_unsafe_yaml_unknown_keys_and_invalid_overlap_rejected(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("!!python/object/apply:os.system ['echo unsafe']")
    with pytest.raises(Exception, match="constructor"):
        load_config(path)
    with pytest.raises(ValidationError):
        AppConfig.model_validate({"api_key": "forbidden"})
    with pytest.raises(ValidationError, match="overlap"):
        AppConfig.model_validate({"storage": {"chunk_characters": 100, "chunk_overlap": 100}})
