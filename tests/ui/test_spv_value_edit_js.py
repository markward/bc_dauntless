"""Source-shape guards for the SPV click-to-edit value rows (no JS runtime
harness -- brainstorm D6; behaviour is Mark's live check, spec S8).

Spec: docs/superpowers/specs/2026-10-02-cef-text-input-keyboard-capture-design.md S5.1
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JS = ROOT / "native/assets/ui-cef/js/ship_property_viewer.js"
HTML = ROOT / "native/assets/ui-cef/index.html"
CSS = ROOT / "native/assets/ui-cef/css/ship_property_viewer.css"


def _fn(src, name):
    m = re.search(r"function\s+%s\s*\(" % name, src)
    assert m, name
    i = src.index("{", m.end())
    depth = 0
    for j in range(i, len(src)):
        depth += {"{": 1, "}": -1}.get(src[j], 0)
        if depth == 0:
            return src[i:j + 1]
    raise AssertionError(name)


def test_spv_root_is_tagged_for_text_capture():
    assert re.search(r'<div id="spv-root"[^>]*data-panel="ship-property-viewer"',
                     HTML.read_text())


def test_value_span_is_still_between_the_steppers_and_starts_an_edit():
    body = _fn(JS.read_text(), "spvStepperRow")
    order = [body.index("b(-big)"), body.index("b(-small)"),
             body.index("spv-coords__val"), body.index("b(small)"),
             body.index("b(big)")]
    assert order == sorted(order)
    assert "spvBeginValueEdit(" in body


def test_all_three_panels_pass_their_kind():
    body = _fn(JS.read_text(), "renderSPVToolPanels")
    for kind in ("'coord'", "'scale'", "'rotate'"):
        assert kind in body


def test_edit_keeps_the_axis_label_and_adds_cancel_then_ok():
    body = _fn(JS.read_text(), "spvBeginValueEdit")
    assert "spv-coords__axis" in body
    assert body.index("\\u2715") < body.index("\\u2713")      # ✕ then ✓
    assert "__dauntlessTextCancel(" in body and "__dauntlessTextCommit(" in body
    assert ".select()" in body


def test_edit_buttons_do_not_steal_focus():
    body = _fn(JS.read_text(), "spvEditButton")
    assert "'mousedown'" in body and "preventDefault()" in body


def test_unchanged_text_sends_nothing_and_commit_routes_each_kind():
    body = _fn(JS.read_text(), "spvFinishValueEdit")
    # The "unchanged" check guards the commit branch (F3 refactor: an `if`
    # block rather than an early `return`, so the re-render at the end of
    # the function still runs on every exit path -- see
    # test_finish_value_edit_rerenders_from_the_cached_payload).
    assert body.index("!== ed.original") < body.index("dauntlessEvent(")
    for ev in ("coord_set", "scale_set", "rotate_set"):
        assert ev in body


def test_parse_rejects_empty_and_accepts_decimal_comma():
    """Review Focus 1 + 2: Number('') is 0, so empty must be refused
    explicitly; '1,5' must read as 1.5."""
    body = _fn(JS.read_text(), "spvParseValue")
    assert ".trim()" in body
    assert "=== ''" in body
    assert body.index("=== ''") < body.index("Number(")
    assert "replace(','" in body
    assert "isFinite(" in body


def test_show_panel_does_not_rebuild_under_an_open_edit():
    body = _fn(JS.read_text(), "spvShowPanel")
    guard = body.index("spvEdit")
    assert guard < body.index("innerHTML")


def test_stale_mouse_only_comments_are_gone():
    """Every 'no keyboard->CEF forwarding' claim is false once capture ships."""
    assert "keyboard->CEF" not in HTML.read_text()
    assert "keyboard->CEF" not in JS.read_text()


def test_value_reads_as_clickable_and_input_is_styled():
    css = CSS.read_text()
    assert re.search(r"\.spv-coords__val\s*\{[^}]*cursor:\s*text", css)
    assert ".spv-coords__input" in css


def test_finish_value_edit_rerenders_from_the_cached_payload():
    """F3: spvShowPanel's edit-mode guard means a payload refresh that
    arrives while a row is being typed into is skipped for that row's
    panel. If spvFinishValueEdit does not re-render once the row swaps
    back, that skipped payload is never applied until some LATER Python
    change -- the panel reads stale until then. renderSPVToolPanels must
    cache the data it was last called with (the same pattern as
    spvDecalRerender/spvLastDecals), and spvFinishValueEdit must re-render
    from that cache after clearing spvEdit, on every exit path (commit,
    revert, and empty/non-finite rejection)."""
    src = JS.read_text()

    panels_body = _fn(src, "renderSPVToolPanels")
    assert "spvLastToolPanelsData = data" in panels_body
    # Cached unconditionally, before any of the three spvShowPanel calls
    # (which is what makes the cache correct even while one of them is
    # being skipped by the edit-mode guard).
    assert (panels_body.index("spvLastToolPanelsData = data")
            < panels_body.index("spvShowPanel("))

    finish_body = _fn(src, "spvFinishValueEdit")
    assert "renderSPVToolPanels(spvLastToolPanelsData)" in finish_body
    # After spvEdit is cleared...
    assert (finish_body.index("spvEdit = null")
            < finish_body.index("renderSPVToolPanels(spvLastToolPanelsData)"))
    # ...and on every exit path: the rerender call must not be nested
    # inside the "text changed" / "value parsed" conditionals that guard
    # the commit event, i.e. it sits at the same brace depth as the
    # function body itself, after those conditionals close.
    commit_idx = finish_body.index("dauntlessEvent(")
    rerender_idx = finish_body.index("renderSPVToolPanels(spvLastToolPanelsData)")
    assert rerender_idx > commit_idx
