"""Controller that mirrors live ships from engine.appc.ship_lifecycle
into a UiPanel's collapsible rows. Stage 1 renders ship names + affiliation;
stage 2 (show_subsystems=True) adds one child button per populated
subsystem slot on each ship.
"""
from __future__ import annotations
from typing import Callable, Optional

from engine.appc import ship_lifecycle
from engine.ui import bindings
from engine.ui.collapsible import UiCollapsibleList
from engine.ui.panel import UiPanel


# Pixels-per-notch (dp) for wheel-driven scroll.  ~one collapsed row
# height = header padding (6+6) + line height (~16) + margin (3) ≈ 31dp.
_ROW_HEIGHT_DP = 30.0


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
        # Pixel-precise scroll offset in dp.  Applied as a negative
        # margin-top on the panel body so .bc-panel's overflow:hidden
        # clips the rows above the visible area.  Smooth row-by-row
        # scroll regardless of how many ships are expanded.
        self._scroll_pixels: float = 0.0
        # Expansion state survives rebuild_from_snapshot so scroll +
        # ship-lifecycle events don't collapse the user's open rows.
        # Ship rows are keyed by ship name; nested subsystem rows are
        # keyed by (ship_name, subsystem_label).
        self._expanded_ships: set[str] = set()
        self._expanded_subs: set[tuple[str, str]] = set()
        # Panel-wide single selection.  May be a ship, a subsystem, or a
        # child subsystem (emitter).  Only one row in the entire panel
        # is rendered as selected at a time, regardless of which ship or
        # weapon-system parent owns it.
        self._selected_target: object | None = None
        # Map target object -> widget (UiButton or UiCollapsibleList) for
        # the current rebuild.  Used to flip set_selected on the previous
        # and new widgets without a full rebuild on every click.
        self._widget_by_target: dict[int, object] = {}
        # Scroll wrapper inside the panel body.  All top-level ship rows
        # attach here, NOT directly to panel.root.  margin-top is applied
        # to the wrapper so the body's layout box stays put and its
        # overflow:hidden clips rows that scroll above the body's top.
        self._wrapper_id = bindings.append_div(panel.root, "bc-target-scroll")
        # Top-level ship rows we own (so we can destroy them on rebuild —
        # they're NOT in panel._children because we bypass the panel
        # factory to attach into self._wrapper_id).
        self._top_widgets: list = []
        self._unsub = ship_lifecycle.subscribe(self._on_event)
        self.rebuild_from_snapshot()

    def scroll(self, delta: int) -> None:
        """Bump pixel scroll offset by ``delta`` rows (positive = scroll
        down).  Clamped to >= 0; the bottom is unconstrained (over-scroll
        is harmless — body wrapper just slides off-screen)."""
        if delta == 0:
            return
        self._scroll_pixels = max(0.0, self._scroll_pixels + delta * _ROW_HEIGHT_DP)
        self._apply_scroll_offset()

    def _apply_scroll_offset(self) -> None:
        """Translate the scroll wrapper upward by the current pixel offset.
        Uses transform instead of margin-top because RmlUi's overflow:hidden
        on the body element doesn't reliably clip negative-margin children
        (rows bled into the panel padding area above the header).  Transform
        keeps the wrapper's layout box in place and only shifts its render,
        which body's overflow:hidden then clips correctly."""
        try:
            bindings.set_element_property(
                self._wrapper_id, "transform",
                f"translateY(-{self._scroll_pixels:.1f}dp)")
        except AttributeError:
            pass  # older backend without set_element_property

    def rebuild_from_snapshot(self) -> None:
        # Tear down our wrapper subtree (panel.clear doesn't know about it
        # because the wrapper sits outside panel._children).
        for w in self._top_widgets:
            w.destroy()
        self._top_widgets.clear()
        self._widget_by_target.clear()
        # Filter out the player.  Sort by name for a stable, user-meaningful
        # order across rebuilds (snapshot() returns a set).
        player = self._get_player()
        non_player = sorted(
            (s for s in ship_lifecycle.snapshot() if s is not player),
            key=lambda s: s.GetName(),
        )
        for ship in non_player:
            self._add_row_for_target(ship)
        self._apply_scroll_offset()

    def destroy(self) -> None:
        self._unsub()
        for w in self._top_widgets:
            w.destroy()
        self._top_widgets.clear()
        bindings.remove_element(self._wrapper_id)
        self._panel.clear()

    def _on_event(self, event: str, ship) -> None:
        self.rebuild_from_snapshot()

    def _add_row_for_target(self, ship) -> None:
        affiliation = _ship_affiliation(ship)
        ship_name = ship.GetName()
        # Attach to our scroll wrapper (NOT panel.root) so margin-top scroll
        # affects only our rows and the body can clip them.
        row = UiCollapsibleList(
            parent_element=self._wrapper_id,
            label=ship_name,
            affiliation=affiliation,
            expanded=ship_name in self._expanded_ships,
            selected=ship is self._selected_target,
            on_click=lambda s=ship: self._select(s),
            on_toggle=lambda exp, n=ship_name: self._track_ship_expanded(n, exp),
        )
        self._top_widgets.append(row)
        self._widget_by_target[id(ship)] = row
        if not self._show_subsystems:
            return
        for label, sub in populated_subsystems(ship):
            num_children = 0
            if hasattr(sub, "GetNumChildSubsystems"):
                num_children = sub.GetNumChildSubsystems()
            if num_children == 0:
                btn = row.button(
                    label,
                    selected=sub is self._selected_target,
                    on_click=lambda s=sub: self._select_subsystem(s),
                )
                self._widget_by_target[id(sub)] = btn
            else:
                key = (ship_name, label)
                child_collapsible = row.collapsible(
                    label=label,
                    expanded=key in self._expanded_subs,
                    selected=sub is self._selected_target,
                    on_click=lambda s=sub: self._select_subsystem(s),
                    on_toggle=lambda exp, k=key: self._track_sub_expanded(k, exp),
                )
                self._widget_by_target[id(sub)] = child_collapsible
                for i in range(num_children):
                    child = sub.GetChildSubsystem(i)
                    if child is None:
                        continue
                    cl = child.GetName() if hasattr(child, "GetName") else label
                    cbtn = child_collapsible.button(
                        cl,
                        selected=child is self._selected_target,
                        on_click=lambda s=child: self._select_subsystem(s),
                    )
                    self._widget_by_target[id(child)] = cbtn

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

    def _set_selected(self, new_target) -> None:
        """Update panel-wide selection: flip the previous widget's
        selected-class off, the new widget's selected-class on, and
        remember the target so rebuilds re-apply the visual."""
        if self._selected_target is new_target:
            return
        old = self._widget_by_target.get(id(self._selected_target))
        if old is not None and hasattr(old, "set_selected"):
            old.set_selected(False)
        self._selected_target = new_target
        new = self._widget_by_target.get(id(new_target))
        if new is not None and hasattr(new, "set_selected"):
            new.set_selected(True)

    def _select(self, ship) -> None:
        self._set_selected(ship)
        player = self._get_player()
        if player is not None:
            player.SetTarget(ship)

    def _select_subsystem(self, sub) -> None:
        self._set_selected(sub)
        player = self._get_player()
        if player is not None:
            player.SetTargetSubsystem(sub)
