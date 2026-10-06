"""The CEF assets must exist, be wired into index.html, and keep the map
viewport transparent so the GL pass beneath shows through."""
import re
from pathlib import Path

from engine.ui.modal_geometry import large_modal_size
from engine.ui.star_map_panel import FOOTER_H, HEADER_H, MAP_RECT, rect_for_view

ASSETS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"


def test_script_and_stylesheet_are_registered_in_index():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert "js/star_map.js" in index
    assert "css/star_map.css" in index


def test_panel_section_exists_with_the_required_ids():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    for el in ("star-map-panel", "star-map-viewport",
               "star-map-labels", "star-map-info"):
        assert 'id="' + el + '"' in index, el


def test_map_viewport_is_transparent():
    """The GL pass draws beneath. An opaque background here hides the map
    entirely — the single most likely way to ship a black rectangle."""
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    block = re.search(r"#star-map-viewport\s*\{[^}]*\}", css)
    assert block, "no #star-map-viewport rule"
    assert "transparent" in block.group(0)


# --- the transparent hole must go all the way down -------------------------
#
# `background: transparent` on #star-map-viewport reveals only what is behind
# it IN PAINT ORDER. The viewport is a positioned descendant of .cp-modal, so
# it paints ABOVE every ancestor background; an opaque ancestor therefore hides
# the GL map just as completely as an opaque viewport would, and the CEF
# composite is premultiplied (GL_ONE / GL_ONE_MINUS_SRC_ALPHA), so alpha 1
# discards the framebuffer outright. The failure mode is vicious: .cp-modal's
# rgb(20,22,28) and the pass's rgb(5,8,15) backdrop are both near-black, so a
# live run shows a dark, correctly-positioned, empty rectangle — indis-
# tinguishable from "the pass ran and drew nothing".
#
# So assert the whole ancestor CHAIN, read out of the real markup, resolves to
# a transparent background across every stylesheet index.html loads.

_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input",
              "link", "meta", "param", "source", "track", "wbr"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)([^>]*?)(/?)>")


def _attr(attrs, name):
    m = re.search(name + r'\s*=\s*"([^"]*)"', attrs)
    return m.group(1) if m else ""


def _ancestor_chain(html, target_id):
    """Elements enclosing #target_id, outermost first, from the real markup.

    Read from index.html rather than hardcoded so that re-parenting the
    viewport (e.g. dropping it into a new opaque wrapper) is covered too.
    """
    stack = []
    for m in _TAG_RE.finditer(html):
        closing, tag, attrs, self_close = m.groups()
        if closing:
            while stack and stack.pop()["tag"] != tag:
                pass
            continue
        el = {"tag": tag, "id": _attr(attrs, "id"),
              "classes": set(_attr(attrs, "class").split())}
        if el["id"] == target_id:
            return list(stack)
        if not self_close and tag not in _VOID_TAGS:
            stack.append(el)
    raise AssertionError("no element with id=" + target_id)


def _stylesheets_in_load_order():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    return [ASSETS / href
            for href in re.findall(r'<link rel="stylesheet" href="([^"]+)"',
                                   index)]


