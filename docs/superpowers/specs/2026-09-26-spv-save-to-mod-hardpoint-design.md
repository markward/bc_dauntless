# SPV: save mod-ship edits into the mod's own hardpoint file

**Status:** design approved in chat 2026-09-26; spec awaiting review.
**Builds on:** `2026-07-25-spv-hardpoint-value-override-editing-design.md`
(the routing seam, "modded ship → mod's own file [future — seam only]"),
`2026-09-23-spv-part-articulation-authoring-design.md` §2.2 ("two homes") and
§2.3 (the `stbc.exe` guard), `2026-09-08-mod-overlay-design.md`.

## 1. Goal

When the Ship Property Viewer saves edits for a ship whose hardpoint module was
loaded **from the mods directory**, write them **into that mod's
`ships/Hardpoints/<leaf>.py`**. `engine/appc/hardpoint_overrides.py` becomes the
home for **stock** ships only.

Success:
- Edit a mod ship in the SPV, Save, rebuild the ship → the edits are there, and
  they live in the mod's file (not in `hardpoint_overrides.py`).
- The author's file is otherwise byte-identical outside the lines we changed and
  one clearly marked machine-owned block at the end.
- The saved mod file still loads in stock `stbc.exe` (Dauntless-only data is
  guarded).
- Stock-ship saves are byte-for-byte unchanged in behaviour.

## 2. Decisions (from the brainstorm)

| # | Question | Decision |
|---|---|---|
| D1 | Where do Dauntless-only edits (glow regions, light emitters, articulated parts) go for a mod ship? | **Into the mod file**, guarded by an App-level `hasattr` so stock BC skips them. The mod file is the single home for its ship. |
| D2 | How is the mod file edited? | **Hybrid.** `SetPosition`/`SetRadius` are rewritten in place on the author's own call; everything else lives in one machine-owned managed block at the end of the file. |
| D3 | Existing overrides that apply to mod-loaded hardpoints? | **No change, no migration.** The override mechanism does not take effect for mod hardpoints today (Mark tried it); that stays as-is. |
| D4 | Backup? | **Yes.** A one-time pristine `<leaf>.py.orig` next to the file before its first write, never overwritten; every write is atomic via `.tmp`. |
| D5 | How does emitted code detect Dauntless? | **A versioned marker**, `App.DAUNTLESS_ENV = 1`, defined explicitly in the root `App.py` shim. Guards read `hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= N`, so later features can require a higher N. Replaces borrowing `hasattr(App, "ArticulatedPartProperty_Create")`, including in the existing part blocks. |

## 3. Routing

`engine/appc/override_routing.py:resolve_override_target(ship)` fills in its
reserved branch:

```
leaf = hardpoint_leaf_for_ship(ship)
path = mods.sdk_override(f"ships/Hardpoints/{leaf}.py")
return ModHardpointFileTarget(path) if path else HardpointOverridesFileTarget()
```

- `mods.sdk_override` is the existing "is this SDK-relative file supplied by a
  mod?" query (`engine/mods.py:624`), already used by `hull_volume._hardpoint_path`
  and `dev_missions/ship_preview.py`. It returns the mod's absolute path or None.
- Both targets keep the same `write(leaf, edits)` signature and the same edit
  tuple vocabulary (`(sub, setter, args)`, `(sub, "__region__", i, calls)`,
  `(sub, "__emitter__", i, calls)`, `(name, "__part__", calls)`), so the SPV
  panel's edit construction is unchanged.
- Each target exposes a human-readable `describe()` (e.g.
  `"mod file: <ModName>/…/Hardpoints/galaxy_refit.py"` /
  `"hardpoint_overrides.py"`).

**SPV feedback.** On a successful save the panel shows a toast via its existing
`_show_toast` naming the destination (`"Saved to " + target.describe()`). On a
failed write it shows a toast with the error in addition to today's
`dev_mode.log_swallowed` call, and — as today — keeps the staged edits.

