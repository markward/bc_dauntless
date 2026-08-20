"""The CEF assets must exist, be wired into index.html, and keep the map
viewport transparent so the GL pass beneath shows through."""
import re
from pathlib import Path

from engine.ui.star_map_panel import (HEADER_H, MAP_H, MAP_RECT, MAP_W,
                                      MODAL_H, MODAL_W, rect_for_view)

ASSETS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"


def test_script_and_stylesheet_are_registered_in_index():
    index = (ASSETS / "index.html").read_text()
    assert "js/star_map.js" in index
    assert "css/star_map.css" in index


def test_panel_section_exists_with_the_required_ids():
    index = (ASSETS / "index.html").read_text()
    for el in ("star-map-panel", "star-map-viewport",
               "star-map-labels", "star-map-warps"):
        assert 'id="' + el + '"' in index, el


def test_map_viewport_is_transparent():
    """The GL pass draws beneath. An opaque background here hides the map
    entirely — the single most likely way to ship a black rectangle."""
    css = (ASSETS / "css" / "star_map.css").read_text()
    block = re.search(r"#star-map-viewport\s*\{[^}]*\}", css)
    assert block, "no #star-map-viewport rule"
    assert "transparent" in block.group(0)


def _viewport_css_body():
    css = (ASSETS / "css" / "star_map.css").read_text()
    block = re.search(r"#star-map-viewport\s*\{([^}]*)\}", css)
    assert block, "no #star-map-viewport rule"
    return block.group(1)


def _calc_offset(body, prop):
    """The Npx in `prop: calc(50% - Npx)` — the CSS half of the centring rule."""
    m = re.search(prop + r"\s*:\s*calc\(\s*50%\s*-\s*(-?\d+(?:\.\d+)?)px\s*\)",
                  body)
    assert m, "missing " + prop + ": calc(50% - Npx) in #star-map-viewport"
    return float(m.group(1))


def test_viewport_css_centring_matches_the_python_formula():
    """Python projects labels and hit-tests clicks against panel.rect; the GL
    pass scissors to it. If the CSS rect disagrees, every label is displaced
    and every click mis-picks.

    The rect is NOT a constant — the CEF logical view tracks the host window
    in points and .cp-modal is flex-centred in it, so both languages express
    the SAME centring rule. Assert the CSS offsets are derived from the same
    modal constants rather than pinning literals (which is exactly how the
    two drifted: fixed CSS + a fixed MAP_RECT agreed only at 1280x720, and at
    1512x982 the chrome sat at (316, 211) with the map at (200, 108))."""
    body = _viewport_css_body()

    # 50% - MODAL_W/2 horizontally; 50% - (MODAL_H/2 - HEADER_H) vertically.
    # The 1px border cancels — see rect_for_view's docstring.
    assert _calc_offset(body, "left") == MODAL_W / 2
    assert _calc_offset(body, "top") == MODAL_H / 2 - HEADER_H

    def _px(prop):
        m = re.search(prop + r"\s*:\s*(-?\d+(?:\.\d+)?)px", body)
        assert m, "missing " + prop + " in #star-map-viewport"
        return float(m.group(1))

    assert (_px("width"), _px("height")) == (float(MAP_W), float(MAP_H))
    assert "position" in body and "fixed" in body

    # #star-map-warps reserves the viewport's width with its own margin-left
    # (the viewport is position:fixed and so out of .sm-body's flow) — that
    # literal is another untested copy of the map width unless pinned here.
    css = (ASSETS / "css" / "star_map.css").read_text()
    warps_block = re.search(r"#star-map-warps\s*\{([^}]*)\}", css)
    assert warps_block, "no #star-map-warps rule"
    m = re.search(r"margin-left\s*:\s*(-?\d+(?:\.\d+)?)px", warps_block.group(1))
    assert m, "missing margin-left in #star-map-warps"
    assert float(m.group(1)) == float(MAP_W)


def test_python_rect_reproduces_the_css_rect_at_two_view_sizes():
    """The two languages must agree on real numbers, not just on constants.
    1280x720 is the boot view (and MAP_RECT's pinned value); 1512x983 is an
    odd size that exercises the half-pixel rounding."""
    body = _viewport_css_body()
    left_off, top_off = _calc_offset(body, "left"), _calc_offset(body, "top")

    def _css_rect(view_w, view_h):
        # Chromium resolves 50% against the view; rect_for_view rounds. The
        # two can differ by <=1px on odd sizes — the labels live INSIDE the
        # CSS rect so they never separate from it, and a <=1px star offset is
        # invisible. Assert agreement to that tolerance.
        return (view_w / 2 - left_off, view_h / 2 - top_off)

    assert rect_for_view(1280, 720) == MAP_RECT == (200, 108, 640, 520)
    for view_w, view_h in ((1280, 720), (1512, 983)):
        rx, ry, rw, rh = rect_for_view(view_w, view_h)
        cx, cy = _css_rect(view_w, view_h)
        assert abs(rx - cx) <= 1.0, (view_w, view_h, rx, cx)
        assert abs(ry - cy) <= 1.0, (view_w, view_h, ry, cy)
        assert (rw, rh) == (MAP_W, MAP_H)


def test_render_fn_matches_the_python_payload_name():
    js = (ASSETS / "js" / "star_map.js").read_text()
    assert "function setStarMapPanel(" in js


def test_events_use_the_panel_routing_prefix():
    js = (ASSETS / "js" / "star_map.js").read_text()
    # star-map/select-system is deliberately excluded: nothing in the JS
    # fires it (map selection goes through star-map/pick:<x>,<y>); the panel
    # still handles select-system: server-side (T4's tests cover it).
    # star-map/cancel is deliberately excluded here too: it fires from the
    # Cancel button's inline onclick in index.html, not from this file (it
    # appears in star_map.js only in a comment) — see
    # test_cancel_event_is_wired_from_the_cancel_button below, which asserts
    # against the real firing site.
    for evt in ("star-map/set-course", "star-map/pick",
                "star-map/orbit", "star-map/zoom"):
        assert evt in js, evt


def test_cancel_event_is_wired_from_the_cancel_button():
    """star-map/cancel fires from the Cancel button's inline onclick in
    index.html (matching the sibling #setting-course-panel convention), not
    from star_map.js. Assert against that real firing site so removing the
    onclick and leaving star_map.js's header-comment mention would fail
    this test, rather than passing vacuously."""
    index = (ASSETS / "index.html").read_text()
    section = re.search(r'<section id="star-map-panel".*?</section>',
                         index, re.DOTALL)
    assert section, "no #star-map-panel section"
    assert "onclick=\"dauntlessEvent('star-map/cancel')\"" in section.group(0)


def test_labels_are_escaped():
    js = (ASSETS / "js" / "star_map.js").read_text()
    assert "escapeHtmlSM" in js


def test_course_and_selected_are_styled_from_different_state_keys():
    """course_system and selected_system are different states (course-set
    vs merely-clicked) and must not share a CSS class."""
    js = (ASSETS / "js" / "star_map.js").read_text()
    assert "state.course_system" in js
    assert "state.selected_system" in js
    assert "sm-label--course" in js
    assert "sm-label--selected" in js
    css = (ASSETS / "css" / "star_map.css").read_text()
    assert re.search(r"\.sm-label--course\s*\{", css)
    assert re.search(r"\.sm-label--selected\s*\{", css)
