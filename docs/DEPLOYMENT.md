# Deployment and operational contracts

## Native desktop and executable distribution

Use uv with the committed lock on the target OS: `uv sync --locked --all-extras --group build`.
Run `uv run --no-sync python build.py --target all`. Outputs are onedir standalone application
bundles under artifacts/<platform>-<architecture>; distribute each entire directory, including
_internal, not just its entry executable. Builds contain a platform/lock/hash manifest and logs
under .pyinstaller/<target>/build.log. GUI model-management builds also need the rag extra; full native
bundles use all extras and the build group.

Windows builds produce .exe files, macOS builds produce native executable bundles, and Linux builds
produce ELF executables. Build on each target OS and CPU architecture; there is no cross-compilation.
Build Linux on the oldest distribution you intend to support because glibc compatibility is tied to
the build host. Windows/macOS signing and notarization require your own certificates and release
infrastructure; generated unsigned binaries are not claimed to be notarized installers.

Tk/Tcl is required on the build host for the native GUI; install the Python distribution's Tk support.
Tesseract is external to all bundles. Install Tesseract and matching language packs, then set its
executable in the GUI if it is not on PATH. Explicitly install a pinned ONNX model with
`outlook-rag models download <supported model>` before semantic ingestion/search. The adapter requires
a validated installation receipt and never downloads weights implicitly. Allow Hugging Face model
downloads or populate the configured cache using a trusted prepared deployment.
Model files and user config are runtime data and are not embedded as credentials in executables.

First run the backend bundle's `init-config --output config.yaml`, then point GUI and dashboard
bundles at the same YAML using `--config`. The default directories are relative to that YAML file.
Keep the .bas module available for manual import into classic Outlook as described in the VBA guide.
The web dashboard serves on the loopback interface by default and the GUI requires a desktop display.

## Container stack

Docker Engine/Compose are required. Set a random EW_API_TOKEN in an untracked .env file. For example,
use your password manager to generate at least 32 random bytes. Do not put that value in YAML or chat.
Optional EW_LLM_BASE_URL, EW_LLM_MODEL, and EW_LLM_API_KEY configure a local or HTTPS remote provider.

Run `docker compose config --quiet` to validate without printing resolved secret values, then
`docker compose up --build -d`. Containers run the backend, internal Chroma, and dashboard. HTTP ports
bind localhost. Chroma has no public host port and is reachable only on the internal storage network.
Backend/dashboard get a separate outbound network for LLM/model downloads. Runtime app containers
use UID 10001, read-only root filesystems, no capabilities, explicit memory/PID limits, and writable
state/model volumes. The desktop GUI runs on the host, not in a headless server container.

Place completed exports in data/raw before starting ingestion. This host directory is mounted
read-only for backend/dashboard. Build the master indexes on the host with `outlook-rag catalog`,
or use the isolated catalog tool with its writable raw mount:

```sh
docker compose run --rm --no-deps catalog
```

On Linux its UID/GID must own or have write access to data/raw. Set EW_CATALOG_UID/EW_CATALOG_GID
to that owner for this one-shot service; ordinary app containers retain UID 10001. The tool needs
neither Chroma nor an LLM and has networking disabled. Change the bind if exports live elsewhere;
maintain root containment. To ingest:

```sh
docker compose exec backend outlook-rag --config /app/config.yaml ingest --manifest /data/raw/Master_Index.jsonl
docker compose exec backend outlook-rag --config /app/config.yaml sync
```

Do not ingest while export.lock/catalog.lock exists or catalog publication requires recovery.
Keep live DuckDB files local and copy completed Mail/ + master files to OneDrive/SharePoint after
cataloging closes. See CATALOG.md for crash recovery and MODELS.md for pinned model installation.
Startup health checks test SQLite and Chroma connectivity,
not model download completion or LLM answer quality. To customize parsing limits or OCR settings,
mount your validated non-secret config.yaml at /app/config.yaml; EW_* environment overrides still
select the container data locations. Add OCR language packages to the image for languages beyond
English/German. The API requires its bearer token; dashboard users have access to configured data.
Before remote exposure, add an authenticated TLS reverse proxy and restrict ingress. Never expose
Chroma directly as an unauthenticated public database.

## Persistence, backups, and recovery

SQLite is authoritative for metadata, chunks, and durable sync jobs. Chroma is a derived semantic
index. Stop ingestion before a consistent backup. Stop the stack (without `-v`), then snapshot app-data,
chroma-data, model-cache, raw exports, non-secret config, and your separately secured environment values.
Do not copy a live .sqlite3 alone while WAL writes are happening; use SQLite's backup API or stop all
writers and retain the complete database state. Daily analytics snapshots track observed counts/bytes;
they are measurements, not a forecast or a detailed event audit log.

Restore volumes/config before restart, then run sync. Pending SQL jobs replay idempotently. A new
embedding model requires a new Chroma collection plus reingestion; model signatures prevent mixing
incompatible vectors. Removing the derived Chroma volume requires reingestion, because completed jobs
have been consumed. Use `ingest --force --manifest <manifest>` to repopulate an empty index even when SQL revisions
are unchanged. Raw exports must be available for that rebuild. Deleting raw files or changing filters does not delete previously indexed data;
retention/purge requires an explicit separate operation and a verified backup.

## Verification boundaries

Tests generate mail metadata and Office/images; no mailbox or destructive macro is accessed. Native
builds must be smoke-tested on their own platforms. The current host's actual build, container, model,
GUI, and provider verification results are recorded in .agent/status.md. Configure and test a real
LLM separately; the integration suite verifies protocol/privacy with a local HTTP stub.

## Cloud proxy builds

On a cloud host with a private egress proxy, forward the existing HTTP_PROXY/HTTPS_PROXY/NO_PROXY as
predefined Docker build arguments. The build accepts an optional BuildKit secret named cloud_ca for
its trusted CA bundle. It is mounted only during installation and is never copied into the image.
Use the provided proxy route and trusted certificate; do not disable TLS or package verification.
If bridge DNS cannot resolve the proxy, supply its known hostname/IP via --add-host and the supported
host build network. Normal desktop builds need none of these cloud-specific options.

MCP accepts one SELECT query over curated views. CTEs and non-curated tables are rejected by a parsed
SQL check in addition to SQLite's authorizer, preventing CTE/view-name impersonation.

The reusable cloud build wrapper is `uv run --no-sync python scripts/cloud_docker_build.py`.
It forwards existing proxy settings, resolves that same proxy for Docker, and mounts the supplied
trust bundle through BuildKit. It never prints proxy credentials or disables certificate checking.
After it succeeds, use `docker --config /workspace/.cache/docker compose up --no-build -d`.
macOS GUI builds also produce a .app bundle; distribute that whole bundle when available.
