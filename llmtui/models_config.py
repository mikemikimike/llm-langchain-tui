"""Model/provider configuration, loaded from models.json at call time.

llmtui core knows nothing about specific providers: this file describes
self-provided OpenAI-compatible endpoints (Ollama, llama.cpp server, vLLM,
LM Studio, ...) in the shape the pi harness uses, and `build_chat_model`
turns an entry into a LangChain chat model. Adding a server is a JSON edit,
never a code change.

Read at call time, not import time: the /model picker reloads the file every
time it opens, so edits show up live. The one dialect implemented today is
"openai-completions"; anything else fails loudly naming provider and model.

models.json is gitignored (providers can carry real api keys);
models.example.json is the committed template.
"""

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT: Path = Path(__file__).resolve().parents[1]

# overridable so tests can point at their own file
MODELS_PATH: Path = Path(
    os.getenv("LLMTUI_MODELS", PROJECT_ROOT / "config" / "models.json")
)

# the one dialect implemented; see build_chat_model
SUPPORTED_APIS = ("openai-completions",)

_ENV_REF = re.compile(r"^\$([A-Za-z_][A-Za-z0-9_]*|\{[A-Za-z_][A-Za-z0-9_]*\})$")

# request fields sampling_params is not allowed to set: these are owned by
# the entry itself (model, reasoning) or by the caller (the conversation).
# sampling params should shape generation, never redirect or reshape the
# request; a collision here is far more likely a mistake than an intent
RESERVED_REQUEST_FIELDS = frozenset({
    "model", "messages", "reasoning", "reasoning_effort", "tools",
    "tool_choice", "response_format", "stream", "stream_options",
    "max_tokens", "max_completion_tokens", "n", "stop", "user",
})

# Authorization is a header: control characters (CRLF and friends) would be
# rejected deep inside httpx at first request; fail here instead, where the
# message names the file and the provider
_UNSAFE_KEY_CHARS = re.compile(r"[\x00-\x1f\x7f\s]")


@dataclass(frozen=True)
class ModelEntry:
    provider: str
    id: str
    # True/False toggles thinking via reasoning_effort (a True maps to
    # "medium", a False to "none"): Ollama's OpenAI endpoint exposes no raw
    # think on/off, only effort levels
    # a string passes through verbatim, for endpoints that name their own
    # effort levels
    reasoning: bool | str | None = None
    # free-form request fields, merged into the request body verbatim;
    # core does not interpret these
    sampling_params: dict | None = None
    # advertised context window in tokens, for the status meter. metadata
    # only -- nothing sends it anywhere
    context_window: int = 0


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api: str
    api_key: str
    models: tuple[ModelEntry, ...]


def _load_json(path: Path) -> dict:
    if not path.exists():
        raise RuntimeError(
            f"{path} not found. Copy config/models.example.json to"
            " config/models.json and point it at a server."
        )
    try:
        with open(path) as f:
            data = json.load(f)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"{path} is not valid JSON: {e}") from None
    if not isinstance(data, dict):
        raise RuntimeError(f"{path}: top level must be an object")
    return data


def _interpolate(value, path: str, key: str):
    """'$NAME' / '${NAME}' in any string is read from the environment.

    A literal passes through as-is; a referenced variable that is unset or
    empty fails here, naming the file, key, and variable.
    """

    if not (isinstance(value, str) and _ENV_REF.match(value)):
        return value
    var = value[1:].strip("{}")
    resolved = os.environ.get(var)
    if not resolved:
        raise RuntimeError(f"{path}: {key} references {var}, which is unset or empty")
    return resolved


def _require(mapping: dict, key: str, path: str, where: str):
    value = _interpolate(mapping.get(key), path, f"{where}.{key}")
    if value is None or (isinstance(value, str) and not value.strip()):
        raise RuntimeError(f"{path}: {where}.{key} is missing or empty")
    if not isinstance(value, str):
        raise RuntimeError(f"{path}: {where}.{key} must be a string, got {value!r}")
    return value.strip()


def _parse_model(raw, provider: str, base_url: str, path: str) -> ModelEntry:
    if not isinstance(raw, dict):
        raise RuntimeError(f"{path}: models entries of provider {provider!r} must be objects")
    where = f"provider {provider!r} model"
    model_id = _require(raw, "id", path, where)

    reasoning = raw.get("reasoning")
    if reasoning is not None and not isinstance(reasoning, (bool, str)):
        raise RuntimeError(f"{path}: {where} {model_id!r} 'reasoning' must be a bool or string")
    if isinstance(reasoning, str):
        reasoning = _interpolate(reasoning, path, f"{where} {model_id!r} reasoning")

    sampling = raw.get("samplingParams")
    if sampling is not None:
        if not isinstance(sampling, dict):
            raise RuntimeError(
                f"{path}: {where} {model_id!r} 'samplingParams' must be an object"
            )
        for key in sampling:
            if key.lower() in RESERVED_REQUEST_FIELDS:
                raise RuntimeError(
                    f"{path}: {where} {model_id!r} samplingParams.{key} is a"
                    " reserved request field and cannot be overridden"
                )
        sampling = {
            key: _interpolate(value, path, f"{where} {model_id!r} samplingParams.{key}")
            for key, value in sampling.items()
        }

    context_window = raw.get("contextWindow", 0)
    if not isinstance(context_window, int) or context_window < 0:
        raise RuntimeError(
            f"{path}: {where} {model_id!r} 'contextWindow' must be a non-negative integer"
        )

    return ModelEntry(
        provider=provider,
        id=model_id,
        reasoning=reasoning,
        sampling_params=sampling,
        context_window=context_window,
    )


