# SPV Light-Type Modal — Design

**Date:** 2026-07-28
**Status:** Approved (design); implementation pending
**Motivation:** Now that the Scale tool owns light-volume sizing, the "Edit Light…" modal shouldn't duplicate size editing — it should just pick the light **type** (shape). And "Add Light Volume" should use that same picker instead of silently assuming a default shape.

**Builds on:** the SPV light-volume nodes + Edit Light modal ([[project-spv-edit-light-glow]]), the Scale tool ([[project-spv-scale-tool]]).

## Goal

Collapse the Edit Light modal (`#spv-light`) into a **light-type picker** (Sphere / Cylinder / Box only), reused for both Edit and Add:
- **Edit Light** → pick a type → the element keeps its current position/axis/size/orientation, only the shape changes (size fine-tuned via the Scale tool).
- **Add Light** → same picker opens → pick a type → a light of that shape (default size) is staged and selected.

Developer-only, mouse-only. No change to persistence, the Scale/Rotate tools, or the render path.

## Key decisions (confirmed with Mark)

1. **Edit shape-change keeps the existing size fields** (radius/extent/scale/orientation), not a shape-specific reset — the Scale tool owns sizing.
2. The **same modal** serves Add and Edit; a `spvLightMode` (`'add'`|`'edit'`) flag routes Apply to `add_light` vs `set_light`.

## Background facts (verified)

- Modal `#spv-light` (index.html): shape-button row → `shipPropertyViewerLightShape(shape)` (highlights the button AND populates `#spv-light-fields` with size steppers); Cancel/Apply → `shipPropertyViewerLightApply` fires `set_light:{i, shape, <size fields>}`.
- Edit opens via `shipPropertyViewerCtxLight` (seeds `spvLight` from the row, fires `select_light`, shows the modal). Add currently via `shipPropertyViewerCtxAddLight` → fires `add_light:<index>` DIRECTLY (no modal).
- Panel `set_light:` dispatch parses shape + size args (radius/aft/fore/sx/sy/sz, all `> 0` guarded), builds a full spec, stages `_pending_light[idx]`.
- Panel `add_light:` dispatch takes an int index, stages `dict(descriptor["light_region"])` (the from-scratch default spec, which carries radius/extent/scale + identity orientation via `_light_region_spec`) and selects the new light node. Guards `not _has_light(idx)`.

## Components

### A. Panel dispatch (`ship_property_viewer_panel.py`)

- `set_light:` — accept `{"i": idx, "shape": shape}` **shape-only** (drop the radius/aft/fore/sx/sy/sz parsing). Build the spec from the effective light (or the descriptor default), then set only `shape` — **all size/position/axis/orientation fields are preserved** from the current spec. Reject an unknown shape. (Result: switching shape keeps the element where and how big it was; Scale re-sizes.)
- `add_light:` — accept `{"i": idx, "shape": shape}` (was a bare int). Stage `dict(descriptor["light_region"])` with `shape` overridden to the chosen type (the base already carries default radius/extent/scale + identity orientation), select the new light node, expand the group. Keep the `not _has_light(idx)` / `light_region` guards. (Accept a bare-int payload too, for safety, defaulting shape to the base's own shape.)

### B. CEF modal (`native/assets/ui-cef/{index.html,js/ship_property_viewer.js}`)

- `index.html`: the modal keeps the shape-button row + Cancel/Apply; **remove `#spv-light-fields`** (the size steppers). Title driven by mode ("Add Light" / "Edit Light").
- `js`:
  - `shipPropertyViewerLightShape(shape)`: set `spvLight.shape` + highlight the active button; **stop populating `#spv-light-fields`** (no size steppers).
  - Add `var spvLightMode = 'edit';`. `shipPropertyViewerCtxLight` (Edit) sets `spvLightMode='edit'`, seeds the shape from the row, opens the modal. `shipPropertyViewerCtxAddLight` (Add) sets `spvLightMode='add'`, defaults the shape (the row's `light_region.shape`, else 'Sphere'), and **opens the modal** (instead of firing `add_light` directly).
  - `shipPropertyViewerLightApply`: fire `add_light:` + `JSON.stringify({i: spvCtxIndex, shape: spvLight.shape})` when `spvLightMode==='add'`, else `set_light:` + `JSON.stringify({i: spvCtxIndex, shape: spvLight.shape})`. No size fields either way.
  - Set the modal title element from the mode when opening.

## Data flow

```
Edit Light: right-click light node -> select_light -> open modal (edit, seed shape)
  pick Box -> Apply -> set_light:{i, "Box"} -> panel keeps size/pos/axis/orient, shape=Box
Add Light: right-click subsystem (no light) -> open modal (add, default shape)
  pick Cylinder -> Apply -> add_light:{i, "Cylinder"} -> stage default cylinder spec + select
Save -> region_spec_to_calls -> set_region -> hardpoint_overrides.py (unchanged)
```

## Edge cases

- **Unknown shape** in either dispatch → return False (no-op).
- **Shape change to Box** on Edit: the spec's `scale` (existing or default) + identity orientation apply; Scale/Rotate then tune it.
- **Add on a subsystem that already has a light** → guarded (`_has_light`), as today.
- Backward-compat: `add_light` still accepts a bare-int payload (defaults shape to the base spec's shape) so nothing else breaks.

## Testing strategy

- **Panel (pytest)**: `set_light:{i, shape}` changes only the shape and preserves radius/extent/scale/position/axis/orientation; rejects unknown shape. `add_light:{i, shape}` stages a light of that shape (default size) and selects it; still guarded by `_has_light`; a bare-int payload still works (defaults shape).
- **CEF**: no automated DOM test (verified in-game); the dispatch behaviour is covered in Python.

## Rollout

Branch `feat/spv-light-type-modal` off `main`, task-by-task via subagent-driven-development, gated by `scripts/check_tests.sh`. Merge is Mark's call after an in-game pass. Never pushed without Mark's say-so.
