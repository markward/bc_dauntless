"""The boot notice splash: Activision's required notice before the bridge.

The Bridge Commander SDK licence (SDKLicense.txt, "New Game Materials")
requires the opening screen to show, "with reasonable duration", the
creator's name and contact and the exact words "THIS MATERIAL IS NOT MADE OR
SUPPORTED BY ACTIVISION." The player README (docs/packaging/README.txt)
carries the same two lines; tests/unit/test_boot_notice_panel.py keeps them
in step.

Black, 1 s fade in, 2 s hold, 2 s fade out, then boot continues. Wall-clock
time throughout: game time can be scaled or paused, and does not run yet.

The clock starts when the PAGE says it is showing the notice, not when the
panel is built. CEF drops every push until the document has loaded (~340 ms
on a cold start, already loaded after the first-run or Mods screen), and
there is no binding to ask which. So the panel offers the arm payload every
frame until the page acknowledges it (`boot-notice/shown`), and the fade
is measured from that acknowledgement. Opacity is pushed from here each
frame rather than left to a CSS animation, so the schedule is the one this
module computes and tests.

Boot loads the game BEHIND the notice (hold=True): the pump loop runs the
fade-in, then hands back with the notice at full opacity, the window holding
that frame while the SDK and the mission load; release() then plays the rest
of the hold and the fade-out. A load longer than the hold simply lengthens
it -- the fade-out starts at whichever comes later, the end of the 2 s hold
or the release.

No skip, on purpose: it is a licence requirement in the shipped game.
"""
from __future__ import annotations

import json
import time
from typing import Callable, Optional

from engine.ui.panel import Panel

NOTICE_LINE = "THIS MATERIAL IS NOT MADE OR SUPPORTED BY ACTIVISION."
CREDIT_LINE = "Created by Mark Ward - github.com/markward/bc_dauntless"

FADE_IN_S = 1.0
HOLD_S = 2.0
FADE_OUT_S = 2.0
TOTAL_S = FADE_IN_S + HOLD_S + FADE_OUT_S

# A page that never loads must not hang boot on a black window.
ACK_TIMEOUT_S = 10.0

# How long full opacity is pushed before a held notice hands back. CEF paints
# asynchronously, and the window shows whichever frame it last presented for
# as long as the load runs -- that frame must be the finished fade-in.
HOLD_SETTLE_S = 0.15


def opacity_at(t: float) -> float:
    """Text opacity `t` seconds after the page first showed the notice."""
    if t <= 0.0:
        return 0.0
    if t < FADE_IN_S:
        return t / FADE_IN_S
    if t < FADE_IN_S + HOLD_S:
        return 1.0
    if t < TOTAL_S:
        return 1.0 - (t - FADE_IN_S - HOLD_S) / FADE_OUT_S
    return 0.0


class BootNoticePanel(Panel):
    """Pumped by host_loop._run_preboot_panel; `outcome` ends the loop.

    `clock` is injected so tests drive the schedule without sleeping.
    `hold` keeps the notice up after the fade-in until release().
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic,
                 hold: bool = False):
        super().__init__()
        self._clock = clock
        self._hold = hold
        self._created_at = clock()
        self._shown_at: Optional[float] = None
        self._released_at: Optional[float] = None
        self._last_pushed: Optional[str] = None

    @property
    def name(self) -> str:
        return "boot-notice"

    @property
    def teardown_script(self) -> Optional[str]:
        """Pushed by host_loop._run_preboot_panel when the screen ends --
        except when it ends on "holding": the notice stays up through the
        load."""
        if self.outcome == "holding":
            return None
        return "setBootNotice(null);"

    def release(self) -> None:
        """The load behind a held notice is done: finish the schedule."""
        if self._released_at is None:
            self._released_at = self._clock()

    def _fade_out_start(self) -> Optional[float]:
        """When the fade-out begins; None while a held notice is unreleased."""
        end_of_hold = self._shown_at + FADE_IN_S + HOLD_S
        if not self._hold:
            return end_of_hold
        if self._released_at is None:
            return None
        return max(end_of_hold, self._released_at)

    def _opacity(self, now: float) -> float:
        t = now - self._shown_at
        if t < FADE_IN_S:
            return opacity_at(t)
        start = self._fade_out_start()
        if start is None or now < start:
            return 1.0
        return max(0.0, 1.0 - (now - start) / FADE_OUT_S)

    @property
    def outcome(self) -> Optional[str]:
        """None while running; "holding" when a held notice has faded in and
        waits for release(); "shown" once the schedule has played out;
        "unshown" if the page never acknowledged within ACK_TIMEOUT_S."""
        now = self._clock()
        if self._shown_at is None:
            if now - self._created_at >= ACK_TIMEOUT_S:
                return "unshown"
            return None
        start = self._fade_out_start()
        if start is None:
            if now - self._shown_at >= FADE_IN_S + HOLD_SETTLE_S:
                return "holding"
            return None
        if now >= start + FADE_OUT_S:
            return "shown"
        return None

    def render_payload(self) -> Optional[str]:
        if self._shown_at is None:
            # Not diffed: a dropped push cannot be detected, so it is offered
            # again every frame until the page answers.
            return "setBootNotice(" + json.dumps({
                "lines": [NOTICE_LINE, CREDIT_LINE],
                "opacity": 0.0,
                "ack": True,
            }) + ");"
        opacity = round(self._opacity(self._clock()), 3)
        script = "setBootNotice(" + json.dumps({"opacity": opacity}) + ");"
        if script == self._last_pushed:
            return None
        self._last_pushed = script
        return script

    def dispatch_event(self, action: str) -> bool:
        if action == "shown":
            if self._shown_at is None:
                self._shown_at = self._clock()
            return True
        return False

    def invalidate(self) -> None:
        """Drop the diff cache. Called on CEF document load."""
        self._last_pushed = None
