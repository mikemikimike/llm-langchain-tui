# Plan: clickable PDF citations

> Working doc for the citation-link feature. We validate each phase against this file as
> it lands. Design rationale lives inline; keep it updated when a decision changes.

## Feature statement

When the agent cites a source in an answer — `[book.pdf, pg. 7]` — that citation becomes
a clickable markdown link. Clicking it opens the referenced PDF at the referenced page
using the system default PDF reader.

## How it works (Textual mechanics, verified against textual 8.2.8)

- Answers stream into a `Markdown` widget (`tui.py`, `AssistantTurn.write_answer`) via
  `Markdown.get_stream()`. Already markdown, so links render for free.
- A markdown link `[text](href)` renders cells carrying
  `style.meta = {"@click": "link('href')"}` (`_markdown.py`, `link_open` token branch).
  No Python handler is attached at render time.
- On click: app synthesizes `Click` → screen stamps `event.style` from
  `get_style_at(x, y)` → widget `_on_click` brokers the event → `app._broker_event`
  extracts the `link(...)` action and `run_action`s it → resolves by naming convention
  to `action_link` on the content block.
- `action_link` posts `Markdown.LinkClicked(markdown, href)` — `href` is already
  `unquote`d. The message bubbles: content block → `Markdown` → screen → app.
- Default behavior: `Markdown.on_markdown_link_clicked` opens the browser unless the
  widget was constructed with `open_links=False`. We take the second path: flag off, one
  app-level handler owns all link routing.

## Architecture

```
search_books result "[book.pdf p.7]"            (exists today)
        │
        ▼
model cites in answer text:  [book.pdf, pg. 7]
        │
        ▼  (1) citations.py — pure, tested
rewrite to markdown link:    [book.pdf, pg. 7](cite://book.pdf?p=7)
        │
        ▼  (2) AssistantTurn.write_answer — normalize before stream
Markdown widget (open_links=False)
        │  click → action_link → post_message(LinkClicked, href unquoted)
        ▼
(3) LlmTui handler @on(Markdown.LinkClicked) — route by scheme
        │  cite://
        ▼
(4) citations.py open_pdf(file, page) — subprocess launch, per-OS
```

## Phases

<!-- Check items as they land. Each phase ends with its validation line. -->

### Phase 1 — `llmtui/citations.py` (pure logic, no UI, mirrors `writes.py`)

- [ ] Constants + `Citation` dataclass: `CITE_SCHEME = "cite://"`,
  `parse(href: str) -> Citation | None` (splits filename + page, tolerates URL-decoded
  input).
- [ ] `normalize(text: str) -> str`: regex rewrite of bare citations
  (`[book.pdf, pg. 7]`, `[book.pdf p.7]`, `[book.pdf, page 7]`) into
  `[book.pdf, pg. 7](cite://book.pdf?p=7)`; filename URL-encoded; skip text already
  inside a markdown link target (no double-wrap).
- [ ] `open_pdf(citation, library_dir: Path) -> str | None`: resolve
  `library_dir / filename`, verify existence + `.pdf`, launch per OS, return an error
  string (None on success) for the TUI to `notify()`. - Linux:
  `xdg-open "<path>#page=<n>"` - macOS: `open "<path>"`; page accuracy needs an
  AppleScript fallback (Preview has no CLI page arg) — defer - Windows:
  `os.startfile(path)` — file only
- [ ] Tests in `tests/test_citations.py`: normalization variants, no-double-wrap, parse
  round-trip with URL-encoded spaces in filenames, missing-file error.

Validate: `uv run pytest tests/test_citations.py`, `make lint`.

### Phase 2 — config + app plumbing

- [ ] `config/config.example.json`: add `"library": { "pdf_dir": "resources/pdfs" }`.
- [ ] `llmtui/config.py`: `LIBRARY_DIR` under a new `"library"` section, path-resolved
  against project root, fail-fast (existing loader style).
- [ ] `app.py`: pass `LIBRARY_DIR` through to `LlmTui.__init__` → `self.library_dir`.
- [ ] Note in a comment: Milvus metadata holds `basename` only, so two same-named PDFs
  in different subdirs collide — accepted limitation.

Validate: run app with the new key present and deliberately absent (loader must name
file, section, key); `make lint`; tests still green.

### Phase 3 — TUI wiring

- [ ] `AssistantTurn.write_answer`: `await self._md.write(citations.normalize(text))` —
  normalize whole appends here, not per-chunk, because a citation can split across
  stream chunks and MarkdownStream re-parses final blocks anyway.

- [ ] Reasoning: leave un-normalized (folded, links inert there) — revisit if it annoys.

- [ ] `tui.py:251`: `Markdown(classes="answer", open_links=False)` — suppresses default
  browser-open on answers; streamed content included (constructor flag covers
  `MarkdownStream`).

- [ ] Handler on `LlmTui`:

  ```python
  @on(Markdown.LinkClicked)
  async def on_link_clicked(self, event: Markdown.LinkClicked) -> None:
      event.stop()
      citation = citations.parse(event.href)
      if citation is None:
          self.app.open_url(event.href)  # http(s) etc. — behavior preserved
          return
      error = citations.open_pdf(citation, Path(self.library_dir))
      if error:
          self.notify(error, severity="error")
  ```

Validate: `uv run python app.py`, ask a cited question, click the citation — PDF opens
(page on Linux); click a URL link if the model produces one — browser still opens.
`make lint`, full `uv run pytest`.

### Phase 4 — prompt

- [ ] `prompts/system.txt`: add citation rule — cite as `[<filename>.pdf, pg. <n>]`
  exactly as returned by search results, e.g.
  `[n1_against_the_cult_of_the_reptile_god.pdf, pg. 14]`; never invent filenames or
  pages. `search_books` output format stays untouched.

Validate: fresh question over the library, answer contains bare citations that normalize
into links (inspect via click behavior, or dump the markdown source temporarily while
testing).

## Open items / accepted limitations

- Page-open fidelity is reader-dependent: `#page=` works on Linux readers (evince,
  zathura) and PDF.js; macOS Preview needs AppleScript; Windows file-only. First cut
  ships Linux-page / macOS-file / Windows-file.
- Same-basename PDF collation (Phase 2 note).
- Model may mangle the format — that is why `normalize` is regex-tolerant instead of
  trusting the model to emit valid markdown links.
- If citations should someday also link to a library side-panel or message footer,
  `cite://` scheme leaves room for a second target type.

## Design decisions log

| # | Decision | Why | | - | -------- | --- | | 1 | `cite://` scheme inside markdown
links | one handler routes by scheme; distinguishes citations from web links;
URL-encoding handles spaces | | 2 | `open_links=False` + app-level
`@on(Markdown.LinkClicked)` | consumption of the message, not overriding Textual;
`action_link`/message path unchanged | | 3 | normalize in `write_answer`, not per stream
chunk | citation can split across chunks; re-parse of final blocks makes whole-append
cheap | | 4 | error string from `open_pdf`, not exceptions | TUI decides presentation
via `notify()`; pure module stays UI-free | | 5 | no changes to `search_books.py` | its
`[source p.N]` output already feeds the model the (file, page) pairs to cite |
