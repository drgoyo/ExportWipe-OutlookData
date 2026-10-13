# Model selection, download, and local installation

The application uses two different model types. **Embedding models** turn parsed text into vectors
for Track 2 retrieval. **Generative LLMs** produce answers for both tracks. Installing an embedding
model does not install an answering model. Track 1 needs an LLM but never needs a vector database or
embeddings; its prompt contains allowlisted metadata only.

The desktop configuration editor has separate **Embedding models on Hugging Face** and
**Local LLM models on Hugging Face** buttons. Discovery and downloads run in worker threads so the
editor remains responsive. A download is an explicit action. Neither opening the editor nor viewing
a model list downloads a large model or runs repository Python code.

## Embeddings for English and German mail

The embedding catalog starts from the models actually supported by the installed FastEmbed version.
It can then check their current Hugging Face repositories, immutable revisions, and licenses. This
avoids presenting an arbitrary Hugging Face model as compatible with the application's ONNX adapter.
Offline registry entries are labeled separately from live verification.

```sh
uv run outlook-rag models list --language de --online
uv run outlook-rag models check sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
uv run outlook-rag models download sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

Useful starting points are:

| Model | Intended use | Approximate weights | Vector dimensions | License |
| --- | --- | ---: | ---: | --- |
| sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2 | Lightweight German/multilingual CPU retrieval | 0.22 GB | 384 | Apache-2.0 |
| jinaai/jina-embeddings-v2-base-de | Larger German/English retrieval with a longer input window | 0.64 GB | 768 | Apache-2.0 |
| BAAI/bge-small-en-v1.5 | Lightweight English retrieval; existing project default | 0.067 GB | 384 | MIT |

Sizes and availability come from the installed registry and current provider metadata; use the
catalog output for current values. The multilingual MiniLM model has a short input window
(128 tokens), so evaluate truncation and chunk size on representative messages. A larger model is
not automatically better for your mailbox. Measure whether the relevant documents appear in the
retrieved results before selecting a model for production.

The default download budget is 1 GB. Increase it explicitly with --max-size-gb if a selected
supported model is larger. Model files live in storage.model_cache and stay outside Git and native
application bundles. A model download also verifies that the adapter can load the installed model.

In the GUI, apply the selected embedding model and **Save** in the main window. A changed embedding
model requires a new Chroma collection and reingestion; the GUI assigns a different collection name
when the model changes. CLI users must update both storage.embedding_model and storage.collection
in their YAML. Existing vectors cannot be reused across incompatible models, even when dimensions
match.
For multilingual MiniLM the GUI also suggests 350-character chunks with 50-character overlap.
This is a conservative starting point, not an exact token guarantee; tune it against representative
German text. CLI users should set these chunk fields explicitly for the model's short input window.

## Generative models from live Hugging Face inventories

The local LLM catalog queries the live Hugging Face API for official Qwen GGUF text-generation
repositories. It excludes embedding and vision models and repositories containing only split GGUF
files. You can check another text-generation repository directly with llm-models check owner/name.
The returned inventory includes actual filenames, file sizes, license, immutable commit revision,
and a RAM estimate. Listing or checking models never downloads their weights.

```sh
uv run outlook-rag llm-models list --search Qwen3 --limit 8
uv run outlook-rag llm-models check Qwen/Qwen3-4B-GGUF
```

Provider inventories were checked successfully on 2026-10-13:

| Repository | Actual selected file | File size | Suggested use |
| --- | --- | ---: | --- |
| Qwen/Qwen3-0.6B-GGUF | Qwen3-0.6B-Q8_0.gguf | 0.639 GB | Small CPU smoke test; limited answer quality |
| Qwen/Qwen3-1.7B-GGUF | Qwen3-1.7B-Q8_0.gguf | 1.834 GB | Lightweight multilingual option |
| Qwen/Qwen3-4B-GGUF | Qwen3-4B-Q4_K_M.gguf | 2.497 GB | Balanced starting point; prefer at least 8 GiB system RAM |

All three repositories reported Apache-2.0. The 4B inventory at revision
bc640142c66e1fdd12af0bd68f40445458f3869b included the Q4_K_M file with exactly 2,497,280,256
bytes. The smaller two repositories offered Q8_0, so the application uses the available files
instead of suggesting nonexistent Q4 variants. Run a fresh check before downloading because provider
inventories can change. RAM estimates include a rough allowance above weights; context length,
KV cache, operating system, OCR, and concurrent applications affect actual requirements.

Download a selected file explicitly:

```sh
uv run outlook-rag llm-models download Qwen/Qwen3-4B-GGUF \
  --filename Qwen3-4B-Q4_K_M.gguf --max-size-gb 3