def load_models(path: Path | None = None) -> dict[str, Provider]:
    """Read and validate models.json. Raises at every call, naming the file.

    Returns providers keyed by name; each holds its model entries. Called at
    app start and again every time the /model picker opens, so live edits
    are picked up.
    """

    path = path or MODELS_PATH
    data = _load_json(path)

    providers_raw = data.get("providers")
    if not isinstance(providers_raw, dict) or not providers_raw:
        raise RuntimeError(f"{path}: 'providers' must be a non-empty object")

    providers: dict[str, Provider] = {}
    for name, prov in providers_raw.items():
        if not isinstance(prov, dict):
            raise RuntimeError(f"{path}: provider {name!r} must be an object")
        where = f"provider {name!r}"
        base_url = _require(prov, "baseUrl", path, f"{where} connection")
        api = _require(prov, "api", path, f"{where} connection")
        api_key = _require(prov, "apiKey", path, f"{where} connection")

        if not base_url.startswith(("http://", "https://")):
            raise RuntimeError(
                f"{path}: {where}.baseUrl must be an http(s) url, got {base_url!r}"
            )
        if _UNSAFE_KEY_CHARS.search(api_key):
            raise RuntimeError(
                f"{path}: {where}.apiKey contains control characters or whitespace"
            )

        if api not in SUPPORTED_APIS:
            raise RuntimeError(
                f"{path}: {where} declares api {api!r}; supported: {SUPPORTED_APIS}"
            )

        models_raw = prov.get("models")
        if not isinstance(models_raw, list) or not models_raw:
            raise RuntimeError(f"{path}: {where}.models must be a non-empty list")

        seen: set[str] = set()
        models = []
        for raw in models_raw:
            entry = _parse_model(raw, name, base_url, path)
            if entry.id in seen:
                raise RuntimeError(f"{path}: duplicate model id {entry.id!r} in {where}")
            seen.add(entry.id)
            models.append(entry)

        providers[name] = Provider(
            name=name, base_url=base_url, api=api, api_key=api_key,
            models=tuple(models),
        )
    return providers


def flatten(providers: dict[str, Provider]) -> list[ModelEntry]:
    """All model entries, in provider-then-file order, for pickers."""

    return [m for p in providers.values() for m in p.models]


# ---------------------------------------------------------------------
# the dialect. one function, one api; a new dialect means a new branch in
# here, not a change anywhere else in the codebase
# ---------------------------------------------------------------------

def _reasoning_effort(entry: ModelEntry):
    if entry.reasoning is None:
        return None
    if isinstance(entry.reasoning, str):
        return entry.reasoning
    return "medium" if entry.reasoning else "none"


def build_chat_model(entry: ModelEntry, provider: Provider):
    """Turn a validated entry into a chat model. Only openai-completions exists.

    sampling_params are merged into the request body verbatim via extra_body --
    the server decides which fields mean what (o. top_k / repeat_penalty on
    Ollama), core does not interpret them. temperature/top_p are also sent
    through extra_body so that what lands on the wire is exactly what the
    json asked for, nothing normalized away.
    """

    if provider.api != "openai-completions":
        raise RuntimeError(
            f"no builder for api {provider.api!r} (provider {provider.name!r})"
        )

    from langchain_openai import ChatOpenAI

    extra_body = dict(entry.sampling_params or {})
    effort = _reasoning_effort(entry)
    if effort is not None:
        extra_body["reasoning_effort"] = effort

    return ChatOpenAI(
        base_url=provider.base_url,
        api_key=provider.api_key,
        model=entry.id,
        extra_body=extra_body or None,
    )


# ---------------------------------------------------------------------
# context length from the provider
#
# metadata (contextWindow on the entry) wins when declared; this is the
# live fallback for servers whose entries omit it. best-effort only -- a
# failure here leaves the meter at 0 (plain token count), never raises
# into the run
# ---------------------------------------------------------------------

async def fetch_context_window(entry: ModelEntry, provider: Provider) -> int:
    """Ask the server how long the context is. 0 when it cannot say.

    Only ollama has a shaped answer today (/api/show on the native port,
    model_info.<arch>.context_length). The /v1 compat endpoint does not
    expose it, so the baseUrl is rewritten to the native one. Other
    openai-compat servers fall through to 0 promptly.
    """

    if provider.name != "ollama":
        return 0

    import httpx

    # http://localhost:11434/v1 -> http://localhost:11434
    native = provider.base_url.rstrip("/")
    if native.endswith("/v1"):
        native = native[: -len("/v1")]

    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.post(
                f"{native}/api/show",
                json={"model": entry.id},
                headers={"Authorization": f"Bearer {provider.api_key}"},
            )
            r.raise_for_status()
            info = r.json().get("model_info") or {}
        lengths = [v for k, v in info.items() if k.endswith(".context_length")]
        return max(lengths) if lengths else 0
    except Exception:
        return 0
