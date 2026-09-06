"""Ease the player's drawn pose across a helm handover.

The player is rendered from two pose pipelines that sit a tick apart:

  * manually flown — integrated per RENDER frame by `_PlayerControl`, so its
    live pose is already smooth and is drawn directly;
  * AI / waypoint / scripted — integrated on the fixed 60 Hz tick, so it is
    drawn at `lerp(prev, cur, alpha)`, up to one full tick BEHIND live.

Handing the helm over switches pipelines in one frame, and the drawn pose
jumps by that phase offset — forward when taking control back, and a one-frame
lurch when giving it away. At 6 GU/s a tick is ~0.1 GU (~17 m), which is very
visible on a chase camera.

This freezes the pose that was on screen at the switch and blends from it to
the true pose over `SMOOTH_DURATION_S`, so the drawn pose is continuous at both
ends of the window. Nothing here touches sim state: the ship is where it always
was, only the pose handed to the camera and the renderer is eased.

Pure — no renderer, no App, no global state — like `transform_buffer` and
`interpolate` beside it. Rotation blending reuses `lerp_transform`'s nlerp +
Gram-Schmidt, the same primitive the render interpolation and
`engine/cameras/chase.py:_advance_smoothing` use; the handover delta is one
tick of motion, well inside the small-angle range that makes nlerp
indistinguishable from slerp.
"""

from engine.appc.math import TGMatrix3
from engine.core.interpolate import lerp_transform

# Fixed window. Long enough to hide a tick of motion, short enough that the
# ship is back on its true pose before the player can act on the discrepancy.
# Tuned live: 0.12 still left a slight shudder, 0.36 was the value that read
# clean. Raising this trades a longer catch-up for a gentler one.
SMOOTH_DURATION_S = 0.36


class HandoverSmoother:
    """Blends from a frozen pose to the live one over a fixed window."""

    __slots__ = ("_frozen_loc", "_frozen_rot", "_elapsed_s")

    def __init__(self):
        self._frozen_loc = None
        self._frozen_rot = None
        self._elapsed_s = 0.0

    @property
    def active(self) -> bool:
        """True while a handover is still being eased out."""
        return (self._frozen_loc is not None
                and self._elapsed_s < SMOOTH_DURATION_S)

    def begin(self, loc, rot) -> None:
        """Freeze the pose currently on screen and start the window.

        Called again while already active (a fast toggle) this re-freezes from
        the new pose rather than blending on from a stale one.
        """
        self._frozen_loc = loc
        self._frozen_rot = rot
        self._elapsed_s = 0.0

    def advance(self, dt: float) -> None:
        """Move the window forward by one frame's worth of time."""
        if self._frozen_loc is None:
            return
        self._elapsed_s += float(dt)

    def cancel(self) -> None:
        """Drop the frozen pose (mission swap / scene discontinuity), so the
        player is drawn live rather than blended in from a dead scene."""
        self._frozen_loc = None
        self._frozen_rot = None
        self._elapsed_s = 0.0

    def blend(self, loc, rot=None):
        """Return the pose to draw: the live `(loc, rot)` when inactive, else
        eased from the frozen pose toward it."""
        if rot is None:
            rot = TGMatrix3()
        if not self.active:
            return loc, rot
        t = self._elapsed_s / SMOOTH_DURATION_S
        eased = t * t * (3.0 - 2.0 * t)   # smoothstep, as LetterboxAnimator
        return lerp_transform(
            self._frozen_loc, self._frozen_rot, loc, rot, eased)
