# SPV Hardpoint Value Override Editing — Design

**Date:** 2026-07-25
**Status:** Approved design, ready for implementation plan
**Branch:** `feat/spv-enhancements`
**Supersedes:** `2026-07-24-spv-subsystem-rename-and-override-editing-design.md` (the
rename MVP + managed-block writer — abandoned; see "Why the pivot").

## Summary

Let the Ship Property Viewer (SPV) edit a subsystem's **hardpoint value** and
persist it into `engine/appc/hardpoint_overrides.py`. The MVP value is a
subsystem's **radius** (`SetRadius`). Edits are **staged** (shown in the SPV, not
written) until the user clicks **Save** and confirms.

To make the override file cleanly machine-editable — every value a single source
of truth, no shadowing, no competing priorities — the file is restructured into
**one function per ship, one expanded block per subsystem, plain Appc setter
calls, fully machine-owned**. The writer reads a ship's current overrides by
*executing* its function against a recording `find`, applies the edit to that
model, and re-emits the file deterministically.

This is the foundation for editing any hardpoint value from the SPV (glow/light
regions next); radius is the smallest safe first value.

## Why the pivot

The prior design added machine "override blocks" *alongside* the existing
per-ship functions. Two problems killed it:

1. **The override files are engine-generated, not hand-authored** (by
   `tools/bake_impulse_glow.py`, `tools/bake_warp_glow.py`, and earlier work).
   There is nothing precious to protect — so the contortions to preserve
   "hand-authored" code around a managed block were solving a non-problem.
2. **Rename is a poor MVP.** A subsystem's name is its *identity/lookup key*:
   the hardpoint itself does `FindByName("Center Impulse")` (galaxy.py:1428), and
   targeting/combat/our own overrides all resolve subsystems by name. Overriding
   a name risks breaking those lookups. Radius is a pure value nothing keys on.

