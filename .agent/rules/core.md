# Core rules

Applies to `src/project_name/core/**` and its mirrored tests. Keep only minimal shared ports,
protocols, and value contracts here. Do not import pipelines, infrastructure, config, Polars, or
pydantic-settings. No service connections, file access, environment reads, or import-time work.
Keep context-specific types in their slice; introduce shared contracts only when justified.
