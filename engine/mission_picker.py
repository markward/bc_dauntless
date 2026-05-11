"""MissionPicker — centered modal that lists every discoverable mission
and routes a click to a swap-mission callback.

This module is a pure consumer of engine.ui and engine.missions and has
no knowledge of how a mission actually loads — the host wires up the
on_load callback.
"""
from __future__ import annotations

from typing import Callable, Optional

from engine.missions import MissionEntry, MissionRegistry
from engine.ui import UiPanel

_SKIP_EPISODE_LEVEL = {"Episode", "."}


class MissionPicker:
    def __init__(self, *,
                 registry: MissionRegistry,
                 on_load: Callable[[str], None],
                 on_cancel: Callable[[], None]):
        self._registry = registry
        self._on_load = on_load
        self._on_cancel = on_cancel
        self._panel: Optional[UiPanel] = None

    def is_open(self) -> bool:
        return self._panel is not None

    def open(self) -> None:
        if self._panel is not None:
            return
        panel = UiPanel(id="mission-picker", anchor="center",
                        width_vw=42.0, height_vh=72.0,
                        title="Load Mission")
        for family in self._registry.families:
            family_row = panel.collapsible(family.display_name,
                                           menu_level=1, expanded=False)
            for episode in family.episodes:
                skip_episode = (
                    len(family.episodes) == 1
                    and episode.dir_name in _SKIP_EPISODE_LEVEL
                )
                if skip_episode:
                    parent = family_row
                else:
                    parent = family_row.collapsible(
                        episode.display_name,
                        menu_level=2, expanded=False)
                for mission in episode.missions:
                    parent.button(
                        mission.display_name,
                        on_click=self._make_pick_callback(mission),
                    )
        panel.set_footer_button("Cancel", on_click=self._cancel)
        self._panel = panel

    def close(self) -> None:
        if self._panel is None:
            return
        self._panel.destroy()
        self._panel = None

    def handle_key_esc(self) -> None:
        if self.is_open():
            self._cancel()

    def _make_pick_callback(self, mission: MissionEntry):
        def _pick():
            self.close()
            self._on_load(mission.module_name)
        return _pick

    def _cancel(self) -> None:
        self.close()
        self._on_cancel()
