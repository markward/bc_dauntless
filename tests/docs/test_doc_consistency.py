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


def test_every_unmarked_oq_is_listed_as_still_open():
    """An OQ with no status marker must appear on the 'Still open' line.

    Catches the drift where an OQ is silently left unmarked and drops out of
    the summary, becoming invisible to scoping.
    """
    text = GAP_ANALYSIS.read_text(encoding="utf-8")
    match = re.search(r"Still open: (.*?) \(\d+\)", text)
    assert match, "gap_analysis.md has no 'Still open: ... (N)' summary line"
    summary = match.group(1)
    for heading in unmarked_oqs(text):
        ident = re.match(r"\*\*(OQ-\d+\.\d+)", heading).group(1)
        major = ident.split("-")[1].split(".")[0]
        # Accept either an explicit mention or a range covering it,
        # e.g. 'OQ-3.1-3.3' covers OQ-3.2.
        assert ident in summary or f"OQ-{major}." in summary, (
            f"{ident} carries no status marker but is absent from the "
            f"'Still open' summary: {summary}"
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


# --- README Windows build instructions vs the actual CEF pinning ----------
#
# The Windows build section and the CEF hash table drifted apart inside a single
# branch: the section was written while CEF was unpinned off macOS and told
# readers to build with -DDAUNTLESS_ENABLE_CEF=OFF, then two later commits on
# that same branch pinned windows64 and taught every native target to link
# under MSVC. The instructions survived, telling Windows users to switch off
# the two things that had just been made to work.

NATIVE_CMAKE = PROJECT_ROOT / "native" / "CMakeLists.txt"


def pinned_cef_platforms() -> dict:
    """CEF_PLATFORM -> whether native/CMakeLists.txt pins a hash for it."""
    text = NATIVE_CMAKE.read_text(encoding="utf-8")
    block = re.search(r'set\(CEF_VERSION.*?\n\s*else\(\)', text, re.DOTALL)
    assert block, "CEF platform selection block not found in native/CMakeLists.txt"
    out = {}
    platform = None
    for line in block.group(0).splitlines():
        m = re.search(r'set\(CEF_PLATFORM "([^"]+)"\)', line)
        if m:
            platform = m.group(1)
            continue
        m = re.search(r'set\(CEF_URL_HASH "([^"]*)"', line)
        if m and platform:
            out[platform] = bool(m.group(1))
            platform = None
    return out


def windows_build_section() -> str:
    text = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
    m = re.search(r"### Building on Windows\n(.*?)(?=\n## )", text, re.DOTALL)
    assert m, "README has no '### Building on Windows' section"
    return m.group(1)


def test_readme_does_not_tell_windows_to_disable_a_pinned_cef():
    if not pinned_cef_platforms().get("windows64"):
        return  # unpinned again: recommending OFF would be correct
    recipe = re.findall(r"```bat\n(.*?)```", windows_build_section(), re.DOTALL)
    assert recipe, "Windows section has no ```bat recipe"
    for block in recipe:
        assert "DAUNTLESS_ENABLE_CEF=OFF" not in block, (
            "windows64 has a pinned CEF hash, but the README's Windows recipe "
            "still disables CEF — the instructions have drifted from the build")


def test_readme_does_not_tell_windows_to_skip_native_tests_that_build():
    """DAUNTLESS_BUILD_TESTS=OFF was advised because the native test targets
    lacked an MSVC force-load arm. They have one now (/WHOLEARCHIVE), so the
    advice is stale the moment those arms exist."""
    msvc_arms = [p for p in (PROJECT_ROOT / "native" / "tests").rglob("CMakeLists.txt")
                 if "WHOLEARCHIVE" in p.read_text(encoding="utf-8")]
    if not msvc_arms:
        return
    for block in re.findall(r"```bat\n(.*?)```", windows_build_section(), re.DOTALL):
        assert "DAUNTLESS_BUILD_TESTS=OFF" not in block, (
            f"{len(msvc_arms)} native test target(s) carry an MSVC /WHOLEARCHIVE "
            "arm, but the README still tells Windows users to skip building them")


# --- CLAUDE.md reference table: a row-length budget ------------------------
#
# The table accreted. A claim would be audited, found stale, and a warning
# APPENDED rather than the claim replaced -- so single rows grew to 3-4.5k
# characters carrying three layers of correction. Two costs, both paid:
#
#   1. The important lines competed with historical scar tissue for attention.
#   2. Rows became the SOLE home for facts (the perf cadences had no topic doc
#      at all), so nobody could prune them safely.
#
# Worse, length hid staleness. When the six heaviest rows were migrated out on
# 2026-09-05, the shield row was found to be describing a texture-sampling
# splash that had been replaced by a procedural one, and still flagging two
# divergences that had been closed weeks earlier (the bubble-entry input on
# 2026-08-19, subsystem residuals on 2026-08-20).
#
# The budget is the fix: a row states what is true NOW and points at a topic
# doc or a well-commented code site for the detail. Detail belongs where it can
# be verified against the tree, not in a summary table.

REFERENCE_TABLE_ROW_BUDGET = 1200


def reference_table_rows() -> list[tuple[int, str, str]]:
    """(line number, label, full row) for each '## Key reference material' row.

    Skips the header and the |---|---| separator.
    """
    lines = CLAUDE_MD.read_text(encoding="utf-8").split("\n")
    rows, in_section = [], False
    for lineno, line in enumerate(lines, start=1):
        if line.startswith("## "):
            in_section = line.strip() == "## Key reference material"
            continue
        if not in_section or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        if len(cells) < 3 or cells[0] in ("Resource",) or set(cells[0]) <= set("-: "):
            continue
        rows.append((lineno, cells[0], line))
    return rows


def test_reference_table_is_found_at_all():
    """Guard the guard: a renamed heading must not silently disable the budget."""
    rows = reference_table_rows()
    assert len(rows) >= 15, (
        f"only {len(rows)} reference-table rows parsed -- the '## Key reference "
        "material' heading or the table format changed, which would silently "
        "switch off the row-length budget below")


def test_no_reference_table_row_exceeds_its_budget():
    """A row over budget means detail is accreting in the summary table again."""
    over = [(n, label, len(row)) for n, label, row in reference_table_rows()
            if len(row) > REFERENCE_TABLE_ROW_BUDGET]
    assert not over, (
        "CLAUDE.md reference-table row(s) over the "
        f"{REFERENCE_TABLE_ROW_BUDGET}-char budget:\n"
        + "\n".join(f"  line {n}: {c} chars -- {label}" for n, label, c in over)
        + "\n\nDo not raise the budget. Move the detail into a topic doc under "
          "docs/engine/ (or a well-commented code site) and leave the row "
          "stating what is true now, plus the pointer.")
