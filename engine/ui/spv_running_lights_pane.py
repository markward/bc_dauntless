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
from engine.ui.spv_decals_pane import MISS_HINT, instance_scale

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
        # Every non-light template name in the ship's property set (ship
        # property, object emitters, positions, ...), snapshotted at open.
        self._rl_template_names: set = set()
        self._pending_running_light: dict = {}
        self._rl_selected: Optional[str] = None
        self._rl_group_expanded: bool = False
        # A validated spec awaiting its hull click (rl/place_begin), and the
        # last refusal's readable reason.
        self._rl_placing: Optional[dict] = None
        self._rl_error: Optional[str] = None

    def _rl_clear_saved(self) -> None:
        self._saved_running_light: dict = {}

    def _rl_load(self, ship) -> None:
        """Snapshot `ship`'s placed lights as the baked layer, and the names
        of every other template in its property set."""
        self._rl_baked = {}
        self._rl_template_names = set()
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
        try:
            names = {prop.GetName()
                     for prop in ship.GetPropertySet().GetPropertyList()}
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv running lights template names", e)
            names = set()
        # A baked light's name is the effective layer's to answer: a light
        # staged for removal frees its name.
        self._rl_template_names = names - set(self._rl_baked)

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

    def _rl_taken_names(self) -> set:
        """Every name a new light may not take: the effective lights, every
        descriptor, every model part and every other template in the ship's
        property set (the ship property, object emitters, positions). All
        templates share one `FindByName` namespace, so a light named "Hull"
        would shadow the hull, and one named "Shuttle Bay" would replace the
        Galaxy's shuttle launcher on Save."""
        names = self._rl_names()
        names |= {d.get("name") for d in self._descriptors}
        names |= self._model_part_names()
        names |= self._rl_template_names
        names.discard(None)
        return names

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
        # Not only dispatch_event syncs: a gizmo drag stages from
        # `_handle_gizmo_input`. Cheap -- it pushes only on a change.
        self._rl_sync_preview()

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
    # Live preview (spec S3.5)
    # ------------------------------------------------------------------
    # The last pushed (iid, tuple list) and the (ship, iid) it went to. Not
    # in `_rl_reset_state`: close() must still see them to restore.
    _rl_last_preview = None
    _rl_preview_target = None

    def _rl_sync_preview(self) -> None:
        """Push the effective lights to native for the SPV instance when
        visible, the iid resolves and the list changed since the last push.
        An empty effective list sends [] (native drops the ship)."""
        if not self._visible:
            return
        iid = self._decal_iid()
        if iid is None:
            return
        lights = [tuple(s["position"]) + tuple(s["color"])
                  + (s["radius"], s["period"], s["duration"])
                  for s in self._rl_effective()]
        key = (iid, lights)
        if key == self._rl_last_preview:
            return
        if (self._rl_preview_target is not None
                and self._rl_preview_target[1] != iid):
            # The instance changed under a live preview (a respawn): give
            # the old one its spawn lights back first.
            self._rl_restore_preview()
        ship = self._ship_getter()
        from engine import renderer
        from engine.appc import running_lights
        try:
            renderer.set_running_lights(iid, lights,
                                         running_lights.phase_for(ship))
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv running light preview", e)
            return
        self._rl_last_preview = key
        self._rl_preview_target = (ship, iid)

    def running_light_preview_iids(self) -> tuple:
        """The instance(s) this SPV is previewing running lights on: the
        host skips their articulated re-send while the preview owns them."""
        if self._rl_preview_target is None:
            return ()
        return (self._rl_preview_target[1],)

    def on_mission_swap(self) -> None:
        """The swap destroys the previewed instance: forget the preview
        WITHOUT the restore callback (its iid is dead, or reused by a new
        ship), then the Decals pane's own swap handling."""
        self._rl_last_preview = None
        self._rl_preview_target = None
        super().on_mission_swap()

    def _rl_restore_preview(self) -> None:
        """Hand (ship, iid) of a preview pushed this session to the injected
        `on_running_lights_closed` callback, then forget the preview."""
        target = self._rl_preview_target
        self._rl_last_preview = None
        self._rl_preview_target = None
        if target is None or self._on_running_lights_closed is None:
            return
        try:
            self._on_running_lights_closed(*target)
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv running light restore", e)

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------
    def _rl_target_key(self):
        """The transform-target key for the selected light, or None."""
        if self._rl_selected is None:
            return None
        return (RL_TARGET_KIND, self._rl_selected)

    def _rl_pipette_source(self, action: str):
        """The pipette source key an armed `rl/select:{"name"}` picks, or
        None for bad JSON / an unknown light (the pick is still consumed)."""
        name = _select_name(action)
        if name is None or self._rl_spec(name) is None:
            return None
        return (RL_TARGET_KIND, name)

    def _rl_clear_selection(self) -> None:
        self._rl_selected = None

    def _rl_select(self, name) -> None:
        """Select light `name`, dropping every other selection."""
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

    def _rl_placing_context(self) -> tuple:
        """Every selection and tool a viewport click answers to. Placing
        survives an action only while this is unchanged."""
        from engine.ui import ship_property_viewer as _spv
        return (self.selected_index, self._selected_light_index,
                self._selected_emitter, self._rl_selected,
                self._decal_selected, self._decals_active, self._decal_adding,
                _spv.selected_model_part(), _spv.selected_part_node(),
                self.active_tool, self._systems_tab, self._pipette_armed)

    def _rl_yield_placing(self, before: tuple) -> None:
        """Leave placing when an action changed the selection or the tool
        (`before` = `_rl_placing_context()` ahead of it): the next viewport
        click must not place a light behind the user's back. By STATE, like
        `_rl_yield_to_other_selection`, so chrome (`overlay:` -- the Add
        modal closes right after `rl/place_begin`) and view toggles keep
        placing."""
        if before != self._rl_placing_context():
            self._rl_cancel_placing()

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
                self._rl_selected, self._rl_group_expanded,
                None if self._rl_placing is None else self._rl_placing["name"],
                self._rl_error)

    def _rl_payload(self) -> dict:
        """The payload's "running_lights" block: placing state, the last
        refusal, and the Add form's next name, defaults and ranges."""
        rle = running_light_editor
        placing = (None if self._rl_placing is None
                   else self._rl_placing["name"])
        return {
            "placing": placing,
            "error": self._rl_error,
            "hint": (None if placing is None else
                     "Click the hull to place %s · Esc cancels" % placing),
            "next_name": rle.default_name(self._rl_taken_names()),
            "defaults": {"color": list(rle.DEFAULT_COLOR),
                         "radius": rle.DEFAULT_RADIUS,
                         "period": rle.DEFAULT_PERIOD,
                         "duration": rle.DEFAULT_DURATION},
            "ranges": {"radius": list(rle.RADIUS_RANGE),
                       "period": list(rle.PERIOD_RANGE),
                       "duration_min": rle.DURATION_MIN},
        }

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------
    def _dispatch_rl_action(self, action: str) -> bool:
        """`rl/select`, `rl/toggle_group`, `rl/place_begin`, `rl/place_cancel`,
        `rl/edit` and `rl/remove` (JSON arguments after the colon)."""
        verb = action[len("rl/"):].partition(":")[0]
        if verb == "toggle_group":
            self._rl_group_expanded = not self._rl_group_expanded
            self._last_pushed = None
            return True
        if verb == "select":
            name = _select_name(action)
            if name is None or self._rl_spec(name) is None:
                return False
            self._rl_select(name)
            # Even the row already selected: a row click ends placing.
            self._rl_cancel_placing()
            return True
        if verb == "place_begin":
            return self._rl_place_begin(action)
        if verb == "place_cancel":
            self._rl_cancel_placing()
            self._rl_error = None
            return True
        if verb == "edit":
            return self._rl_edit(action)
        if verb == "remove":
            name = _select_name(action)
            if name is None or self._rl_spec(name) is None:
                return False
            self._rl_stage(name, None)
            # A staged parent for a removed light would be written onto a
            # template that no longer exists.
            self._pending_physical.pop(name, None)
            if self._rl_selected == name:
                self._rl_selected = None
            return True
        return False

    def _rl_refuse(self, message: str) -> bool:
        self._rl_error = message
        self._last_pushed = None
        return False

    def _rl_validate(self, spec, taken) -> Optional[dict]:
        """`validate_spec`, with every refusal -- a bad value, or a malformed
        CEF payload (missing key, wrong shape) -- as a readable `_rl_error`
        and None: a payload must never raise out of dispatch."""
        if not isinstance(spec, dict):
            self._rl_refuse("Malformed light spec")
            return None
        try:
            return running_light_editor.validate_spec(spec, taken)
        except ValueError as e:
            self._rl_refuse(str(e))
        except KeyError as e:
            self._rl_refuse("Malformed light spec: missing %s" % e)
        except TypeError:
            self._rl_refuse("Malformed light spec")
        return None

    def _rl_place_begin(self, action: str) -> bool:
        """Arm placing with a validated spec. Not an edit: no undo entry.
        The click decides the position, so the spec need not carry one."""
        spec = _json_arg(action)
        if isinstance(spec, dict):
            spec = dict({"position": (0.0, 0.0, 0.0)}, **spec)
        valid = self._rl_validate(spec, self._rl_taken_names())
        if valid is None:
            return False
        self._rl_placing = valid
        self._rl_error = None
        self._last_pushed = None
        return True

    def _rl_edit(self, action: str) -> bool:
        """Restage light `name` from `spec`; the name is fixed."""
        arg = _json_arg(action)
        name = arg.get("name") if isinstance(arg, dict) else None
        if not isinstance(name, str) or self._rl_spec(name) is None:
            return self._rl_refuse("No running light to edit")
        spec = arg.get("spec")
        if isinstance(spec, dict):
            spec = dict(spec, name=name)
        valid = self._rl_validate(spec, self._rl_taken_names() - {name})
        if valid is None:
            return False
        self._rl_stage(name, valid)
        self._rl_error = None
        return True

    # ------------------------------------------------------------------
    # Placing (a viewport click while armed)
    # ------------------------------------------------------------------
    def _rl_cancel_placing(self) -> bool:
        """Esc while placing cancels it. True when it was placing."""
        if self._rl_placing is None:
            return False
        self._rl_placing = None
        self._rl_error = None
        self._last_pushed = None
        return True

    def _rl_click(self, x, y, viewport) -> bool:
        """A viewport click. False when not placing (the click falls
        through); otherwise it is consumed. A miss keeps placing with the
        hint. A hit stages the light at the hit -- the NIF-unit body point
        scaled to unscaled GU, lifted off the hull along the normal by the
        light's drawn size -- selects it and, on a rigged part's mesh,
        stages that part as its physical parent. Refused while mount
        editing is locked: a posed rig would record the position wrong."""
        if self._rl_placing is None:
            return False
        self._last_pushed = None
        if not self._mount_editing_enabled():
            self._rl_error = (self._mount_lock_state_and_reason()[1]
                              or "Mount editing is locked")
            return True
        before = self._snapshot_pending()
        hit = self._decal_hull_hit(x, y, viewport)
        if hit is None:
            self._rl_error = MISS_HINT
            return True
        pb, nb, mesh = hit
        from engine.appc import running_light_dials
        spec = dict(self._rl_placing)
        scale = instance_scale(self._ship_getter())
        lift = running_light_dials.current()["size_gu_per_radius"] * spec["radius"]
        spec["position"] = tuple(pb[k] * scale + nb[k] * lift for k in range(3))
        name = spec["name"]
        self._rl_stage(name, spec)
        part = self._rl_part_of_mesh(mesh)
        if part is not None:
            self._pending_physical[name] = part
        self._rl_placing = None
        self._rl_error = None
        self._rl_select(name)
        if before != self._snapshot_pending():
            self._undo_stack.append(before)
        self._physical_sync_preview()
        self._rl_sync_preview()
        return True

    def _rl_part_of_mesh(self, mesh) -> Optional[str]:
        """The articulated part mesh `mesh` hangs under (the nearest one in
        its root-to-leaf node chain), or None off the parts / unknown."""
        if not self._decal_shape_of_mesh(mesh):
            return None
        try:
            entry = next((m for m in self._decal_meshes(self._decal_iid())
                          if m.get("mesh") == mesh), None)
            parts = self._decal_part_names(self._ship_getter())
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv running light part", e)
            return None
        if entry is None:
            return None
        for node in reversed(entry.get("node_chain", ())):
            if node in parts:
                return node
        return None


def _json_arg(action: str):
    """The JSON argument after the action's colon, or None when bad."""
    try:
        return json.loads(action.partition(":")[2])
    except ValueError:
        return None


def _select_name(action: str) -> Optional[str]:
    """The light name in `rl/<verb>:{"name": ...}`, or None."""
    arg = _json_arg(action)
    if not isinstance(arg, dict):
        return None
    name = arg.get("name")
    return name if isinstance(name, str) else None
