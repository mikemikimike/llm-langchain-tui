Langchain practice: a chat agent behind a Textual TUI, running on any
OpenAI-compatible model endpoint (Ollama locally, or a remote API) using
`python3.12`

Dependencies are managed with [`uv`](https://docs.astral.sh/uv/); after cloning, run `uv sync` to create `.venv` and install the pinned deps, then run things through `uv run`.

Configuration lives in `config/`, gitignored and copied from committed
examples:

- `config/config.json` (from `config.example.json`) — app settings: paths,
  milvus index options, obsidian key/cert. Paths are relative to the project
  root and resolved in `config.py`, so scripts run the same from any
  directory. A bad file fails at import naming the offending key.
- `config/models.json` (from `models.example.json`) — providers and models,
  pi-harness style. Any OpenAI-compatible endpoint (ollama, llama.cpp server,
  vLLM, LM Studio, remote APIs) is a JSON entry; no code changes. Sampling
  params (`temperature`, `top_k`, ...) are per model and sent through
  verbatim. `"$ENV_VAR"` in any string reads from the environment. `/model`
  in the TUI switches between entries and re-reads the file on every open.

`ingest.py` to build vector db for retrieval. db is built into a dev_db first. to migrate dev milvus db to prod:

```
-rf milvus_prod.db && cp -r milvus_dev.db milvus_prod.db
```

embeddings are still ollama-bound (`EMBEDDING_MODEL` in `config/config.json`).

## running it

```
uv run python app.py                        # the chat TUI
uv run python scripts/ingest.py <pdf_dir>   # build the vector store
uv run python scripts/inspect_context.py    # dump a thread's context as html
```
