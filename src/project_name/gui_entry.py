"""Desktop composition root for central configuration and the native GUI."""

from __future__ import annotations

import argparse
import tkinter as tk
from hashlib import sha256
from pathlib import Path
from tkinter import messagebox
from typing import TYPE_CHECKING

from config.application import AppConfig, load_config, save_config, write_vba_ini
from pipelines.configuration_gui.editor import ConfigurationEditor, apply_form

if TYPE_CHECKING:
    from project_name.core.records import JsonRow


def main() -> None:
    parser = argparse.ArgumentParser(description="Edit Outlook RAG configuration")
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    parser.add_argument("--smoke-test", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    config_path: Path = args.config
    if not config_path.exists():
        save_config(config_path, AppConfig())
    configuration = load_config(config_path, environment=False)

    def persist(payload: dict[str, object]) -> Path:
        candidate = AppConfig.model_validate(payload)
        ini = (
            config_path.resolve().parent / candidate.extraction.output_directory / "extractor.ini"
        ).resolve()
        # Validate everything before either file is replaced.
        save_config(config_path, candidate)
        write_vba_ini(ini, candidate)
        return ini

    root = tk.Tk()

    def current_config() -> AppConfig:
        return AppConfig.model_validate(
            apply_form(
                editor.payload,
                {name: variable.get() for name, variable in editor.variables.items()},
            )
        )

    def set_text(name: str, value: str) -> None:
        variable = editor.variables[name]
        if not isinstance(variable, tk.StringVar):
            raise ValueError(f"Expected a text field: {name}")
        variable.set(value)

    def model_cache() -> Path:
        cache = current_config().storage.model_cache.expanduser()
        return (
            cache.resolve()
            if cache.is_absolute()
            else (config_path.resolve().parent / cache).resolve()
        )

    def open_models() -> None:
        from pipelines.configuration_gui.model_picker import ModelPicker
        from project_name.infrastructure.model_catalog import ModelCatalog

        try:
            candidate = current_config()
            catalog = ModelCatalog(model_cache())

            def choose(model: str) -> None:
                previous = str(editor.variables["storage.embedding_model"].get())
                set_text("storage.embedding_model", model)
                if model != previous:
                    suffix = sha256(model.encode()).hexdigest()[:8]
                    name = str(editor.variables["storage.collection"].get())[:50]
                    set_text("storage.collection", f"{name}_{suffix}")
                    if model == "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2":
                        set_text("storage.chunk_characters", "350")
                        set_text("storage.chunk_overlap", "50")

            ModelPicker(
                root,
                candidate.storage.embedding_model,
                discover=lambda online: catalog.list_models(language="de", online=online),
                install=catalog.download,
                select=choose,
            )
        except (ValueError, ImportError, OSError) as exc:
            messagebox.showerror("Models", f"{exc}\nInstall the rag extra if missing.", parent=root)

    def open_llm_models() -> None:
        from pipelines.configuration_gui.llm_picker import LLMModelPicker
        from project_name.infrastructure.local_llm_models import (
            LocalLLMModelCatalog,
            install_ollama,
        )

        try:
            catalog = LocalLLMModelCatalog(model_cache() / "llm")

            def download(repository: str, filename: str | None, install: bool) -> JsonRow:
                result = catalog.download(repository, filename)
                return install_ollama(result) if install else result

            def choose(model: str, base_url: str) -> None:
                set_text("llm.model", model)
                set_text("llm.base_url", base_url)

            LLMModelPicker(root, catalog.list_models, catalog.check, download, choose)
        except (ValueError, ImportError, OSError) as exc:
            messagebox.showerror("Local LLM models", str(exc), parent=root)

    editor = ConfigurationEditor(
        root,
        configuration.model_dump(mode="json"),
        persist,
        open_models=open_models,
        open_llm_models=open_llm_models,
    )
    if args.smoke_test:
        root.after(200, root.destroy)
    root.mainloop()


if __name__ == "__main__":
    main()
