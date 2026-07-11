"""SDK UI layout primitives: normalized (0..1, top-left, y-down) rects, the
ALIGN_* anchor mapping, and the single normalized→CEF (vw/vh) boundary.

These sentinels are the single source of truth; the root App.py shim's
TGUIObject class imports them directly (App.TGUIObject.ALIGN_* == these same
ints) so real SDK AlignTo calls resolve real anchors instead of falling
through App's module __getattr__ to the int()==0 _NamedStub stub."""

# Anchor sentinels (halign, valign codes). App.TGUIObject.ALIGN_* (defined in
# the root App.py shim, near the tg_ui.widgets import block) imports these
# directly, so SDK comparisons against App.TGUIObject.ALIGN_* match by
# construction — no duplicated/drifting int table.
ALIGN_UL = 0   # (0.0, 0.0)
ALIGN_UC = 1   # (0.5, 0.0)
ALIGN_UR = 2   # (1.0, 0.0)
ALIGN_CL = 3   # (0.0, 0.5)
ALIGN_CC = 4   # (0.5, 0.5)
ALIGN_CR = 5   # (1.0, 0.5)
ALIGN_BL = 6   # (0.0, 1.0)
ALIGN_BC = 7   # (0.5, 1.0)
ALIGN_BR = 8   # (1.0, 1.0)

ANCHOR_FRACTIONS = {
    ALIGN_UL: (0.0, 0.0), ALIGN_UC: (0.5, 0.0), ALIGN_UR: (1.0, 0.0),
    ALIGN_CL: (0.0, 0.5), ALIGN_CC: (0.5, 0.5), ALIGN_CR: (1.0, 0.5),
    ALIGN_BL: (0.0, 1.0), ALIGN_BC: (0.5, 1.0), ALIGN_BR: (1.0, 1.0),
}


class Rect:
    __slots__ = ("left", "top", "width", "height")

    def __init__(self, left=0.0, top=0.0, width=0.0, height=0.0):
        self.left = float(left)
        self.top = float(top)
        self.width = float(width)
        self.height = float(height)

    @property
    def right(self):
        return self.left + self.width

    @property
    def bottom(self):
        return self.top + self.height


def anchor_point(rect, anchor):
    fx, fy = ANCHOR_FRACTIONS[anchor]
    return (rect.left + fx * rect.width, rect.top + fy * rect.height)


def _fmt(value, unit):
    # Normalized fraction → viewport-percent string, trimmed to 1 decimal.
    return "%svw" % round(value * 100.0, 1) if unit == "vw" else "%svh" % round(value * 100.0, 1)


def norm_to_vhvw(left, top, width, height):
    """The one documented normalized→CEF boundary: fraction-of-screen → vw/vh.
    x/width use vw (fraction of viewport width); y/height use vh. No y-flip."""
    return {
        "left": _fmt(left, "vw"),
        "top": _fmt(top, "vh"),
        "width": _fmt(width, "vw"),
        "height": _fmt(height, "vh"),
    }


class LayoutNotResolved(RuntimeError):
    """Raised when GetScreenOffset is called on a widget the resolver has not
    placed (no top-down Layout() pass has reached it). Replaces the old
    silent (0,0) stub so unimplemented panels are loud, not plausibly-wrong.

    GetLeft()/GetTop() deliberately do NOT raise this: real (read-only) SDK
    scripts read a sibling's GetLeft()/GetTop() immediately after AddChild,
    before any Layout() pass runs (e.g. Bridge/PowerDisplay.py:474). They
    fall back to the known local placement instead."""
