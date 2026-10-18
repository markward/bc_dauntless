"""No file in native/src may read a file through istreambuf_iterator.

Copying a stream through istreambuf_iterator reads one byte at a time. In
the Debug build that cost ~36 ms per MB: the 12.6 MB collision-scuff normal
map took ~350 ms inside a gameplay frame (perf-register P-11, SIG-046).
assets::read_binary_file (assets/file_bytes.h) reads the whole file in one
block and returns the same bytes.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
NATIVE = ROOT / "native" / "src"
_SOURCES = ("*.cc", "*.cpp", "*.h", "*.hpp")


def _strip_comments(src):
    """Drop // and /* */ comments, keeping every newline so line numbers
    hold; string literals are left alone (no source here spells the iterator
    inside one)."""
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                 src, flags=re.S)
    return re.sub(r"//[^\n]*", "", src)


def bytewise_reads(src):
    """1-based line numbers of each istreambuf_iterator use outside comments."""
    code = _strip_comments(src)
    return [code.count("\n", 0, m.start()) + 1
            for m in re.finditer(r"\bistreambuf_iterator\b", code)]


def test_the_detector_ignores_comments_and_finds_code():
    src = ("// istreambuf_iterator in a comment\n"
           "/* and istreambuf_iterator\n in a block */\n"
           "auto v = std::vector<char>(std::istreambuf_iterator<char>(in), {});\n")
    assert bytewise_reads(src) == [4]


def test_no_bytewise_file_reads_in_native_src():
    hits = []
    for pattern in _SOURCES:
        for path in sorted(NATIVE.rglob(pattern)):
            text = path.read_text(encoding="utf-8", errors="replace")
            for line in bytewise_reads(text):
                hits.append("%s:%d" % (path.relative_to(ROOT), line))
    assert not hits, (
        "byte-at-a-time file reads (use assets::read_binary_file from "
        "assets/file_bytes.h):\n  " + "\n  ".join(hits))
