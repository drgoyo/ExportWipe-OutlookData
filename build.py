"""Build native standalone bundles on the target OS, retaining logs and platform manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
TARGETS = {
    "gui": ("OutlookRAGConfig", "frozen_gui.py"),
    "backend": ("OutlookRAGBackend", "frozen_backend.py"),
    "dashboard": ("OutlookRAGDashboard", "frozen_dashboard.py"),
}


def build_target(target: str, output: Path) -> None:
    name, script = TARGETS[target]
    work = ROOT / ".pyinstaller" / target
    work.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--onedir",
        "--name",
        name,
        "--distpath",
        str(output),
        "--workpath",
        str(work / "work"),
        "--specpath",
        str(work),
        "--paths",
        str(ROOT / "src"),
        "--paths",
        str(ROOT),
        "--exclude-module",
        "mypy",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "ruff",
        "--copy-metadata",
        "exportwipe-outlookdata",
        "--add-data",
        f"{ROOT / 'config.example.yaml'}:.",
        "--add-data",
        f"{ROOT / 'src/pipelines/vba_extraction/Outlook_RAG_Extractor.bas'}"
        ":pipelines/vba_extraction",
    ]
    for package in ["duckdb", "huggingface_hub", "fastembed"]:
        command += ["--collect-all", package, "--copy-metadata", package]
    if target == "gui":
        command += ["--windowed"]
        # Some standalone Python distributions ship Tk 9 under non-system names that the
        # standard hook cannot resolve. Collect their native libraries explicitly.
        libraries: set[Path] = set()
        for directory in [Path(sys.base_prefix) / "lib", Path(sys.base_prefix) / "DLLs"]:
            for pattern in [
                "*tcl*.so*",
                "*tk*.so*",
                "*tcl*.dylib",
                "*tk*.dylib",
                "*tcl*.dll",
                "*tk*.dll",
            ]:
                libraries.update(path for path in directory.glob(pattern) if path.is_file())
        for library in sorted(libraries):
            command += ["--add-binary", f"{library}:."]
    else:
        for package in ["chromadb", "mcp", "sqlglot"]:
            command += ["--collect-all", package, "--copy-metadata", package]
        command += ["--collect-submodules", "pipelines", "--collect-submodules", "project_name"]
        if target == "dashboard":
            command += [
                "--collect-all",
                "streamlit",
                "--copy-metadata",
                "streamlit",
                "--add-data",
                f"{ROOT / 'src/project_name/dashboard_app.py'}:project_name",
            ]
        else:
            command += ["--exclude-module", "streamlit", "--exclude-module", "tkinter"]
    command.append(str(ROOT / "scripts" / script))
    log = work / "build.log"
    print(f"Building {name} on {platform.system()}/{platform.machine()}; log: {log}", flush=True)
    with log.open("w", encoding="utf-8") as stream:
        # All arguments are fixed build inputs; no shell expansion or user command execution.
        result = subprocess.run(  # noqa: S603
            command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False
        )
    if result.returncode:
        raise RuntimeError(f"{name} build failed ({result.returncode}); inspect {log}")
    suffix = ".exe" if sys.platform == "win32" else ""
    executable = output / name / f"{name}{suffix}"
    bundle = output / name
    if sys.platform == "darwin" and target == "gui":
        app = output / f"{name}.app"
        app_executable = app / "Contents" / "MacOS" / name
        if app_executable.is_file():
            executable = app_executable
            bundle = app
    if not executable.is_file():
        raise RuntimeError(f"Expected executable is missing: {executable}")
    # Hash files incrementally: ONNX/native shared libraries can be large.
    with executable.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    manifest = {
        "target": target,
        "platform": platform.system(),
        "architecture": platform.machine(),
        "python": platform.python_version(),
        "entry_sha256": digest,
        "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
        "external_requirements": [
            "Tesseract executable and language data for OCR",
            "Configured LLM for answers",
            "FastEmbed model cache or download access",
        ],
    }
    (bundle / "build-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Built {executable}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Native PyInstaller builds; run separately on each OS"
    )
    parser.add_argument("--target", choices=[*TARGETS, "all"], default="all")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    output: Path = args.output or ROOT / "artifacts" / f"{sys.platform}-{platform.machine()}"
    output.mkdir(parents=True, exist_ok=True)
    for target in TARGETS if args.target == "all" else [args.target]:
        build_target(target, output)


if __name__ == "__main__":
    main()
