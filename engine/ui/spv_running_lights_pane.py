"""The Ship Property Viewer's running lights (spec docs/superpowers/specs/
2026-10-22-spv-running-lights-design.md S3.1, S3.2, S3.6, S5).

A mixin for `ShipPropertyViewerPanel`, like `DecalsPaneMixin`: the panel
owns the undo stack, Save and the payload; this module owns the light
staging model and everything kind-specific about it (the list rows, the
`rl/*` actions, the Save edit tuples), so the panel never branches on it.

Three layers, each `name -> canonical spec` (see
`running_light_editor.spec_from_property`):

- `_rl_baked`: the ship's placed `BlinkingLightProperty` entries,
  snapshotted at `open()` in property-set order.
- `_saved_running_light`: lights saved THIS session (the file write only
  reaches the live properties on the next ship build). Survives close/
  reopen of the same ship; dropped with the panel's other saved overlays.
- `_pending_running_light`: staged, unsaved edits.

A `None` spec in saved/pending removes the light. The effective list is
baked, then saved, then pending, in insertion order (an added light goes
last). Lights are never descriptors, never pins and never targetable.
"""
from __future__ import annotations

import json
from typing import List, Optional

from engine.ui import running_light_editor

RL_GROUP_NAME = "Running Lights"
RL_ADD_NAME = "+ Add"
RL_TARGET_KIND = "running_light"
_EDIT_VERB = "__running_light__"


class RunningLightsPaneMixin:
    """Running-light staging, rows and actions. See the module docstring."""

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------
    def _rl_reset_state(self) -> None:
        """Session state: reset every open/close. The saved overlay is not
        session state (see `_rl_clear_saved`)."""
        self._rl_baked: dict = {}
        self._pending_running_light: dict = {}
        self._rl_selected: Optional[str] = None
        self._rl_group_expanded: bool = False

    def _rl_clear_saved(self) -> None:
        self._saved_running_light: dict = {}

    def _rl_load(self, ship) -> None:
        """Snapshot `ship`'s placed lights as the baked layer."""
        self._rl_baked = {}
        if ship is None:
            return
        from engine.appc import running_lights
        try:
            for prop in running_lights.light_properties(ship):
                spec = running_light_editor.spec_from_property(prop)
                self._rl_baked[spec["name"]] = spec
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv running lights load", e)
            self._rl_baked = {}

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------
    def _rl_effective(self) -> List[dict]:
        merged = dict(self._rl_baked)
        for layer in (self._saved_running_light, self._pending_running_light):
            for name, spec in layer.items():
                if spec is None:
                    merged.pop(name, None)
                else:
                    merged[name] = spec
        return list(merged.values())

    def _rl_names(self) -> set:
        return {spec["name"] for spec in self._rl_effective()}

    def _rl_spec(self, name) -> Optional[dict]:
        for spec in self._rl_effective():
            if spec["name"] == name:
                return spec
        return None

    def _rl_stage(self, name, spec) -> None:
        """Stage `spec` (a FULL canonical spec) for light `name`, or None to
        remove it. Removing a light that exists only as a pending add drops
        the add instead: there is nothing in the file to remove."""
        if (spec is None and name not in self._rl_baked
                and name not in self._saved_running_light):
            self._pending_running_light.pop(name, None)
        else:
            self._pending_running_light[name] = (
                None if spec is None else dict(spec))
        if self._rl_selected is not None and self._rl_spec(self._rl_selected) is None:
            self._rl_selected = None
        self._last_pushed = None

    def _rl_dirty_names(self) -> List[str]:
        return list(self._pending_running_light)

    def _rl_save_edits(self) -> list:
        return [(name, _EDIT_VERB, {"spec": spec,
                                    "new": name not in self._rl_baked})
                for name, spec in self._pending_running_light.items()]

    def _rl_commit_saved(self) -> None:
        """A successful Save: the pending edits become the saved overlay."""
        self._saved_running_light.update(self._pending_running_light)
        self._pending_running_light = {}

    def _rl_snapshot(self) -> dict:
        return {name: (None if spec is None else dict(spec))
                for name, spec in self._pending_running_light.items()}

    def _rl_restore(self, pending: dict) -> None:
        self._pending_running_light = {
            name: (None if spec is None else dict(spec))
            for name, spec in pending.items()}
        if self._rl_selected is not None and self._rl_spec(self._rl_selected) is None:
            self._rl_selected = None

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _rl_target_key(self):
        """The transform-target key for the selected light, or None."""
        if self._rl_selected is None:
            return None
        return (RL_TARGET_KIND, self._rl_selected)

    def _rl_clear_selection(self) -> None:
        self._rl_selected = None

    def _rl_yield_to_other_selection(self) -> None:
        """Drop the light selection when anything else is selected. Decided
        by STATE, not by which action ran: many actions select as a side
        effect (`add_light:` selects the new volume, `add_emitter:` the new
        emitter, every part add its new node), and `rl/select` clears all
        of these, so any one being set means it was selected later."""
        if self._rl_selected is None:
            return
        from engine.ui import ship_property_viewer as _spv
        if (self.selected_index is not None
                or self._selected_light_index is not None
                or self._selected_emitter is not None
                or _spv.selected_part_node() is not None
                or _spv.selected_model_part() is not None
                or self._decal_selected is not None):
            self._rl_selected = None

    # ------------------------------------------------------------------
    # Rows / payload
    # ------------------------------------------------------------------
    def _rl_rows(self) -> List[dict]:
        rows: List[dict] = []
        lights = self._rl_effective()
        if lights:
            rows.append({
                "kind": "rl_group", "name": RL_GROUP_NAME,
                "expanded": self._rl_group_expanded,
                "children": [{
                    "kind": RL_TARGET_KIND, "name": spec["name"],
                    "spec": dict(spec),
                    "dirty": spec["name"] in self._pending_running_light,
                    "chosen": spec["name"] == self._rl_selected,
                } for spec in lights]})
        rows.append({"kind": "rl_add", "name": RL_ADD_NAME})
        return rows

    def _rl_physical_entries(self, baked_parents: dict) -> List[dict]:
        """Physical-tab entries for every effective light; `baked_parents`
        maps a light name to its open-time `GetPhysicalParent()`."""
        return [{"key": "light:" + spec["name"], "name": spec["name"],
                 "kind": RL_TARGET_KIND, "index": None,
                 "baked": baked_parents.get(spec["name"]),
                 "point": tuple(spec["position"])}
                for spec in self._rl_effective()]

    def _rl_state_key(self) -> tuple:
        return (tuple(tuple(sorted(s.items())) for s in self._rl_effective()),
                tuple(self._pending_running_light),
                self._rl_selected, self._rl_group_expanded)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _dispatch_rl_action(self, action: str) -> bool:
        """`rl/select:{"name": ...}` and `rl/toggle_group`."""
        verb, _, raw = action[len("rl/"):].partition(":")
        if verb == "toggle_group":
            self._rl_group_expanded = not self._rl_group_expanded
            self._last_pushed = None
            return True
        if verb == "select":
            try:
                arg = json.loads(raw)
            except ValueError:
                return False
            name = arg.get("name") if isinstance(arg, dict) else None
            if not isinstance(name, str) or self._rl_spec(name) is None:
                return False
            self._rl_selected = name
            self.selected_index = None
            self._selected_light_index = None
            self._selected_emitter = None
            self._decal_selected = None
            self._decal_reposition = False
            from engine.ui import ship_property_viewer as _spv
            _spv.select_model_part(None, self._model_part_nodes)
            _spv.select_part_node(None, None)
            self._last_pushed = None
            return True
        return False
