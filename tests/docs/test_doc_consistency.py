"""Mechanical guards on self-reported counts in project docs.

These exist because gap_analysis.md, CLAUDE.md and stub_heatmap.md each declare
counts that drifted from their own contents, which produced confident, wrong
scoping work. A declared number that disagrees with the table under it is a bug.

See docs/superpowers/specs/2026-08-09-open-question-reconciliation-design.md.
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
GAP_ANALYSIS = PROJECT_ROOT / "docs" / "gap_analysis.md"
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
HEATMAP = PROJECT_ROOT / "docs" / "stub_heatmap.md"

# A status marker is a green tick (resolved) or a warning sign (partial).
STATUS_MARKERS = ("✅", "⚠")


def oq_headings(text: str) -> list[str]:
    """Every '**OQ-N.M — ...**' heading line in the document, verbatim."""
    return re.findall(r"^\*\*OQ-\d+\.\d+.*$", text, flags=re.MULTILINE)


def unmarked_oqs(text: str) -> list[str]:
    """OQ headings carrying no status marker — i.e. still open."""
    return [h for h in oq_headings(text) if not any(m in h for m in STATUS_MARKERS)]


def test_still_open_count_matches_unmarked_oqs():
    """The '(N)' on the 'Still open' line must equal the OQs lacking a marker."""
    text = GAP_ANALYSIS.read_text(encoding="utf-8")
    match = re.search(r"Still open:.*?\((\d+)\)", text)
    assert match, "gap_analysis.md has no 'Still open: ... (N)' summary line"
    declared = int(match.group(1))
    actual = unmarked_oqs(text)
    assert declared == len(actual), (
        f"gap_analysis.md declares {declared} still open but {len(actual)} OQ "
        f"headings carry no status marker: {[h[:40] for h in actual]}"
    )


def test_claude_md_oq_total_matches_gap_analysis():
    """CLAUDE.md's OQ total must equal the OQ headings in gap_analysis.md."""
    total = len(oq_headings(GAP_ANALYSIS.read_text(encoding="utf-8")))
    claude = CLAUDE_MD.read_text(encoding="utf-8")
    match = re.search(r"Gap analysis OQs \((\d+) total\)", claude)
    assert match, "CLAUDE.md has no '### Gap analysis OQs (N total)' heading"
    assert int(match.group(1)) == total, (
        f"CLAUDE.md claims {match.group(1)} OQs; gap_analysis.md has {total}"
    )


def test_heatmap_header_open_count_matches_table():
    """Regression guard: header 'Open: N' must equal open-roadmap row count.

    This currently PASSES (229 == 229). It is here to keep it that way.
    """
    text = HEATMAP.read_text(encoding="utf-8")
    match = re.search(r"Open: (\d+),", text)
    assert match, "stub_heatmap.md header has no 'Open: N,' count"
    declared = int(match.group(1))

    # The open roadmap is the section before '## Resolved'.
    open_section = text.split("## Resolved")[0]
    rows = re.findall(r"^\| \d+ \|", open_section, flags=re.MULTILINE)
    assert declared == len(rows), (
        f"heatmap header declares {declared} open rows; table has {len(rows)}"
    )
