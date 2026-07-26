# SPV Light Volumes as Selectable Child Nodes — Design

**Date:** 2026-07-26
**Status:** Approved design, ready for implementation plan
**Branch:** `feat/spv-tweaks`
**Builds on:** `2026-07-26-spv-edit-light-glow-region-design.md` (the glow-region
editor: `set_region` writer, routing target, staged-edit/Save flow, the glow
wireframe overlay) and the recent SPV selection/pin/sphere work on this branch.

## Summary

Reconceptualize a subsystem's **light volume** (its index-0 glow region) as a
**first-class, selectable child node** in the SPV subsystem list, decoupled from
the subsystem itself:

- A subsystem that has a light volume shows a **"Light Volume"** child node under
  it. Selecting that node renders **only that light's glow wireframe** (the
  parent's radius sphere hidden), so you can inspect/edit the light on its own.
- **Add Light Volume** — right-click a subsystem with no light → creates one.
- **Edit Light** — right-click the light node → the existing shape/size modal.
- **Remove Light Volume** — right-click the light node → deletes that region.

This replaces the previous model where "Edit Light…" lived on the subsystem row
and was gated to impulse/warp/sensor. Now **any** subsystem can carry (one) light
volume.

## Scope decisions (from brainstorming)

1. **Add on any subsystem.** The impulse/warp/sensor gate is dropped. The SPV
   wireframe shows a light volume on any subsystem. **In-scene glow still renders
   only for impulse/warp/sensor** (`ShipGlowController` is unchanged) — a light
   authored on another subsystem is valid data that previews in the SPV but does
   not glow in gameplay until the glow engine is extended (separate future work).
2. **One light volume per subsystem** (region index 0). Add is offered only when
   the subsystem has none.
3. **Light node selected → only its glow wireframe** (parent radius sphere +
   other pins hidden). The parent subsystem's **icon pin stays** as the anchor.
4. **Remove is in scope** (right-click the light node).
5. Light node label: **"Light Volume"**.

## Presence model — "has a light volume"

A subsystem has a light volume when its **effective light** at index 0 is a real
region (not absent, not removed). Effective light resolves like radius/glow
already do: **pending → saved → baked**, where a value is either a baked-shaped
region spec or a **removed sentinel**:

- **Baked**: `baked_glow_regions(sub.GetProperty())[0]` if present. Computed for
  **every** subsystem in `build_descriptors` (the old `glow_bearing_subsystem_ids`
  gate is removed); `light_region` is attached to any subsystem with a baked
  region 0, else the descriptor carries a from-scratch default used by Add.
- **Pending / saved**: staged Add/Edit (a spec) or Remove (the sentinel).

`has_light(idx)` = `effective_light(idx)` is a spec (not None, not the removed
sentinel). The light child node exists iff `has_light(idx)`.

## Selection model — light is its own selection

The panel gains a second, mutually-exclusive selection:

- `selected_index: int | None` — the selected **subsystem** (pin + radius sphere).
- `selected_light_index: int | None` — the subsystem descriptor index whose
  **light** is selected (glow wireframe only).

Invariant: at most one is set. Setting one clears the other; `deselect` clears
both. New dispatch event `select_light:<subsystem_index>`; subsystem rows keep
`select_pin:<index>`. `handle_key_esc`/close reset both.

### Render wiring (host_loop, viewer-mode block)

| State | Radius sphere | Glow wireframe (toggle off) | Pins |
|---|---|---|---|
| nothing selected | — | — | all |
| subsystem selected | that subsystem | — | only that pin |
| light selected | — | that subsystem's light | only the parent's pin |

- `selected_subsystem_sphere()` returns a sphere only when `selected_index` is set
  (unchanged behavior; None while a light is selected).
- The glow overlay's `selected_name` is driven by `selected_light_index` (the
  subsystem whose light is selected), **not** by `selected_index`. So selecting a
  subsystem no longer shows its glow — that is now the light node's job. The Glow
  Regions toggle (`show_all`) is unchanged (shows every subsystem's glow).
- `subsystem_pins()`: subsystem selected → only that pin; light selected → only
  the parent subsystem's pin (anchor icon); neither → all pins.
- The glow overlay must also honor the effective light (pending Add/Edit shows
  live; a pending Remove hides the wireframe). It already takes `pending` specs
  `{name: spec}`; extend it to carry a **hide sentinel** (`None`) for a removed
  light so the overlay draws nothing for that subsystem instead of falling
  through to the still-present baked region. The overlay resolves
  `pending[name]` only when non-`None`, else emits no op for that subsystem.
  `pending_light_specs()` therefore maps Add/Edit subsystems to their spec and
  Removed subsystems to `None`.

## Tree — a light child under its subsystem

`_subsystem_rows` currently builds a 2-level accordion via `parent_index`. Add a
light child:

- Each subsystem row with `has_light(idx)` gets one extra child row:
  `{kind: "light", parent_index: idx, name: "Light Volume", light_region: <effective spec>}`.
  It carries no `index` of its own for pin selection — instead a `light_of: idx`
  so its click fires `select_light:<idx>`.
- Because a subsystem may itself be a pod under a category, the light node can be
  a 3rd level. The CEF list renderer (`renderSPVSubsystemList`) becomes
  **recursive** (render a row, then its children, at any depth) rather than the
  current fixed two levels. The light row is chrome-aware (never orbits/picks the
  3D view) like every other row.
- Selecting a subsystem no longer needs to also reveal its light (they are
  separate nodes now); the accordion auto-expands a subsystem when its light (or
  the subsystem) is selected, so the node is visible.

## Staging — add / edit / remove unified

Extend the panel's light staging (`_pending_light` / `_saved_light`, keyed by
descriptor index) so a value is **either a region spec or the removed sentinel**
(`REMOVED = None` — distinct from "absent from the dict"):

