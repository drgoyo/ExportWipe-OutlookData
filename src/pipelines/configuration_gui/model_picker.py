"""Native model selection with injected callbacks and background network/download work."""

from __future__ import annotations

import queue
import threading
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from project_name.core.records import JsonRow


def model_summary(model: JsonRow) -> str:
    """Render registry, live verification, and installed state without conflating them."""
    recommendation = str(model.get("recommendation", ""))
    revision = str(model.get("revision", "not checked"))
    installed_revision = str(model.get("installed_revision", ""))
    installed = (
        f"Validated installation: {installed_revision}" if installed_revision else "Not installed"
    )
    lines = [
        str(model["model"]),
        f"Hugging Face: {model['hf_repo']}",
        f"CPU ONNX / dimensions: {model['dim']} / approximately {model['size_gb']} GB download",
        f"SDK license: {model['license']}; Hub license: {model.get('hub_license', 'not checked')}",
        f"Live Hub check: {model.get('live_status', 'not_checked')}; revision: {revision}",
        installed,
        str(model.get("description", "")),
    ]
    if recommendation:
        lines.append(f"Recommendation: {recommendation}")
    if model.get("live_error"):
        lines.append(str(model["live_error"]))
    lines.append("Changing a model/revision requires a separate Chroma collection and reingestion.")
    return "\n\n".join(lines)


