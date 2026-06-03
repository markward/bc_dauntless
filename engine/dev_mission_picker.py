"""MissionPicker — dev-only mission loader panel for the CEF overlay.

Subclasses engine.ui.panel.Panel so the host loop's PanelRegistry
pumps render_payload() each tick and routes mission-picker/* events
to dispatch_event. Lazy on registry walk: the constructor receives a
getter that is not invoked until the first open(). The picker carries
one external callback (on_pick); pause-menu visibility arbitration is
the host loop's responsibility — see _apply_pause_menu_side_effects.
"""
from __future__ import annotations

import json
from typing import Callable, Optional

from engine.missions import FamilyEntry, MissionRegistry
from engine.ui.panel import Panel

# Episode-level directories that the original SDK layout uses as a
# pass-through wrapper when a family has only one episode; we collapse
# those into the family row so the tree feels less noisy.
_SKIP_EPISODE_LEVEL = {"Episode", "."}


class MissionPicker(Panel):
    def __init__(self,
                 registry_getter: Callable[[], MissionRegistry],
                 on_pick: Callable[[str], None]):
        super().__init__()
        self._registry_getter = registry_getter
        self._on_pick = on_pick
        self._visible: bool = False
        self._registry: Optional[MissionRegistry] = None
        self._cached_tree: Optional[list] = None
        # render_payload snapshot — tuple of (visible, tree_built_flag)
        # so the first open emits with the tree and the first close
        # emits the hide message; subsequent ticks with no change emit
        # None.
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "mission-picker"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        if self._registry is None:
            self._registry = self._registry_getter()
            self._cached_tree = _build_tree(self._registry)
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def render_payload(self) -> Optional[str]:
        snapshot = (self._visible, self._cached_tree is not None)
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if self._visible:
            payload = {"tree": self._cached_tree, "visible": True}
        else:
            payload = {"visible": False}
        return "setMissionPicker(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("pick:"):
            module = action[len("pick:"):]
            self._on_pick(module)
            self.close()
            return True
        return False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def invalidate(self) -> None:
        """Drop the render_payload snapshot so the next call re-emits
        regardless of state changes since the last emit. Called by
        PanelRegistry.invalidate_all() on CEF document load — required
        so a Cmd+R reload while the picker is open re-paints it on
        the fresh page."""
        self._last_pushed = None


def _build_tree(registry: MissionRegistry) -> list:
    """Convert a MissionRegistry to the JSON-serialisable tree the JS
    side renders. Applies the skip-episode-level heuristic: when a
    family has exactly one episode whose dir_name is in
    _SKIP_EPISODE_LEVEL, the episode wrapper is dropped and the
    family's children list contains mission rows directly. Display
    names come from the registry's resolved display_name (with the
    name_resolver's dir-name fallback already applied)."""
    out: list = []
    for family in registry.families:
        family_node = {
            "kind": "family",
            "label": family.display_name or family.dir_name,
            "children": [],
        }
        skip = (
            len(family.episodes) == 1
            and family.episodes[0].dir_name in _SKIP_EPISODE_LEVEL
        )
        if skip:
            ep = family.episodes[0]
            for mission in ep.missions:
                family_node["children"].append({
                    "kind": "mission",
                    "label": mission.display_name or mission.dir_name,
                    "module": mission.module_name,
                })
        else:
            for episode in family.episodes:
                ep_node = {
                    "kind": "episode",
                    "label": episode.display_name or episode.dir_name,
                    "children": [],
                }
                for mission in episode.missions:
                    ep_node["children"].append({
                        "kind": "mission",
                        "label": mission.display_name or mission.dir_name,
                        "module": mission.module_name,
                    })
                family_node["children"].append(ep_node)
        out.append(family_node)
    return out
