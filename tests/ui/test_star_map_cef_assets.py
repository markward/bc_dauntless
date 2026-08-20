"""The CEF assets must exist, be wired into index.html, and keep the map
viewport transparent so the GL pass beneath shows through."""
import re
from pathlib import Path

from engine.ui.star_map_panel import (FOOTER_H, HEADER_H, MAP_H, MAP_RECT,
                                      MAP_W, MODAL_H, MODAL_OFFSET_X, MODAL_W,
                                      rect_for_view)

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
    index = (ASSETS / "index.html").read_text()
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
        for selectors, body in _rules(path.read_text()):
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
    index = (ASSETS / "index.html").read_text()
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
    the warp-point list and the footer painting transparently over the live
    scene. Each chrome piece that sits inside the (now transparent) modal
    carries its own fill."""
    index = (ASSETS / "index.html").read_text()
    chain = _ancestor_chain(index, "star-map-viewport")
    targets = {"tag": "div", "id": "star-map-targets", "classes": set()}
    footer = {"tag": "div", "id": "", "classes": {"cp-footer"}}
    for el in (targets, footer):
        bg = _effective_background(el, chain)
        assert bg is not None and not _is_transparent(bg), el

    # ...and the popup's list must not re-open the hole inside the card. A
    # bare <ul> carries the UA `margin: 1em 0`, which would inset it top and
    # bottom. (#star-map-warps has no .sc-col class, so it gets no reset from
    # configuration_panel.css.)
    css = (ASSETS / "css" / "star_map.css").read_text()
    block = re.search(r"#star-map-warps\s*\{([^}]*)\}", css)
    assert block, "no #star-map-warps rule"
    assert re.search(r"(?<!-)margin\s*:\s*0\b", block.group(1)), \
        "#star-map-warps must zero the UA <ul> margin"
    assert "list-style" in block.group(1)


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
    assert _calc_offset(body, "left") == MODAL_W / 2 - MODAL_OFFSET_X
    assert _calc_offset(body, "top") == MODAL_H / 2 - HEADER_H

    def _px(prop):
        m = re.search(prop + r"\s*:\s*(-?\d+(?:\.\d+)?)px", body)
        assert m, "missing " + prop + " in #star-map-viewport"
        return float(m.group(1))

    assert (_px("width"), _px("height")) == (float(MAP_W), float(MAP_H))
    assert "position" in body and "fixed" in body

    # The map fills the modal now, so MAP_W is MODAL_W and the CSS left
    # offset doubles as the width pin. The right-hand column that used to
    # reserve space with a hard-coded margin-left duplicating MAP_W is gone —
    # the target list is a centred popup, which cannot drift out of step.
    assert MAP_W == MODAL_W
    css = (ASSETS / "css" / "star_map.css").read_text()
    warps_block = re.search(r"#star-map-warps\s*\{([^}]*)\}", css)
    assert warps_block, "no #star-map-warps rule"
    assert "margin-left" not in warps_block.group(1), (
        "the target list is a centred popup — a margin-left here would "
        "reintroduce the duplicated map width")


def _rule_px(css, selector, prop):
    block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
    assert block, "no " + selector + " rule"
    m = re.search(prop + r"\s*:\s*(-?\d+(?:\.\d+)?)px", block.group(1))
    assert m, "missing " + prop + " in " + selector
    return float(m.group(1))


def test_the_map_rect_fits_the_modal_body():
    """The map must fit BETWEEN the header and the footer.

    The centring test above is a closed loop between MAP_* and the two CSS
    calc() offsets: it pins where the rect starts, and nothing checked that it
    ENDS inside the modal body. It did not — MAP_H was an asserted 520 against
    a body of MODAL_H - HEADER_H - FOOTER_H, so the GL backdrop (opaque, and
    scissored to exactly this rect) painted across the left 640px of the
    footer strip and hid its top border. Invisible only for as long as an
    opaque .cp-modal hid the whole map.

    So assert the budget SUMS, and that every term is the real measured CSS
    rather than a Python-side assertion about it."""
    assert HEADER_H + MAP_H + FOOTER_H == MODAL_H

    cp = (ASSETS / "css" / "configuration_panel.css").read_text()
    sm = (ASSETS / "css" / "star_map.css").read_text()

    # .cp-header is a fixed height in the shared chrome; .cp-footer is given
    # one here (it is otherwise padding-sized, i.e. font-dependent, which is
    # not a number the map rect can be derived from).
    assert _rule_px(cp, ".cp-header", "height") == HEADER_H
    assert _rule_px(sm, "#star-map-panel .cp-footer", "height") == FOOTER_H

    # ...and the modal those three divide up is the one Python assumes.
    assert _rule_px(sm, "#star-map-panel .cp-modal", "width") == MODAL_W
    assert _rule_px(sm, "#star-map-panel .cp-modal", "height") == MODAL_H

    # The target popup is a centred card INSIDE the map rect, not a column
    # beside it, so it is sized in percentages of the viewport and shares no
    # literal with MAP_H. What must hold is that it cannot escape the rect:
    # #star-map-viewport clips it (overflow: hidden) and the card's own
    # max-height is a fraction, never a pixel count that could exceed MAP_H.
    targets = re.search(r"#star-map-targets\s*\{([^}]*)\}", sm)
    assert targets, "no #star-map-targets rule"
    mh = re.search(r"max-height\s*:\s*(\d+)%", targets.group(1))
    assert mh and int(mh.group(1)) <= 100, targets.group(1)
    assert "overflow" in _viewport_css_body() and "hidden" in _viewport_css_body()


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

    assert rect_for_view(1280, 720) == MAP_RECT == (256, 108, 880, 478)
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


def test_nebula_labels_render_subordinate_to_system_labels():
    """The baked nebula names must actually reach the DOM (they were a
    producer with no consumer), and must read as scenery: a distinct class,
    smaller and dimmer than .sm-label, emitted BEFORE the system labels so
    those paint on top."""
    js = (ASSETS / "js" / "star_map.js").read_text()
    assert "disc_labels" in js
    assert "sm-label--disc" in js

    css = (ASSETS / "css" / "star_map.css").read_text()

    def _font_px(selector):
        block = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", css)
        assert block, "no " + selector + " rule"
        m = re.search(r"font-size\s*:\s*(-?\d+(?:\.\d+)?)px", block.group(1))
        assert m, "missing font-size in " + selector
        return float(m.group(1))

    assert _font_px(".sm-label--disc") < _font_px(".sm-label")


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


def test_the_popup_dismiss_control_is_a_close_icon_on_the_right():
    """A cross top-right, not a Back button top-left. The action is unchanged
    (still star-map/back — it dismisses the popup, while the modal's own
    Cancel closes Set Course); only the affordance moved."""
    index = (ASSETS / "index.html").read_text()
    head = re.search(r'<div id="star-map-targets-head">(.*?)</div>',
                     index, re.S)
    assert head, "no #star-map-targets-head block"
    body = head.group(1)
    # Title first, dismiss control second — source order IS visual order
    # under the head's flex row.
    assert body.index("star-map-targets-title") < body.index("star-map-back")
    assert "&times;" in body, "dismiss control is not a cross glyph"
    assert "dauntlessEvent('star-map/back')" in body

    css = (ASSETS / "css" / "star_map.css").read_text()
    head_rule = re.search(r"#star-map-targets-head\s*\{([^}]*)\}", css)
    assert head_rule, "no #star-map-targets-head rule"
    assert "space-between" in head_rule.group(1), (
        "the head must push the close icon to the right edge")


def test_the_warp_button_is_bottom_left_and_disabled_by_default():
    """Warp bottom-LEFT, Cancel bottom-right, and disabled in the markup so
    it can never render live for a frame before Python's first payload."""
    index = (ASSETS / "index.html").read_text()
    # Scope to THIS panel first: index.html holds several cp-* modals and an
    # unscoped search finds the configuration panel's footer instead.
    section = re.search(r'<section id="star-map-panel".*?</section>',
                        index, re.S)
    assert section, "no #star-map-panel section"
    footer = re.search(r'<div class="cp-footer">(.*?)</div>',
                       section.group(0), re.S)
    assert footer, "no star map cp-footer block"
    body = footer.group(1)
    assert body.index("star-map/warp") < body.index("star-map/cancel"), (
        "Warp must precede Cancel in source order — the footer is a flex row")
    assert "disabled" in body
    assert 'id="star-map-warp"' in body

    css = (ASSETS / "css" / "star_map.css").read_text()
    rule = re.search(r"#star-map-panel \.cp-footer\s*\{([^}]*)\}", css)
    assert rule, "no star map footer rule"
    assert "space-between" in rule.group(1), (
        "the shared .cp-footer is flex-end; this modal must split its two "
        "buttons to opposite ends")


