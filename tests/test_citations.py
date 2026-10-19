"""Citation rewrite/parse: a small test, because the regex drifts."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from llmtui.citations import Citation, normalize, open_pdf, parse


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
    assert parse("https://x.io") is None
    assert parse("cite://book.pdf") is None  # no page
    assert parse("cite://book.pdf?p=x") is None
    # trust boundary: no paths may smuggle through
    assert parse("cite://../etc/passwd?p=3") is None
    assert parse("cite://..%2F..%2Fetc%2Fpasswd?p=3") is None
    assert parse("cite://C:\\\\windows\\\\evil.pdf?p=1") is None


def test_open_pdf_errors(tmp_path):
    missing = open_pdf(Citation("gone.pdf", 3), tmp_path)
    assert missing is not None and "not found" in missing
    assert open_pdf(Citation("x.pdf", 0), tmp_path) is not None