def _rules(css):
    """(selector_list, declaration_body) pairs, in source order.

    Comments are stripped first so a commented-out `background:` in the
    documentation blocks above each rule cannot be read as a declaration.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _matches(selector, element, chain):
    """Does `selector` match `element`, given its ancestor `chain`?

    Descendant combinators only (all the star-map chrome uses), plus #id,
    .class and tag names — the four constructs these stylesheets contain.
    """
    parts = selector.split()
    if any(c in selector for c in ">+~"):
        return False

    def compound_matches(part, el):
        for tok in re.findall(r"[#.]?[\w-]+", part):
            if tok.startswith("#"):
                if el["id"] != tok[1:]:
                    return False
            elif tok.startswith("."):
                if tok[1:] not in el["classes"]:
                    return False
            elif el["tag"] != tok:
                return False
        return True

    if not compound_matches(parts[-1], element):
        return False
    i = 0
    for part in parts[:-1]:
        while i < len(chain) and not compound_matches(part, chain[i]):
            i += 1
        if i == len(chain):
            return False
        i += 1
    return True


def _specificity(selector):
    return (selector.count("#"), selector.count("."),
            len(re.findall(r"(?:^|\s)[a-zA-Z]", selector)))


def _effective_background(element, chain):
    """Winning `background` / `background-color` value, or None if unset.

    A minimal cascade: highest (specificity, source order) wins. The shorthand
    resets background-color, so tracking one winner across both properties is
    correct for the declarations these sheets actually contain.
    """
    best, best_key = None, None
    for order, path in enumerate(_stylesheets_in_load_order()):
        for selectors, body in _rules(path.read_text(encoding="utf-8")):
            decls = re.findall(r"background(?:-color)?\s*:\s*([^;]+)", body)
            if not decls:
                continue
            for selector in selectors.split(","):
                selector = selector.strip()
                if not selector or not _matches(selector, element, chain):
                    continue
                key = (_specificity(selector), order)
                if best_key is None or key >= best_key:
                    best, best_key = decls[-1].strip(), key
    return best


def _is_transparent(value):
    if value is None:
        return True
    value = value.strip().lower()
    if value in ("transparent", "none", "initial", "unset", "revert"):
        return True
    m = re.match(r"rgba\(\s*[\d.]+\s*,\s*[\d.]+\s*,\s*[\d.]+\s*,\s*([\d.]+)\s*\)",
                 value)
    return bool(m) and float(m.group(1)) == 0.0


def test_no_ancestor_of_the_map_viewport_paints_an_opaque_background():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    chain = _ancestor_chain(index, "star-map-viewport")
    assert any(el["id"] == "star-map-panel" for el in chain), chain
    assert any("cp-modal" in el["classes"] for el in chain), chain

    for i, el in enumerate(chain):
        bg = _effective_background(el, chain[:i])
        assert _is_transparent(bg), (
            "opaque ancestor of #star-map-viewport: "
            + (el["id"] or ".".join(sorted(el["classes"])) or el["tag"])
            + " -> background: " + str(bg))


def test_the_opaque_star_map_chrome_still_has_a_fill():
    """The counterweight to the test above: punching the hole must not leave
    the footer painting transparently over the live scene. Each chrome piece
    inside the (now transparent) modal carries its own fill. (The info panel's
    fill is checked with the two-panel layout, which is where it lives.)"""
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    chain = _ancestor_chain(index, "star-map-viewport")
    footer = {"tag": "div", "id": "", "classes": {"cp-footer"}}
    bg = _effective_background(footer, chain)
    assert bg is not None and not _is_transparent(bg), footer


def _viewport_css_body():
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    block = re.search(r"#star-map-viewport\s*\{([^}]*)\}", css)
    assert block, "no #star-map-viewport rule"
    return block.group(1)


def test_the_viewport_is_the_modal_body_by_construction():
    """Python projects labels and hit-tests clicks against panel.rect; the GL
    pass scissors to it. If the CSS rect disagrees, every label is displaced
    and every click mis-picks.

    The viewport used to be position:fixed at a calc() centring offset that
    duplicated the modal's pixel size — which is how the two once drifted (a
    fixed CSS rect and a fixed MAP_RECT agreed only at 1280x720). Now the
    modal is viewport-sized, so the viewport is simply `inset: 0` inside
    .sm-body, the flex child between the header and the footer: the CSS
    states no geometry of its own to drift. The Python half of the same rect
    is pinned in test_python_rect_is_the_large_modal_body."""
    body = _viewport_css_body()
    assert re.search(r"position\s*:\s*absolute", body), body
    # The right 70% of the body; the split is pinned against Python in
    # test_the_two_panel_split_matches_python.
    assert re.search(r"inset\s*:", body), body
    for prop in ("left", "top", "width", "height"):
        assert not re.search(r"(?<![-\w])" + prop + r"\s*:", body), (
            "#star-map-viewport must not state its own " + prop
            + " — the rect comes from .sm-body")

    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    sm_body = re.search(r"\.sm-body\s*\{([^}]*)\}", css)
    assert sm_body and re.search(r"position\s*:\s*relative", sm_body.group(1)), (
        ".sm-body must be the viewport's positioning context")
    # ...and the viewport is its direct child, so nothing in between can
    # become the containing block instead.
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    chain = _ancestor_chain(index, "star-map-viewport")
    assert "sm-body" in chain[-1]["classes"], chain[-1]


def _rule_px(css, selector, prop):
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, "no " + selector + " rule"
    m = re.search(prop + r"\s*:\s*(-?\d+(?:\.\d+)?)px", block.group(1))
    assert m, "missing " + prop + " in " + selector
    return float(m.group(1))


def test_the_map_rect_fits_the_modal_body():
    """The map must fit BETWEEN the header and the footer.

    Once MAP_H was an asserted 520 against a 478px body, so the GL backdrop
    (opaque, and scissored to exactly this rect) painted across the footer
    strip and hid its top border. So the rect's height is the modal's height
    less the two strips, and each strip is the real measured CSS rather than
    a Python-side assertion about it."""
    cp = (ASSETS / "css" / "configuration_panel.css").read_text(encoding="utf-8")
    sm = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")

    # .cp-header is a fixed height in the shared chrome; .cp-footer is given
    # one here (it is otherwise padding-sized, i.e. font-dependent, which is
    # not a number the map rect can be derived from).
    assert _rule_px(cp, ".cp-header", "height") == HEADER_H
    assert _rule_px(sm, "#star-map-panel .cp-footer", "height") == FOOTER_H

    for view in ((1280, 720), (1512, 983), (1000, 600)):
        _w, h = large_modal_size(*view)
        assert rect_for_view(*view)[3] == round(h - HEADER_H - FOOTER_H), view
    # Labels are clipped to the map rect.
    assert "overflow" in _viewport_css_body() and "hidden" in _viewport_css_body()


def test_python_rect_is_the_large_modal_body():
    """The real numbers, worked by hand from the CSS: 80vw x 80vh floored at
    900x560, flex-centred (the 1px border cancels), less HEADER_H on top and
    FOOTER_H below, and above a 1024px view less the 30% info panel. 1280x720 is the boot view (MAP_RECT); 1512x983 lays out
    fractionally (Chromium may land <=1px from round(), invisible, and the
    labels live inside the CSS rect so they cannot separate from it);
    1000x600 is below the floor."""
    # Wide (> 1024): the map is the body's right 70%, beside the info panel.
    assert rect_for_view(1280, 720) == MAP_RECT == (435, 100, 717, 494)
    assert rect_for_view(1512, 983) == (514, 126, 847, 704)
    # A floored 900-wide modal: still split.
    assert rect_for_view(1000, 600) == (320, 48, 630, 478)


def test_render_fn_matches_the_python_payload_name():
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "function setStarMapPanel(" in js


def test_events_use_the_panel_routing_prefix():
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    # star-map/select-system is deliberately excluded: nothing in the JS
    # fires it (map selection goes through star-map/pick:<x>,<y>); the panel
    # still handles select-system: server-side (T4's tests cover it).
    # star-map/cancel is deliberately excluded here too: it fires from the
    # Cancel button's inline onclick in index.html, not from this file (it
    # appears in star_map.js only in a comment) — see
    # test_cancel_event_is_wired_from_the_cancel_button below, which asserts
    # against the real firing site.
    for evt in ("star-map/set-course", "star-map/pick-course",
                "star-map/pick",
                "star-map/orbit", "star-map/zoom"):
        assert evt in js, evt


def test_cancel_event_is_wired_from_the_cancel_button():
    """star-map/cancel fires from the Cancel button's inline onclick in
    index.html (matching the sibling #setting-course-panel convention), not
    from star_map.js. Assert against that real firing site so removing the
    onclick and leaving star_map.js's header-comment mention would fail
    this test, rather than passing vacuously."""
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    section = re.search(r'<section id="star-map-panel".*?</section>',
                         index, re.DOTALL)
    assert section, "no #star-map-panel section"
    assert "onclick=\"dauntlessEvent('star-map/cancel')\"" in section.group(0)


def test_nebula_labels_render_subordinate_to_system_labels():
    """The baked nebula names must actually reach the DOM (they were a
    producer with no consumer), and must read as scenery: a distinct class,
    smaller and dimmer than .sm-label, emitted BEFORE the system labels so
    those paint on top."""
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "disc_labels" in js
    assert "sm-label--disc" in js

    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")

    def _font_px(selector):
        block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert block, "no " + selector + " rule"
        m = re.search(r"font-size\s*:\s*(-?\d+(?:\.\d+)?)px", block.group(1))
        assert m, "missing font-size in " + selector
        return float(m.group(1))

    assert _font_px(".sm-label--disc") < _font_px(".sm-label")


def test_labels_are_escaped():
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "escapeHtmlSM" in js


def test_course_and_selected_are_stamped_from_different_state_keys():
    """course_system and selected_system are different states (course-set vs
    merely-clicked) and must not collapse into one class.

    The assertion is on the JS, not on CSS rules: the state classes carry no
    declarations now that every system name is white, so requiring a rule per
    class would only force empty blocks into the stylesheet. What must not
    regress is that the two states stay separately identifiable."""
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "state.course_system" in js
    assert "state.selected_system" in js
    assert "sm-label--course" in js
    assert "sm-label--selected" in js
    assert "sm-label--course" != "sm-label--selected"



def test_the_warp_button_is_bottom_right_and_disabled_by_default():
    """Cancel bottom-LEFT, Warp bottom-right, and Warp disabled in the markup
    so it can never render live for a frame before Python's first payload.

    The footer is space-between, so DOM order IS the placement. Warp moved to
    the right to put the primary action where the eye ends up; the assertion
    is on order rather than on CSS because that is what actually decides it.
    """
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    # Scope to THIS panel first: index.html holds several cp-* modals and an
    # unscoped search finds the configuration panel's footer instead.
    section = re.search(r'<section id="star-map-panel".*?</section>',
                        index, re.S)
    assert section, "no #star-map-panel section"
    # To the END of the section, not to the first </div>: the right-hand
    # group is itself a div, so a non-greedy stop lands mid-footer.
    start = section.group(0).find('<div class="cp-footer">')
    assert start != -1, "no star map cp-footer block"
    body = section.group(0)[start:]
    assert body.index("star-map/cancel") < body.index("star-map/warp"), (
        "Cancel must precede Warp in source order — the footer is a flex row")
    assert "disabled" in body
    assert 'id="star-map-warp"' in body

    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    rule = re.search(r"#star-map-panel \.cp-footer\s*\{([^}]*)\}", css)
    assert rule, "no star map footer rule"
    assert "space-between" in rule.group(1), (
        "the shared .cp-footer is flex-end; this modal must split its two "
        "buttons to opposite ends")


def test_the_warp_button_label_comes_from_the_payload():
    """Not a hard-coded string in the JS: the label is the Helm menu's own
    translated text, so the two buttons cannot ship differently."""
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "warp_label" in js
    assert "warp_enabled" in js


def test_the_window_is_the_shared_large_modal():
    """Set Course is a standard large modal: same root layer, same size as
    Quick Battle Setup, centred. It used to be a fixed 880x560 shifted 56px
    right to keep the Helm menu visible; the large modal covers that column
    and hides the HUD beneath it instead (js/modal_layer.js), so any local
    size or offset here would only re-separate the map from its frame."""
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    chain = _ancestor_chain(index, "star-map-viewport")
    root = next(el for el in chain if el["id"] == "star-map-panel")
    modal = next(el for el in chain if "cp-modal" in el["classes"])
    assert "cp-modal-layer" in root["classes"]
    assert "cp-modal--large" in modal["classes"]

    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    for block in re.findall(r"#star-map-panel(?:\s+\.cp-modal)?\s*\{([^}]*)\}",
                            css):
        for prop in ("width", "height", "left", "z-index", "position"):
            assert not re.search(r"(?<![-\w])" + prop + r"\s*:", block), (
                "star_map.css overrides the shared large modal's " + prop)


def _rule_color(css, selector):
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, "no " + selector + " rule"
    m = re.search(r"color\s*:\s*(#[0-9a-fA-F]{3,8})", block.group(1))
    assert m, "missing color in " + selector
    return m.group(1).lower()



def test_the_here_arrow_uses_the_colour_python_declares():
    from engine.ui.star_map import HERE_MARKER_COLOR
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    block = re.search(r"\.sm-here-arrow\s*\{([^}]*)\}", css)
    assert block, "no .sm-here-arrow rule"
    m = re.search(r"border-top\s*:[^;]*?(#[0-9a-fA-F]{3,8})", block.group(1))
    assert m, "the arrow's fill is its border-top colour"
    assert m.group(1).lower() == HERE_MARKER_COLOR



def test_unoffered_system_labels_are_dimmed_to_match_the_star():
    """star_map.py dims the GL dot by INERT_DIM; the CSS must dim the label by
    the same fraction, or the two halves of one marker disagree."""
    from engine.ui.star_map import INERT_DIM
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    block = re.search(r"\.sm-label--inert\s*\{([^}]*)\}", css)
    assert block, "no .sm-label--inert rule"
    m = re.search(r"opacity\s*:\s*([0-9.]+)", block.group(1))
    assert m, "no opacity on .sm-label--inert"
    assert float(m.group(1)) == INERT_DIM

    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "sm-label--inert" in js


def test_the_show_all_toggle_is_wired_and_lives_beside_warp():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert "star-map/toggle-labels" in index
    assert 'id="star-map-show-all"' in index


def test_unoffered_labels_are_withheld_unless_show_all_is_on():
    """Hidden, not merely dimmed — the point is a map that names only where
    the mission will take you. .sm-label--inert survives for the show-all
    case, where the extra names must not compete with the shortlist."""
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "show_all_labels" in js
    assert "sm-label--inert" in js


def test_system_labels_are_white_in_every_state():
    """One colour for every system name. State is carried by the GL reticle
    and the arrow, not by tinting the text: with unlisted systems unnamed by
    default, a second colour axis on the few remaining names read as noise."""
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    assert _rule_color(css, ".sm-label") == "#ffffff"
    for state in ("--here", "--course", "--mission", "--selected"):
        block = re.search(r"\.sm-label" + state + r"\s*\{([^}]*)\}", css)
        if block:
            assert "color" not in block.group(1), (
                ".sm-label" + state + " must not re-tint the name")


def test_system_labels_paint_above_nebula_names():
    """Nebulae are scenery. DOM order already put system names last, but that
    is incidental to how the two lists are concatenated; the stacking is
    stated so a reordering of that concatenation cannot bury a system name."""
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")

    def _z(selector):
        block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert block, "no " + selector + " rule"
        m = re.search(r"z-index\s*:\s*(-?\d+)", block.group(1))
        assert m, "no z-index in " + selector
        return int(m.group(1))

    assert _z(".sm-label") > _z(".sm-label--disc")


def test_the_here_arrow_bobs_by_three_pixels():
    """A slow 3px hover. Pinned because the whole point of the marker is that
    it moves — a keyframe block that stops translating would still render a
    perfectly plausible static arrow."""
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    arrow = re.search(r"\.sm-here-arrow\s*\{([^}]*)\}", css)
    assert arrow, "no .sm-here-arrow rule"
    assert "animation" in arrow.group(1)

    frames = re.search(r"@keyframes\s+sm-here-bob\s*\{(.*?)\n\}", css, re.S)
    assert frames, "no sm-here-bob keyframes"
    offsets = {abs(float(v)) for v in
               re.findall(r"translateY\((-?[\d.]+)px\)", frames.group(1))}
    assert 3.0 in offsets, "the hover must travel 3px"


def test_the_here_arrow_is_rendered_from_the_payload():
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "here_marker" in js
    assert "sm-here-arrow" in js


def _z_index(css, selector):
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, "no " + selector + " rule"
    m = re.search(r"z-index\s*:\s*(-?\d+)", block.group(1))
    return int(m.group(1)) if m else None



def test_the_window_is_titled_after_the_row_that_opens_it():
    """The map opens from Helm -> Set Course -> Stellar Cartography, so the
    window carries that row's name rather than the menu's."""
    from engine.ui.crew_menu_panel import CARTOGRAPHY_LABEL

    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    section = index[index.index('id="star-map-panel"'):]
    m = re.search(r'<div class="cp-header">([^<]*)</div>', section)
    assert m and m.group(1) == CARTOGRAPHY_LABEL, m and m.group(1)



def test_the_two_panel_split_matches_python():
    """CSS decides what is drawn; Python decides where the GL map, labels and
    picks go. Both must split by the same fraction, at every size."""
    from engine.ui.star_map_panel import INFO_FRACTION

    css = re.sub(r"/\*.*?\*/", "", (ASSETS / "css" / "star_map.css")
                 .read_text(encoding="utf-8"), flags=re.S)
    assert "@media" not in css, "the split no longer depends on the width"
    pct = "%d%%" % round(INFO_FRACTION * 100)
    info = re.search(r"#star-map-info\s*\{([^}]*)\}", css)
    assert info and re.search(r"(?<![-\w])width\s*:\s*" + pct, info.group(1))
    assert re.search(r"(?<![-\w])left\s*:\s*0\b", info.group(1))
    assert re.search(r"inset\s*:\s*0 0 0 " + pct, _viewport_css_body())
    # Opaque chrome beside the hole, like the footer.
    bg = re.search(r"background\s*:\s*([^;]+);", info.group(1))
    assert bg and not _is_transparent(bg.group(1).strip())


def test_the_info_panel_renders_text_never_markup():
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    start = js.index("const info = state.info")
    block = js[start:js.index("root.style.display = 'flex'", start)]
    assert "textContent" in block and "innerHTML" not in block



def test_each_destination_row_has_a_set_course_crosshair():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert 'id="star-map-info-regions"' in index
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    fn = js[js.index("function renderStarMapRegions"):js.index("// ── Search (bottom-left of the map)")]
    assert "sm-region__course" in fn and "star-map/set-course:" in fn
    # Labels are mission-supplied: text, never markup. The only innerHTML is
    # the fixed crosshair SVG.
    assert "label.textContent" in fn
    # The only innerHTML is fixed SVG: the crosshair and the objective mark.
    assert fn.count("innerHTML") == 2
    assert "btn.innerHTML = SM_CROSSHAIR_SVG" in fn
    assert "mark.innerHTML = SM_OBJECTIVE_SVG" in fn
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    for sel in (".sm-region__course", ".sm-region--course .sm-region__course",
                ".sm-region--mission"):
        assert re.search(re.escape(sel) + r"\s*\{", css), sel



def test_the_objective_marker_sits_left_of_the_crosshair():
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    fn = js[js.index("function renderStarMapRegions"):js.index("// ── Search (bottom-left of the map)")]
    assert "w.objective" in fn
    # DOM order is screen order in the flex row: label, marker, crosshair.
    assert fn.index("sm-region__objective") < fn.index("sm-region__course")
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    assert re.search(r"\.sm-region__objective\s*\{[^}]*#99ccff", css)


def test_search_box_sits_beside_the_map_not_inside_it():
    """Inside #star-map-viewport its clicks would reach the drag/pick
    handlers and orbit or pick a star. It is a sibling, in .sm-body."""
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    chain = _ancestor_chain(index, "star-map-search-input")
    ids = [el["id"] for el in chain]
    assert "star-map-viewport" not in ids
    assert "star-map-search" in ids
    assert any("sm-body" in el["classes"] for el in chain)
    # Bottom-left of the MAP: just past the info panel's 30%, not the body's
    # own left edge (which is under the info panel).
    from engine.ui.star_map_panel import INFO_FRACTION
    css = (ASSETS / "css" / "star_map.css").read_text(encoding="utf-8")
    block = re.search(r"#star-map-search\s*\{([^}]*)\}", css)
    pct = "%d%%" % round(INFO_FRACTION * 100)
    assert block and re.search(r"left\s*:\s*calc\(" + pct, block.group(1)) \
        and re.search(r"bottom\s*:", block.group(1))


def test_search_field_takes_the_keyboard_and_sends_encoded_queries():
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    # The text-capture contract: the panel root carries its registry name.
    assert re.search(r'<section id="star-map-panel"[^>]*data-panel="star-map"', index)
    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "'star-map/search:' + encodeURIComponent(input.value)" in js
    assert "'star-map/select-system:' + systemId" in js
    fn = js[js.index("function renderStarMapSearch"):js.index("document.addEventListener('DOMContentLoaded', function () {\n    const toggle")]
    assert "textContent" in fn and "innerHTML" not in fn



def test_the_search_box_paints_over_the_system_names():
    """The label layer's z-index must stay inside the map: the viewport is a
    stacking context, and the search box comes after it in .sm-body. Live
    bug: BIRANU drew through the search field."""
    body = _viewport_css_body()
    assert re.search(r"z-index\s*:\s*0\b", body), body
    index = (ASSETS / "index.html").read_text(encoding="utf-8")
    assert index.index('id="star-map-search"') > index.index('id="star-map-viewport"')
    css = re.sub(r"/\*.*?\*/", "", (ASSETS / "css" / "star_map.css")
                 .read_text(encoding="utf-8"), flags=re.S)
    search = re.search(r"#star-map-search\s*\{([^}]*)\}", css)
    assert search and "z-index" not in search.group(1)



_DOUBLE_CLICK_HARNESS = r"""
const fs = require("fs");
const vm = require("vm");
const ctx = {document: {addEventListener: function () {}},
             dauntlessEvent: function () {}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], "utf8"), ctx);
const f = ctx.starMapIsDoubleClick;
const a = {t: 1000, x: 100, y: 100};
console.log(JSON.stringify({
  first: f(null, a),
  quick: f(a, {t: 1300, x: 103, y: 98}),
  slow: f(a, {t: 1500, x: 100, y: 100}),
  far: f(a, {t: 1100, x: 120, y: 100}),
}));
"""


def test_double_click_is_detected_without_the_dom_dblclick_event():
    """The host sends every click with clickCount 1, so `dblclick` never
    fires in-game (live: double-click silently did nothing). The map pairs
    its own clicks instead."""
    import json, shutil, subprocess, tempfile
    from pathlib import Path
    import pytest

    js = (ASSETS / "js" / "star_map.js").read_text(encoding="utf-8")
    assert "'dblclick'" not in js
    assert "starMapIsDoubleClick(lastClick, click)" in js
    assert "'star-map/pick-course:'" in js

    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(_DOUBLE_CLICK_HARNESS)
        harness = f.name
    try:
        r = subprocess.run([node, harness, str(ASSETS / "js" / "star_map.js")],
                           capture_output=True, text=True, timeout=10)
    finally:
        Path(harness).unlink()
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == {"first": False, "quick": True,
                                    "slow": False, "far": False}
