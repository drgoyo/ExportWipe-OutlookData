# Infrastructure rules

Applies to `src/project_name/infrastructure/**` and its mirrored tests. Adapters implement core
ports and may depend on core and config. Never import pipeline implementations. Add providers only
for an authorized feature. Avoid work at import time; separate optional live checks from deterministic
tests. Implement providers behind typed core ports; verify error handling and idempotent recovery.