```

The downloader rechecks the live manifest, pins that exact commit for the download, checks the size
budget and available disk space, and verifies the downloaded file's GGUF header and size. When the
manifest supplies an LFS SHA-256, it verifies that hash too. Results report the computed checksum and
whether a provider checksum was available. The cache lives under storage.model_cache/llm; Hugging
Face may resolve a snapshot symlink to an extensionless cache blob, which is still a valid GGUF file.
Existing verified cache entries are reused. No remote model repository code is executed.

## Import into Ollama and connect the agent

Install and start [Ollama](https://ollama.com/download) on your native desktop first. The application
imports a selected GGUF into an existing local Ollama service; it does not install the Ollama program
or a system service. The import command uses a temporary Modelfile and a fixed subprocess argument
list, and it targets the local service at 127.0.0.1:11434.

```sh
uv run outlook-rag llm-models download Qwen/Qwen3-4B-GGUF \
  --filename Qwen3-4B-Q4_K_M.gguf --max-size-gb 3 \
  --install-ollama --ollama-name outlook-rag
```

Downloading without --install-ollama only populates the model cache. The optional flag runs
ollama create after verification. A successful import reports the provider model name and
OpenAI-compatible endpoint. Set these non-secret fields in your central YAML:

```yaml
llm:
  base_url: http://127.0.0.1:11434/v1
  model: outlook-rag
  timeout_seconds: 120
  max_context_characters: 24000
```

In the GUI, select and check a repository, choose its GGUF file, and enable **Import the download into
a running Ollama installation** only when you want that import. After the import succeeds, choose
**Use installed model in configuration**, then **Save** in the main editor. The separate steps keep a
download from silently changing the active answering model.

An existing OpenAI-compatible HTTPS provider also works. Configure its endpoint and model name and
put EW_LLM_API_KEY in the local environment or ignored .env; never put credentials in YAML.

## Docker and native executables

For Docker, keep Ollama on the host and set EW_LLM_BASE_URL=http://host.docker.internal:11434/v1
and EW_LLM_MODEL=outlook-rag in the ignored deployment .env. The Compose stack defines the host
gateway. Host Ollama must accept traffic from Docker's host gateway; configure its listen address
and host firewall for that private path. A service bound only to host loopback cannot be reached
from a container. The application containers do not contain or launch Ollama.

To populate the container's embedding cache explicitly:

```sh
docker compose exec backend outlook-rag --config /app/config.yaml models download \
  sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

The model-cache volume persists across container replacement. A native OutlookRAGBackend
executable exposes the same models and llm-models commands; replace uv run outlook-rag with
the executable path. Native GUI model dialogs use the same adapters as the CLI.

Live metadata verification does not prove inference quality. The current cloud tests check real
Hugging Face metadata and deterministic download/import failure handling; no multi-gigabyte
generative weights were downloaded and no real local LLM answer was claimed. Validate your chosen
model against representative documents after installation.

The cloud environment's current metadata requests returned HTTP 200. Its attempted real embedding
weight download encountered a proxy HTTP 403 at the model CDN, including us.aws.cdn.hf.co. An online
catalog check therefore does not imply that every download host is reachable. Apply the environment's
model-host allowlist changes or use an approved network before retrying that installation.

