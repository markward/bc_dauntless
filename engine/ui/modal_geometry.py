"""The large modal: one shared shape and size for full-screen-ish CEF windows.

Quick Battle Setup and Helm -> Set Course both use it, and further windows
are expected to. The CSS half is `.cp-modal--large` in configuration_panel.css
(sizing) and `.cp-modal-layer` (the full-viewport root that centres it and
lifts it above the HUD). This module is the Python half, for the panels that
must know the modal's true screen rect — the star map draws its GL backdrop
into a transparent hole in the modal and picks clicks against it.

The two halves agree by test (tests/ui/test_modal_geometry.py), not by
convention: change a number here and the CSS literal must change with it.

All values are CEF logical pixels (the view tracks the window in points, see
host_loop._compute_cef_resize).
"""

# 80vw x 80vh, floored at 900x560 so a small window still gets a usable
# modal. These are Quick Battle Setup's original numbers, promoted to the
# shared component when Set Course adopted them.
LARGE_MODAL_FRACTION = 0.8
LARGE_MODAL_MIN_W = 900
LARGE_MODAL_MIN_H = 560
# ...but the floor itself never exceeds 96% of the window, so in a window
# smaller than the floor the modal keeps shrinking with it instead of running
# off the screen (live, 2026-10-06: a ~680-wide window cut both sides off).
LARGE_MODAL_FIT_FRACTION = 0.96

# .cp-modal is content-box with a 1px border on every side.
MODAL_BORDER = 1


def large_modal_size(view_w, view_h) -> tuple:
    """Content-box (w, h) of a `.cp-modal--large` in a view of this size.

    CSS: width 80vw, min-width min(900px, 96vw) — so max(min(900, .96v), .8v).

    Floats, not rounded: Chromium lays 80vw out in fractional pixels, and
    rounding here and again at the caller would compound. Callers round once,
    at the edge where they need an integer rect.
    """
    floor_w = min(LARGE_MODAL_MIN_W, LARGE_MODAL_FIT_FRACTION * view_w)
    floor_h = min(LARGE_MODAL_MIN_H, LARGE_MODAL_FIT_FRACTION * view_h)
    return (max(floor_w, LARGE_MODAL_FRACTION * view_w),
            max(floor_h, LARGE_MODAL_FRACTION * view_h))


def large_modal_content_origin(view_w, view_h) -> tuple:
    """Top-left of the modal's CONTENT box when flex-centred in the view.

    The outer box is w + 2*MODAL_BORDER wide and centred, so its content edge
    is (view - (w + 2)) / 2 + 1 == view / 2 - w / 2: the border cancels.
    """
    w, h = large_modal_size(view_w, view_h)
    return (view_w / 2 - w / 2, view_h / 2 - h / 2)
