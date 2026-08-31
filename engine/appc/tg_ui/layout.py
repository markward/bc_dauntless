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
#
# BC's real TGUIObject enum only names four anchors — UL/UR/BL/BR — and the
# q13 dump measured them as 0/1/2/3 (CLASS_CONSTANTS["TGUIObject"] in
# engine/appc/constants_generated.py). Those four MUST use BC's numbers here:
# App.TGUIObject.ALIGN_UR/ALIGN_BL/ALIGN_BR are plain int copies of these
# constants, and Task 8 needed App's copies to read as BC's measured values.
# UC/CL/CC/CR/BC are a Dauntless-only extension to a fuller 9-point compass
# layout BC's real enum doesn't have — nothing in the SDK ever reaches them
# through App.TGUIObject, so they were free to move to whatever non-colliding
# slots keep every anchor distinct; they sit at 4-8.
ALIGN_UL = 0   # (0.0, 0.0)     -- BC measured
ALIGN_UR = 1   # (1.0, 0.0)     -- BC measured
ALIGN_BL = 2   # (0.0, 1.0)     -- BC measured
ALIGN_BR = 3   # (1.0, 1.0)     -- BC measured
ALIGN_UC = 4   # (0.5, 0.0)     -- Dauntless-only, no BC anchor
ALIGN_CL = 5   # (0.0, 0.5)     -- Dauntless-only, no BC anchor
ALIGN_CC = 6   # (0.5, 0.5)     -- Dauntless-only, no BC anchor
ALIGN_CR = 7   # (1.0, 0.5)     -- Dauntless-only, no BC anchor
ALIGN_BC = 8   # (0.5, 1.0)     -- Dauntless-only, no BC anchor

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


