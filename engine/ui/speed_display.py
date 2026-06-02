"""CEF view for the bottom-row Speed readout.

Read-only panel. Renders the player's current and max impulse speed
(in KPH) plus a WARP badge when the in-system warp boost (Ctrl+I) is
engaged. Idempotent — `render_payload()` returns None unless the
snapshot has changed since the last call.

State source is injected at construction: `player_control` is the
`_PlayerControl` instance from `host_loop.run()` (owns `_current_speed`
and `_warp_boost`). Max speed is read from the player ship's
ImpulseEngineSubsystem each tick so it stays in sync if the SDK swaps
ships or applies upgrades.

Spec: docs/ui_designs/04-weapons-and-speed.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel


# m/s → km/h. KPH is the unit shown in the mockup; the engine integrates
# in m/s, so we convert at the render boundary.
_MPS_TO_KPH = 3.6


class SpeedDisplay(Panel):
    @property
    def name(self) -> str:
        return "speed"

    def __init__(self, player_control):
        super().__init__()
        # The _PlayerControl singleton from host_loop owns the integrated
        # _current_speed (m/s) and the _warp_boost toggle.
        self._player_control = player_control
        self._last_snapshot: Optional[tuple] = None

    def _snapshot(self) -> tuple:
        if not self._visible:
            return (False, 0, 0, False)

        from engine.core.game import Game_GetCurrentGame
        game = Game_GetCurrentGame()
        player = game.GetPlayer() if game is not None else None
        if player is None:
            return (True, 0, 0, False)

        current_mps = self._player_control._current_speed
        ies = player.GetImpulseEngineSubsystem() if hasattr(player, "GetImpulseEngineSubsystem") else None
        max_mps = ies.GetMaxSpeed() if ies is not None else 0.0

        # Round to whole KPH — sub-km/h jitter from the integrator is
        # not interesting to a pilot reading the panel.
        current_kph = int(round(current_mps * _MPS_TO_KPH))
        max_kph = int(round(max_mps * _MPS_TO_KPH))
        warp = bool(self._player_control._warp_boost)
        return (True, current_kph, max_kph, warp)

    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, current_kph, max_kph, warp = snapshot
        payload = {
            "visible": visible,
            "current_kph": current_kph,
            "max_kph": max_kph,
            "warp": warp,
        }
        return "setSpeedDisplay(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        return False

    def invalidate(self) -> None:
        self._last_snapshot = None
