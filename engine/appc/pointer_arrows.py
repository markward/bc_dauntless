"""Host-facing collector for MissionLib pointer arrows.

MissionLib owns the placement math (ShowPointerArrow/HidePointerArrows,
MissionLib.py:4412-4503); this module exposes the resulting normalized
placements + direction so the host can emit a CEF overlay (Task 9).

Direction is NOT tagged onto the icon by the (unedited) SDK — ShowPointerArrow
never sets an attribute like `_pointer_dir`. Instead it bakes the direction
into the icon's glyph id: `App.TGIcon_Create(lcars, 220 + eDirection, kColor)`.
So the direction is recovered here as `icon.GetIconID() - 220`, which is
faithful to what BC itself draws. Note the two corner directions
(POINTER_UL_CORNER=8, POINTER_UR_CORNER=9) are created with glyph
220+POINTER_RIGHT / 220+POINTER_LEFT respectively (MissionLib.py:4425-4430),
so they resolve to RIGHT(4)/LEFT(0) here rather than 8/9 — that collapse is
what BC's own art shows, not a bug in this derivation.
"""

from engine.appc.top_window import TopWindow_GetTopWindow

_ICON_ID_DIRECTION_BASE = 220


def emitted_arrows():
    top = TopWindow_GetTopWindow()
    placements = getattr(top, "_arrow_placements", [])
    out = []
    for icon, x, y in placements:
        out.append({
            "x": x, "y": y,
            "w": icon.GetWidth(), "h": icon.GetHeight(),
            "dir": icon.GetIconID() - _ICON_ID_DIRECTION_BASE,
        })
    return out
