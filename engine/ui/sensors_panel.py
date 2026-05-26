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


# The disc's default world-space radius. Spec value
# (docs/ui_designs/05-sensors-radar.md "SDK runtime contract"). Real
# SDK code calls pRadar.SetRange(8000); for now the panel defaults to
# the spec value when no SetRange has been issued. SDK scripts that
# need a different range call _RadarDisplay.SetRange and we re-read it
# each snapshot.
DEFAULT_RANGE_M = 8000.0

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

    def _resolve_range_m(self) -> float:
        """Read the range from the SDK RadarDisplay if one's been
        registered with the TacticalControlWindow; else use the spec
        default. Lets SDK scripts override per-mission via SetRange."""
        import App
        tcw = App.TacticalControlWindow_GetTacticalControlWindow()
        radar = tcw.GetRadarDisplay() if tcw is not None else None
        if radar is not None and hasattr(radar, "GetRange"):
            try:
                return float(radar.GetRange())
            except Exception:
                pass
        return DEFAULT_RANGE_M

    def _snapshot(self):
        """Build a hashable snapshot of the rendered state."""
        if not self._visible:
            return (False, ())

        import App
        from engine.core.game import Game_GetCurrentGame
        from engine.appc.target_menu import STSubsystemMenu

        game = Game_GetCurrentGame()
        player = game.GetPlayer() if game is not None else None
        if player is None:
            return (True, ())

        spatial = getattr(player, "_containing_set", None)
        if spatial is None:
            return (True, ())

        menu = App.STTargetMenu_GetTargetMenu()
        if menu is None:
            return (True, ())

        target_ship = player.GetTarget() if hasattr(player, "GetTarget") else None
        range_m = self._resolve_range_m()
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
                range_m=range_m,
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
        return (True, tuple(rows))

    def render_payload(self) -> Optional[str]:
        snapshot = self._snapshot()
        if snapshot == self._last_snapshot:
            return None
        self._last_snapshot = snapshot
        visible, rows = snapshot
        payload = {
            "visible": visible,
            "range_m": self._resolve_range_m() if visible else 0.0,
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
        """The radar disc is read-only in v1. No clickable contacts —
        the target list already handles target selection. Reserved for
        a future zoom-in / zoom-out gesture (SDK icons 90-102 are
        defined but unused in stock BC)."""
        return False

    def invalidate(self) -> None:
        self._last_snapshot = None
