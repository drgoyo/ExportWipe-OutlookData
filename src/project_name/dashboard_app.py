"""Streamlit script retained as source in native bundles for its script runner."""

import os
from pathlib import Path

from config.application import load_config
from pipelines.analytics.dashboard import render
from project_name.application import Runtime


def run() -> None:
    path = Path(os.environ.get("EW_CONFIG_PATH", "config.yaml")).resolve()
    config = load_config(path)
    runtime = Runtime(config, path)
    render(
        runtime.metadata,
        vector_count=lambda: runtime.vectors().count() if config.tracks.track2_enabled else 0,
        ask_metadata=runtime.metadata_agent().ask if config.tracks.track1_enabled else None,
        ask_deep=(lambda question: runtime.deep_agent().ask(question))
        if config.tracks.track2_enabled
        else None,
    )


if __name__ == "__main__":
    run()