def test_the_warp_button_label_comes_from_the_payload():
    """Not a hard-coded string in the JS: the label is the Helm menu's own
    translated text, so the two buttons cannot ship differently."""
    js = (ASSETS / "js" / "star_map.js").read_text()
    assert "warp_label" in js
    assert "warp_enabled" in js


def test_the_modal_is_offset_clear_of_the_helm_menu():
    """The modal sits RIGHT of centre so the Helm menu it is opened from stays
    visible. #tactical-left-column is left:24 width:224 (x 24..248); a centred
    880-wide modal starts at x 200 and covered the map's leftmost 48px.

    Two numbers must agree — the modal's own `left` and the viewport's calc()
    offset — so pin both against the Python constant. An offset applied to one
    and not the other separates the map from its own frame, which is the exact
    failure the centring rule was introduced to end.
    """
    css = (ASSETS / "css" / "star_map.css").read_text()
    modal = re.search(r"#star-map-panel \.cp-modal\s*\{([^}]*)\}", css)
    assert modal, "no #star-map-panel .cp-modal rule"
    m = re.search(r"left\s*:\s*(-?\d+(?:\.\d+)?)px", modal.group(1))
    assert m, "modal has no left offset"
    assert float(m.group(1)) == float(MODAL_OFFSET_X)
    assert "relative" in modal.group(1), (
        "the offset must be relative, so it shifts the modal without "
        "disturbing the flex centring the viewport calc() assumes")

    # ...and the resulting rect actually clears the HUD column.
    assert MAP_RECT[0] >= 248, MAP_RECT
