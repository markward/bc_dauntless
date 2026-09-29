# SPV Edit-Target Refactor — design

**Date:** 2026-09-29
**Status:** design agreed with Mark; this spec written
**Branch:** `feat/spv-decal-editing` (continues the decal-editing work)
**Builds on:**
- `docs/superpowers/specs/2026-06-08-ship-property-viewer-design.md`
- `docs/superpowers/specs/2026-09-28-spv-decal-editing-design.md`

---

## 1. Why

The Ship Property Viewer's editing tools (Move, Rotate, Scale, their
Copy/Paste, Mirror, Pipette, and the gizmo drags) are implemented once per
kind of editable thing.

- **Duplication.** `engine/ui/ship_property_viewer_panel.py` (3.7k lines)
  holds about nine independent `if/elif` ladders over the kinds:
  - `_target_pos_of` and `_set_transform_target_pos`;
  - `_scale_kind_and_fields` and `_set_scale_field`;
  - `_rotate_target`, `_rotate_axis` and `_mirror_target_rotation`;
  - the scale and ring drag begin/apply methods.

  Together that is roughly 600–800 lines of the same per-kind branching.
- **Decals as a parallel path.** Decals were added as a separate path
  (`engine/ui/spv_decals_pane.py`, ~880 lines) of early returns in front of
  each tool. That is why decals have no Copy/Paste, Mirror or Pipette.
- **Mark's call.** Mark (2026-09-29): *"why arent we modularising these and
  making them reusable across the board?"*
- **Scope agreed as (a).** The refactor preserves behaviour for every
  existing kind, and decals gain per-tool Copy/Paste plus Mirror.
- **Deferred as (b).** Pipette for decals and part nodes, and any other
  capability gap, is recorded as owed follow-up in memory
  (`project_spv_edit_target_refactor.md`).

## 2. Kinds today (the behaviour to preserve)

| kind | move | rotate | scale | clipboards (coord / scale / rotate) | mirror | pipette | undo |
|---|---|---|---|---|---|---|---|
| subsystem mount (sphere) | yes | — | radius | yes / yes / — | coord | src+tgt | yes |
| light Sphere | yes | — | radius | yes / yes / — | coord | src+tgt | yes |
| light Cylinder | yes | axis | radius+length | yes / yes / yes | yes | src+tgt | yes |
| light Box | yes | fwd+up | xyz (+uniform) | yes / yes / yes | yes | src+tgt | yes |
| emitter point | yes | — | radius | yes / yes / — | coord | src+tgt | yes |
| emitter strip | yes | axis | radius+length | yes / yes / yes | yes | src+tgt | yes |
| emitter cone | yes | fwd+up | 3-field | yes / yes / yes | yes | src+tgt | yes |
| part anchor | yes | — | — | own kind / — / — | coord (x-flip) | — | yes |
| part pose | yes (posed anchor) | Euler | — | own kind / — / yes | yes | — | yes |
| decal | yes (centre) | roll | width+depth | **none** | **none** | — | yes |

This refactor must preserve the clipboard compatibility tags exactly:
- **coord:** `"mount"` is shared by subsystem, light and emitter;
  `"part_anchor"` and `"part_pose"` are each their own.
- **rotate:** `pose_euler`, `cone_orientation`, `box_orientation`, and
  `cylinder_axis`, which a cylinder light and a strip emitter share.
- **scale:** the scale kind tuple.

## 3. The `EditTarget` interface

New module: `engine/ui/spv_edit_targets.py`.

An adapter is constructed from `(panel, key)`. It is a **thin view** over
the panel's existing staged-edit dicts: it owns no state, so staging, undo
snapshots and save are unchanged.

| Member | Meaning |
|---|---|
| `key` | today's target tuple, e.g. `("light", 3)`, `("part_pose", name, state)`; decals: `("decal", name)` |
| `locked` | today's `_current_target_is_locked_mount` |
| `position()` / `set_position(xyz)` | the Move tool's value |
| `gizmo_frame()` | origin and axes every gizmo draws with |
| `rotate_spec()` | `None` or `{fields, clipboard_kind}` |
| `get_rotation()` / `set_rotation(v)` / `rotate_nudge(field, d)` | the Rotate tool |
| `ring_drag_begin(...)` / `ring_drag_apply(angle)` | per-kind maths kept inside: Euler about the posed anchor, cone dual basis, cylinder axis, box fwd+up, decal roll |
| `scale_spec()` | `None` or `{kind, fields, step_scale}` |
| `get_scale()` / `set_scale_field(name, v)` / `scale_drag_begin/apply` | the Scale tool, including the cone handle→field map |
| `coord_kind()` / `rotate_kind()` / `scale_kind()` | the clipboard compatibility tags (§2) |
| `mirror()` | reflect across the ship's centreline in place. **Decal:** instead creates a new placement (§5) |
| `pipette_fields_from(src)` | what may be copied from `src`; empty for decals and part nodes in this refactor |

A capability a kind lacks today is `None` or empty. With every capability
routed through the adapter, the §2 table is preserved by construction.

