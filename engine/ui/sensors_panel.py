"""CEF view for the bottom-left Sensors / radar panel.

Each tick, walks the player's spatial set, runs each ship through
radar_projection.project_contact, and emits a `setRadar(...)` JS call
with the filtered contact list. Idempotent — re-emits only when the
snapshot changes.

Visibility shares state with the target list: only ships whose
STSubsystemMenu.IsVisible() == 1 are emitted. The host loop already
runs update_target_list_visibility() each tick; we read the result.

Spec: docs/ui_designs/05-sensors-radar.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.ui.panel import Panel
from engine.ui.radar_projection import project_contact
import engine.dev_mode as dev_mode


# The disc's default world-space radius, in BC game units (GU). 1 GU
# = 0.175 km, so 1000 GU ≈ 175 km of radar reach. The original BC
# Appc.dll hardcodes its own value internally and never exposes it to
# the SDK (sdk/Build/scripts/App.py:8513-8533 — RadarDisplay has no
# SetRange method). 1000 was chosen by feel after a first-pass smoke
# test at 8000 felt too tight; tracked for measurement in
# docs/instrumented_experiments/2026-05-26-radar-range-calibration.md.
DEFAULT_RANGE_GU = 1000.0

_AFFILIATION_TO_KIND = {
    "FRIENDLY": "ship",
    "ENEMY":    "ship",
    "NEUTRAL":  "ship",
    "UNKNOWN":  "ship",
}


class SensorsPanel(Panel):
    @property
    def name(self) -> str:
        return "sensors"

    def __init__(self):
        super().__init__()
        self._last_snapshot: Optional[tuple] = None
        # Panel-internal collapse state, used when no RadarDisplay is
        # registered on the TCW. When one IS registered, that wins —
        # the SDK is the source of truth so save/load works.
        self._minimizable: bool = True
        self._minimized: bool = False

    def _radar_display(self):
        """Return the RadarDisplay registered on the TCW, or None."""
        import App
        tcw = App.TacticalControlWindow_GetTacticalControlWindow()
        return tcw.GetRadarDisplay() if tcw is not None else None

    def _resolve_range_gu(self) -> float:
        """Read the range (in game units) from the SDK RadarDisplay if
        one's been registered with the TacticalControlWindow; else use
        the spec default."""
        radar = self._radar_display()
        if radar is not None and hasattr(radar, "GetRange"):
            try:
                return float(radar.GetRange())
            except Exception as _e:
                dev_mode.log_swallowed("RadarDisplay.GetRange fallback", _e)
        return DEFAULT_RANGE_GU

    def _resolve_minimize_state(self) -> tuple:
        """Return (minimizable, minimized) as bools, reading from the
        registered RadarDisplay if present, else the panel's own flags."""
        radar = self._radar_display()
        if radar is not None:
            return (bool(radar.IsMinimizable()), bool(radar.IsMinimized()))
        return (self._minimizable, self._minimized)

    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        minimize_state = self._resolve_minimize_state()
        if not self._visible:
            return (False, minimize_state, ())

        import App
        from engine.core.game import Game_GetCurrentGame
        from engine.appc.target_menu import STSubsystemMenu

        game = Game_GetCurrentGame()
        player = game.GetPlayer() if game is not None else None
        if player is None:
            return (True, minimize_state, ())

        spatial = getattr(player, "_containing_set", None)
        if spatial is None:
            return (True, minimize_state, ())

        menu = App.STTargetMenu_GetTargetMenu()
        if menu is None:
            return (True, minimize_state, ())

        target_ship = player.GetTarget() if hasattr(player, "GetTarget") else None
        range_gu = self._resolve_range_gu()
        player_pos = player.GetWorldLocation()
        player_rot = player.GetWorldRotation()

        rows = []
        for ship in spatial.GetObjectList():
            if ship is player:
                continue
            row = menu.GetObjectEntry(ship)
            if row is None or not isinstance(row, STSubsystemMenu):
                continue
            if row.IsVisible() != 1:
                continue
            contact = project_contact(
                player_pos=player_pos,
                player_rot=player_rot,
                target_pos=ship.GetWorldLocation(),
                target_rot=ship.GetWorldRotation(),
                range_gu=range_gu,
            )
            if contact is None:
                continue
            aff = row.GetAffiliation()
            kind = _AFFILIATION_TO_KIND.get(aff, "ship")
            rows.append((
                ship.GetName(),
                aff,
                kind,
                contact.x,
                contact.y,
                contact.alt,
                contact.heading,
                ship is target_ship,
            ))
        # Sort by name so the snapshot is deterministic.
        rows.sort(key=lambda r: r[0])
        return (True, minimize_state, tuple(rows))

    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, (minimizable, minimized), rows = snapshot
        payload = {
            "visible": visible,
            "minimizable": minimizable,
            "minimized": minimized,
            "range_gu": self._resolve_range_gu() if visible else 0.0,
            "contacts": [
                {
                    "name": name,
                    "affiliation": aff,
                    "kind": kind,
                    "x": x,
                    "y": y,
                    "alt": alt,
                    "heading": heading,
                    "targeted": targeted,
                }
                for (name, aff, kind, x, y, alt, heading, targeted) in rows
            ] if visible else [],
        }
        return "setRadar(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        """Action protocol:
          - "toggle" — flip the minimized state if the panel is
            minimizable. SDK code that sets SetMinimizable(0) (e.g. at
            640x480 — we don't run there, but the contract is honoured)
            disables the toggle.
        Other actions are unhandled. The radar's contacts themselves
        aren't clickable in v1.
        """
        if action == "toggle":
            radar = self._radar_display()
            if radar is not None:
                if not radar.IsMinimizable():
                    return False
                radar.SetMinimized(0 if radar.IsMinimized() else 1)
                return True
            if not self._minimizable:
                return False
            self._minimized = not self._minimized
            return True
        return False

    def invalidate(self) -> None:
        self._last_snapshot = None
