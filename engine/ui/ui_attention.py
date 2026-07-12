"""Identifier-centric UI attention.

BC's MissionLib.ShowPointerArrow is POSITION-based: it reads the target widget's
screen rect and drops an LCARS arrow icon at computed coordinates. Chrome draws our
UI, so those coordinates can never be made reliably correct (headless SDK font
metrics are 0; BC's real metrics are 1024x768 bitmap values that don't match Chrome's
layout). The information the SDK is conveying is not a coordinate — it is "draw the
player's attention to THIS widget".

So we override the two SDK functions (the sdk/ file is untouched — this is a RENDERER
substitution, not a logic fork; the SDK still decides what and when) and record the
target's widget id. CrewMenuPanel's existing snapshot carries the flag; CEF styles the
element Chrome already drew. Cannot mis-place, needs no geometry.

Persistent, not time-boxed: a widget stays highlighted from ShowPointerArrow until
HidePointerArrows (matches BC — the arrow persists while the player still hasn't
acted). eDirection/fSpacing (BC arrow-art placement details) are accepted for
signature compatibility and discarded; kColor is kept.

Spec: docs/superpowers/specs/2026-07-12-identifier-centric-ui-attention-design.md
"""

from engine.appc.tg_ui.widgets import ensure_widget_id

_highlighted: set = set()
_colors: dict = {}


def highlighted_ids() -> set:
    return _highlighted


def highlight_color(wid):
    return _colors.get(wid)


def apply(node: dict, wid: int) -> None:
    """Set `node["highlighted"]` (+ `node["highlightColor"]` when set) for
    widget id `wid`. The single source of truth for the flag-setting
    two-liner: every id-bearing node in a CEF-facing snapshot -- menu/button
    nodes, the EngRepairPaneWidget node itself, and each eng_repair_pane
    row -- must call this so none of them are silently un-highlightable."""
    node["highlighted"] = wid in highlighted_ids()
    color = highlight_color(wid)
    if color is not None:
        node["highlightColor"] = color


def show_pointer_arrow(pAction=None, pUIObject=None, eDirection=0,
                        fSpacing=0.0, kColor=None) -> int:
    # Preserve the SDK's own gates (MissionLib.py:4413-4416).
    if pUIObject is None:
        return 0
    try:
        if pUIObject.IsCompletelyVisible() == 0:
            return 0
    except AttributeError:
        return 0
    wid = ensure_widget_id(pUIObject)
    _highlighted.add(wid)
    if kColor is not None:
        _colors[wid] = kColor
    # eDirection / fSpacing are BC arrow-art placement details with no meaning
    # under a glow; deliberately discarded (see module docstring).
    return 0


def hide_pointer_arrows(pAction=None):
    # SDK semantics: HidePointerArrows empties g_lPointerArrows wholesale.
    _highlighted.clear()
    _colors.clear()
    if pAction is not None:
        return 0


def install() -> None:
    """Override the SDK's two attention functions. The SDK file is untouched.

    Safe to call repeatedly (idempotent — reassigns the same two attributes).
    Called from engine.host_loop.reset_sdk_globals(), which runs before every
    mission Initialize() — the first mission load AND every in-process swap —
    so the override is (re-)applied on that same cadence even though MissionLib
    itself is never reloaded on swap (see that function's docstring/comments).
    """
    import MissionLib
    MissionLib.ShowPointerArrow = show_pointer_arrow
    MissionLib.HidePointerArrows = hide_pointer_arrows