- **Add Light Volume** → `dispatch_event("add_light:<i>")`: stage a default spec
  (`Sphere`, radius from the descriptor's `light_region` default, position = the
  subsystem mount) into `_pending_light[i]`. The child node appears; it becomes
  selected (`select_light:<i>`).
- **Edit Light** → the existing `set_light:<json>` (now fired from the light node
  context menu; `i` = the parent subsystem index).
- **Remove Light Volume** → `dispatch_event("remove_light:<i>")`: stage the
  removed sentinel into `_pending_light[i]`; if that light was selected, clear
  `selected_light_index`.
- **Save**: for each `_pending_light[i]`:
  - spec → `("<name>", "__region__", 0, region_spec_to_calls(0, spec))`;
  - removed sentinel → `("<name>", "__region__", 0, [])` (clears region 0).
  Then move all into `_saved_light` (preview persists post-Save, as today).
- `has_light`/`effective_light`/`pending_light_specs`/the tree/the popover all
  read through the same effective-light resolver, so Add/Edit/Remove reflect
  immediately and consistently.

`dirty`, `pending_count`, and the Save-confirm tally count a subsystem with any
pending light change (spec or removal), unchanged in spirit.

## Context menus (CEF)

Gate the items on the right-clicked node's kind/state (data already on the row):

- Subsystem row, no light → `Set Radius…`, `Add Light Volume`.
- Subsystem row, has light → `Set Radius…` (Edit/Remove are on the light child).
- Light node → `Edit Light…`, `Remove Light Volume`.

The right-click handler already receives the row; extend it to read `kind` /
`has_light` / `light_of` and show/hide the three items accordingly. The Edit
modal is unchanged; it pre-fills from the light node's `light_region`.

## Writer fix — drop empty subsystem blocks

`set_region(0, [])` can leave a subsystem with **no** remaining setter calls.
`emit` currently renders `p = find("Name")` / `if p is not None:` with the call
lines beneath — an empty call list would emit an `if` with no body (a
`SyntaxError`). Fix `emit` (`hardpoint_override_writer.py`) to **skip any
subsystem whose call list is empty**, and a `_<leaf>` whose subsystems are all
empty emits `return` (as the no-override case already does). Covered by a writer
test (remove the only region → the subsystem block disappears; the file still
round-trips to a canonical fixed point).

## Testing

- **Writer:** `set_region(0, [])` empties a block; `emit` drops the empty
  subsystem (no `SyntaxError`); round-trip fixed point holds; other subsystems /
  indices intact.
- **Descriptors:** `light_region` is attached to any subsystem with a baked
  region 0 (not just impulse/warp/sensor); a subsystem with none carries the
  from-scratch default; the impulse/warp/sensor gate is gone.
- **Panel:** `add_light` stages a default spec and makes `has_light` true +
  selects the light; `remove_light` stages the sentinel and hides the node +
  clears the light selection; `set_light` edits; selecting a subsystem vs its
  light sets the right one and clears the other; `selected_subsystem_sphere` is
  None while a light is selected; `pending_light_specs` includes Add/Edit and
  omits Removed; the tree emits a light child only when `has_light`; Save routes
  specs and removals and clears/persists; close resets both selections.
- **Overlay/host_loop (Python-level):** the glow overlay shows the light-selected
  subsystem's region and hides a removed one; the sphere is suppressed while a
  light is selected.
- **CEF:** no JS unit harness — gate build + live `--developer` check (right-click
  a subsystem → Add Light Volume → the child appears and is selected showing its
  wireframe → Edit → shape/size updates live → Remove → node gone, wireframe gone
  → Save → inspect `hardpoint_overrides.py`).
- Full `scripts/check_tests.sh` gate green.

## Risks / out of scope

- **In-scene glow for non-standard subsystems.** A light authored on a
  non-impulse/warp/sensor subsystem previews in the SPV but does not glow in
  gameplay (ShipGlowController unchanged). Explicitly accepted; extending the glow
  engine is separate future work.
- **Recursive tree rendering** replaces the fixed 2-level list render; the
  chrome-geometry constants and wheel-forwarding behavior must be preserved.
- **One region per subsystem** — multi-region (index > 0) remains out of scope;
  Add is disabled when a light exists.
- **Baked glow source.** Glow regions live only in `hardpoint_overrides.py`
  (a Dauntless extension; BC hardpoints set no `SetGlowRegion*`), so Remove fully
  clears a light by emptying region 0 in the override — there is no SDK-set glow
  to fight.

## Future work

- Multiple light volumes per subsystem (index > 0) as multiple child nodes.
- Extending `ShipGlowController` so authored lights on any subsystem glow in-game.
- Position/axis editing of a light volume (still preserved, not user-editable).