class ModelPicker:
    """Every network operation runs outside Tk; the UI polls results on its own thread."""

    def __init__(
        self,
        parent: tk.Misc,
        current_model: str,
        *,
        discover: Callable[[bool], list[JsonRow]],
        install: Callable[[str], JsonRow],
        select: Callable[[str], None],
    ) -> None:
        self.discover = discover
        self.install = install
        self.select = select
        self.records: dict[str, JsonRow] = {}
        self._busy = False
        self._closed = False
        self._results: queue.Queue[tuple[str, object]] = queue.Queue()
        self._poll_id: str | None = None
        self._preferred_model = current_model
        self.window = tk.Toplevel(parent)
        self.window.title("Outlook RAG — Hugging Face embedding models")
        self.window.geometry("1100x750")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        container = ttk.Frame(self.window, padding=16)
        container.pack(fill="both", expand=True)
        ttk.Label(
            container,
            text="Models come from the installed FastEmbed SDK. Downloads need your action.",
            wraplength=1000,
        ).pack(anchor="w", pady=(0, 10))
        self.tree = ttk.Treeview(
            container, columns=("model", "status", "size", "license"), show="headings", height=13
        )
        for name, title, width in (
            ("model", "Model (recommendations first)", 490),
            ("status", "Live check / installation", 200),
            ("size", "GB estimate", 90),
            ("license", "License", 140),
        ):
            self.tree.heading(name, text=title)
            self.tree.column(name, width=width, stretch=name == "model")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", self._show_selection)
        self.details = tk.Text(container, height=14, wrap="word", state="disabled")
        self.details.pack(fill="both", expand=True, pady=12)
        controls = ttk.Frame(container)
        controls.pack(fill="x")
        self.check_button = ttk.Button(
            controls, text="Check Hugging Face now", command=lambda: self._discover(online=True)
        )
        self.check_button.pack(side="left", padx=(0, 8))
        self.install_button = ttk.Button(
            controls, text="Download & validate CPU model", command=self._download
        )
        self.install_button.pack(side="left", padx=8)
        self.select_button = ttk.Button(controls, text="Use selected model", command=self._select)
        self.select_button.pack(side="left", padx=8)
        ttk.Button(controls, text="Close", command=self.close).pack(side="right")
        self.status = tk.StringVar(value="Loading local SDK compatibility registry…")
        ttk.Label(container, textvariable=self.status, wraplength=1000).pack(anchor="w", pady=12)
        self._poll_id = self.window.after(100, self._poll)
        self._discover(online=False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        state = "disabled" if busy else "normal"
        for button in (self.check_button, self.install_button, self.select_button):
            button.configure(state=state)

    def _start(self, action: str, work: Callable[[], object]) -> None:
        if self._busy:
            return
        self._set_busy(True)

        def worker() -> None:
            try:
                self._results.put((action, work()))
            except Exception as exc:
                self._results.put(("error", str(exc)))

        threading.Thread(target=worker, daemon=True, name="embedding-model-operation").start()

    def _discover(self, *, online: bool) -> None:
        self.status.set(
            "Checking current Hugging Face metadata; no weights are downloaded…"
            if online
            else "Reading local SDK registry; live availability has not been checked…"
        )
        self._start("catalog", lambda: self.discover(online))

    def _selected(self) -> JsonRow | None:
        selection = self.tree.selection()
        return self.records.get(selection[0]) if selection else None

    def _show_selection(self, _event: tk.Event[tk.Misc] | None = None) -> None:
        selected = self._selected()
        if selected is None:
            return
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", model_summary(selected))
        self.details.configure(state="disabled")

    def _download(self) -> None:
        selected = self._selected()
        if selected is None or self._busy:
            return
        model = str(selected["model"])
        if not messagebox.askyesno(
            "Install embedding model",
            f"Download {model} (approximately {selected['size_gb']} GB) into the configured "
            f"model cache and validate a CPU embedding?\n\nLicense: {selected['license']}\n"
            "This does not change the selected model or ingest any mail.",
            parent=self.window,
            default="no",
        ):
            return
        self.status.set("Downloading pinned weights and validating a CPU embedding…")
        self._start("installed", lambda: self.install(model))

    def _select(self) -> None:
        selected = self._selected()
        if selected is None or self._busy:
            return
        self.select(str(selected["model"]))
        self.status.set("Model applied to the form. Choose a new Chroma collection, then save.")

    def _poll(self) -> None:
        if self._closed:
            return
        try:
            action, result = self._results.get_nowait()
        except queue.Empty:
            self._poll_id = self.window.after(100, self._poll)
            return
        self._set_busy(False)
        if action == "catalog" and isinstance(result, list):
            self._populate(result)
        elif action == "installed" and isinstance(result, dict):
            model = str(result.get("model", ""))
            if model in self.records:
                self.records[model]["installed"] = True
                self.records[model]["installed_revision"] = str(result.get("revision", ""))
                row = self.records[model]
                self.tree.item(
                    model,
                    values=(
                        model,
                        f"{row['live_status']} / installed",
                        row["size_gb"],
                        row["license"],
                    ),
                )
            self.status.set(f"Installed and CPU-validated: {model}. Use selected model, then save.")
            self._show_selection()
        else:
            self.status.set("Model operation failed. Existing configuration is unchanged.")
            messagebox.showerror("Model operation", str(result), parent=self.window)
        self._poll_id = self.window.after(100, self._poll)

    def _populate(self, records: list[JsonRow]) -> None:
        previous = self._selected()
        model = str(previous["model"]) if previous else self._preferred_model
        self.tree.delete(*self.tree.get_children())
        self.records = {str(row["model"]): row for row in records}
        for row in records:
            status = str(row["live_status"])
            if row.get("installed"):
                status += " / installed"
            self.tree.insert(
                "",
                "end",
                iid=str(row["model"]),
                values=(row["model"], status, row["size_gb"], row["license"]),
            )
        if model not in self.records and records:
            model = str(records[0]["model"])
        if model in self.records:
            self.tree.selection_set(model)
            self.tree.see(model)
            self._show_selection()
        checked = sum(row.get("live_status") == "verified" for row in records)
        self.status.set(
            f"{len(records)} SDK-compatible models; {checked} live-verified repositories."
        )

    def close(self) -> None:
        self._closed = True
        if self._poll_id is not None:
            self.window.after_cancel(self._poll_id)
        self.window.destroy()
