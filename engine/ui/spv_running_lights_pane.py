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

Renames (follow-up 2026-10-23) ride beside the saved and pending layers as
`{new name: the name it had in the layer below}` maps, applied to the layer
below before that layer's specs; a renamed light keeps its place. Only a
light Dauntless created (added this session, or attach-queued by a stock
leaf's overrides) or any light of a mod's own hardpoint file may be renamed:
a stock ship's other lights are templates from the game's own hardpoint
file, which is keyed by name.
"""
from __future__ import annotations

import json
from typing import List, Optional

from engine.ui import running_light_editor
from engine.ui.spv_decals_pane import MISS_HINT, instance_scale

RL_GROUP_NAME = "Running Lights"
RL_ADD_NAME = "+ Add"
RL_TARGET_KIND = "running_light"
RL_RENAME_LOCK_REASON = "Named in the game's hardpoint file"
_EDIT_VERB = "__running_light__"
_RENAME_VERB = "__rename_light__"


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
        # Staged renames, {new name: committed name}. A pending add needs
        # none: it is simply re-keyed.
        self._pending_rl_renames: dict = {}
        # Who may be renamed: every light of a mod file, else the names the
        # stock leaf's hardpoint exec attach-queued (`_rl_rename_sources`).
        self._rl_renames_any: bool = False
        self._rl_attached: set = set()

    def _rl_clear_saved(self) -> None:
        self._saved_running_light: dict = {}
        # Renames saved this session, {committed name: baked name}.
        self._saved_rl_renames: dict = {}

    def _rl_load(self, ship) -> None:
        """Snapshot `ship`'s placed lights as the baked layer, and the names
        of every other template in its property set."""
        self._rl_baked = {}
        self._rl_template_names = set()
        if ship is None:
            return
        self._rl_renames_any, self._rl_attached = self._rl_rename_sources(ship)
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

    def _rl_rename_sources(self, ship) -> tuple:
        """(every light renameable, attach-queued names) for `ship`: a mod
        file's target renames any light; a stock leaf only the lights its
        overrides created, which are exactly the names the attach queue
        attached when the leaf's hardpoint module last executed."""
        # Through the panel module: Save resolves the target the same way.
        from engine.ui import ship_property_viewer_panel as _panel
        from engine.appc import attach_templates
        try:
            target = _panel.resolve_override_target(ship)
            if getattr(target, "renames_any_light", False):
                return True, set()
            leaf = _panel.hardpoint_leaf_for_ship(ship)
            return False, (attach_templates.attached_names(leaf) if leaf
                           else set())
        except Exception as e:
            from engine import dev_mode
            dev_mode.log_swallowed("spv running light rename sources", e)
            return False, set()

    # ------------------------------------------------------------------
    # Staging
    # ------------------------------------------------------------------
    def _rl_committed_map(self) -> dict:
        """name -> spec as the file holds it: baked, then this session's
        saved renames and saved specs."""
        merged = _apply_renames(dict(self._rl_baked), self._saved_rl_renames)
        return _apply_layer(merged, self._saved_running_light)

    def _rl_effective_map(self) -> dict:
        merged = _apply_renames(self._rl_committed_map(),
                                self._pending_rl_renames)
        return _apply_layer(merged, self._pending_running_light)

    def _rl_effective(self) -> List[dict]:
        return list(self._rl_effective_map().values())

    def _rl_committed_identity(self, name) -> Optional[str]:
        """The committed name effective light `name` has in the file, or
        None for a light added since the last Save."""
        if name in self._pending_rl_renames:
            return self._pending_rl_renames[name]
        if (name in self._rl_committed_map()
                and name not in self._pending_rl_renames.values()):
            return name
        return None

    def _rl_baked_identity(self, committed) -> Optional[str]:
        """The open-time (baked) name of committed light `committed`, or
        None for a light a Save created this session."""
        if committed in self._saved_rl_renames:
            return self._saved_rl_renames[committed]
        if (committed in self._rl_baked
                and committed not in self._saved_rl_renames.values()):
            return committed
        return None

    def _rl_renameable(self, name) -> bool:
        """Added since the ship was built, created by Dauntless (attach-
        queued), or any light of a mod's own file. The attach record is the
        leaf's LAST build: after a saved rename another ship of the class may
        have re-recorded it under the committed (new) name. It only ever
        holds names the overrides file creates, so neither name can unlock a
        game template."""
        committed = self._rl_committed_identity(name)
        baked = (None if committed is None
                 else self._rl_baked_identity(committed))
        return (baked is None or self._rl_renames_any
                or baked in self._rl_attached
                or committed in self._rl_attached)

    def _rl_committed_parent(self, committed, baked_parents=None):
        """The explicit physical parent the file holds for committed light
        `committed`: saved this session, else the open-time value of its
        baked light (`baked_parents`, default the panel's open-time light
        snapshot). None = Auto."""
        if committed in self._saved_physical:
            return self._saved_physical[committed]
        baked = self._rl_baked_identity(committed)
        if baked is None:
            return None
        if baked_parents is None:
            baked_parents = {light["name"]: light["physical_parent"]
                             for light in self._physical_lights}
        return baked_parents.get(baked)

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
        the add instead: there is nothing in the file to remove. Removing a
        renamed light drops the rename and removes it under its committed
        name (unless a new light has since taken that name: that one stays,
        as an edit of the committed light)."""
        if spec is None:
            committed = self._rl_committed_identity(name)
            renamed = self._pending_rl_renames.pop(name, None) is not None
            self._pending_running_light.pop(name, None)
            if committed is not None and not (
                    renamed
                    and self._pending_running_light.get(committed) is not None):
                self._pending_running_light[committed] = None
        else:
            self._pending_running_light[name] = dict(spec)
        if self._rl_selected is not None and self._rl_spec(self._rl_selected) is None:
            self._rl_selected = None
        self._last_pushed = None
        # Not only dispatch_event syncs: a gizmo drag stages from
        # `_handle_gizmo_input`. Cheap -- it pushes only on a change.
        self._rl_sync_preview()

    def _rl_rename(self, old, valid) -> None:
        """Rename effective light `old` to `valid["name"]`, restaging it
        from `valid`. A committed light gets a rename-map entry (a chain
        collapses to its committed name; renaming back drops it) and a
        pending spec only when more than the name changed; a pending spec
        and a pending physical parent are re-keyed in place; the selection
        follows."""
        new = valid["name"]
        committed = self._rl_committed_identity(old)
        current = self._rl_spec(old)
        self._pending_rl_renames.pop(old, None)
        pending = self._pending_running_light
        if old in pending:
            pending = _rekey(pending, old, new)
            pending[new] = dict(valid)
        elif dict(valid, name=old) != current:
            pending[new] = dict(valid)
        self._pending_running_light = pending
        if committed is not None and committed != new:
            self._pending_rl_renames[new] = committed
        if old in self._pending_physical:
            self._pending_physical = _rekey(self._pending_physical, old, new)
        if self._rl_selected == old:
            self._rl_selected = new
        self._last_pushed = None
        self._rl_sync_preview()

    def _rl_file_name_refusal(self, old, new) -> Optional[str]:
        """Refuse renaming `old` onto a name the hardpoint file may still
        hold for another light -- one staged or saved for removal, or
        renamed away this session: Save would have to free and reuse it in
        one go, which neither writer can. Renaming back to the light's own
        original name is fine."""
        committed = self._rl_committed_identity(old)
        baked = (None if committed is None
                 else self._rl_baked_identity(committed))
        held = (set(self._rl_baked) | set(self._saved_running_light)
                | set(self._saved_rl_renames)
                | set(self._saved_rl_renames.values())
                | set(self._pending_running_light)) - {old, committed}
        if new not in held:
            return None
        if new == baked and new not in self._saved_running_light:
            return None
        return ("A light named '%s' was removed or renamed this session; "
                "choose another name" % new)

    def _rl_dirty_names(self) -> List[str]:
        return list(self._pending_running_light) + [
            n for n in self._pending_rl_renames
            if n not in self._pending_running_light]

    def _rl_dirty_counts(self) -> List[tuple]:
        """(light name, staged changes): a spec edit and a rename count one
        each."""
        return [(n, (n in self._pending_running_light)
                 + (n in self._pending_rl_renames))
                for n in self._rl_dirty_names()]

    def _rl_pending_count(self) -> int:
        return len(self._pending_running_light) + len(self._pending_rl_renames)

    def _rl_has_pending(self) -> bool:
        return bool(self._pending_running_light or self._pending_rl_renames)

    def _rl_parent_moves(self) -> List[tuple]:
        """(committed name, new name, explicit parent) per staged rename of
        a light whose committed parent is set."""
        moves = []
        for new, committed in self._pending_rl_renames.items():
            parent = self._rl_committed_parent(committed)
            if parent is not None:
                moves.append((committed, new, parent))
        return moves

    def _rl_save_edits(self) -> list:
        """The Save edits, in the order the writers need: removals, then
        renames (so a name a rename takes is free), then specs under their
        final names, then each renamed light's explicit parent moved to its
        new name. The panel puts these before every other edit, so a
        physical parent staged for a new name lands after its rename."""
        committed = self._rl_committed_map()
        renamed_from = set(self._pending_rl_renames.values())
        pending = self._pending_running_light
        edits = [(name, _EDIT_VERB, {"spec": None, "new": False})
                 for name, spec in pending.items() if spec is None]
        edits += [(old, _RENAME_VERB, new)
                  for new, old in self._pending_rl_renames.items()]
        for name, spec in pending.items():
            if spec is None:
                continue
            new = (name not in self._pending_rl_renames
                   and not (name in committed and name not in renamed_from))
            edits.append((name, _EDIT_VERB, {"spec": spec, "new": new}))
        for old, new, parent in self._rl_parent_moves():
            # A parent staged for either name is the panel's to write.
            if old not in self._pending_physical:
                edits.append((old, "__unset__", "SetPhysicalParent"))
            if new not in self._pending_physical:
                edits.append((new, "SetPhysicalParent", (parent,)))
        return edits

    def _rl_commit_saved(self) -> None:
        """A successful Save: the pending edits become the saved overlay.
        Called BEFORE the panel folds the pending physical parents into
        `_saved_physical`, so a parent staged for a renamed light wins over
        the one its rename moved."""
        renames = self._pending_rl_renames
        parents = [(old, new, self._rl_committed_parent(old))
                   for new, old in renames.items()]
        bakeds = {new: self._rl_baked_identity(old)
                  for new, old in renames.items()}
        for old, _new, _parent in parents:
            self._saved_physical[old] = None
        for _old, new, parent in parents:
            self._saved_physical[new] = parent
        inverse = {old: new for new, old in renames.items()}
        self._saved_running_light = {
            inverse.get(k, k): (dict(v, name=inverse[k])
                                if k in inverse and v is not None else v)
            for k, v in self._saved_running_light.items()}
        for old in inverse:
            self._saved_rl_renames.pop(old, None)
        for new, baked in bakeds.items():
            if baked is not None and baked != new:
                self._saved_rl_renames[new] = baked
        self._saved_running_light.update(self._pending_running_light)
        self._pending_running_light = {}
        self._pending_rl_renames = {}

    def _rl_snapshot(self) -> tuple:
        return ({name: (None if spec is None else dict(spec))
                 for name, spec in self._pending_running_light.items()},
                dict(self._pending_rl_renames))

    def _rl_restore(self, snap: tuple) -> None:
        pending, renames = snap
        self._pending_running_light = {
            name: (None if spec is None else dict(spec))
            for name, spec in pending.items()}
        self._pending_rl_renames = dict(renames)
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
            dirty = set(self._rl_dirty_names())
            rows.append({
                "kind": "rl_group", "name": RL_GROUP_NAME,
                "expanded": self._rl_group_expanded,
                "children": [self._rl_row(spec, dirty) for spec in lights]})
        rows.append({"kind": "rl_add", "name": RL_ADD_NAME})
        return rows

    def _rl_row(self, spec, dirty) -> dict:
        name = spec["name"]
        row = {"kind": RL_TARGET_KIND, "name": name, "spec": dict(spec),
               "dirty": name in dirty, "chosen": name == self._rl_selected,
               "renameable": self._rl_renameable(name)}
        if not row["renameable"]:
            row["rename_lock_reason"] = RL_RENAME_LOCK_REASON
        return row

    def _rl_physical_entries(self, baked_parents: dict) -> List[dict]:
        """Physical-tab entries for every effective light; `baked_parents`
        maps a baked light's name to its open-time `GetPhysicalParent()`.
        Each entry carries its `committed` parent -- what the file holds for
        the light, following renames -- which the panel reads in place of
        its own name-keyed saved/baked lookup."""
        out = []
        for spec in self._rl_effective():
            committed = self._rl_committed_identity(spec["name"])
            parent = (None if committed is None
                      else self._rl_committed_parent(committed, baked_parents))
            out.append({"key": "light:" + spec["name"], "name": spec["name"],
                        "kind": RL_TARGET_KIND, "index": None,
                        "baked": parent, "committed": parent,
                        "point": tuple(spec["position"])})
        return out

    def _rl_state_key(self) -> tuple:
        return (tuple(tuple(sorted(s.items())) for s in self._rl_effective()),
                tuple(self._pending_running_light),
                tuple(self._pending_rl_renames.items()),
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
            entry = self._physical_entry("light:" + name)
            committed = (self._physical_committed(entry)
                         if entry is not None else None)
            # A renamed light is removed under its committed name.
            file_name = self._rl_committed_identity(name)
            self._rl_stage(name, None)
            # A merely staged parent would be written onto a template that
            # no longer exists.
            self._pending_physical.pop(name, None)
            if committed is not None and file_name is not None:
                # A SAVED or BAKED parent lives in the file as its own
                # find-block: reset it, or a later light of this name
                # inherits it.
                self._pending_physical[file_name] = None
            if self._rl_selected == name:
                self._rl_selected = None
            return True
        return False

    def _rl_refuse(self, message: str) -> bool:
        self._rl_error = message
        self._last_pushed = None
        return False

    def _rl_lock_reason(self) -> str:
        return (self._mount_lock_state_and_reason()[1]
                or "Mount editing is locked")

    def _rl_note_lock_refusal(self, action: str) -> None:
        """The panel's mount-lock gate refused `action` before any verb ran.
        An `rl/` action shows the lock's reason: the Add modal has already
        closed, so a silent refusal would look like nothing happened."""
        if action.startswith("rl/"):
            self._rl_refuse(self._rl_lock_reason())

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
        """Restage light `name` from `spec`. A different `spec.name` renames
        it -- refused for a light the game's own hardpoint file names."""
        arg = _json_arg(action)
        name = arg.get("name") if isinstance(arg, dict) else None
        if not isinstance(name, str) or self._rl_spec(name) is None:
            return self._rl_refuse("No running light to edit")
        spec = arg.get("spec")
        if isinstance(spec, dict):
            new = spec.get("name", name)
            if not isinstance(new, str):
                return self._rl_refuse("Malformed light spec")
            if new.strip() != name:
                return self._rl_edit_rename(name, spec)
            spec = dict(spec, name=name)
        valid = self._rl_validate(spec, self._rl_taken_names() - {name})
        if valid is None:
            return False
        self._rl_stage(name, valid)
        self._rl_error = None
        return True

    def _rl_edit_rename(self, name, spec) -> bool:
        if not self._rl_renameable(name):
            return self._rl_refuse(RL_RENAME_LOCK_REASON)
        valid = self._rl_validate(spec, self._rl_taken_names() - {name})
        if valid is None:
            return False
        refusal = self._rl_file_name_refusal(name, valid["name"])
        if refusal is not None:
            return self._rl_refuse(refusal)
        self._rl_rename(name, valid)
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
            self._rl_error = self._rl_lock_reason()
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
        # The new light is selected: never inside a collapsed group.
        self._rl_group_expanded = True
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


def _rekey(d: dict, old, new) -> dict:
    """`d` with key `old` renamed `new`, in the same position."""
    return {(new if k == old else k): v for k, v in d.items()}


def _apply_renames(merged: dict, renames: dict) -> dict:
    """`merged` (name -> spec) with every `renames` entry (new -> old)
    applied at once: each light keeps its place and its spec takes the new
    name."""
    inverse = {old: new for new, old in renames.items() if old in merged}
    return {inverse.get(k, k): (dict(v, name=inverse[k]) if k in inverse else v)
            for k, v in merged.items()}


def _apply_layer(merged: dict, layer: dict) -> dict:
    """`merged` with a saved/pending layer's specs on top (None removes)."""
    for name, spec in layer.items():
        if spec is None:
            merged.pop(name, None)
        else:
            merged[name] = spec
    return merged


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
