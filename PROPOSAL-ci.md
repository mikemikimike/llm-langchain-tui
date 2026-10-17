# Proposal: CI pipeline + homogeneous formatting

Status: proposal, awaiting approval. Scope: formatting rules, markdown source style, and
a minimal CI workflow. Out of scope (phase 2): pytest conversion and running tests in CI
— see "Tests" at the bottom.

______________________________________________________________________

## 1. Problem

The repo currently mixes three width rules with nothing enforcing the prose ones:

| What | Today | Enforced by | | ------------------ | ---------------------------- |
------------------------- | | Python code | 96 cols | `ruff format` | | Markdown prose |
88 cols | `mdformat --wrap 88` | | Comments/docstring | "96-ish" convention (AGENT.) |
nothing |

Separately: markdown files that went through `mdformat --wrap 88` have hard line breaks
inserted mid-paragraph in the raw source. They render correctly, but the source no
longer looks like what was typed. That is mdformat working as designed, not a bug — but
it is a choice the repo has been making by accident. This proposal makes it explicitly.

## 2. Rule: one width everywhere — 88

Adopt **88 columns** as the single width for all text in the repo:

- Python code (`[tool.ruff] line-length = 88`, the Black/ruff default)
- Markdown prose (`mdformat --wrap 88`, unchanged)
- Comments and docstrings (convention, not tool-enforced — ruff's formatter deliberately
  leaves prose alone, and `E501` reacts to the formatter rather than replacing it;
  AGENT.md states the rule, humans and reviewers apply it)

Why 88 and not 80: it is the formatting mainstream's default, it gives code a few
comfortable extra columns, and it removes the current 96/88 split. If 80 is preferred,
every number in this doc and `pyproject.toml` changes; the structure does not.

## 3. Markdown source style: pick A or B, deliberately

**Option A — keep the reflow (recommended).** `mdformat --wrap 88` rewrites each
paragraph as one clause-per-line block at 88 columns. The source is verbose-looking,
but:

- diffs become word-granular: a one-word edit is a one-line diff, not a re-signed
  paragraph
- no manual wrangling: `mdformat` is the single source of truth; nobody hand-wraps
  markdown ever again

The "weird newlines" impression comes from the *first* reflow of hand-wrapped files.
After that initial commit, reflow only touches paragraphs you actually edited. This is
the same trade long-lived manuals make.

**Option B — `--wrap keep`.** mdformat only normalizes md syntax (list markers,
emphasis, spacing) and never reflows your lines. The source stays as typed, but line
length in markdown becomes unpoliced and diffs stay noisy.

The recommendation is A: one command owns the file, and the odd-looking source is a
predictable, stable artifact.

## 4. Everything lives inside uv

- Dev tools are declared in `[dependency-groups] dev` (already true: `ruff==0.17.1`,
  `mdformat==1.0.0`) and installed **only** via `uv sync --group dev`.
- Every command in docs, CI, and the Makefile goes through `uv run ...`. No pip, no
  pre-installed tools, no npx, no global state.
- CI needs no Python on the runner beyond uv itself; uv fetches the pinned interpreter
  and the locked env from `uv.lock`.

### Makefile (thin wrapper, same strings as CI)

```makefile
format:   ## reformat code + markdown
	uv run ruff format .
	uv run ruff check --fix .
	uv run mdformat --wrap 88 .

lint:     ## check only (what CI runs)
	uv run ruff format --check .
	uv run ruff check .
	uv run mdformat --check --wrap 88 .

test:     ## script-style suites (phase 2 moves these into CI)
	uv run python tests/test_tools.py
	uv run python tests/test_writes.py
	uv run python tests/test_middleware.py
```

Note: `mdformat .` with the repo's gitignore honored skips `config/*.json`; those files
stay hand-formatted 4-space by convention (mdformat's json style is too flat for
config). If the glob ever misbehaves in mdformat 1.x, pass explicit paths:
`mdformat --wrap 88 *.md docs/`.

## 5. CI workflow (`.github/workflows/ci.yml`)

One job, no matrix, sub-minute runtime:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:

jobs:
  check:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v5
      - run: uv sync --group dev
      - run: uv run ruff format --check .
      - run: uv run ruff check .
      - run: uv run mdformat --check --wrap 88 .
```

Phase 2 adds `uv run pytest -m "not live"` to the end of this job once the test suites
are pytest-collectable.

## 6. Sequence of work (one PR is enough)

1. Flip `line-length` to 88 in `pyproject.toml`; run `ruff format .` (only a handful of
   files change beyond the current 96 sweep).
1. First mdformat pass over all tracked `.md` files — this is the commit where the
   "weird newlines" land once, and never again (Option A), or the `--wrap keep` config
   (Option B).
1. Add the Makefile and the workflow file.
1. AGENT.md: replace the 96/88 mixed convention with the single-width rule and the
   fmt/lint commands.
1. CI goes green; formatting enforcement is then automatic for every PR.

## 7. Tests

Out of scope for this PR, stated so the omission is deliberate:

- `tests/` are script-style (`asyncio.run(main())` + `check()`), not pytest-collectable.
- `tests/test_tui.py` currently fails on main for pre-existing reasons
  (`LlmTui.__init__` signature drift, plus a suspected double-compose in the Textual
  harness under investigation).

Phase 2 (separate PR): convert suites or wrap them for pytest, add
`pytest`/`pytest-asyncio` to the dev group, mark live-provider tests with a `live`
marker, and append the pytest step to `ci.yml`.
