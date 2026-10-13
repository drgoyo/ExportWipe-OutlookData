"""Prove architectural contracts reject forbidden imports in isolated copies."""

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CORE_CONTRACT = "Core stays independent of adapters, slices, and runtime configuration"
PIPELINES_CONTRACT = "Slices depend on core ports, never concrete adapters or runtime configuration"
INFRASTRUCTURE_CONTRACT = "Infrastructure cannot depend on pipeline implementations"
CONFIG_CONTRACT = "Configuration cannot depend on application packages"
INDEPENDENCE_CONTRACT = "Pipeline bounded contexts are independent"
RUN_LINTER = (
    "import sys; sys.path.insert(0, 'src'); "
    "from importlinter.cli import lint_imports_command; lint_imports_command()"
)


@pytest.fixture
def architecture_copy(tmp_path: Path) -> Path:
    shutil.copytree(
        REPO_ROOT / "src", tmp_path / "src", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copytree(
        REPO_ROOT / "config", tmp_path / "config", ignore=shutil.ignore_patterns("__pycache__")
    )
    shutil.copy2(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    return tmp_path


def run_contracts(directory: Path) -> subprocess.CompletedProcess[str]:
    # The executable and command are fixed; only a pytest-owned temporary cwd varies.
    return subprocess.run(  # noqa: S603
        [sys.executable, "-c", RUN_LINTER, "--no-cache", "--no-logo"],
        cwd=directory,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )


def test_allowed_port_and_adapter_directions(architecture_copy: Path) -> None:
    (architecture_copy / "src/pipelines/document_parsing/boundary_probe.py").write_text(
        "import project_name.core\nimport polars\n", encoding="utf-8"
    )
    (architecture_copy / "src/project_name/infrastructure/boundary_probe.py").write_text(
        "import project_name.core\nimport config.settings\n", encoding="utf-8"
    )
    result = run_contracts(architecture_copy)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "Contracts: 5 kept, 0 broken." in result.stdout


@pytest.mark.parametrize(
    ("source", "target", "contract"),
    [
        ("src/project_name/core", "project_name.infrastructure", CORE_CONTRACT),
        ("src/project_name/core", "pipelines", CORE_CONTRACT),
        ("src/project_name/core", "config.settings", CORE_CONTRACT),
        ("src/project_name/core", "polars", CORE_CONTRACT),
        ("src/project_name/core", "pydantic_settings", CORE_CONTRACT),
        (
            "src/pipelines/document_parsing",
            "project_name.infrastructure",
            PIPELINES_CONTRACT,
        ),
        ("src/pipelines/data_ingestion", "config.settings", PIPELINES_CONTRACT),
        ("src/pipelines/export_catalog", "project_name.infrastructure", PIPELINES_CONTRACT),
        (
            "src/project_name/infrastructure",
            "pipelines.rag_agents",
            INFRASTRUCTURE_CONTRACT,
        ),
        ("config", "project_name.core", CONFIG_CONTRACT),
        (
            "src/pipelines/document_parsing",
            "pipelines.rag_agents",
            INDEPENDENCE_CONTRACT,
        ),
    ],
)
def test_forbidden_import_is_rejected(
    architecture_copy: Path, source: str, target: str, contract: str
) -> None:
    (architecture_copy / source / "boundary_probe.py").write_text(
        f"import {target}\n", encoding="utf-8"
    )
    result = run_contracts(architecture_copy)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{contract} BROKEN" in result.stdout


def test_indirect_cross_context_import_is_rejected(architecture_copy: Path) -> None:
    (architecture_copy / "src/pipelines/document_parsing/boundary_probe.py").write_text(
        "import project_name.core.bridge\n", encoding="utf-8"
    )
    (architecture_copy / "src/project_name/core/bridge.py").write_text(
        "import pipelines.rag_agents\n", encoding="utf-8"
    )
    result = run_contracts(architecture_copy)
    assert result.returncode == 1, result.stdout + result.stderr
    assert f"{INDEPENDENCE_CONTRACT} BROKEN" in result.stdout
