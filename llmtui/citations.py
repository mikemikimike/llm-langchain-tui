"""Clickable citations: turn the model's bare "[book.pdf, pg. 7]" into links.

The model cites sources the way search_books presents them -- "[file.pdf p.N]".
This module rewrites those citations in streamed answers into markdown links
with a custom scheme:

    [book.pdf pg. 7](cite://book.pdf?p=7)

so a click can be told apart from any other link (the TUI routes by scheme and
opens the PDF at that page). Nothing here imports the UI: open_pdf hands back an
error string instead of raising, and the caller decides how to show it.
"""

import os
import platform
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, unquote

# the custom link scheme that marks a citation. kept as a constant because both
# normalize (writes it) and the TUI handler (routes on it) must agree
CITE_SCHEME = "cite://"


@dataclass
class Citation:
    """A parsed citation link: which book, which page."""

    filename: str
    page: int


# Bare citation in answer text. The bracket form is how search_books presents
# results, so the model tends to repeat it; the page part drifts between
# "pg. 7", "p.7", "page 7", with ,/space separators. Filename non-greedy so the
# first "]" closes the match rather than swallowing a following citation.
_CITATION = re.compile(
    r"\[(?P<file>[^\[\]]+?\.(?:pdf|PDF))(?:[,\s]+(?:pg?|page)\.?\s*(?P<page>\d+))?\s*\]"
)

# text inside an existing markdown link target -- never double-wrap. Only the
# "](...)" side is checked, not the label, because a citation as link *text* is
# exactly what we want to attach a target to
_LINK_TARGET = re.compile(r"\]\([^)\s]*\)")


def parse(href: str) -> Citation | None:
    """A cite:// href (already URL-decoded by Textual) or None if not one."""

    if not href.startswith(CITE_SCHEME):
        return None
    body = href[len(CITE_SCHEME) :]
    # tolerate the encoded form too, in case hrefs ever arrive un-decoded
    if "%" in body:
        body = unquote(body)
    filename, _, page_part = body.partition("?p=")
    if not filename or not page_part.isdigit():
        return None
    return Citation(filename=filename, page=int(page_part))


def normalize(text: str) -> str:
    """Rewrite bare citations into cite:// markdown links, idempotently.

    Text already inside a link target is left alone, so a model-emitted
    markdown link and our own rewrite form both pass through unchanged.
    """

    out: list[str] = []
    pos = 0
    for target in _LINK_TARGET.finditer(text):
        out.append(_rewrite_citations(text[pos : target.start()]))
        out.append(target.group())
        pos = target.end()
    out.append(_rewrite_citations(text[pos:]))
    return "".join(out)


def _rewrite_citations(text: str) -> str:
    """normalize's worker: citations to links on a span with no link targets."""

    def link(match: re.Match) -> str:
        label = match.group().strip("[]")
        href = f"{CITE_SCHEME}{quote(match.group('file'))}"
        if match.group("page"):
            href += f"?p={match.group('page')}"
        return f"[{label}]({href})"

    # a citation nested inside another bracket group (model wrote its own
    # bracketed aside) would rewrite into an unbalanced link and mangle the
    # paragraph -- rewrite only citations at bracket depth 0, leave the rest
    out: list[str] = []
    pos = depth = 0
    for match in _CITATION.finditer(text):
        depth += text[pos : match.start()].count("[") - text[pos : match.start()].count(
            "]"
        )
        out.append(text[pos : match.start()])
        out.append(link(match) if depth == 0 else match.group())
        pos = match.end()
        depth += text[match.start() : pos].count("[") - text[match.start() : pos].count(
            "]"
        )
    out.append(text[pos:])
    return "".join(out)


def _search_library(citation: Citation, library_dir: Path, root: Path) -> str | None:
    """The model abbreviates full-path markers to basenames, so a root miss
    falls back to scanning the library for that filename. One unique match
    opens; several ask the caller to disambiguate; none is the ingest-desync
    case. The scan is a few hundred rglob entries -- fast enough per click,
    and rare (only on misses)."""

    matches = [
        p
        for p in library_dir.rglob("*.pdf")
        if p.name == Path(citation.filename).name
        # case-insensitive root check, same reasoning as open_pdf's boundary
        if str(p.resolve()).lower().startswith(str(root).lower().rstrip("/") + "/")
    ]
    if len(matches) == 1:
        citation.filename = str(matches[0])
        return None
    if len(matches) > 1:
        listing = "\n".join(f"  {p.relative_to(library_dir)}" for p in matches[:5])
        return (
            f"{citation.filename} matches {len(matches)} books in the library; "
            f"cannot pick one:\n{listing}"
        )
    return (
        f"PDF not found in the library: {citation.filename}. The vector store "
        f"may be out of sync with the files -- re-run ingest if it should be "
        f"there."
    )


def open_pdf(citation: Citation, library_dir: Path) -> str | None:
    """Open the cited PDF at its page with the system default reader.

    Returns an error message on failure -- caller shows it -- or None on
    success. Page-arg fidelity is reader-dependent: the "#page=" fragment works
    on Linux readers (evince, zathura) and PDF.js; macOS Preview has no CLI
    page argument so the file alone opens; Windows opens files only.
    """

    if citation.page < 1:
        return f"{citation.filename}: page {citation.page} is not a real page."
    # the citation may name a full path from search results or a bare filename in
    # the library root. resolve() first: it is the security boundary against a
    # crafted link escaping the library (traversal, symlinks) -- string checks
    # cannot see through either. the case-insensitive compare is deliberate:
    # macOS filesystems are case-insensitive, so config and ingest argv can
    # disagree on letter case and both still name the same directory
    path = (library_dir / citation.filename).resolve()
    root = library_dir.resolve()
    root_str = str(root).rstrip("/")
    path_str = str(path)
    if path_str.lower() != root_str.lower() and not path_str.lower().startswith(
        root_str.lower() + "/"
    ):
        return (
            f"Refusing to open {citation.filename}: it resolves outside the "
            f"library at {root}."
        )
    if not path.is_file():
        return _search_library(citation, library_dir, root)
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", str(path)], check=True)
        elif system == "Windows":
            os.startfile(path)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", f"{path}#page={citation.page}"], check=True)
    except (OSError, subprocess.CalledProcessError) as error:
        return f"Could not open {citation.filename}: {error}"
    return None