The clean answer: own the whole file, express overrides as plain setter calls
(exactly how BC and today's glow overrides already work), and make the SPV edit
values in place with no duplicates.

## How overrides reach the ship (mechanism the design relies on)

`RegisterLocalTemplate(prop)` files a subsystem template **by name** into
`g_kModelPropertyManager._local` (properties.py:1024). Ship build
(`loadspacehelper.CreateShip`) then `reload()`s the hardpoint, calls
`LoadPropertySet` (which `FindByName`s each template and `AddToSet`s a
*reference* into the ship's property set — galaxy.py:1357, properties.py:1104),
and `SetupProperties()` copies values off each template onto the live subsystem
(e.g. `pod.SetRadius(prop.GetRadius())` — ships.py:1364).

Our override runs from the SDK-loader hook **after** the reload re-registers the
templates and **before** `LoadPropertySet`/`SetupProperties` read them, mutating
the same shared template object:

```
hardpoint runs → Register "Center Impulse" (radius 0.25)
apply("galaxy") → find("Center Impulse").SetRadius(0.5)   # mutate shared template
LoadPropertySet / SetupProperties → pod.SetRadius(GetRadius())  → 0.5
```

Consequence: a saved value takes effect at the **next ship build (reload)**, not
retroactively — matching the persist→reload proof model.

## File structure

`engine/appc/hardpoint_overrides.py` becomes fully machine-owned:

```python
# engine/appc/hardpoint_overrides.py — MACHINE-OWNED.
# Edited by the Ship Property Viewer (docs/.../2026-07-25-...-design.md).
# Do not hand-edit; the SPV regenerates this file on save.

def apply(leaf):
    """Run a ship's override function, if any (called from the SDK-loader hook)."""
    fn = OVERRIDES.get(leaf)
    if fn is None:
        return
    import App
    mgr = App.g_kModelPropertyManager

    def find(name):
        return mgr.FindByName(name, App.TGModelPropertyManager.LOCAL_TEMPLATES)

    fn(find)


def _galaxy(find):
    """Galaxy."""
    p = find("Port Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Star Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
    p = find("Center Impulse")
    if p is not None:
        p.SetGlowRegionShape(0, "Cylinder")
        p.SetGlowRegionAxis(0, 0.0, -1.0, 0.0)
        p.SetGlowRegionRadius(0, 0.25)
        p.SetGlowRegionExtent(0, 0.0, 2.0)
        p.SetRadius(0.5)                     # ← a value override, same block


OVERRIDES = {
    "galaxy": _galaxy,
    # ...one entry per ship...
}
```

Rules:
- **One `def _<leaf>(find):` per ship**, all that ship's logic co-located, keyed
  in `OVERRIDES` (unchanged dispatch; `apply(leaf)` unchanged in spirit).
- **One block per subsystem** — `p = find("Name")` / `if p is not None:` /
  its setter calls. The block holds *all* of that subsystem's overrides and is
  the single source of truth for its values.
- **No loops.** Subsystems that happen to share values (e.g. the three impulse
  engines' glow) are expanded into separate blocks, because the SPV edits one
  subsystem at a time and each must be independently addressable. Cross-subsystem
  repetition of a value is not a competing definition — each subsystem states
  each of its properties exactly once.
- **Per-ship banner only.** A minimal docstring/name for navigation; the current
  freeform provenance comments (formula notes, `####` banners) are dropped (git
  history preserves them).
- **Machine-owned.** The SPV regenerates the file; humans do not hand-edit it.

## Editing mechanism — execute-to-model, then re-emit

The writer never text-parses the override file. It recovers each ship's model by
**executing** the function against a recording `find`:

- `read_models() -> {leaf: {subsystem: [(setter, args), ...]}}`: for each
  `leaf, fn` in `OVERRIDES`, call `fn(recording_find)` where `recording_find`
  returns a permissive proxy that records every method call (`SetX(*args)`)
  grouped by the `name` passed to `find`. The current functions are pure
  straight-line setter calls (plus `if p is not None` guards the proxy always
  passes), so execution reproduces the model exactly — and this works on both
  the pre-conversion file (loops included) and the emitted canonical form.
- **Apply the edit** to the model: for `SetRadius`, replace the target
  subsystem's existing `SetRadius` entry (or append one; create the subsystem
  block if absent). "One setter per (subsystem, method)" is enforced here — no
  duplicates.
- `emit(models) -> str`: deterministically render the whole file (apply + every
  `_<leaf>` + `OVERRIDES`). Deterministic ordering → a single-value edit produces
  a one-line diff.
- **Crash-safe:** validate the emitted text with `ast.parse`; write atomically
  (`os.replace`). A failure aborts without touching the file.

Conversion of the existing file is just the first emit: `read_models()` on
today's file → `emit()` → the canonical form. Equivalence is verified by
re-recording the emitted file and diffing the per-subsystem setter-call sequences
against the original (identical calls == no behavior change).

The writer lives in `engine/appc/hardpoint_override_writer.py` (replacing the
abandoned managed-block writer).

## Routing seam (unchanged from prior design)

```
resolve_override_target(ship) -> OverrideTarget
    game ship   → HardpointOverridesFileTarget  (engine/appc/hardpoint_overrides.py)  [v1]
    modded ship → mod's own file                [future — seam only, not built]
```
- `hardpoint_leaf_for_ship(ship)` = `ship.GetScript()` → import →
  `GetShipStats()["HardpointFile"]` (None-safe; mirrors host_loop `_ship_nif_path`).
- Save calls `resolve_override_target(ship).write(leaf, edits)`; the target owns
  the file I/O around the writer. The SPV/UI never names a path.

## SPV interaction

- **Right-click** a subsystem row → cursor context menu, extensible; MVP item
  **Set Radius…**. Right-click sets a context-target highlight; it does not
  change the 3D pin selection. Right-click over the list is chrome (never orbits
  or picks); `preventDefault` suppresses the browser menu.
- **Set Radius…** → small centred modal (`cp-*` styling) with the subsystem's
  current radius pre-filled → **Apply**.
- **Staging:** Apply records a pending edit `(subsystem, "SetRadius", value)`;
  the SPV property readout shows the pending radius and the row gets a dirty
  marker. Nothing is written; the live sim is not mutated (radius has no
  in-session visual, and leaving the live ship untouched keeps production/dev
  render byte-identical). The proof is persist→reload.
- **Save:** while edits are pending a **Save changes (N)** control is visible;
  clicking it opens a confirmation listing the pending edits ("Amend
  hardpoint_overrides.py?"). Only on confirm does it call the routed target.
- **Radius in the readout:** the property readout gains a `radius` row
  (`GetRadius`), showing the pending value when staged.
- Closing the SPV with unsaved edits discards the pending list (nothing was
  written; nothing was mutated live).
- Mouse: while a context menu or modal is open, `handle_input` suppresses
  orbit/pick (an `overlay_open` flag toggled by the CEF overlay).

## Testing

- **Writer (pure, no engine):** recording-proxy `read_models` on synthetic
  functions (single/multiple subsystems, multiple glow indices); `apply` a
  radius edit (replaces not duplicates; creates a block when absent); `emit`
  round-trips (`read_models(emit(m)) == m`); deterministic output (same model →
  same bytes); malformed emit aborts via `ast.parse`.
- **Conversion equivalence:** record the real file's setter calls, convert,
  re-record the converted file, assert per-subsystem call sequences are
  identical (no value/behavior change). Assert the converted module imports and
  `apply` is callable.
- **Routing:** `hardpoint_leaf_for_ship` reads `HardpointFile` (None-safe);
  `HardpointOverridesFileTarget.write` persists a radius edit to a temp file;
  `resolve_override_target` returns the game target.
- **Panel:** staging records a pending edit and shows it in the readout + dirty
  marker; Save routes `(leaf, edits)` and clears; close-without-save discards;
  overlay-open suppresses orbit.
- Full gate (`scripts/check_tests.sh`) green; live-verify under `--developer`:
  right-click Center Impulse → Set Radius → Apply → Save → confirm → inspect the
  regenerated `_galaxy` block, reload, confirm the new radius persists.

## Risks / out of scope

- **Whole-file regeneration** replaces the override file on every Save. Mitigated
  by deterministic emit (minimal diffs), `ast.parse` validation, atomic write,
  and the conversion-equivalence check. The file is committed source, so a bad
  write is recoverable from git.
- **Recording proxy assumptions:** relies on the ship functions being
  straight-line setter calls with `if p is not None` guards (true today). If a
  future override needs real logic, it can't be expressed as recorded setters —
  out of scope; flagged so it isn't silently mis-modeled.
- **Glow/light region editing** in the SPV is the next stage — the file
  structure, writer, routing seam, and staging model are built to carry it, but
  no glow-edit UI or new setter beyond `SetRadius` is added here.
- **Modded-ship routing** is structure-only.

## Future work

- SPV glow/light region editing: reuse the writer (`SetGlowRegion*` setters are
  already modeled), the routing seam, and the staging/Save model — add the edit
  UI and, if wanted, the 3D radius/volume visualization deferred from this MVP.
- Modded-ship `OverrideTarget`.
