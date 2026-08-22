"""Every pause-menu modal is a full-viewport overlay root that stacks above
the HUD and is hidden until its panel says otherwise.

These four properties are what MAKE a modal a modal, and all of them live in
one rule per root:

  position: fixed + inset: 0   the root is the full viewport, so the flex
                               centring below has something to centre IN. Lose
                               it and the root becomes a static in-flow box: it
                               collapses onto the modal's own size and lands at
                               the top-left of the page.
  align/justify: center        the modal sits in the middle of the screen.
  z-index                      the HUD paints at z-index 40 (info_box.css) and
                               the SDK mirror at 40-50 (sdk_mirror.css). A root
                               with NO z-index is not "at 0" against those — it
                               is unpositioned, creates no stacking context,
                               and every positioned HUD element with a z-index
                               paints over it.
  display: none                the panels are driven by Python; without this
                               they render on the very first frame, before the
                               first payload arrives to hide them.

This file exists because all four were lost at once, silently. 011a4273 deleted
`#setting-course-panel` from the middle of a shared selector list:

    #configuration-panel,
    #developer-options-panel,
    #setting-course-panel {        <-- deleted, opening brace and all
        position: fixed; inset: 0; z-index: 50; ...
    }
    .cp-modal { width: 640px; ... }

which left the two surviving selectors dangling onto the NEXT rule, so
#configuration-panel and #developer-options-panel silently became .cp-modal:
640x420 static boxes in the top-left corner, no backdrop, no stacking context,
and `display: flex` where `display: none` had been. Still valid CSS — nothing
warns, nothing fails to parse, and the panels still open. They just open wrong.

So the tests below assert the DECLARATIONS each root actually resolves to,
never merely that its id appears somewhere in the stylesheet: under the bug the
id was still present, in a selector list, in the right file.
"""
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"

# The centred, full-viewport modal roots reachable from the pause menu.
# Deliberately excluded: #engpower-root and #ai-inspector-panel (docked HUD
# panels, not centred modals) and #spv-root (its own chrome, and it owns the
# whole frame rather than overlaying the HUD).
OVERLAY_ROOTS = (
    "configuration-panel",
    "developer-options-panel",
    "mission-picker",
    "quick-battle-setup",
    "star-map-panel",
)


def _stylesheets_in_load_order():
    index = (ASSETS / "index.html").read_text()
    return [ASSETS / href
            for href in re.findall(r'<link rel="stylesheet" href="([^"]+)"',
                                   index)]


def _rules(css):
    """(selector_list, declaration_body) pairs, in source order.

    Comments are stripped first, so the prose above each rule — which quotes
    real declarations, including this file's own failure mode — cannot be read
    as CSS.
    """
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)
    return re.findall(r"([^{}]+)\{([^{}]*)\}", css)


def _selectors(selector_list):
    return [s.strip() for s in selector_list.split(",") if s.strip()]


def _declarations_for_root(root_id):
    """Every declaration that reaches `#root_id` itself, as {prop: value}.

    Only rules selecting the bare root are considered — `#root .cp-modal` and
    friends style descendants and must not stand in for the root's own
    geometry. Later declarations win, which is the cascade for equal
    specificity and is all these sheets rely on.
    """
    out = {}
    for path in _stylesheets_in_load_order():
        for selector_list, body in _rules(path.read_text()):
            if ("#" + root_id) not in _selectors(selector_list):
                continue
            for prop, value in re.findall(r"([\w-]+)\s*:\s*([^;]+)", body):
                out[prop.strip()] = value.strip()
    return out


def test_every_overlay_root_is_a_full_viewport_stacking_layer():
    for root in OVERLAY_ROOTS:
        decls = _declarations_for_root(root)
        assert decls, "no rule selects #" + root

        assert decls.get("position") == "fixed", (
            root + ": position is " + str(decls.get("position"))
            + " — a modal root that is not `fixed` collapses to its content "
              "and flows into the top-left corner")
        assert decls.get("inset") == "0", (
            root + ": inset is " + str(decls.get("inset")))

        # Centring: the modal is a flex child of the root.
        assert decls.get("align-items") == "center", root
        assert decls.get("justify-content") == "center", root

        # Stacking: must beat the HUD (info_box z-index 40, sdk_mirror 40-50).
        z = decls.get("z-index")
        assert z is not None and int(z) >= 50, (
            root + ": z-index is " + str(z) + " — the HUD paints at 40-50, so "
            "anything lower (or absent) lets the HUD cover the modal")

        # Hidden until Python's first payload says otherwise.
        assert decls.get("display") == "none", (
            root + ": display is " + str(decls.get("display"))
            + " — the root must default hidden or it renders on frame 1")


def test_no_overlay_root_shares_a_selector_list_with_the_modal_box():
    """The exact shape of the 011a4273 regression.

    An overlay root and `.cp-modal` want opposite geometry — full-viewport
    fixed backdrop vs a fixed-size centred box — so they can never legitimately
    share declarations. Landing in one selector list means a selector list ran
    on into the following rule, which is how the roots lost their geometry
    while remaining, to every grep, still styled.
    """
    for path in _stylesheets_in_load_order():
        for selector_list, _ in _rules(path.read_text()):
            selectors = _selectors(selector_list)
            roots = [s for s in selectors
                     if s.lstrip("#") in OVERLAY_ROOTS and s.startswith("#")]
            if not roots:
                continue
            assert ".cp-modal" not in selectors, (
                path.name + ": " + ", ".join(roots) + " share a selector list "
                "with .cp-modal — a dangling selector list has run on into the "
                "next rule")


def test_the_key_capture_overlay_is_contained_by_its_panel():
    """`.cp-capture-modal` is `position: absolute; inset: 0`, so it covers its
    nearest POSITIONED ancestor. That ancestor is #configuration-panel. If the
    panel root stops being positioned, the capture overlay escapes to the
    initial containing block and dims the entire screen instead of the panel —
    a second, quieter casualty of the same deleted rule."""
    css = (ASSETS / "css" / "configuration_panel.css").read_text()
    block = re.search(r"\.cp-capture-modal\s*\{([^}]*)\}", css)
    assert block, "no .cp-capture-modal rule"
    assert "absolute" in block.group(1)

    root = _declarations_for_root("configuration-panel")
    assert root.get("position") in ("fixed", "relative", "absolute"), (
        "#configuration-panel must be positioned to contain .cp-capture-modal")
