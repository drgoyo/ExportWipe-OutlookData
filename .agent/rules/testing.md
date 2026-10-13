# Testing rules

Mirror slices under `tests/pipelines/`, core/adapters under `tests/project_name/` and configuration under `tests/config/`. Scaffold tests
may live directly under tests. Use annotated pytest fixtures, temporary directories, and fake adapters.
Validate outcomes that can fail; no empty tests or dependency on credentials, mail, or live services.
Architecture probes use temporary copies and never modify real application source.