## 4. The mod file after a save

### 4.1 In-place edits (`SetPosition`, `SetRadius`)

The rewriter parses the file with Python 3 `ast` and, at **module level**,
locates the subsystem's binding:

```python
PortWarp = App.EngineProperty_Create("Port Warp")   # any App.<X>Property_Create("<literal>")
PortWarp.SetPosition(-1.300000, -2.100000, -0.060000)
PortWarp.SetRadius(1.200000)
```

For an edit `(sub, setter, args)` with `setter in {"SetPosition", "SetRadius"}`:
find the module-level `V = App.<X>Property_Create("<sub>")` and the **last**
module-level expression statement `V.<setter>(...)` after it and before any
rebinding of `V`. Replace **only that call's source span** (using
`lineno/col_offset/end_lineno/end_col_offset`) with
`V.<setter>(<args formatted as %f, matching the SDK's style>)`. Nothing else in
the file changes.

Replacements are applied **bottom-up** by source offset so earlier spans stay
valid.

### 4.2 The managed block

Everything that is not an in-place edit lives in one block at the end of the
file:

```python
# >>> dauntless SPV edits -- machine-owned, regenerated on save; do not edit >>>
def _dauntless_spv(find):
    import App
    p = find("Port Warp")
    if p is not None:
        p.SetGlowRegionShape(0, ...)
        ...
    ...part blocks, exactly as _emit_part writes them...

if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:
    _dauntless_spv(lambda n: App.g_kModelPropertyManager.FindByName(n, App.TGModelPropertyManager.LOCAL_TEMPLATES))
# <<< dauntless SPV edits <<<
```

- **One emitter.** The function body is produced by the writer's existing
  `_emit_function` / `_emit_part` logic (parameterised on the function name), so
  the override file and the mod file share one code path for block text.
- **Guard.** The call site is guarded by the `DAUNTLESS_ENV` marker (§4.3).
  Stock `stbc.exe` defines the function (harmless) and never calls it, so
  unguarded `SetGlowRegion*` / `SetLightEmitter*` calls inside it never reach
  stock property objects.
- **Python 1.5 safe.** The block uses no f-strings, no `True`/`False`, no
  `import X as Y`; `lambda` and two-argument `hasattr` exist in 1.5.
- **Ordering.** The block is at the end of the file, after the author's
  `RegisterLocalTemplate` calls, so `find` sees every subsystem.
- **Empty model → no block.** If the merged model is empty, the markers and
  block are removed entirely.
- **Markers are the ownership boundary.** Only text between the markers is ever
  regenerated. A file with a start marker but no end marker (or two blocks) is
  refused with an error, never guessed at.

### 4.3 The `DAUNTLESS_ENV` marker

- Defined **explicitly** as a module-level int in the project-root `App.py`
  shim: `DAUNTLESS_ENV = 1`. It must be a real definition: the shim's module
  `__getattr__` answers *any* undefined name with a stub, so in Dauntless
  `hasattr(App, <anything>)` is always true and an undefined marker would
  compare as a stub, not a number.
- Emitted guard form (Python 1.5 safe — two-arg `hasattr`, short-circuit
  `and`): `if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 1:`.
  The required level is a parameter of the emitter; everything shipped by this
  spec requires 1.
- **Bump rule:** raise `DAUNTLESS_ENV` only when newly emitted hardpoint code
  needs engine surface that an older Dauntless lacks; the emitter then guards
  that code with the new level. Documented beside the definition in `App.py`.
- `_emit_part`'s existing `hasattr(App, "ArticulatedPartProperty_Create")`
  guard switches to the marker form, so there is one convention. The part
  blocks already in `engine/appc/hardpoint_overrides.py` are re-emitted with the
  new guard in the same change, and `tests/unit/test_bop_pose_migration.py`
  (which pins the old text) is updated with it.
