"""Controller that mirrors live ships from engine.appc.ship_lifecycle
into a UiPanel's collapsible rows. Stage 1 renders ship names + affiliation;
stage 2 (show_subsystems=True) adds one child button per populated
subsystem slot on each ship.
"""
from __future__ import annotations
from typing import Callable, Optional

from engine.appc import ship_lifecycle
from engine.ui.panel import UiPanel


_SUBSYSTEM_GETTERS = (
    ("Hull",                "GetHull"),
    ("Sensor Subsystem",    "GetSensorSubsystem"),
    ("Impulse Engines",     "GetImpulseEngineSubsystem"),
    ("Warp Engines",        "GetWarpEngineSubsystem"),
    ("Phaser System",       "GetPhaserSystem"),
    ("Pulse Weapon System", "GetPulseWeaponSystem"),
    ("Torpedo System",      "GetTorpedoSystem"),
    ("Tractor Beam System", "GetTractorBeamSystem"),
)


def populated_subsystems(ship) -> list[tuple[str, object]]:
    """Return [(label, subsystem)] for each non-None subsystem slot on ship.

    Labels prefer ``subsystem.GetName()`` and fall back to the canonical
    label if the subsystem has no name. Missing getters are skipped
    silently.
    """
    out: list[tuple[str, object]] = []
    for fallback, getter_name in _SUBSYSTEM_GETTERS:
        getter = getattr(ship, getter_name, None)
        if getter is None:
            continue
        sub = getter()
        if sub is None:
            continue
        label = None
        if hasattr(sub, "GetName"):
            label = sub.GetName()
        out.append((label or fallback, sub))
    return out


def _ship_affiliation(ship) -> str:
    """Friendly/enemy/neutral via the current Mission's name groups; default unknown."""
    from engine.core.game import Game_GetCurrentGame
    game = Game_GetCurrentGame()
    if game is None: return "unknown"
    episode = game.GetCurrentEpisode()
    if episode is None: return "unknown"
    mission = episode.GetCurrentMission()
    if mission is None: return "unknown"
    name = ship.GetName()
    if mission.GetFriendlyGroup().IsNameInGroup(name): return "friendly"
    if mission.GetEnemyGroup().IsNameInGroup(name):    return "enemy"
    if mission.GetNeutralGroup().IsNameInGroup(name):  return "neutral"
    return "unknown"


class TargetListController:
    """Mirrors ship_lifecycle into a UiPanel.

    Every event triggers a panel.clear() + rebuild from
    ship_lifecycle.snapshot(). For BC's typical ship counts (<20) the DOM
    churn cost is negligible and the implementation stays trivially
    correct under add/remove/reorder.
    """
    def __init__(self, panel: UiPanel, *,
                 player_provider: Callable[[], Optional[object]],
                 show_subsystems: bool = False):
        self._panel = panel
        self._get_player = player_provider
        self._show_subsystems = show_subsystems
        self._unsub = ship_lifecycle.subscribe(self._on_event)
        self.rebuild_from_snapshot()

    def rebuild_from_snapshot(self) -> None:
        self._panel.clear()
        for ship in ship_lifecycle.snapshot():
            self._add_row(ship)

    def destroy(self) -> None:
        self._unsub()
        self._panel.clear()

    def _on_event(self, event: str, ship) -> None:
        self.rebuild_from_snapshot()

    def _add_row(self, ship) -> None:
        if ship is self._get_player():
            return
        affiliation = _ship_affiliation(ship)
        row = self._panel.collapsible(
            label=ship.GetName(),
            affiliation=affiliation,
            expanded=False,
            on_click=lambda s=ship: self._select(s),
        )
        if self._show_subsystems:
            for label, sub in populated_subsystems(ship):
                row.button(label, on_click=lambda s=sub: self._select_subsystem(s))

    def _select(self, ship) -> None:
        player = self._get_player()
        if player is not None:
            player.SetTarget(ship)

    def _select_subsystem(self, sub) -> None:
        player = self._get_player()
        if player is not None:
            player.SetTargetSubsystem(sub)
