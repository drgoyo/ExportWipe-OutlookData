"""Validate actual environment loading, precedence, validation, and immutability."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from pydantic import ValidationError

from config.settings import Settings

if TYPE_CHECKING:
    from pathlib import Path


class ProbeSettings(Settings):
    """Test-only schema for exercising the shared settings policy."""

    probe_value: int = 1


def test_environment_overrides_dotenv_and_constructor_overrides_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("EW_PROBE_VALUE=2\n", encoding="utf-8")
    monkeypatch.delenv("EW_PROBE_VALUE", raising=False)
    assert ProbeSettings().probe_value == 2

    monkeypatch.setenv("EW_PROBE_VALUE", "3")
    assert ProbeSettings().probe_value == 3
    assert ProbeSettings(probe_value=4).probe_value == 4


def test_invalid_environment_value_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("EW_PROBE_VALUE", "invalid-integer")
    with pytest.raises(ValidationError, match="valid integer"):
        ProbeSettings()


def test_settings_are_frozen(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("EW_PROBE_VALUE", raising=False)
    settings = ProbeSettings()
    with pytest.raises(ValidationError, match="frozen"):
        settings.probe_value = 2
