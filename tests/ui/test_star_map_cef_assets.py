"""The CEF assets must exist, be wired into index.html, and keep the map
viewport transparent so the GL pass beneath shows through."""
import re
from pathlib import Path

from engine.ui.star_map_panel import MAP_RECT

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


def test_viewport_css_geometry_matches_map_rect():
    """Python projects labels and hit-tests clicks against MAP_RECT; the GL
    pass scissors to it. If the CSS rect disagrees, every label is displaced
    and every click mis-picks. #star-map-viewport is positioned `fixed` at
    explicit left/top/width/height so its screen rect does not depend on
    .cp-modal padding/border — parse those four numbers back out of the CSS
    and require they equal MAP_RECT exactly."""
    css = (ASSETS / "css" / "star_map.css").read_text()
    block = re.search(r"#star-map-viewport\s*\{([^}]*)\}", css)
    assert block, "no #star-map-viewport rule"
    body = block.group(1)

    def _px(prop):
        m = re.search(prop + r"\s*:\s*(-?\d+(?:\.\d+)?)px", body)
        assert m, "missing " + prop + " in #star-map-viewport"
        return float(m.group(1))

    css_rect = (_px("left"), _px("top"), _px("width"), _px("height"))
    assert css_rect == tuple(float(v) for v in MAP_RECT)
    assert "position" in body and "fixed" in body

    # #star-map-warps reserves the viewport's width with its own margin-left
    # (the viewport is position:fixed and so out of .sm-body's flow) — that
    # literal is a fourth, untested copy of MAP_RECT's width unless pinned
    # here too, alongside the viewport's own left/top/width/height.
    warps_block = re.search(r"#star-map-warps\s*\{([^}]*)\}", css)
    assert warps_block, "no #star-map-warps rule"
    m = re.search(r"margin-left\s*:\s*(-?\d+(?:\.\d+)?)px", warps_block.group(1))
    assert m, "missing margin-left in #star-map-warps"
    assert float(m.group(1)) == float(MAP_RECT[2])


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
