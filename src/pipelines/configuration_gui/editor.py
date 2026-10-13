"""Native configuration editor; validation and persistence are injected by the composition root."""

from __future__ import annotations

import tkinter as tk
from functools import partial
from tkinter import filedialog, messagebox, ttk
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

# Flat fields keep the editor independent of concrete runtime configuration schemas.
FIELDS: tuple[tuple[str, str, str], ...] = (
    ("extraction.output_directory", "Export directory", "path"),
    ("extraction.filter_date", "Date boundary (YYYY-MM-DD)", "text"),
    ("extraction.date_filter_mode", "Date filter: 0 all / 1 before / 2 from", "int"),
    ("extraction.process_all_subfolders", "Include Outlook subfolders", "bool"),
    ("extraction.minimum_attachment_bytes", "Minimum attachment bytes", "int"),
    ("extraction.exclude_freemail", "Exclude freemail providers", "bool"),
    ("extraction.freemail_domains", "Exact freemail domains (comma separated)", "list"),
    ("extraction.deletion_mode", "Cleanup: 0 copy / 1 attachments / 2 mail", "int"),
    ("extraction.allow_destructive", "Explicitly allow destructive cleanup", "bool"),
    ("tracks.track1_enabled", "Track 1: metadata-only agent", "bool"),
    ("tracks.track2_enabled", "Track 2: bodies, attachments, deep RAG", "bool"),
    ("parsing.output_directory", "Processed Markdown directory", "path"),
    ("parsing.ocr_language", "OCR language (eng or eng+deu)", "text"),
    ("parsing.tesseract_command", "Tesseract executable", "text"),
    ("storage.sqlite_path", "SQLite database file", "text"),
    ("storage.chroma_directory", "Local Chroma directory", "path"),
    ("storage.chroma_host", "Chroma host (blank = local)", "text"),
    ("storage.chroma_port", "Chroma port", "int"),
    ("storage.chroma_ssl", "Chroma HTTPS", "bool"),
    ("storage.collection", "Chroma collection", "text"),
    ("storage.embedding_model", "FastEmbed model", "text"),
    ("storage.model_cache", "Downloaded model cache", "path"),
    ("storage.chunk_characters", "Chunk characters", "int"),
    ("storage.chunk_overlap", "Chunk overlap", "int"),
    ("llm.base_url", "OpenAI-compatible LLM base URL", "text"),
    ("llm.model", "LLM model", "text"),
)


def flatten_values(payload: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for section, values in payload.items():
        if isinstance(values, dict):
            for key, value in values.items():
                result[f"{section}.{key}"] = value
    return result


def apply_form(payload: dict[str, object], values: dict[str, str | bool]) -> dict[str, object]:
    """Convert editor inputs without silently accepting malformed numeric values."""
    result: dict[str, object] = {
        key: dict(value) if isinstance(value, dict) else value for key, value in payload.items()
    }
    for name, _label, kind in FIELDS:
        section, key = name.split(".")
        value: object = values[name]
        if kind == "int":
            value = int(str(value))
        elif kind == "list":
            value = [part.strip() for part in str(value).split(",") if part.strip()]
        section_values = result[section]
        if not isinstance(section_values, dict):
            raise ValueError(f"Invalid section: {section}")
        section_values[key] = value
    return result


class ConfigurationEditor:
    """Scrollable form that saves validated central YAML and VBA settings."""

    def __init__(
        self,
        root: tk.Tk,
        payload: dict[str, object],
        save: Callable[[dict[str, object]], Path],
        *,
        open_models: Callable[[], None] | None = None,
        open_llm_models: Callable[[], None] | None = None,
    ) -> None:
        self.root = root
        self.payload = payload
        self.save = save
        self.variables: dict[str, tk.StringVar | tk.BooleanVar] = {}
        root.title("Outlook RAG — Configuration")
        root.geometry("900x750")
        canvas = tk.Canvas(root, highlightthickness=0)
        scrollbar = ttk.Scrollbar(root, orient="vertical", command=canvas.yview)
        frame = ttk.Frame(canvas, padding=16)
        frame.bind("<Configure>", lambda _event: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=frame, anchor="nw")
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True)
        scrollbar.pack(side="right", fill="y")
        ttk.Label(
            frame, text="Track 1 sends metadata only. Track 2 reads bodies and attachments."
        ).grid(row=0, column=0, columnspan=3, sticky="w", pady=10)
        flat = flatten_values(payload)
        for row, (name, label, kind) in enumerate(FIELDS, start=1):
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", padx=8, pady=5)
            value = flat[name]
            if kind == "bool":
                variable: tk.StringVar | tk.BooleanVar = tk.BooleanVar(value=bool(value))
                ttk.Checkbutton(frame, variable=variable).grid(row=row, column=1, sticky="w")
            else:
                rendered = ",".join(map(str, value)) if isinstance(value, list) else str(value)
                variable = tk.StringVar(value=rendered)
                ttk.Entry(frame, textvariable=variable, width=52).grid(
                    row=row, column=1, sticky="ew"
                )
            self.variables[name] = variable
            if kind == "path":
                ttk.Button(frame, text="Browse", command=partial(self.browse, name)).grid(
                    row=row, column=2, padx=8
                )
        ttk.Label(
            frame,
            text="Credentials belong in .env (EW_LLM_API_KEY / EW_API_TOKEN), never this form.",
        ).grid(row=len(FIELDS) + 1, column=0, columnspan=3, pady=10)
        ttk.Button(frame, text="Validate & save YAML + extractor.ini", command=self.persist).grid(
            row=len(FIELDS) + 2, column=0, columnspan=3, pady=12
        )
        if open_models is not None:
            ttk.Button(frame, text="Embedding models on Hugging Face", command=open_models).grid(
                row=len(FIELDS) + 3, column=0, columnspan=3, pady=6
            )
        if open_llm_models is not None:
            ttk.Button(
                frame, text="Local LLM models on Hugging Face", command=open_llm_models
            ).grid(row=len(FIELDS) + 4, column=0, columnspan=3, pady=6)

    def browse(self, name: str) -> None:
        selected = filedialog.askdirectory(parent=self.root)
        if selected:
            variable = self.variables[name]
            if isinstance(variable, tk.StringVar):
                variable.set(selected)

    def persist(self) -> None:
        try:
            candidate = apply_form(
                self.payload, {key: variable.get() for key, variable in self.variables.items()}
            )
            extraction = candidate["extraction"]
            if isinstance(extraction, dict) and extraction.get("deletion_mode") != 0:  # noqa: SIM102
                if not messagebox.askyesno(
                    "Cleanup configuration",
                    "This enables mailbox modification after export. Continue?",
                    parent=self.root,
                    default="no",
                ):
                    return
            ini = self.save(candidate)
            self.payload = candidate
            messagebox.showinfo(
                "Saved",
                f"Configuration saved. In Outlook, select this INI:\n{ini}",
                parent=self.root,
            )
        except (ValueError, OSError) as exc:
            messagebox.showerror("Configuration error", str(exc), parent=self.root)
