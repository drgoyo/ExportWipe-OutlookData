"""Native Hugging Face GGUF picker with injected catalog, download, and provider actions."""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass
from math import ceil
from queue import Empty, Queue
from threading import Thread
from tkinter import ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_name.core.records import JsonRow


@dataclass(frozen=True)
class _Result:
    action: str
    payload: list[JsonRow] | JsonRow | None = None
    failure: str = ""


class LLMModelPicker:
    """Keep network work off Tk's thread; selecting a download never installs it implicitly."""

    def __init__(
        self,
        parent: tk.Misc,
        discover: Callable[[str], list[JsonRow]],
        check: Callable[[str], JsonRow],
        download: Callable[[str, str | None, bool], JsonRow],
        select: Callable[[str, str], None],
    ) -> None:
        self.discover = discover
        self.check = check
        self.download = download
        self.select = select
        self.window = tk.Toplevel(parent)
        self.window.title("Hugging Face — local LLM models")
        self.window.geometry("960x760")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        self._results: Queue[_Result] = Queue()
        self._closed = False
        self._busy = False
        self._models: list[JsonRow] = []
        self._checked: JsonRow | None = None
        self._installed: tuple[str, str] | None = None
        self.query = tk.StringVar(master=self.window, value="Qwen")
        self.filename = tk.StringVar(master=self.window)
        self.install = tk.BooleanVar(master=self.window, value=False)
        self.status = tk.StringVar(master=self.window, value="Search for current GGUF models.")

        frame = ttk.Frame(self.window, padding=16)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(2, weight=1)
        ttk.Label(
            frame,
            text=(
                "These models generate answers. Embedding models are configured separately.\n"
                "Check the model files, license, and memory recommendation before downloading."
            ),
            wraplength=900,
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
        ttk.Entry(frame, textvariable=self.query, width=58).grid(
            row=1, column=0, sticky="ew", pady=6
        )
        self.search_button = ttk.Button(frame, text="Search Hugging Face", command=self.search)
        self.search_button.grid(row=1, column=1, padx=8)
        self.check_button = ttk.Button(frame, text="Check selected model", command=self.check_model)
        self.check_button.grid(row=1, column=2)
        self.models = tk.Listbox(frame, height=8, exportselection=False)
        self.models.grid(row=2, column=0, columnspan=3, sticky="nsew", pady=8)
        self.models.bind("<<ListboxSelect>>", self._selection_changed)
        self.details = tk.Text(frame, height=11, wrap="word", state="disabled")
        self.details.grid(row=3, column=0, columnspan=3, sticky="ew", pady=8)
        ttk.Label(frame, text="GGUF file to download").grid(
            row=4, column=0, columnspan=3, sticky="w"
        )
        self.files = ttk.Combobox(frame, textvariable=self.filename, state="readonly", width=80)
        self.files.grid(row=5, column=0, columnspan=3, sticky="ew", pady=6)
        self.files.bind("<<ComboboxSelected>>", self._file_changed)
        self.install_checkbox = ttk.Checkbutton(
            frame,
            text="Import the download into a running Ollama installation",
            variable=self.install,
        )
        self.install_checkbox.grid(row=6, column=0, columnspan=3, sticky="w", pady=6)
        self.download_button = ttk.Button(
            frame, text="Download selected file", command=self.download_model
        )
        self.download_button.grid(row=7, column=0, sticky="w", pady=8)
        self.apply_button = ttk.Button(
            frame, text="Use installed model in configuration", command=self.apply
        )
        self.apply_button.grid(row=7, column=1, columnspan=2, padx=8)
        ttk.Label(frame, textvariable=self.status, wraplength=900).grid(
            row=8, column=0, columnspan=3, sticky="w", pady=10
        )
        ttk.Label(
            frame,
            text=(
                "Downloading alone leaves your LLM configuration unchanged. After applying an "
                "installed model, save the configuration in the main window. Closing this window "
                "lets an in-progress download finish."
            ),
            wraplength=900,
        ).grid(row=9, column=0, columnspan=3, sticky="w")
        self._update_buttons()
        self._poll_id = self.window.after(100, self._poll)
        self.window.bind("<Destroy>", self._destroyed, add="+")

    def show(self) -> None:
        """Raise an existing picker, allowing composition roots to reuse the same instance."""
        self.window.deiconify()
        self.window.lift()

    def _update_buttons(self) -> None:
        state = "disabled" if self._busy else "normal"
        self.search_button.configure(state=state)
        self.check_button.configure(
            state="normal" if not self._busy and self._selection() else "disabled"
        )
        self.download_button.configure(
            state="normal"
            if not self._busy and self._checked and self.filename.get()
            else "disabled"
        )
        self.install_checkbox.configure(state=state)
        self.models.configure(state="disabled" if self._busy else "normal")
        self.files.configure(state="disabled" if self._busy else "readonly")
        self.apply_button.configure(
            state="normal" if not self._busy and self._installed else "disabled"
        )

    def _start(self, action: str, operation: Callable[[], list[JsonRow] | JsonRow]) -> None:
        if self._closed or self._busy:
            return
        self._busy = True
        self.status.set(f"{action.capitalize()} in progress…")
        self._update_buttons()

        def run() -> None:
            try:
                self._results.put(_Result(action, operation()))
            except Exception as exc:
                # Provider errors may contain URLs or credentials; expose only their class.
                self._results.put(_Result(action, failure=type(exc).__name__))

        Thread(target=run, daemon=True, name="outlook-rag-model-picker").start()

    def search(self) -> None:
        query = self.query.get().strip()
        if not query:
            self.status.set("Enter a model family or repository name.")
            return
        self._start("search", lambda: self.discover(query))

    def _selection(self) -> tuple[int, ...]:
        """Read Tcl's selection through its typed API; Listbox.curselection lacks a stub."""
        selected = self.models.tk.call(str(self.models), "curselection")
        return tuple(int(index) for index in self.models.tk.splitlist(selected))

    def _selection_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        if self._busy:
            return
        self._checked = None
        self._installed = None
        self.files.configure(values=())
        self.filename.set("")
        selection = self._selection()
        if selection and selection[0] < len(self._models):
            self._render_details(self._models[selection[0]])
            self.status.set("Check this model to fetch its current GGUF files and recommendation.")
        self._update_buttons()

    def check_model(self) -> None:
        selection = self._selection()
        if not selection or selection[0] >= len(self._models):
            return
        repo = self._models[selection[0]].get("repo_id")
        if isinstance(repo, str):
            self._checked = None
            self._installed = None
            self.files.configure(values=())
            self.filename.set("")
            self._start("check", lambda: self.check(repo))

    def _file_changed(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        self._installed = None
        if self._checked is not None:
            self._render_details(self._checked)
        self._update_buttons()

    def download_model(self) -> None:
        if self._checked is None:
            return
        repo = self._checked.get("repo_id")
        filename = self.filename.get().strip()
        if not isinstance(repo, str) or not filename:
            return
        files = self._checked.get("files")
        if not isinstance(files, list) or not any(
            isinstance(item, dict) and item.get("filename") == filename for item in files
        ):
            self.status.set("Select a file returned by the current model check.")
            return
        install = self.install.get()
        self._installed = None
        self._start("download", lambda: self.download(repo, filename, install))

    def _render_details(self, row: JsonRow) -> None:
        labels = (
            ("repo_id", "Repository"),
            ("revision", "Checked revision"),
            ("license", "License"),
            ("live_status", "Hugging Face status"),
            ("recommended_filename", "Recommended quantization"),
            ("size_gb", "Recommended file size (GB)"),
            ("minimum_ram_gib", "Estimated RAM for recommended file (GiB)"),
            ("recommendation", "Recommendation"),
        )
        lines = [f"{label}: {row[key]}" for key, label in labels if row.get(key) is not None]
        filename = self.filename.get()
        files = row.get("files")
        if filename and isinstance(files, list):
            for item in files:
                if isinstance(item, dict) and item.get("filename") == filename:
                    lines.append(f"Selected file: {filename}")
                    size = item.get("size_bytes")
                    if isinstance(size, int) and not isinstance(size, bool) and size > 0:
                        lines.append(f"Selected file size (GB): {size / 1_000_000_000:.2f}")
                        ram = ceil(size / 1024**3 * 1.5 + 2)
                        lines.append(f"Estimated RAM for selected file (GiB): {ram}")
                        lines.append("Context length and provider settings can require more RAM.")
                    else:
                        lines.append("Selected file size and RAM estimate are unavailable.")
                    break
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", "\n".join(lines))
        self.details.configure(state="disabled")

    def _complete(self, result: _Result) -> None:
        self._busy = False
        self.models.configure(state="normal")
        payload = result.payload
        if result.failure:
            self.status.set(
                f"{result.action.capitalize()} failed ({result.failure}). "
                "Check network availability, repository access, and the local provider."
            )
        elif result.action == "search" and isinstance(payload, list):
            self._models = payload
            self._checked = None
            self._installed = None
            self.models.delete(0, "end")
            self.files.configure(values=())
            self.filename.set("")
            for row in payload:
                self.models.insert("end", str(row.get("repo_id", "Unknown repository")))
            self.status.set(f"Found {len(payload)} models. Select one and check its current files.")
        elif result.action == "check" and isinstance(payload, dict):
            self._checked = payload
            self._installed = None
            rows = payload.get("files")
            filenames: list[str] = []
            if isinstance(rows, list):
                for item in rows:
                    if isinstance(item, dict):
                        name = item.get("filename")
                        if isinstance(name, str):
                            filenames.append(name)
            self.files.configure(values=filenames)
            recommendation = payload.get("recommended_filename")
            preferred = recommendation if isinstance(recommendation, str) else ""
            self.filename.set(preferred if preferred in filenames else "")
            self._render_details(payload)
            self.status.set(
                "Model checked. Select a GGUF file to download."
                if filenames
                else "No downloadable GGUF files were returned for this model."
            )
        elif result.action == "download" and isinstance(payload, dict):
            model = payload.get("installed_provider_model")
            base_url = payload.get("base_url")
            self._installed = (
                (model, base_url)
                if isinstance(model, str) and model and isinstance(base_url, str) and base_url
                else None
            )
            cache_path = payload.get("cache_path", "the configured model cache")
            self.status.set(
                f"Downloaded to {cache_path}. "
                + ("Installed model is ready to apply." if self._installed else "Model downloaded.")
            )
        self._update_buttons()

    def _poll(self) -> None:
        if self._closed:
            return
        try:
            while True:
                self._complete(self._results.get_nowait())
        except Empty:
            pass
        self._poll_id = self.window.after(100, self._poll)

    def apply(self) -> None:
        if self._installed is not None and not self._busy:
            self.select(*self._installed)
            self.status.set("Model fields updated. Save the configuration in the main window.")

    def close(self) -> None:
        self._closed = True
        self.window.after_cancel(self._poll_id)
        self.window.destroy()

    def _destroyed(self, event: tk.Event[tk.Misc]) -> None:
        if event.widget is self.window and not self._closed:
            self._closed = True
            self.window.after_cancel(self._poll_id)
