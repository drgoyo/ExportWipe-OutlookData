"""Guard canonical shape and registration of every bounded context."""

import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_all_pipeline_contexts_are_registered_and_have_mirrored_tests() -> None:
    contexts = {
        path.name
        for path in (REPO_ROOT / "src/pipelines").iterdir()
        if path.is_dir() and (path / "__init__.py").is_file()
    }
    configuration = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    contract = next(
        contract
        for contract in configuration["tool"]["importlinter"]["contracts"]
        if contract["type"] == "independence"
    )
    registered = {module.removeprefix("pipelines.") for module in contract["modules"]}
    assert contexts == registered
    assert {"document_parsing", "data_ingestion", "rag_agents"} <= contexts
    for context in contexts:
        assert (REPO_ROOT / "tests/pipelines" / context).is_dir()


def test_canonical_directories_and_memory_exist_without_horizontal_layers() -> None:
    for directory in [
        ".agent/rules",
        ".vscode",
        "config",
        "src/project_name/core",
        "src/project_name/infrastructure",
        "src/pipelines",
        "tests",
        "data/raw",
        "data/processed",
    ]:
        assert (REPO_ROOT / directory).is_dir(), directory
    for file in ["AGENTS.md", ".agent/plan.md", ".agent/decisions.md", ".agent/status.md"]:
        assert (REPO_ROOT / file).is_file(), file
    assert not any(
        path.is_dir() and path.name in {"models", "services", "repositories"}
        for path in (REPO_ROOT / "src").rglob("*")
    )
