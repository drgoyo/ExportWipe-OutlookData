# Pipeline rules

Applies to src/pipelines/** and tests/pipelines/**. Keep each context self-contained. Never import
sibling contexts or concrete infrastructure. Processing, ingestion, agents, and analytics receive
core ports and typed values from the application composition root, never runtime config imports.
Use Polars for tabular processing. Register every new context in the independence contract.
No nested/global horizontal model or service layers. Preserve metadata-only Track 1 isolation.
