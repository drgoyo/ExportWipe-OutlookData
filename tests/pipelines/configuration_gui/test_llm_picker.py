"""Exercise the native model picker with a display and injected network/provider operations."""

from __future__ import annotations

import tkinter as tk
from threading import get_ident
from typing import TYPE_CHECKING

import pytest

from pipelines.configuration_gui.llm_picker import LLMModelPicker

if TYPE_CHECKING:
    from collections.abc import Iterator

    from project_name.core.records import JsonRow


@pytest.fixture
def gui_root() -> Iterator[tk.Tk]:
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("Native GUI test requires a display (use Xvfb on Linux).")
    root.withdraw()
    yield root
    root.destroy()


def wait_for_operation(root: tk.Tk, picker: LLMModelPicker) -> None:
    timeout = root.after(5000, root.quit)

    def completed() -> None:
        if picker._busy:
            root.after(10, completed)
        else:
            root.quit()

    root.after(10, completed)
    root.mainloop()
    root.after_cancel(timeout)
    assert not picker._busy, "Model operation did not finish within five seconds"


def test_download_is_opt_in_and_only_an_installed_model_can_update_configuration(
    gui_root: tk.Tk,
) -> None:
    main_thread = get_ident()
    worker_threads: list[int] = []
    downloads: list[tuple[str, str | None, bool]] = []
    selections: list[tuple[str, str]] = []
    row: JsonRow = {
        "repo_id": "example/instruct-GGUF",
        "revision": "a" * 40,
        "license": "apache-2.0",
        "live_status": "verified",
        "recommended_filename": "instruct-Q4_K_M.gguf",
        "size_gb": 2.1,
        "minimum_ram_gib": 6,
        "files": [
            {"filename": "instruct-Q4_K_M.gguf", "size_bytes": 2_100_000_000},
            {"filename": "instruct-Q8_0.gguf", "size_bytes": 4_200_000_000},
        ],
    }

    def discover(query: str) -> list[JsonRow]:
        worker_threads.append(get_ident())
        assert query == "Qwen"
        return [row]

    def check(repo: str) -> JsonRow:
        worker_threads.append(get_ident())
        assert repo == row["repo_id"]
        return row

    def download(repo: str, filename: str | None, install: bool) -> JsonRow:
        worker_threads.append(get_ident())
        downloads.append((repo, filename, install))
        result: JsonRow = {"cache_path": "/models/instruct-Q4_K_M.gguf"}
        if install:
            result.update(
                {
                    "installed_provider_model": "outlook-rag-instruct",
                    "base_url": "http://localhost:11434/v1",
                }
            )
        return result

    def select(model: str, base_url: str) -> None:
        assert get_ident() == main_thread
        selections.append((model, base_url))

    picker = LLMModelPicker(gui_root, discover, check, download, select)
    picker.search_button.invoke()
    wait_for_operation(gui_root, picker)
    assert not downloads
    picker.models.selection_set(0)
    picker.models.event_generate("<<ListboxSelect>>")
    gui_root.update()
    picker.check_button.invoke()
    wait_for_operation(gui_root, picker)
    assert picker.filename.get() == "instruct-Q4_K_M.gguf"
    assert "apache-2.0" in picker.details.get("1.0", "end")
    picker.files.set("instruct-Q8_0.gguf")
    picker.files.event_generate("<<ComboboxSelected>>")
    gui_root.update()
    details = picker.details.get("1.0", "end")
    assert "Selected file size (GB): 4.20" in details
    assert "Estimated RAM for selected file (GiB): 8" in details
    picker.files.set("instruct-Q4_K_M.gguf")
    picker.files.event_generate("<<ComboboxSelected>>")
    gui_root.update()
    assert not downloads
    picker.download_button.invoke()
    wait_for_operation(gui_root, picker)
    assert downloads == [("example/instruct-GGUF", "instruct-Q4_K_M.gguf", False)]
    assert str(picker.apply_button.cget("state")) == "disabled"
    assert not selections
    picker.install.set(True)
    picker.download_button.invoke()
    wait_for_operation(gui_root, picker)
    picker.apply_button.invoke()
    assert downloads[-1][-1] is True
    assert selections == [("outlook-rag-instruct", "http://localhost:11434/v1")]
    assert all(thread != main_thread for thread in worker_threads)
    picker.close()


def test_failed_recheck_discards_old_files_and_redacts_provider_errors(gui_root: tk.Tk) -> None:
    attempts = 0
    row: JsonRow = {
        "repo_id": "example/model",
        "recommended_filename": "model.gguf",
        "files": [{"filename": "model.gguf"}],
    }

    def check(_repo: str) -> JsonRow:
        nonlocal attempts
        attempts += 1
        if attempts > 1:
            raise RuntimeError("Bearer highly-sensitive-test-token")
        return row

    def download(_repo: str, _filename: str | None, _install: bool) -> JsonRow:
        pytest.fail("A failed model check must not permit download")

    picker = LLMModelPicker(gui_root, lambda _query: [row], check, download, lambda _m, _u: None)
    picker.search_button.invoke()
    wait_for_operation(gui_root, picker)
    picker.models.selection_set(0)
    picker.models.event_generate("<<ListboxSelect>>")
    gui_root.update()
    picker.check_button.invoke()
    wait_for_operation(gui_root, picker)
    assert picker.filename.get() == "model.gguf"
    picker.check_button.invoke()
    wait_for_operation(gui_root, picker)
    assert "highly-sensitive" not in picker.status.get()
    assert "RuntimeError" in picker.status.get()
    assert str(picker.download_button.cget("state")) == "disabled"
    assert not picker.filename.get()
    picker.close()
