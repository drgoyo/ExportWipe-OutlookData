# Coding rules

Use uv and the lockfile, Python 3.12+, absolute imports, annotated functions, Ruff, and strict mypy.
Keep use cases in independent slices, with no global or nested horizontal application layers.
Use Polars for tabular processing; introduce providers and frameworks only for requested features.
Load pydantic-settings at the outer boundary. Never embed credentials or log secret values.
Update contracts, decisions, roadmap, and verified state when changing the canonical shape.
Run meaningful checks and report their actual results.
