"""Developer Options panel — dev-only pause-menu modal with combat cheats.

Mirrors engine.ui.configuration_panel.ConfigurationPanel: a Panel
subclass pumped by PanelRegistry, rendered as a pause-menu modal that
reuses the configuration panel's cp-* CSS. A single "Combat" tab exposes
three toggles wired to engine.dev_combat_cheats. Dev-mode only —
constructed in host_loop.py inside ``if dev_mode.is_enabled():``.

Spec: docs/superpowers/specs/2026-06-08-developer-options-menu-design.md
"""
from __future__ import annotations

import json
from typing import List, Optional, Tuple

from engine.ui.panel import Panel
from engine import dev_combat_cheats as cheats
from engine import dev_light_preview as light_preview
from engine import renderer


class DeveloperOptionsPanel(Panel):
    # Controls that fire once instead of flipping a flag. They have no entry in
    # `settings` and dispatch under "action:" rather than "toggle:".
    _ACTION_CONTROLS = frozenset({"quick_repair", "normal_strength"})

    # Presets cycled through by the "normal_strength" action row: 0 = flat
    # (identical to disabled), 1 = as authored, 2/4 exaggerate for tuning.
    _NORMAL_STRENGTHS = (0.0, 0.5, 1.0, 2.0, 4.0)

    def __init__(self) -> None:
        super().__init__()
        self._tabs: List[Tuple[str, str]] = [("combat", "Combat"), ("lighting", "Lighting")]
        self._selected_tab = "combat"
        self._god_mode = cheats.god_mode_active()
        self._double_weapons = cheats.double_player_weapons_active()
        self._no_npc_shields = cheats.disable_npc_shields_active()
        self._disable_collisions = cheats.disable_collisions_active()
        self._systems_damaged = light_preview.systems_damaged_active()
        self._systems_disabled = light_preview.systems_disabled_active()
        self._normal_maps = True
        self._normal_flip_g = False
        self._normal_strength = 1.0
        self._visible = False
        self._focused = -1
        self._last_pushed: Optional[tuple] = None

    @property
    def name(self) -> str:
        return "developer-options"

    def is_open(self) -> bool:
        return self._visible

    def open(self) -> None:
        # Re-sync the local mirror from the cheats module so a reopened
        # panel reflects whatever the flags currently are.
        self._god_mode = cheats.god_mode_active()
        self._double_weapons = cheats.double_player_weapons_active()
        self._no_npc_shields = cheats.disable_npc_shields_active()
        self._disable_collisions = cheats.disable_collisions_active()
        self._systems_damaged = light_preview.systems_damaged_active()
        self._systems_disabled = light_preview.systems_disabled_active()
        self._visible = True

    def close(self) -> None:
        self._visible = False
        self._focused = -1

    def render_payload(self) -> Optional[str]:
        snapshot = (
            self._visible, tuple(self._tabs), self._selected_tab,
            self._focused, self._god_mode, self._double_weapons,
            self._no_npc_shields, self._disable_collisions,
            self._systems_damaged, self._systems_disabled,
            self._normal_maps, self._normal_flip_g, self._normal_strength,
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
            "settings": {
                "god_mode": self._god_mode,
                "double_weapons": self._double_weapons,
                "no_npc_shields": self._no_npc_shields,
                "disable_collisions": self._disable_collisions,
                "systems_damaged": self._systems_damaged,
                "systems_disabled": self._systems_disabled,
                "normal_maps": self._normal_maps,
                "normal_flip_g": self._normal_flip_g,
                "normal_strength": self._normal_strength,
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
        if action == "toggle:disable_collisions":
            new_val = not self._disable_collisions
            cheats.set_disable_collisions(new_val)
            self._disable_collisions = new_val
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
        """Ordered focusable list: the tab row then the combat controls."""
        out: list = [("tab", tid) for tid, _ in self._tabs]
        if self._selected_tab == "combat":
            out += [("ctrl", "god_mode"), ("ctrl", "double_weapons"),
                    ("ctrl", "no_npc_shields"), ("ctrl", "disable_collisions"),
                    ("ctrl", "quick_repair")]
        if self._selected_tab == "lighting":
            out += [("ctrl", "systems_damaged"), ("ctrl", "systems_disabled"),
                    ("ctrl", "normal_maps"), ("ctrl", "normal_flip_g"),
                    ("ctrl", "normal_strength")]
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
