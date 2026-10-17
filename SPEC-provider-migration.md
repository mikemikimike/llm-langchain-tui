# SPEC — pluggable providers (roadmap task 2)

> Working spec for branch `12-different-provider-support-like-pi`.
> Not committed — validate steps as we go, delete when done.
>
> Mirrors the pi harness `models.json` design
> (pi docs: models.md). llmtui core gains zero provider knowledge:
> it reads one self-provided config file and speaks openai-completions only.

## Decisions (from discussion)

1. `.env` loses all provider-related config. App config moves to JSON.
2. Provider(s) live in their own config file, pi-style: multiple providers
   per file, `/model` picks from it, file reloaded when the picker opens.
3. OpenAI-compatible dialect only for now. No Anthropic yet.
4. Stop hand-tuning context window: get it from the provider; degrade the
   meter gracefully when the provider can't say.
5. No hardcoded providers in llmtui. One config file, core just loads it.
6. Design mirrors pi: `providers` map + per-model `samplingParams` + `/model`.

---

## Step 1 — config.json replaces .env (app-level)

- [ ] new `config.json` (project root), holding ONLY llm-tui app config:
  - paths: `SQLITE_DB_PATH`, `MILVUS_DEV_DB_PATH`, `MILVUS_PROD_DB_PATH`,
    `SYSTEM_PROMPT_PATH`, `SELF_NAME_PROMPT_PATH`, `OBSIDIAN_CERT_PATH`
  - milvus schema: `DENSE_METRIC_TYPE`, `DENSE_INDEX_TYPE`,
    `SPARSE_METRIC_TYPE`, `SPARSE_INDEX_TYPE`
  - agent behaviour: `MAX_TOOL_CALLS`, `DISPLAY_THINKING`
  - secrets: `OBSIDIAN_API_KEY`
  - NOT present anymore (moved to models.json or dropped):
    `MODEL`, `EMBEDDING_MODEL`*, `IS_REASONING`, `TEMPERATURE`, `TOP_K`,
    `TOP_P`, `REPETITION_PENALTY`, `CONTEXT_SIZE`
    (*ingest embeddings stay Ollama-bound for now — note in AGENT.md)
- [ ] `llmtui/config.py` rewritten as typed fail-fast JSON loader
      (drop python-dotenv; keep path resolution against PROJECT_ROOT)
- [ ] `.env` / `.env.example` / `python-dotenv` dep removed
- [ ] `CONFIG_PATH` overridable for tests (env var is fine here, harmless)

Validate: `uv run python -c "import llmtui.config"` fails loudly on bad/missing
`config.json`; scripts still find db/ and prompts/ from any cwd.

## Step 2 — models.json (pi-style providers)

- [ ] new `models.json` + `models.example.json`:
```json
{
  "providers": {
    "ollama": {
      "baseUrl": "http://localhost:11434/v1",
      "api": "openai-completions",
      "apiKey": "ollama",
      "models": [
        {
          "id": "qwen3.8:27b",
          "reasoning": true,
          "samplingParams": { "temperature": 1.0, "top_p": 0.95, "top_k": 20 }
        }
      ]
    }
  }
}
```
- [ ] loader in llmtui (e.g. `llmtui/models_config.py`):
      - validates per entry: `id`, `baseUrl`, `api`
      - `$NAME` / `${NAME}` env interpolation for `apiKey` (pi parity)
      - unknown `api` value → clear error (only `openai-completions` today)
- [ ] MODEL-level keys pass through to the request: `samplingParams` as
      extra OpenAI kwargs (o.f. langchain `model_kwargs`) — core does not
      interpret them; `reasoning` mapped to the dialect's reasoning flag.
- [ ] no provider names known to core — a new OpenAI-compatible server
      (vLLM/LM Studio/llama.cpp router) is just another JSON entry

Validate: entries from two providers (e.g. ollama + a llama.cpp router)
both build a chat model; a malformed entry fails at load naming provider+model.

## Step 3 — agent.py uses the loader

- [ ] `build_model()` takes a provider/model entry, builds
      `ChatOpenAI(base_url=..., api_key=..., model=..., model_kwargs=sampling)`
      — no ChatOllama import left in core
- [ ] `validate_model_on_init` equivalent: fail fast on unreachable baseUrl
- [ ] `build_agent()` signature unchanged otherwise (pass-through)

Validate: chat round-trips against local ollama; middleware stack untouched
(approval gate ordering, repair, tool-limit keep their comments/behavior).

## Step 4 — /model picker in the TUI

- [ ] `/model` slash command: picker over models.json, reloaded on open
      (pi parity: edits show up live)
- [ ] selection persists for the session (not baked into config)
- [ ] new models.json → prompt: switch to a valid one, don't crash sessions
- [ ] session records the switch (tui already logs context lines — keep simple)

Validate: `/model` switches mid-session; broken models.json while a picker
openses → error screen, session survives.

## Step 5 — context window from the provider

- [ ] drop `CONTEXT_SIZE` everywhere (agent no longer sends `num_ctx`;
      the server's own ctx setting rules)
- [ ] header meter: fetch context length from the provider
      - ollama: `/api/show` → `model_info.*.context_length`
      - generic OpenAI-compat: try `/models` details; if unavailable →
        meter degrades to plain token count, NO invented `/N` ceiling
- [ ] USAGE: `usage.total_tokens` from response where the server reports it

Validate: ollama shows real ctx length; pointing at a server without metadata
shows a degraded meter, no crash.

## Step 6 — docs & cleanup

- [ ] pyproject: drop `python-dotenv`; deps otherwise unchanged
- [ ] README/AGENT.md: config.json + models.json walkthrough,
      note ingest.py embeddings still Ollama-bound
- [ ] AGENT.md roadmap: strike task 2
- [ ] delete this spec

## Out of scope (explicitly)

- anthropic / other api dialects (structure allows, later)
- embeddings provider switch (search_books ingest stays ollama)
- `/thinking` level picker, model pricing/catalog
