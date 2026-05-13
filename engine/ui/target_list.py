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
    ("Shield Generator",    "GetShieldSubsystem"),
    ("Sensor Subsystem",    "GetSensorSubsystem"),
    ("Power Plant",         "GetPowerSubsystem"),
    ("Engineering",         "GetRepairSubsystem"),
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
        self._scroll_offset: int = 0
        # Expansion state survives rebuild_from_snapshot so scroll +
        # ship-lifecycle events don't collapse the user's open rows.
        # Ship rows are keyed by ship name; nested subsystem rows are
        # keyed by (ship_name, subsystem_label).
        self._expanded_ships: set[str] = set()
        self._expanded_subs: set[tuple[str, str]] = set()
        self._unsub = ship_lifecycle.subscribe(self._on_event)
        self.rebuild_from_snapshot()

    def scroll(self, delta: int) -> None:
        """Bump scroll offset by ``delta`` (positive = scroll down through
        the list, showing later ships). Clamped so at least one ship row is
        always visible. Triggers a rebuild."""
        if delta == 0:
            return
        self._scroll_offset = max(0, self._scroll_offset + int(delta))
        self.rebuild_from_snapshot()

    def rebuild_from_snapshot(self) -> None:
        self._panel.clear()
        # Filter out the player BEFORE slicing so the offset semantics are
        # "skip N non-player ships from the top". Sort by name for a stable,
        # user-meaningful order across rebuilds (snapshot() returns a set).
        player = self._get_player()
        non_player = sorted(
            (s for s in ship_lifecycle.snapshot() if s is not player),
            key=lambda s: s.GetName(),
        )
        # Clamp offset so at least one ship row is shown when ships exist.
        max_offset = max(0, len(non_player) - 1)
        if self._scroll_offset > max_offset:
            self._scroll_offset = max_offset
        for ship in non_player[self._scroll_offset:]:
            self._add_row_for_target(ship)

    def destroy(self) -> None:
        self._unsub()
        self._panel.clear()

    def _on_event(self, event: str, ship) -> None:
        self.rebuild_from_snapshot()

    def _add_row_for_target(self, ship) -> None:
        affiliation = _ship_affiliation(ship)
        ship_name = ship.GetName()
        row = self._panel.collapsible(
            label=ship_name,
            affiliation=affiliation,
            expanded=ship_name in self._expanded_ships,
            on_click=lambda s=ship: self._select(s),
            on_toggle=lambda exp, n=ship_name: self._track_ship_expanded(n, exp),
        )
        if not self._show_subsystems:
            return
        for label, sub in populated_subsystems(ship):
            num_children = 0
            if hasattr(sub, "GetNumChildSubsystems"):
                num_children = sub.GetNumChildSubsystems()
            if num_children == 0:
                row.button(label, on_click=lambda s=sub: self._select_subsystem(s))
            else:
                key = (ship_name, label)
                child_collapsible = row.collapsible(
                    label=label,
                    expanded=key in self._expanded_subs,
                    on_click=lambda s=sub: self._select_subsystem(s),
                    on_toggle=lambda exp, k=key: self._track_sub_expanded(k, exp),
                )
                for i in range(num_children):
                    child = sub.GetChildSubsystem(i)
                    if child is None:
                        continue
                    cl = child.GetName() if hasattr(child, "GetName") else label
                    child_collapsible.button(
                        cl,
                        on_click=lambda s=child: self._select_subsystem(s),
                    )

    def _track_ship_expanded(self, ship_name: str, expanded: bool) -> None:
        if expanded:
            self._expanded_ships.add(ship_name)
        else:
            self._expanded_ships.discard(ship_name)

    def _track_sub_expanded(self, key: tuple[str, str], expanded: bool) -> None:
        if expanded:
            self._expanded_subs.add(key)
        else:
            self._expanded_subs.discard(key)

    def _select(self, ship) -> None:
        player = self._get_player()
        if player is not None:
            player.SetTarget(ship)

    def _select_subsystem(self, sub) -> None:
        player = self._get_player()
        if player is not None:
            player.SetTargetSubsystem(sub)