**Adapters:**
- `MountTarget`
- `LightTarget` (Sphere, Cylinder, Box)
- `EmitterTarget` (point, strip, cone)
- `PartAnchorTarget`
- `PartPoseTarget`
- `DecalTarget`

Existing per-kind code **moves verbatim** into these adapters. It is
relocated, not rewritten, so live-tuned maths stays byte-identical.

## 4. The panel after the refactor

- **`_edit_target()`** returns the adapter for the one live selection. It
  replaces `_active_transform_target()` and the decal early returns. The
  rule that only one selection may own the tools is enforced here and
  nowhere else.
- **Written once against the adapter:**
  - `transform_coords` / `rotate_values` / `scale_values`, the payloads,
    with `decal` and `step_scale` carried from the spec;
  - all `coord_*`, `rotate_*` and `scale_*` nudge/copy/paste/mirror
    handlers;
  - the axis, scale and ring drag begin/apply/end;
  - `transform_gizmo`, `rotate_gizmo` and `scale_gizmo`;
  - `mirror_element`;
  - Pipette.
- **Unchanged:**
  - the staging dicts;
  - `_snapshot_pending` / `_restore_pending`, the undo stack, and save
    routing;
  - picking and selection events;
  - the Decals sidebar (registry, list, Add/Delete/Reposition, hints).
- **`spv_decals_pane.py`** shrinks to the sidebar, the decal-specific
  actions (Add, Reposition, Delete, registry, class default) and the live
  override. Its gizmo, nudge and early-return code moves into
  `DecalTarget`.
- **JS:** the `decal` flag stops hiding Copy/Paste/Mirror. It stays only
  for decal-specific stepper labelling. No layout change.

## 5. Decal Copy / Paste / Mirror

- **Copy/Paste, per tool:**
  - Move: centre X/Y/Z;
  - Rotate: roll;
  - Scale: width and depth, with width aspect-locked to the target's mask
    on paste.

  Clipboard kinds are `"decal"` for coord, rotate and scale. Pasting
  between a decal and any other kind is refused, with Paste greyed.
- **Pasted position:** the decal keeps its own normal, so a pasted centre
  may float off the hull. The user re-seats it with Reposition.
- **Mirror** creates a new placement:
  - named `<mask>_N` (the first free N), with the same `mask` and `shape`;
  - geometry: reflect origin, `u_axis`, `v_axis` and normal across X=0.
    Reflection flips handedness, so then negate `u_axis` and move the
    origin to the old far corner, which keeps `(u×v)·n < 0`, i.e. readable
    from outside;
  - the new placement becomes the selection;
  - refused inline at 16 placements.
- Each Paste or Mirror is one undo step.

## 6. Migration order

Each step leaves the full SPV suite green, and each is its own reviewed
task.

1. **Characterisation suite**, run against the CURRENT code first. For
   each of the ten kind/variants it records:
   - every tool payload;
   - each nudge's effect;
   - copy→paste, including refused kinds;
   - mirror;
   - the pipette result;
   - one drag's effect.

   Add the interface skeleton.
2. **Move:** position and `gizmo_frame` for every adapter. Route
   `transform_coords`, coord nudge/copy/paste/mirror, axis drag and
   `transform_gizmo` through `_edit_target()`. Delete those ladders.
3. **Scale:** specs, nudge, clipboard, drag, gizmo.
4. **Rotate:** specs, nudge, clipboard, ring drag, `rotate_mirror`.
5. **Pipette and `mirror_element`.**
6. **`DecalTarget`:** remove the decal early returns and add decal
   Copy/Paste/Mirror (§5), plus the JS flag change.
7. **Clean-up:**
   - delete dead helpers;
   - assert that no per-kind ladder remains outside `spv_edit_targets.py`;
   - update the `CLAUDE.md` SPV row;
   - run the gate.

## 7. Testing

- **Safety net:** the characterisation suite (§6.1) plus the ~500 existing
  SPV tests. Existing tests may change imports or helper calls, but **not
  assertions**. A step that would need an assertion changed stops for a
  ruling.
- **New decal tests:**
  - copy→paste for each tool;
  - cross-kind paste refused both ways;
  - Mirror gives a readable-from-outside `<mask>_N` at the reflected
    centre, with the same mask;
  - Mirror refused at 16;
  - each is one undo step.
- **Live (Mark):** one target of each kind with each tool, checking drag
  feel, plus decal Copy/Paste/Mirror across both pylons.

## 8. Errors

| Fault | Result |
|---|---|
| Paste with an incompatible clipboard kind | Paste greyed; no-op (as today) |
| Decal Mirror at 16 placements | refused; inline pane error |
| Decal Mirror needing a 5th distinct mask | cannot happen: mirror reuses the source mask |

## 9. Out of scope

- (b): Pipette for decals and part nodes, and other capability gaps. This
  is owed follow-up; see memory `project_spv_edit_target_refactor.md`.
- Any change to staging, undo, save or picking.
- Any JS layout change.
