"""Citation rewrite/parse: a small test, because the regex drifts."""

import sys
from pathlib import Path
from unittest import mock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llmtui.citations import (
    Citation,
    _linux_reader_args,
    _windows_reader_args,
    normalize,
    open_pdf,
    parse,
)


# open_pdf's happy path launches a real reader (or xdg-open) -- these tests
# only care about the path logic, so every launch is mocked out. The fixture
# is autouse so a new success-path test can't accidentally pop up a window.
@pytest.fixture(autouse=True)
def no_real_launches():
    with (
        mock.patch("llmtui.citations._spawn") as spawn,
        mock.patch("llmtui.citations.subprocess.run") as run,
    ):
        yield spawn, run


def test_normalize_variants():
    assert normalize("[book.pdf, pg. 7]") == "[book.pdf, pg. 7](cite://book.pdf?p=7)"
    assert normalize("[book.pdf p.7]") == "[book.pdf p.7](cite://book.pdf?p=7)"
    assert (
        normalize("[book.pdf, page 12]") == "[book.pdf, page 12](cite://book.pdf?p=12)"
    )
    # spaces URL-encoded, visible label unchanged
    assert normalize("[my book.pdf, pg 3]") == (
        "[my book.pdf, pg 3](cite://my%20book.pdf?p=3)"
    )


def test_normalize_idempotent_and_skips():
    ours = "[book.pdf, pg. 7](cite://book.pdf?p=7)"
    assert normalize(ours) == ours
    assert normalize("[a label](https://x.io)") == "[a label](https://x.io)"
    # no page -> link without ?p=
    assert normalize("[notes.pdf]") == "[notes.pdf](cite://notes.pdf)"


def test_normalize_leaves_nested_brackets_alone():
    nested = "[book.pdf, pg 7 and [x.pdf p.2]]"
    assert normalize(nested) == nested


def test_parse_round_trip_and_rejects():
    assert parse("cite://book.pdf?p=7") == Citation("book.pdf", 7)
    assert parse("cite://my%20book.pdf?p=2") == Citation("my book.pdf", 2)
    # full paths from the vector store survive (library has per-game subfolders)
    assert parse("cite://%2FUsers%2Fu%2Fbooks%2FKnave%2FKnave.pdf?p=4") == Citation(
        "/Users/u/books/Knave/Knave.pdf", 4
    )
    assert parse("https://x.io") is None
    assert parse("cite://book.pdf") is None  # no page
    assert parse("cite://book.pdf?p=x") is None


def test_open_pdf_errors(tmp_path):
    missing = open_pdf(Citation("gone.pdf", 3), tmp_path)
    assert missing is not None and "not found" in missing
    assert open_pdf(Citation("x.pdf", 0), tmp_path) is not None


def test_open_pdf_trust_boundary(tmp_path, no_real_launches):
    spawn, run = no_real_launches
    # the resolve() check is the security boundary, not string rejection in parse
    escape = open_pdf(Citation("../outside.pdf", 1), tmp_path)
    assert escape is not None and "outside the library" in escape
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "in.pdf").touch()
    assert open_pdf(Citation("sub/in.pdf", 1), tmp_path) is None
    # a launch was attempted, and it pointed at the file that exists
    argv = spawn.call_args.args[0] if spawn.call_count else run.call_args.args[0]
    assert "sub/in.pdf" in argv[-1]


def test_linux_reader_args_by_preference(tmp_path):
    p = tmp_path / "book.pdf"
    p.touch()
    # first installed reader wins; page is a real CLI arg, never a path suffix
    with mock.patch("llmtui.citations.shutil.which", side_effect=["okular"]):
        assert _linux_reader_args(p, 11) == ["okular", "--page", "11", str(p)]
    with mock.patch("llmtui.citations.shutil.which", side_effect=[None, "evince"]):
        assert _linux_reader_args(p, 3) == ["evince", "--page-number", "3", str(p)]
    # nothing installed: bare xdg-open, no fragment (it cannot interpret one)
    with mock.patch("llmtui.citations.shutil.which", return_value=None):
        assert _linux_reader_args(p, 3) == ["xdg-open", str(p)]


def test_windows_reader_args_fragment_as_argument(tmp_path):
    p = tmp_path / "book.pdf"
    p.touch()
    # Edge is not on PATH: resolved from the fixed install location instead
    with (
        mock.patch("llmtui.citations.shutil.which", return_value=None),
        mock.patch(
            "llmtui.citations.glob.glob",
            return_value=[r"C:\Edge\msedge.exe"],
        ),
    ):
        assert _windows_reader_args(p, 11) == [
            r"C:\Edge\msedge.exe",
            f"{p}#page=11",
        ]
    # a reader on PATH is used directly; Foxit uses its own /t /p syntax
    with mock.patch(
        "llmtui.citations.shutil.which",
        side_effect=[None, None, None, r"C:\Foxit\FoxitPDFReader.exe"],
    ):
        assert _windows_reader_args(p, 11) == [
            r"C:\Foxit\FoxitPDFReader.exe",
            "/t",
            str(p),
            "/p",
            "11",
        ]
    # no reader found: caller falls back to os.startfile (file only)
    with (
        mock.patch("llmtui.citations.shutil.which", return_value=None),
        mock.patch("llmtui.citations.glob.glob", return_value=[]),
    ):
        assert _windows_reader_args(p, 11) is None
