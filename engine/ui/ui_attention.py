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
acted), or until the next mission swap re-installs the override (see install()).
eDirection/fSpacing (BC arrow-art placement details) are accepted for signature
compatibility and discarded; kColor is coerced to a JSON-safe CSS colour string
at capture time (or dropped if it can't be) — see _coerce_highlight_color.

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


def _coerce_highlight_color(kColor):
    """Coerce an SDK kColor argument to a JSON-safe CSS colour string, or
    None if it can't be.

    No live SDK ShowPointerArrow call site passes kColor today (verified
    across every E1M1/E1M2/E2M0 ShowArrow site), but the signature accepts
    one, and if a mission ever did, the raw object must never reach the
    highlight dict: it lands in the CrewMenuPanel snapshot node and that
    snapshot is json.dumps()'d every single frame in render_payload(). BC's
    kColor is a TGColorA/NiColorA (App.py: r/g/b/a floats in 0.0-1.0 range,
    e.g. App.NiColorA_WHITE == NiColorA(1.0, 1.0, 1.0, 1.0)).

    Plain strings ("gold", "rgb(...)") are already CSS and pass through
    unchanged. A TGColorA-shaped object (has r/g/b, optionally a) is scaled
    to 0-255 ints and rendered as "rgb(...)"/"rgba(...)". Anything else
    (missing/non-numeric components) is dropped -- returns None -- rather
    than risk a non-serialisable value in the snapshot.
    """
    if kColor is None:
        return None
    if isinstance(kColor, str):
        return kColor
    r = getattr(kColor, "r", None)
    g = getattr(kColor, "g", None)
    b = getattr(kColor, "b", None)
    if r is None or g is None or b is None:
        return None
    try:
        r255 = round(float(r) * 255)
        g255 = round(float(g) * 255)
        b255 = round(float(b) * 255)
    except (TypeError, ValueError):
        return None
    a = getattr(kColor, "a", None)
    try:
        af = float(a) if a is not None else None
    except (TypeError, ValueError):
        af = None
    if af is None:
        return "rgb(%d,%d,%d)" % (r255, g255, b255)
    return "rgba(%d,%d,%d,%.3f)" % (r255, g255, b255, af)


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
    color = _coerce_highlight_color(kColor)
    if color is not None:
        _colors[wid] = color
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

    Also clears any highlight state left over from the previous mission.
    _highlighted/_colors are otherwise only cleared by HidePointerArrows, so
    without this a mission that ends mid-highlight (never calling
    HidePointerArrows) would leak its widget ids into the next mission for
    the whole process lifetime, and a same-id widget in the new mission
    could come up pre-highlighted.
    """
    import MissionLib
    MissionLib.ShowPointerArrow = show_pointer_arrow
    MissionLib.HidePointerArrows = hide_pointer_arrows
    hide_pointer_arrows()
