"""SDK UI layout primitives: normalized (0..1, top-left, y-down) rects, the
ALIGN_* anchor mapping, and the single normalized→CEF (vw/vh) boundary.

These sentinels are our own; the SDK references App.TGUIObject.ALIGN_* which
must resolve to these same values (wired in Task 4)."""

# Anchor sentinels (halign, valign codes). Values are internal but must be the
# ones App.TGUIObject.ALIGN_* expose so SDK comparisons match (Task 4 wires them).
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
