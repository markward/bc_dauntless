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
from engine.ui import bindings as _ui_bindings

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
        self._open: bool = False
        # Click handlers fire from inside RmlUi's event dispatch — tearing
        # the panel down synchronously crashes the renderer. Instead, the
        # callback stashes a deferred action here and drain() does the
        # actual close + on_load/on_cancel at a tick boundary.
        self._pending: Optional[tuple[str, Optional[str]]] = None

    def is_open(self) -> bool:
        return self._open

    def open(self) -> None:
        if self._panel is not None:
            _ui_bindings.set_panel_visible(self._panel.panel_id, True)
            self._open = True
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
        panel.set_footer_button("Cancel", on_click=self._queue_cancel)
        self._panel = panel
        self._open = True

    def close(self) -> None:
        # Hide rather than destroy. Destroying an RmlUi document that
        # recently dispatched a click is unsafe; keep the panel alive
        # and just hide it off-screen.
        if self._panel is None or not self._open:
            return
        _ui_bindings.set_panel_visible(self._panel.panel_id, False)
        self._open = False

    def destroy(self) -> None:
        """Tear down the picker entirely. Only called at host shutdown."""
        if self._panel is not None:
            self._panel.destroy()
            self._panel = None
        self._open = False

    def handle_key_esc(self) -> None:
        # ESC is polled from the host loop, not from an RmlUi callback,
        # so it's safe to close synchronously here.
        if self.is_open():
            self.close()
            self._on_cancel()

    def drain(self) -> None:
        """Process any deferred pick/cancel queued by a UI click.

        Call once per host tick. Closing the panel + invoking callbacks
        happens here, outside the RmlUi event dispatch, so the renderer
        can safely hide the document.
        """
        if self._pending is None:
            return
        action, arg = self._pending
        self._pending = None
        self.close()
        if action == "load" and arg is not None:
            self._on_load(arg)
        elif action == "cancel":
            self._on_cancel()

    def _make_pick_callback(self, mission: MissionEntry):
        def _pick():
            self._pending = ("load", mission.module_name)
        return _pick

    def _queue_cancel(self) -> None:
        self._pending = ("cancel", None)
