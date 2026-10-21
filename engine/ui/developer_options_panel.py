"""Developer Options panel — dev-only pause-menu modal with combat cheats.

Mirrors engine.ui.configuration_panel.ConfigurationPanel: a Panel
subclass pumped by PanelRegistry, rendered as a pause-menu modal that
reuses the configuration panel's cp-* CSS. Six tabs: "Combat" (cheats
wired to engine.dev_combat_cheats, plus the Sensor Occlusion switch),
"Lighting" (forced glow states, normal-map tunables), "Environments"
(rock toggles), "Hull damage" (layered hull damage tuning rows, via
engine.dev_hull_damage_tuning), "Diagnostics" (the frame profiler, the performance
monitor overlay, the dial-group picker), and "Characters" (put any SDK character on the viewscreen, via
engine.dev_character_viewscreen). Dev-mode only — constructed in host_loop.py inside
``if dev_mode.is_enabled():``.

Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

from engine.ui.panel import Panel
from engine import dev_character_viewscreen as character_viewscreen
from engine import dev_combat_cheats as cheats
from engine import dev_dial_groups
from engine import dev_hull_damage_tuning as hull_damage_tuning
from engine import dev_light_preview as light_preview
from engine import dev_perf_monitor
from engine import host_io
from engine import renderer
from engine.appc import sensor_occlusion
from engine.rocks import catalogue as rock_catalogue
from engine import planet_geosphere
from engine import planet_atmosphere
from engine import planet_surface
from engine.planets import atmosphere as planet_atmosphere_catalogue
from engine.planets import surface as planet_surface_catalogue


def _minors_enabled() -> bool:
    """renderer.minors_enabled(), or True (the native default) when the
    renderer is unavailable -- this panel is constructed in headless tests."""
    try:
        return bool(renderer.minors_enabled())
    except Exception:
        return True


def _far_enabled() -> bool:
    """renderer.far_enabled(), or True (the native default) when the
    renderer is unavailable -- this panel is constructed in headless tests."""
    try:
        return bool(renderer.far_enabled())
    except Exception:
        return True


def _running_lights_enabled() -> bool:
    """renderer.running_lights_enabled(), or True (the native default) when
    the renderer is unavailable -- this panel is constructed in headless tests."""
    try:
        return bool(renderer.running_lights_enabled())
    except Exception:
        return True


def _rock_specks_enabled() -> bool:
    """renderer.rock_specks_enabled(), or True (the native default) when the
    renderer is unavailable -- this panel is constructed in headless tests."""
    try:
        return bool(renderer.rock_specks_enabled())
    except Exception:
        return True


def _rock_puffs_enabled() -> bool:
    """renderer.rock_puffs_enabled(), or True (the native default) when the
    renderer is unavailable -- this panel is constructed in headless tests."""
    try:
        return bool(renderer.rock_puffs_enabled())
    except Exception:
        return True


def _frame_profiler():
    """Imported lazily. engine.core.frame_profiler reaches the native timer
    through host_io, and this panel is constructed in tests that never build
    the extension module."""
    from engine.core import frame_profiler
    return frame_profiler


class DeveloperOptionsPanel(Panel):
    # Controls that fire once instead of flipping a flag. They have no entry in
    # `settings` and dispatch under "action:" rather than "toggle:".
    # The "Hull damage" rows are all actions except the interior toggle.
    _ACTION_CONTROLS = frozenset({"quick_repair", "normal_strength",
                                 "dial_group", "reload_atmospheres", "reload_surfaces",
                                 "bridge_debug_view"}) | hull_damage_tuning.ACTION_KEYS

    # Presets cycled through by the "normal_strength" action row: 0 = flat
    # (identical to disabled), 1 = as authored, 2/4 exaggerate for tuning.
    _NORMAL_STRENGTHS = (0.0, 0.5, 1.0, 2.0, 4.0)

    # Names cycled through by the "bridge_debug_view" action row, index ==
    # renderer.BridgeDebugView's int value (0 Off .. 11 Reflection layers).
    # 6-11 are the bridge-PBR debug views added alongside the PBR A/B switch.
    _BRIDGE_DEBUG_VIEWS = ("Off", "Normals", "Light Only", "AO Only",
                          "Triangle ID", "Mesh ID", "Roughness", "Metalness",
                          "Specular only", "Probe (mirror)", "Map normals",
                          "Reflection layers")

    def __init__(self) -> None:
        super().__init__()
        self._tabs: List[Tuple[str, str]] = [("combat", "Combat"),
                                             ("lighting", "Lighting"),
                                             ("environments", "Environments"),
                                             ("hull_damage", "Hull damage"),
                                             ("diagnostics", "Diagnostics"),
                                             ("characters", "Characters")]
        self._selected_tab = "combat"
        self._god_mode = cheats.god_mode_active()
        self._double_weapons = cheats.double_player_weapons_active()
        self._no_npc_shields = cheats.disable_npc_shields_active()
        self._disable_collisions = cheats.disable_collisions_active()
        self._sensor_occlusion = sensor_occlusion.enabled()
        self._systems_damaged = light_preview.systems_damaged_active()
        self._systems_disabled = light_preview.systems_disabled_active()
        self._profiler = _frame_profiler().is_enabled()
        self._normal_maps = True
        # Mirrors the native default in native/src/renderer/frame.cc
        # (dauntless_normal_map::g_flip_green): v runs downward in image
        # space, so flipping green is what makes a standard OpenGL-convention
        # (+Y up) authored map render correctly out of the box.
        self._normal_flip_g = True
        self._normal_strength = 1.0
        self._bridge_debug_view = 0
        # Developer-only A/B switch for bridge PBR (default ON, not
        # persisted -- no getter exists, so there is nothing to resync from
        # on open(), the same shape as _normal_maps above).
        self._bridge_pbr = True
        self._rock_catalogue = rock_catalogue.enabled()
        self._planet_geosphere = planet_geosphere.enabled()
        self._planet_atmosphere = planet_atmosphere.enabled()
        self._planet_surface = planet_surface.enabled()
        # No native getter for the debug tint (set_planet_detail_debug is
        # write-only) -- defaults off like every other dev A/B toggle.
        self._surface_debug = False
        self._minor_rocks = _minors_enabled()
        self._far_tier = _far_enabled()
        self._rock_specks = _rock_specks_enabled()
        self._running_lights = _running_lights_enabled()
        self._rock_puffs = _rock_puffs_enabled()
        self._dial_group = dev_dial_groups.active() or "nebula"
        # Read live, never assumed off: DAUNTLESS_PROFILE_FRAMES enables the
        # profiler at startup, so a hard-coded False would show OFF while it
        # was running.
        self._profiler = _frame_profiler().is_enabled()
        self._perf_monitor = dev_perf_monitor.enabled()
        # The character the Characters tab last put on the viewscreen, or
        # None. Only what this panel did: a mission can switch the viewscreen
        # behind its back, so this labels the row, it is not a live readout.
        self._viewscreen_character: Optional[str] = None
        self._visible = False
        self._focused = -1
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "developer-options"

    def is_open(self) -> bool:
        return self._visible

    def bridge_debug_view_names(self) -> List[str]:
        """The "Bridge Debug View" row's cycle list, in index order."""
        return list(self._BRIDGE_DEBUG_VIEWS)

    def open(self) -> None:
        # Re-sync the local mirror from the cheats module so a reopened
        # panel reflects whatever the flags currently are.
        self._god_mode = cheats.god_mode_active()
        self._double_weapons = cheats.double_player_weapons_active()
        self._no_npc_shields = cheats.disable_npc_shields_active()
        self._disable_collisions = cheats.disable_collisions_active()
        self._sensor_occlusion = sensor_occlusion.enabled()
        self._systems_damaged = light_preview.systems_damaged_active()
        self._systems_disabled = light_preview.systems_disabled_active()
        self._dial_group = dev_dial_groups.active() or "nebula"
        self._minor_rocks = _minors_enabled()
        self._far_tier = _far_enabled()
        self._rock_specks = _rock_specks_enabled()
        self._running_lights = _running_lights_enabled()
        self._rock_puffs = _rock_puffs_enabled()
        self._planet_geosphere = planet_geosphere.enabled()
        self._planet_atmosphere = planet_atmosphere.enabled()
        self._planet_surface = planet_surface.enabled()
        # The profiler can be enabled behind the panel's back by
        # DAUNTLESS_PROFILE_FRAMES at startup, so re-read rather than trust
        # the mirror -- otherwise the row shows OFF while it is reporting.
        self._profiler = _frame_profiler().is_enabled()
        self._perf_monitor = dev_perf_monitor.enabled()
        self.visible = True

    def close(self) -> None:
        self.visible = False
        self._focused = -1

    def render_payload(self) -> Optional[str]:
        # EVERY setting the payload reports must appear here. A setting left
        # out toggles INVISIBLY: the flag flips and the underlying feature
        # really does change, but the snapshot compares equal, render_payload
        # returns None, and the button keeps showing its old state forever.
        # _profiler shipped missing from this tuple and did exactly that.
        # test_every_setting_is_in_the_render_snapshot now guards the whole set.
        # The "Hull damage" rows are read LIVE (the / L O dial keys change
        # the same values behind the panel's back), so their values are part
        # of the snapshot too. Read only while visible; nothing is mutated.
        hull_rows = hull_damage_tuning.rows() if self._visible else []
        hull_snapshot = tuple((r["key"], r["value"]) for r in hull_rows)
        snapshot = (
            self._visible, tuple(self._tabs), self._selected_tab,
            self._focused, self._god_mode, self._double_weapons,
            self._no_npc_shields, self._disable_collisions,
            self._sensor_occlusion,
            self._systems_damaged, self._systems_disabled,
            self._normal_maps, self._normal_flip_g, self._normal_strength,
            self._bridge_pbr, self._bridge_debug_view,
            self._profiler, self._perf_monitor,
            self._rock_catalogue, self._dial_group,
            self._minor_rocks, self._far_tier,
            self._rock_specks, self._rock_puffs, self._running_lights,
            self._planet_geosphere, self._planet_atmosphere,
            self._planet_surface, self._surface_debug,
            self._viewscreen_character, hull_snapshot,
        )
        if snapshot == self._last_pushed:
            return None
        self._last_pushed = snapshot
        if not self._visible:
            return "setDeveloperOptions(" + json.dumps({"visible": False}) + ");"
        payload = {
            "visible": True,
            "tabs": [{"id": tid, "label": label} for tid, label in self._tabs],
            "selected_tab": self._selected_tab,
            "focused": self._focused,
            # Read only when the tab is showing: building the catalogue walks
            # the SDK tree (cached after the first time).
            "characters": ([e.name for e in character_viewscreen.catalogue()]
                           if self._selected_tab == "characters" else []),
            "viewscreen_character": self._viewscreen_character,
            "hull_damage": hull_rows,
            "settings": {
                "god_mode": self._god_mode,
                "double_weapons": self._double_weapons,
                "no_npc_shields": self._no_npc_shields,
                "disable_collisions": self._disable_collisions,
                "sensor_occlusion": self._sensor_occlusion,
                "systems_damaged": self._systems_damaged,
                "systems_disabled": self._systems_disabled,
                "normal_maps": self._normal_maps,
                "normal_flip_g": self._normal_flip_g,
                "normal_strength": self._normal_strength,
                "bridge_pbr": self._bridge_pbr,
                "bridge_debug_view": self._BRIDGE_DEBUG_VIEWS[self._bridge_debug_view],
                "profiler": self._profiler,
                "perf_monitor": self._perf_monitor,
                "rock_catalogue": self._rock_catalogue,
                "dial_group": self._dial_group,
                "minor_rocks": self._minor_rocks,
                "far_tier": self._far_tier,
                "rock_specks": self._rock_specks,
                "running_lights": self._running_lights,
                "rock_puffs": self._rock_puffs,
                "planet_geosphere": self._planet_geosphere,
                "planet_atmosphere": self._planet_atmosphere,
                "planet_surface": self._planet_surface,
                "surface_debug": self._surface_debug,
            },
        }
        return "setDeveloperOptions(" + json.dumps(payload) + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        # Setter-before-local-write mirrors ConfigurationPanel.dispatch_event:
        # if the cheats setter ever grows validation and raises, the local
        # mirror stays consistent with what the renderer last saw.
        if action == "toggle:god_mode":
            new_val = not self._god_mode
            cheats.set_god_mode(new_val)
            self._god_mode = new_val
            return True
        if action == "toggle:double_weapons":
            new_val = not self._double_weapons
            cheats.set_double_player_weapons(new_val)
            self._double_weapons = new_val
            return True
        if action == "toggle:no_npc_shields":
            new_val = not self._no_npc_shields
            cheats.set_disable_npc_shields(new_val)
            self._no_npc_shields = new_val
            return True
        if action == "toggle:profiler":
            # Drives the REAL profiler (both halves — set_enabled fans out to
            # the native timer through host_io), not a local mirror. This
            # replaced the backtick keybinding: backtick sits next to Esc and
            # once on the profiler printed a full report every ~2 s forever,
            # so a stray keypress buried every other diagnostic.
            new_val = not self._profiler
            _frame_profiler().set_enabled(new_val)
            self._profiler = new_val
            return True
        if action == "toggle:perf_monitor":
            new_val = not self._perf_monitor
            dev_perf_monitor.set_enabled(new_val)
            self._perf_monitor = new_val
            return True
        if action == "toggle:disable_collisions":
            new_val = not self._disable_collisions
            cheats.set_disable_collisions(new_val)
            self._disable_collisions = new_val
            return True
        if action == "toggle:sensor_occlusion":
            new_val = not self._sensor_occlusion
            sensor_occlusion.set_enabled(new_val)
            self._sensor_occlusion = new_val
            return True
        if action == "toggle:systems_damaged":
            light_preview.set_systems_damaged(not self._systems_damaged)
            self._systems_damaged = light_preview.systems_damaged_active()
            self._systems_disabled = light_preview.systems_disabled_active()
            return True
        if action == "toggle:systems_disabled":
            light_preview.set_systems_disabled(not self._systems_disabled)
            self._systems_damaged = light_preview.systems_damaged_active()
            self._systems_disabled = light_preview.systems_disabled_active()
            return True
        if action == "toggle:running_lights":
            renderer.running_lights_set_enabled(not self._running_lights)
            self._running_lights = not self._running_lights
            return True
        if action == "toggle:normal_maps":
            renderer.set_normal_map_enabled(not self._normal_maps)
            self._normal_maps = not self._normal_maps
            return True
        if action == "toggle:normal_flip_g":
            renderer.set_normal_map_flip_green(not self._normal_flip_g)
            self._normal_flip_g = not self._normal_flip_g
            return True
        if action == "action:normal_strength":
            presets = self._NORMAL_STRENGTHS
            try:
                idx = presets.index(self._normal_strength)
            except ValueError:
                idx = presets.index(1.0)
            nxt = presets[(idx + 1) % len(presets)]
            renderer.set_normal_map_strength(nxt)
            self._normal_strength = nxt
            return True
        if action == "toggle:bridge_pbr":
            new_val = not self._bridge_pbr
            host_io.set_bridge_pbr_enabled(new_val)
            self._bridge_pbr = new_val
            return True
        if action == "action:bridge_debug_view":
            nxt = (self._bridge_debug_view + 1) % len(self._BRIDGE_DEBUG_VIEWS)
            renderer.set_bridge_debug_view(nxt)
            self._bridge_debug_view = nxt
            return True
        if action == "toggle:rock_catalogue":
            rock_catalogue.set_enabled(not self._rock_catalogue)
            self._rock_catalogue = not self._rock_catalogue
            return True
        if action == "toggle:planet_geosphere":
            planet_geosphere.set_enabled(not self._planet_geosphere)
            self._planet_geosphere = not self._planet_geosphere
            return True
        if action == "toggle:planet_atmosphere":
            planet_atmosphere.set_enabled(not self._planet_atmosphere)
            self._planet_atmosphere = not self._planet_atmosphere
            return True
        if action == "toggle:planet_surface":
            planet_surface.set_enabled(not self._planet_surface)
            self._planet_surface = not self._planet_surface
            return True
        if action == "toggle:surface_debug":
            new_val = not self._surface_debug
            renderer.set_planet_detail_debug(new_val)
            self._surface_debug = new_val
            return True
        if action == "toggle:minor_rocks":
            renderer.minors_set_enabled(not self._minor_rocks)
            self._minor_rocks = not self._minor_rocks
            return True
        if action == "toggle:far_tier":
            renderer.far_set_enabled(not self._far_tier)
            self._far_tier = not self._far_tier
            return True
        if action == "toggle:rock_specks":
            renderer.rock_specks_set_enabled(not self._rock_specks)
            self._rock_specks = not self._rock_specks
            return True
        if action == "toggle:rock_puffs":
            renderer.rock_puffs_set_enabled(not self._rock_puffs)
            self._rock_puffs = not self._rock_puffs
            return True
        if action.startswith(("action:hull_", "toggle:hull_")):
            # Developer Options -> "Hull damage" (dev-only; refuses otherwise).
            return hull_damage_tuning.dispatch(action)
        if action == "action:dial_group":
            self._dial_group = dev_dial_groups.cycle_active() or "nebula"
            return True
        if action == "action:reload_atmospheres":
            # One-shot ACTION, not a toggle: no local flag, no render_payload
            # entry (mirrors action:quick_repair / action:dial_group). Drops
            # the catalogue memo + warning set so the NEXT read of
            # atmospheres.json picks up edits made while the game is running,
            # then re-pushes every live planet so already-realized ones take
            # the fresh values too (and shed any dial override).
            import sys
            from engine.planets import atmosphere_dials
            planet_atmosphere_catalogue.reload()
            atmosphere_dials.repush_live()
            print("[atmosphere] catalogue reloaded", file=sys.stderr)
            return True
        if action == "action:reload_surfaces":
            # One-shot ACTION (mirrors action:reload_atmospheres). The two
            # catalogue blocks ("atmosphere" and "surface") live in the SAME
            # atmospheres.json, read through ONE shared file memo -- but
            # `surface.reload()` refreshes that memo via
            # `atmosphere.reload_file()` (memo-only), NOT the full
            # `atmosphere.reload()`, so this action picks up edited surface
            # fields (and drops this group's own overrides) WITHOUT also
            # dropping the "atmosphere" dial group's live tuning (fix round
            # 1, I1). Then re-push every live planet.
            import sys
            from engine.planets import surface_dials
            planet_surface_catalogue.reload()
            surface_dials.repush_live()
            print("[surface] catalogue reloaded", file=sys.stderr)
            return True
        if action.startswith("action:show_character:"):
            entry = character_viewscreen.find(action[len("action:show_character:"):])
            if entry is None:
                return False
            try:
                shown = character_viewscreen.show(entry)
            except Exception:
                # A developer tool: say what broke rather than leave the
                # button silently doing nothing.
                import sys
                import traceback
                print("[dev-character-viewscreen] showing %s failed:" % entry.name,
                      file=sys.stderr)
                traceback.print_exc()
                shown = False
            self._viewscreen_character = entry.name if shown else None
            return True
        if action == "action:viewscreen_off":
            character_viewscreen.hide()
            self._viewscreen_character = None
            return True
        if action == "action:quick_repair":
            # One-shot ACTION, not a toggle: nothing to mirror in state, so
            # there is no local flag and no render_payload entry. Lived on the
            # F9 dev keybinding until BC's ET_INPUT_TOGGLE_CINEMATIC_MODE
            # needed that key back.
            import App
            from engine.appc.subsystems import repair_ship_fully
            repair_ship_fully(App.Game_GetCurrentPlayer())
            return True
        if action.startswith("tab:"):
            tab_id = action[len("tab:"):]
            if any(tid == tab_id for tid, _ in self._tabs):
                self._selected_tab = tab_id
                return True
            return False
        return False

    def invalidate(self) -> None:
        self._last_pushed = None

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    def _focusables(self) -> list:
        """Ordered focusable list: the tab row then the selected tab's controls."""
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "combat":
            out += [("ctrl", "god_mode"), ("ctrl", "double_weapons"),
                    ("ctrl", "no_npc_shields"), ("ctrl", "disable_collisions"),
                    ("ctrl", "sensor_occlusion"), ("ctrl", "quick_repair")]
        if self._selected_tab == "lighting":
            out += [("ctrl", "systems_damaged"), ("ctrl", "systems_disabled"),
                    ("ctrl", "running_lights"),
                    ("ctrl", "normal_maps"), ("ctrl", "normal_flip_g"),
                    ("ctrl", "normal_strength"), ("ctrl", "bridge_pbr"),
                    ("ctrl", "bridge_debug_view")]
        if self._selected_tab == "environments":
            out += [("ctrl", "rock_catalogue"), ("ctrl", "minor_rocks"),
                    ("ctrl", "far_tier"), ("ctrl", "rock_specks"),
                    ("ctrl", "rock_puffs"), ("ctrl", "planet_geosphere"),
                    ("ctrl", "planet_atmosphere"),
                    ("ctrl", "reload_atmospheres"),
                    ("ctrl", "planet_surface"), ("ctrl", "surface_debug"),
                    ("ctrl", "reload_surfaces")]
        if self._selected_tab == "hull_damage":
            out += [("ctrl", r["key"]) for r in hull_damage_tuning.rows()]
        if self._selected_tab == "diagnostics":
            out += [("ctrl", "profiler"), ("ctrl", "perf_monitor"),
                    ("ctrl", "dial_group")]
        return out

    def handle_input(self, h) -> None:
        """Poll up/down to move focus and Space/Enter to activate. Mirrors
        ConfigurationPanel.handle_input; optional keys degrade silently."""
        if not self._visible:
            return
        keys = h.keys
        focusables = self._focusables()
        if not focusables:
            return
        if h.key_pressed(keys.KEY_DOWN):
            self._focused = 0 if self._focused < 0 else (self._focused + 1) % len(focusables)
        if h.key_pressed(keys.KEY_UP):
            self._focused = (len(focusables) - 1) if self._focused < 0 \
                else (self._focused - 1) % len(focusables)
        kind, target = focusables[self._focused] if self._focused >= 0 else (None, None)
        k_space = getattr(keys, "KEY_SPACE", None)
        k_enter = getattr(keys, "KEY_ENTER", None)

        def _pressed(code):
            return code is not None and h.key_pressed(code)

        activate = _pressed(k_space) or _pressed(k_enter)
        if activate and kind == "ctrl":
            verb = "action:" if target in self._ACTION_CONTROLS else "toggle:"
            self.dispatch_event(verb + target)
        elif activate and kind == "tab":
            self.dispatch_event("tab:" + target)
