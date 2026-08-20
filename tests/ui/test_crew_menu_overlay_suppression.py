"""Character popups and SDK status windows hide while a crew menu is open.

Both are absolutely-positioned overlays that can land anywhere on screen —
the SDK "stylized" windows (officer status cards such as "ENSIGN KISKA
LOMAR, HELM / Awaiting Orders") are positioned from SDK coordinates — so
they can cover a crew menu, or a modal opened from one.

The star map is what made this matter. Its map region is deliberately
transparent so the native GL pass beneath shows through, and z-index cannot
make a transparent element occlude an opaque one: ANY opaque CEF element
over the map rect paints on top of the map regardless of stacking order.
Suppressing these overlays while a crew menu is open is the general fix.

Deliberately CEF-only. Nothing here touches Python, so
`crew_menu_panel.has_open_menu()` stays true while a menu is open — which is
what suppresses bridge free-look when the star map is dragged.
"""
import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[2] / "native" / "assets" / "ui-cef"

BODY_CLASS = "crew-menu-open"

# Overlays that must be suppressed. Both are absolutely positioned and can
# land over a crew menu or a modal opened from one.
SUPPRESSED = ("#sdk-stylized-stack", "#character-tooltip-host")


def _js():
    return (ASSETS / "js" / "crew_menus.js").read_text()


def _css():
    return (ASSETS / "css" / "crew_menus.css").read_text()


def test_renderer_toggles_the_body_class_from_the_open_menu_state():
    """The class must be driven by whether a menu actually rendered, not set
    unconditionally — otherwise the overlays never come back."""
    js = _js()
    assert BODY_CLASS in js, "renderer never names the " + BODY_CLASS + " class"
    toggle = re.search(
        r"classList\.toggle\(\s*['\"]" + BODY_CLASS + r"['\"]\s*,\s*([^)]+)\)", js)
    assert toggle, "no classList.toggle keyed on " + BODY_CLASS
    # Second argument must be a computed condition, not a bare literal.
    condition = toggle.group(1).strip()
    assert condition not in ("true", "false"), (
        "class is toggled with a literal " + condition
        + " — it must follow the open-menu state")


def test_css_hides_every_suppressed_overlay_under_the_class():
    css = _css()
    for selector in SUPPRESSED:
        rule = re.search(
            r"[^}]*\." + BODY_CLASS + r"[^{}]*" + re.escape(selector)
            + r"[^{]*\{([^}]*)\}", css)
        assert rule, selector + " is not hidden under ." + BODY_CLASS
        body = rule.group(1)
        assert ("visibility" in body and "hidden" in body) or "display: none" in body, (
            selector + " rule under ." + BODY_CLASS + " does not hide it: " + body)


def test_suppression_does_not_use_display_none_on_sdk_windows():
    """SDK stylized windows are positioned from SDK coordinates. `visibility`
    keeps their boxes intact; `display: none` would drop them from layout for
    no benefit, since both hosts are absolutely positioned overlays."""
    css = _css()
    rule = re.search(
        r"[^}]*\." + BODY_CLASS + r"[^{}]*#sdk-stylized-stack[^{]*\{([^}]*)\}", css)
    assert rule, "no suppression rule for #sdk-stylized-stack"
    assert "display: none" not in rule.group(1)