- Not a measured BC constant: it must not be added to
  `constants_generated.py`; if `tests/unit/test_constant_surface.py` objects to
  an unmeasured name, it gets a documented exemption there.

### 4.4 Fallback into the managed block

A `SetPosition`/`SetRadius` edit that cannot be done in place goes into the
managed block instead (as a `find(name)` setter, which still wins because the
block runs last):

- the file does not parse under Python 3 (py1.5/py2-era syntax — then **all**
  edits go to the block, and the file's text outside the block is untouched);
- the subsystem is not bound by a module-level literal `Create` (loop-built,
  computed name, created inside a function);
- there is no existing `V.<setter>(...)` call to rewrite.

When an in-place edit succeeds, any stale entry for the same setter on the same
subsystem is **removed** from the managed-block model, so the two never
disagree.

## 5. The write sequence (`ModHardpointFileTarget.write`)

1. Read the file's source text.
2. If `<leaf>.py.orig` does not exist beside it, copy the file there (once;
   never overwritten).
3. Split off the existing managed block (by markers). Recover its model by
   executing the block's `_dauntless_spv` against the writer's existing
   recording `find` + `_RecordingApp` (same mechanism as `read_models`),
   yielding the same `{sub: [(setter, args)], "__parts__": {...}}` shape.
4. Apply the edits: in-place candidates per §4.1; everything else (and every
   §4.4 fallback) via the existing `set_setter` / `set_region` / `set_part`
   into the block model.
5. Emit the new block (or none) and append it to the author's text.
6. Verify before swapping:
   - if the original parsed under Python 3, the result must parse;
   - the managed block text on its own must parse;
   - the author's text **outside** the rewritten call spans and the block is
     identical to the original.
7. Write `<file>.tmp`, `os.replace` onto the file. Any failure at any step
   raises and leaves the mod file untouched.

## 6. Out of scope

- Migrating existing `hardpoint_overrides.py` entries (D3).
- Changing whether `hardpoint_overrides.apply` runs for mod-loaded hardpoints.
- Subsystem orientation (the SPV does not edit it).
- `GetShipStats`-level ship overrides (`ship_overrides.py`) — unchanged.
- Undo-to-original from the UI; `.orig` is a manual recovery path.
- Mods delivered as archives — mods are extracted folders today.

## 7. Testing

All unit-level with fixture mod files in `tmp_path`; the real `mods` index is
replaced by a fake for routing tests.

- **Routing:** mod-backed leaf → `ModHardpointFileTarget` with the mod path;
  stock leaf → `HardpointOverridesFileTarget`.
- **In-place:** a `SetPosition` / `SetRadius` edit changes only that call's span
  (full-text diff against the original shows exactly those lines).
- **Fallbacks:** subsystem with no `SetPosition`; loop-created subsystem;
  py2-syntax file (`print x`) — each lands in the managed block, author text
  untouched.
- **Managed block:** two successive saves → exactly one block with merged
  values; glow, emitter and part edits round-trip; emptying the model removes
  the block; malformed markers are refused.
- **Stale-entry removal:** a block `SetPosition` for a sub is dropped once an
  in-place `SetPosition` for it succeeds.
- **Safety:** `.orig` created exactly once and not overwritten on the second
  save; a forced bad emit leaves the file byte-identical and no `.tmp` behind.
- **End to end:** load the saved fixture through the real SDK loader and
  `LoadPropertySet`; the new position, radius and glow values reach the
  property objects.
- **Stock-BC compatibility:** exec the saved file against an `App` stand-in
  lacking `DAUNTLESS_ENV` and the Dauntless setters; it runs without raising
  and applies only the in-place SDK edits.
- **Marker:** `App.DAUNTLESS_ENV` is a real int `>= 1` (not a stub); a guard
  requiring level 2 is skipped under level 1.
- **SPV:** save on a mod-backed ship routes to the mod target and toasts its
  `describe()`; a failing write toasts the error and keeps the staged edits.
