# AGENT.md — guidance for agents working in this repo

A LangChain/LangGraph practice project: a self-hosted chat agent (Ollama local
models) behind a Textual TUI, with RAG over a PDF library and Obsidian vault
tools over MCP.

## Run it (Python 3.12)

```bash
uv sync                                # creates .venv with python 3.12 and installs pinned deps
uv run python app.py                   # the chat TUI
uv run python scripts/ingest.py <pdf_dir>   # build the vector store (dev db first)
uv run python scripts/inspect_context.py    # dump a thread's context as HTML for debugging
```

- Requires a running Ollama server (`ollama run <model>` to pull models).
- All settings live in `.env` (copy `.env.example`). Every key is read,
  type-checked, and path-resolved against the project root in
  `llmtui/config.py` — a bad `.env` fails at import with the offending key.
  Add new settings there, never via raw `os.getenv` elsewhere.
- Prompts are plain files under `prompts/` (`system.txt`, `self_name.txt`),
  pointed at by `.env` paths.

## Architecture

- `app.py` — entry point. Wires model + checkpointer + MCP tools + TUI together.
- `llmtui/agent.py` — the agent: model construction, tool list, and the
  LangChain `create_agent` middleware stack (approval gate, tool-call limit,
  tool-error handling, malformed-call repair). Ordering of middleware matters;
  the comments in `build_agent` explain why.
- `llmtui/tools/` — built-in tools (`search_books`, RAG over Milvus) and the
  MCP client layer (`mcp.py`: server config, tool whitelist, write-tool
  classification, live `MCPStatus`, self-signed-cert httpx factory).
- `llmtui/middleware/` — custom LangChain middleware: `repair.py` (after_model
  hook that recovers malformed tool calls) and `errors.py` (per-tool error
  handlers that feed failures back to the model instead of killing the run).
- `llmtui/tui.py` — Textual frontend only. Streams via
  `astream_events(version="v3")`; it consumes events and never touches
  agent/tool logic.
- `llmtui/writes.py` — diff previews for pending Obsidian writes (pure logic,
  view injected, no UI or MCP imports).
- `llmtui/sessions.py`, `llmtui/naming.py` — session titles in a `sessions`
  table beside LangGraph's checkpoint tables; model names its own threads.
- `scripts/` — async support tasks run straight from a shell. They insert the
  project root onto `sys.path` themselves before importing `llmtui`.
  - `ingest.py`: PDFs → Milvus dev db (hybrid dense+BM25). Promote dev → prod
    by copying `db/milvus_dev.db` over `db/milvus_prod.db` (see README).
  - `inspect_context.py`: renders a checkpointed thread as a self-contained
    HTML page in `resources/context_inspection/`.

**Boundary rule:** LangChain implementation code (models, tools, middleware,
graph assembly) stays inside `llmtui/agent.py`, `llmtui/tools/`, and
`llmtui/middleware/`. The TUI, writes, sessions, and naming modules consume
what the run emits — don't leak LangChain concerns into them.

## Conventions & gotchas

- The codebase is heavily commented with reasoning about *why*; read and
  preserve that style. Don't strip explanatory comments.
- The checkpointer must be `AsyncSqliteSaver` (the sync saver raises on async
  calls); `sessions.py` opens the same file with WAL for the sync side.
- MCP failures are transport-level vs server-reported — `mcp.py` and
  `middleware/errors.py` distinguish and handle these deliberately.
- Tests live in `tests/` (tui, middleware, tools, writes). Run them before
  handing changes back.

## Roadmap (near-term, planned work)

2. **Make the LLM provider pluggable.** Inference is currently hardwired to
   `langchain_ollama.ChatOllama` in `llmtui/agent.py` (`build_model`) with
   Ollama-specific sampling params in `.env`/`config.py`. Refactor so Ollama
   remains the default but other providers can be loaded (provider config in
   `.env`, e.g. a `PROVIDER` key, with per-provider model/sampling handling).
   Note that `IS_REASONING`, `repeat_penalty`, `num_ctx` etc. are
   Ollama-specific and need neutral equivalents or per-provider mapping.
   `scripts/ingest.py` embeddings are also Ollama-bound (`EMBEDDING_MODEL`).
