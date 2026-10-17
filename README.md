Langchain practice with self-hosted model through ollama using `python3.12`

Dependencies are managed with [`uv`](https://docs.astral.sh/uv/); after cloning, run `uv sync` to create `.venv` and install the pinned deps, then run things through `uv run`.

Most constants and hyperparameters are defined in `.env`. paths in `.env` are relative to the project root and resolved against it in
`config.py`, so scripts run the same from any directory.

works with ollama, so can install [models](https://ollama.com/library) through `ollama run`. im using the new qwen3.8-27b because why not.

`ingest.py` to build vector db for retrieval. db is built into a dev_db first. to migrate dev milvus db to prod:

```
-rf milvus_prod.db && cp -r milvus_dev.db milvus_prod.db
```

ollama server systemd env variables:

```
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
Environment="OLLAMA_MAX_LOADED_MODELS=2"
```

more parameters (inside .env) injected through python

## running it

```
uv run python app.py                        # the chat TUI
uv run python scripts/ingest.py <pdf_dir>   # build the vector store
uv run python scripts/inspect_context.py    # dump a thread's context as html
```
