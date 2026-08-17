"""CEF view for the bottom-left Sensors / radar panel.

Each tick, walks the frame's pushed contacts, runs each through
radar_projection.project_contact, and emits a `setRadar(...)` JS call
with the filtered contact list. Idempotent — re-emits only when the
snapshot changes.

Membership and detectability come from the same perception.Contact records
the target list reads (pushed by host_loop._pump_contacts every frame): the
radar draws a contact when its record says `perceivable`. What it does NOT
share is the range — the disc clips to RadarDisplay.GetRange(), a display
scale, while perception uses the player's actual sensor range. The target
list legitimately lists contacts the disc does not draw.

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

        # A player in no set has no contacts (perceived_by returns () for that
        # case, so the push is empty). Kept as a cheap early-out only — the
        # set is NOT walked for membership any more; see below.
        if getattr(player, "_containing_set", None) is None:
            return (True, minimize_state, ())

        menu = App.STTargetMenu_GetTargetMenu()
        if menu is None:
            return (True, minimize_state, ())

        target_ship = player.GetTarget() if hasattr(player, "GetTarget") else None
        range_gu = self._resolve_range_gu()
        player_pos = player.GetWorldLocation()
        player_rot = player.GetWorldRotation()

        rows = []
        # Membership is the frame's pushed contact list, walked once. This used
        # to walk player._containing_set and look each ship back up with
        # GetObjectEntry — a SECOND membership source, which is the failure the
        # contact model exists to remove (a set pointer that outlives the ships
        # it named, e.g. across a warp).
        #
        # The record's own verdict decides drawability: the menu's children are
        # this frame's targetable contacts (`_rows()` filters on
        # `Contact.targetable`). NOTHING writes `perceivable` into a row's
        # IsVisible — `set_contacts` asserts `SetVisible()` on every listed row
        # unconditionally, so that flag is write-once-True here and answers no
        # question this panel asks.
        #
        # The RANGE CLIP below stays the radar's own. It reads
        # RadarDisplay.GetRange() (1000 GU default), not the player's sensor
        # range (2000 GU on a Galaxy), so the target list legitimately lists
        # contacts the disc does not draw — display scale and perception are
        # different concepts. It is also a DISC-PLANE clip, not a 3D distance,
        # so no centre-distance the record could carry would answer it: a
        # contact directly overhead at 2x range still renders at the centre
        # with a full-length stem. (That is half of why `Contact` carries no
        # squared centre distance — the other half is that nothing else read
        # it either. See engine/appc/perception.py:Contact.)
        row = menu.GetFirstChild()
        while row is not None:
            # Advance first: the child list is DERIVED, so hold no cursor into
            # it across the body.
            this_row, row = row, menu.GetNextChild(row)
            if not isinstance(this_row, STSubsystemMenu):
                continue
            ship = this_row.GetShip()
            if ship is None or ship is player:
                continue
            # NO perceivability re-check here. This loop's source is the
            # menu's children, i.e. `_rows()`, which filters on
            # `Contact.targetable` — and `perceived_by` builds `targetable` as
            # `perceivable and ...`, so every row reached here is perceivable
            # by construction and has a record. The guard that used to sit on
            # this line (`record is None or not record.perceivable: continue`)
            # could only ever fire for a hand-built record the production path
            # cannot produce. The implication is pinned at its source by
            # tests/unit/test_perceived_by.py::
            # test_targetable_always_implies_perceivable.
            contact = project_contact(
                player_pos=player_pos,
                player_rot=player_rot,
                target_pos=ship.GetWorldLocation(),
                target_rot=ship.GetWorldRotation(),
                range_gu=range_gu,
            )
            if contact is None:
                continue
            aff = this_row.GetAffiliation()
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
