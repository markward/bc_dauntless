# SPV Running Lights: add, place and edit — design

**Date:** 2026-10-22
**Status:** built, awaiting live verification (⚠️ **Not live-verified.**)
**Branch:** `feat/spv-running-lights` (worktree `.claude/worktrees/spv-running-lights`, from local `main` at 11744546f)
**Builds on:** `2026-10-14-ship-running-lights-design.md` (the renderer + `RunningLightSpec`),
`2026-07-25-spv-hardpoint-value-override-editing-design.md` (staged edits + Save),
`2026-09-26-spv-save-to-mod-hardpoint-design.md` (mod-file writer, `DAUNTLESS_ENV`),
`2026-09-28-spv-decal-editing-design.md` (click-to-place on the hull),
`2026-10-17-subsystem-physical-parents-design.md` (Physical tab).

---

## 1. What this is and why

Running lights (`BlinkingLightProperty`) are something only mod authors can add today.
The LC Intrepid has 19 and DCMPv2 has 10 per ship. Stock ships have none, because no
stock hardpoint attaches one. The Kessok Light declares a "Strobe" but its
`LoadPropertySet` never adds it to the ship.

Mark wants to add running lights to **stock ships** the way the Intrepid's author did,
saved through our hardpoint overrides. He also wants to edit them on mod ships.

The larger aim: this is another step towards the Ship Property Viewer (SPV) fully
replacing BC's SDK Model Property Editor (MPE). That aim sets two rules:
- **"Add" must be extensible.** Running Light is the first of many types the SPV will
  be able to add, not a one-off button.
- **Lights are first-class SPV objects.** They work with the same tools as everything
  else: move gizmo, Copy/Paste, Mirror, Pipette, Undo, Save.

### Goals

- Add a running light to any ship from the SPV. Choose its colour, size and blink, then
  click the hull where it goes.
- Edit, move, mirror and remove running lights. This covers lights the SPV added and a
  mod's own lights.
- Lights are drawn, blinking, in the SPV while editing.
- Save stock ships to `engine/appc/hardpoint_overrides.py` and mod ships into the mod's
  own hardpoint file. Both routes already exist.

### Non-goals

- **No "Running Lights" entry in the hardpoint file.** BC has no system or aggregator
  for blinking lights; each is a standalone property. The group row in the list is
  list-only (§3.1). Mark raised this; a parent entry would invent a mechanism BC never
  had.
- **No live update of the in-game ship already in the scene.** The edited ship picks up
  its lights on its next build, meaning the next mission load (§3.7). Only the SPV view
  previews live.
- **Not adopting the Kessok "Strobe".** It stays unattached, and nothing in this work
  may start attaching it (§4.1). Mark can add a fresh light to the Kessok Light instead.
- No other Add types yet. The modal's dropdown is built to take them, but only Running
  Light ships.
- No rotation or scale-gizmo editing of a light. A running light is a point. Size lives
  in the form.

### Anti-goals (would make this a failure even if it "works")

- **Stock BC breaks.** Everything emitted for a stock ship must be skipped by the
  original game, behind the existing `DAUNTLESS_ENV` guard.
- **Production behaviour changes for ships nobody edited.** A stock ship with no saved
  lights must load and render byte-identically. A mod ship's lights must behave as now
  unless edited.
- **A UI that only fits running lights.** Examples: an "Add Running Light" button, or
  per-kind `if` ladders in the panel. `test_spv_no_kind_ladders.py` already forbids the
  ladders.
- **A light that appears in the target list or can be targeted.** Lights are always
  non-targetable (Mark).

## 2. The approved flow (Mark, 2026-10-22, from the mockups)

The mockups were built from the SPV's real stylesheet and colour wheel. They are in
`.superpowers/brainstorm/8952-1792670287/content/add-running-light.html` in the main
checkout, which is gitignored. Mark: "pretty much bang on".

1. **"+ Add" row** sits at the foot of the Functional tab's subsystem list. It is always
   the last row.
2. Clicking it opens an **Add** modal (`spv-modal`) with a **Type dropdown**. CEF OSR
   draws no native `<select>`, so the dropdown is drawn in the page from the SPV's
   context-menu look (`spv-ctxmenu` / `spv-ctxmenu__item`), the way the Bridge Editor's
   Add Modifier menu does it. Running Light is the only entry for now.
3. Picking **Running Light** turns the modal into the **Running Light form**, with no
   Next button. The dropdown stays at the top so you can change type. The form holds:
   - **Name** (text field via the text-capture contract)
   - **Colour wheel**: the shared `ColourWheel` from `js/colour_wheel.js`
   - **Size** stepper
   - **Steady / Blinking** toggle (`spv-shape-row` buttons)
   - When Blinking, **Every** (period, s) and **On for** (duration, s) steppers
   - **Cancel** and **Place on hull** buttons
4. **Place on hull.** The modal closes and a hint reads "Click the hull to place
   <name> · Esc cancels". The next hull click places the light; it appears under the
   Running Lights group and is **selected**, so the move gizmo, Mirror, Copy/Paste and
   Pipette work on it at once. A miss shows the decal flow's miss hint and stays in
   placing mode. **Esc** or Cancel leaves placing mode with nothing added.
5. **Right-click a light → Edit… / Remove.** Edit reopens the same form, titled "Edit
   Running Light" and filled with the light's values, with Apply instead of Place on
   hull. Remove stages a removal.

The **Running Lights** group row is a list-only accordion row, like Phasers, with its
eye always shut. It appears only when the ship has at least one light, counting pending
adds and excluding pending removals.

## 3. SPV behaviour in detail

### 3.1 List rows

- The Functional list gains two synthetic rows after the descriptor rows (end of
  `_subsystem_rows`):
  - the **Running Lights** group, whose children are one row per light in property-set
    order, then pending adds in creation order;
  - the **+ Add** row.
- Neither is a descriptor. Pins, `_descriptors`, Save indexing and `_physical_entries`
  key on descriptor index and must not see them.
- The group needs its **own expand/collapse key**; `toggle_group:<index>` is
  descriptor-keyed today. Collapsed or expanded state follows the same session rules as
  other groups.
- Light rows carry no condition bar. They show the shut eye, the dirty marker
  (`spv-sys-row--dirty`) when staged, and the chosen style when selected.
- The **Physical tab** already lists running lights (`key "light:<name>"`). It must list
  pending adds too, and drop pending removals. Physical-parent edits on a pending light
  stage onto that light.
- JS `spvRowHtml` gains row kinds for the group, a light, and the Add row. Today
  anything that is not light or emitter is drawn as a subsystem.

### 3.2 Selection, the gizmo and tools

- Selecting a light row makes it the **edit target** (§5), shown with the move gizmo at
  the light's position.
- Selecting a light by clicking it in the 3D view is **not required**. The builder may
  add it if it falls out cheaply from the pin-pick path.
- The selected light needs a visible marker in the 3D view beyond the gizmo, because a
  2.5 px blinking dot can be "off". **Builder's choice how.** The existing selected
  radius sphere, sized to the light, is the obvious reuse.
- **Move gizmo, coordinate panel and Copy/Paste** behave as for mounts. Coord kind is
  "mount", so a position can be pasted between a light and a subsystem.
- **Rotate and Scale** are unavailable for lights, greyed as for other kinds that lack
  them.
- **Mirror** creates a new light at −x and selects it, the decal precedent
  (`DecalTarget.mirror`). It does not flip the selected light in place. The copy takes
  colour, size and blink. Its name swaps a leading "Port"↔"Star"/"Starboard" word if
  present; otherwise it gets the next free "<name> 2", "<name> 3" and so on. If the
  swapped name is already taken (the Intrepid ships both halves of most nav pairs),
  the swapped name is numbered ("Port Dorsal Nav Static 2"). Names must stay unique
  per ship. *(Builder-check call.)*
- **Physical parent when a light moves** *(builder-check call, following existing SPV
  behaviour)*:
  - **Mirror** re-derives the copy's parent the way decals do
    (`_decal_with_derived_shape`), so a left-wing light's copy lands on the right wing.
    This applies only on a rigged ship. If the trace misses, the copy is left on Auto.
  - **Gizmo, Paste and Pipette** keep the light's parent, as they do for subsystems
    today. A wrong parent after a big move is fixed on the Physical tab.
- **Pipette.** A light as target and a light as source copies position, colour, size,
  period and duration. A subsystem, light-volume or emitter as source copies position
  only. A light as source onto another kind copies position only. Picking a light row
  while the pipette is armed must count as a source pick; today sources are keyed on
  `select_*` actions, so the light-row select action joins that set.
- **Undo** covers add, edit, move, mirror and remove. It works by snapshotting the
  pending state, as now.
- **Pose lock.** While an articulated pose preview locks mount editing, light editing is
  locked too. Lights are authored in the rest frame, like mounts.

### 3.3 Placing

- Reuse the decal hull pick (`spv_decals_pane._decal_hull_hit`). It returns the body
  point, the normal and the hit mesh. Move it somewhere shared if that is cleaner;
  that's the builder's choice.
- ⚠️ **Units.** Decal hits are in **NIF units**. Running-light positions are
  **unscaled GU** (the emitter-light and hardpoint convention). Convert with
  `instance_scale(ship)` (= `BC_MODEL_SCALE × GetScale()`).
- **Lift off the surface:** place the light a small distance out along the hit normal,
  so the depth-tested disc isn't buried in the hull. The amount is the builder's call;
  start around the light's drawn radius and tune live with Mark.
- **Physical parent:** on a **rigged** ship (one with articulated parts), when the hit
  mesh maps to a model part, stage `SetPhysicalParent(<part>)` for the new light. This
  is explicit membership, Mark's stated preference over the nearest-mesh guess. On an
  unrigged ship, set nothing.
- **Esc** cancels placing. `handle_key_esc` gains this branch next to the pipette
  disarm. The decal add has no Esc today; adding it there too is welcome but not
  required.

### 3.4 The form's values

| Field | Hardpoint setter | Default for a new light | Range / step (builder may tune) |
|---|---|---|---|
| Name | `BlinkingLightProperty_Create(name)` | "Running Light N", first free N | unique per ship; non-empty |
| Colour | `SetColor(TGColorA)`, alpha 1 | white | hue/sat wheel, V = 1 |
| Size | `SetRadius` | 1.0 (Intrepid's value) | 0.1 – 5.0, step 0.1 |
| Steady / Blinking | `SetDuration(0)` = steady | Blinking | — |
| Every (period) | `SetPeriod` | 3.0 s | 0.5 – 10 s, step 0.5 |
| On for (duration) | `SetDuration` | 0.5 s | 0.1 s up to the period, step 0.1 |

- Steady hides the two timing rows and saves duration 0. It keeps a period, because BC
  files always carry one; 3.0 if unset.
- The colour wheel has no brightness control. That is fine: the renderer's level and
  distance fade govern brightness, and `RunningLightSpec` drops alpha.
- **Name** can be set on Add only. Edit shows it read-only. Renaming a mod's light would
  mean rewriting the mod's `LoadPropertySet`, which nothing here touches.
- Intrepid lights also call `SetOrientation` and `SetTextureName` (a NanoFX
  `Blank.tga`). Neither affects our renderer. New lights **omit both**: they are only
  ever seen by Dauntless, which ignores them.

### 3.5 Live preview in the SPV

- ⚠️ **Today the SPV draws no running lights.** The running-light pass runs inside
  `render_space_vfx`, which `host_bindings.cc` skips under `viewer_mode`
  (`g_hologram_only_mode`). This work adds drawing the **viewed ship's** lights in
  hologram mode.
- The drawn lights are the **effective** ones: saved state with pending edits, adds and
  removals applied. They blink with real timing and are re-sent to the renderer when
  that set changes.
- Use the existing per-instance API (`set_running_lights(iid, specs, phase)`; an empty
  list clears).
- When the SPV closes, restore the ship's real (spawn-time) lights, or clear them if it
  had none.
- **Production unchanged:** with the SPV closed, the running-light path is
  byte-identical.

### 3.6 Save

- The Save bar counts light changes. The confirm modal lists each light added, edited
  or removed by name, in the style of the existing per-subsystem tally.
- Save routes through `resolve_override_target(ship)`, as today:
  - a stock leaf goes to `hardpoint_overrides.py`;
  - a mod-supplied leaf goes to the mod's own file (§4.3).
- After a successful Save, the SPV keeps showing the saved state for the rest of the
  session. This is the existing `_saved_*` pattern. The in-game ship updates on its
  next build (§3.7).

### 3.7 Stock saves take effect on the next mission load (Mark, 2026-10-22: "yes, this is really annoying")

- **Today** a stock-ship Save takes effect only after a **game restart**.
  - `engine/appc/hardpoint_overrides.py` is imported once, by
    `sdk_overrides.on_sdk_module_exec`.
  - Nothing re-reads it after `HardpointOverridesFileTarget.write`, so the next
    `CreateShip` applies the stale in-memory `OVERRIDES`.
  - Mod-file saves already apply on the next load, because SDK `reload(mod)` re-reads
    the mod's file.
- **Change:** after a successful stock write, re-read the overrides module, so the next
  ship build applies the saved file. This covers **every** SPV stock edit (radius,
  light volumes, emitters, parts, physical parents), not just running lights.
- A failed write must leave the in-memory overrides as they were.
- A re-read that raises (it shouldn't, since the writer `ast.parse`-validates) must
  report through the existing Save error toast. It must never leave the module half
  loaded.
- Anything else that captured the overrides module, or values derived from it, at
  import must see the new values. The builder audits this, for example the
  `articulated_part` snapshots, which are taken per exec and so are already fresh.

## 4. Runtime: getting a light onto a ship

### 4.1 Attaching a Dauntless-created light (new mechanism)

- **No mechanism today puts an override-created property into a ship's property set.**
  SDK `CreateShip` runs `ClearLocalTemplates` → `reload(mod)` (our override hook runs
  here) → `mod.LoadPropertySet(pset)` → `SetupProperties`.
- `LoadPropertySet` adds only the names it already lists (`FindByName` + `AddToSet`).
  Articulated parts dodge this by being snapshotted from the template registry
  (`articulated_part.snapshot_for_leaf`) and never read from the set.
- Running lights **are** read from the set:
  `running_lights.light_properties` → `GetPropertiesByType(CT_BLINKING_LIGHT_PROPERTY)`.
  So a new light must be **added to the set**.

**Requirement:**
- A light created by Dauntless-authored hardpoint code (stock override or mod-file SPV
  block) ends up in the ship's property set before `SetupProperties` and before
  `_register_running_lights` reads it.
- Every other registered-but-unlisted template is left alone. In particular the Kessok
  "Strobe" must **not** become attached.
- So the mechanism has to know which templates Dauntless code created. A blanket "add
  every `BlinkingLightProperty` template" rule would light up the Kessok Strobe at the
  hull origin.

**My recommendation (builder may choose otherwise if it meets the requirement):**
- The emitted guarded block, after `RegisterLocalTemplate(light)`, also calls a new
  Dauntless-only call that queues the name for attachment per leaf. An example is
  `App.DauntlessAttachTemplate(light)`; the builder picks the name.
- The engine drains the queue right after `LoadPropertySet` (or at the top of
  `SetupProperties`), adding each queued template with `AddToSet("Scene Root", prop)`.
  That is the same call the SDK's own load functions use.
- This is new engine surface used by emitted code, so **bump `App.DAUNTLESS_ENV` to 2**
  and guard these blocks with `>= 2`. Then an older Dauntless build that lacks the call
  skips the block instead of raising.
- Stock BC skips the block via `hasattr(App, "DAUNTLESS_ENV")`, as today.

### 4.2 Removing a light

- A **mod's** light: `LoadPropertySet` guards with `if (prop != None)` (verified on the
  Intrepid). So a guarded block calling
  `App.g_kModelPropertyManager.RemoveTemplate(<found light>)` before `LoadPropertySet`
  stops it being attached. `RemoveTemplate` exists in both the SDK and our shim.
- The SDK has no "remove from set", and none is needed. **Verify** the guard holds for
  DCMPv2's load function before relying on it; if a mod's loader does not guard
  `None`, fall back to a filtered removal at attach time.
- A light **the SPV created**: removal deletes its creating block on the next Save,
  because the writer regenerates the whole managed function.

### 4.3 Writers

**`hardpoint_override_writer.py` (stock).** It models created properties only for
articulated parts (`__parts__`, `_emit_part` hard-codes
`App.ArticulatedPartProperty_Create`). Its read-back runs each function against a fake
`_RecordingApp` that has only `ArticulatedPartProperty_Create`. Needed:
- **Created running lights** as a modelled kind: emit, read back, and edit through
  `apply_edit`. Emit in BC's own idiom where it exists:
  - `App.BlinkingLightProperty_Create(name)`
  - position, colour via `App.TGColorA()` + `SetRGBA`
  - `SetRadius`, `SetPeriod`, `SetDuration`, `RegisterLocalTemplate`
  - then the §4.1 attach call
  The fake App must grow what the read-back executes (`BlinkingLightProperty_Create`,
  `TGColorA`, `TGPoint3` if used, `RemoveTemplate`, the attach call).
- **Edits to an existing light** (a mod's) as setter calls on `find(name)`. `SetColor`
  needs a colour object, and `_lit` takes only scalars. Either emit the
  `TGColorA`/`SetRGBA` form, or have the engine's `BlinkingLightProperty.SetColor` also
  accept four floats inside the guarded block. Builder's choice; the emitted text must
  round-trip through `read_models` (`test_hardpoint_overrides_canonical.py`).
- **Removal** of an existing light (§4.2).
- The file stays machine-owned and canonical: `emit(read_models(module)) == source`.

**`mod_hardpoint_writer.py` (mod files).** Its managed block reuses `_emit_function`, so
created-light support comes along. Needed beyond that:
- **In-place rewrites** of a mod light's literal values follow the existing rule
  (`SetRadius` literal yes). Anything else goes to the managed block. The Intrepid's
  `SetPosition(TGPoint3 var)` already falls back to `p.SetPosition(x,y,z)` in the block,
  and the engine accepts that.
- **Never edit the mod's `LoadPropertySet`.** Adds attach via §4.1; removals work via
  §4.2.
- Python 1.5 rules apply to everything emitted (spec 2026-09-26 §4.2-4.3: no f-strings,
  no `True`/`False`, no `import X as Y`). Use `%f` formatting and finite numbers only.

**Mod ships get the same block.** A mod leaf skips `hardpoint_overrides.apply`, but the
mod-file block runs at the end of the mod module's own exec, before `LoadPropertySet`.
So §4.1 and §4.2 work identically there.

## 5. Edit-target integration

Add a **`RunningLightTarget`** adapter in `engine/ui/spv_edit_targets.py` and register it
in `_ADAPTERS`. No kind ladders go in the panel (`test_spv_no_kind_ladders.py`).

**The adapter:**
- **Key:** by light **name**. Names are unique per ship. Pending adds use their chosen
  name.
- **Implements:** `position`/`set_position`, `gizmo_frame`, `axis_drag_*`,
  `coord_kind = "mount"`, `colour`/`set_colour`, the light fields, a `mirror` that
  creates a twin, and `pipette_fields_from`/`pipette_arms`.
- **Lacks:** `rotate_*` and `scale_*`, so those tools grey.

**Staging:** a new `_pending_running_light` dict (and a `_saved_running_light` twin),
keyed by name. Values hold the full light spec, or a removal sentinel. It is wired into
everything the other staging dicts are wired into:
- `_snapshot_pending` / `_restore_pending` (undo)
- `render_payload`
- `pending_count` / `_pending_edits`
- Save edit building
- `_active_transform_target` (selection precedence: a selected light behaves like a
  selected emitter)
- the pipette source keys

**Add modal, JS side:**
- New dispatch actions, named in the existing `ship-property-viewer/<action>` style.
  The builder names them; the list must cover:
  - open Add
  - choose type
  - begin placing with a spec
  - cancel placing
  - edit a light's spec
  - remove a light
  - select a light
  - toggle the group
- Running Light's form is one entry in a **type → form** registry on the JS side, so
  the next type adds an entry rather than a branch.
- The Python side validates every field: finite numbers in range, a unique non-empty
  name, and a duration not over the period. It refuses bad input with the existing
  toast or error idiom.
- Light actions join `_MOUNT_SELECT_ACTIONS` (or its equivalent) so the pose lock
  refuses them.

## 6. Testing (focused files only; no gate, no whole-suite runs)

Run only the test files for the change, never `tests/` or `tests/unit` whole (CLAUDE.md
"Test gate"). The gate runs only when Mark merges into main.

- **Writer:**
  - created-light emit + read-back round trip;
  - edit of an existing light (including colour);
  - removal;
  - canonical-form test still green;
  - every emitted file passes `ast.parse` and a Python 1.5 syntax check (the existing
    mod-block test's stock-BC `App` e2e pattern).
- **Attach mechanism:**
  - an override-created light reaches `GetPropertiesByType` and `lights_for`;
  - the Kessok Strobe does **not**;
  - a ship with no Dauntless lights builds an identical property set (regression pin);
  - a removed Intrepid light is absent.
- **Panel:**
  - add → place (with a mocked hull hit), including the NIF→GU unit conversion;
  - Esc cancels;
  - edit; remove; undo of each;
  - mirror makes a named twin at −x;
  - pipette light→light copies all fields, light→subsystem copies position only;
  - pose lock refuses light edits;
  - Save produces the right edits for stock and mod routes.
- **In-session reload (§3.7):** after a stock Save, a fresh `CreateShip` of that class
  applies the new override, with no process restart. A failed write leaves the old
  overrides in force.
- **Payload:** each new field is tested as present **in the payload**. That is where the
  Edit Light bug lived: the descriptor had the field, the row didn't.
- **CEF:** the JS row kinds, the Add modal and dropdown, the form, and Steady hiding the
  timing rows. Follow the pattern of the existing `*_cef.py` / node-run JS tests.
- **Native:** hologram mode draws the viewed ship's running lights. With the SPV closed,
  output is unchanged.

## 7. Live verification (Mark, in the worktree)

Run `cd <worktree> && ./build/dauntless --developer`. Mark tests in the worktree.

1. Galaxy:
   - add a red port nav light by clicking the saucer rim;
   - Mirror it, then make the copy green;
   - add a steady white light and a blinking strobe;
   - Save.
2. Reload the mission **without restarting the game**. The lights appear on the in-game
   Galaxy, blinking as authored (§3.7). Also check that an older kind of stock edit,
   such as a radius change, now shows on reload too. Original BC is unaffected (an
   optional check in the real game).
3. Intrepid:
   - recolour one of its lights;
   - move one;
   - remove one;
   - Save, reload, and confirm all three.
4. Undo through a run of edits. Esc out of placing.

Record the result in the spec and memory as soon as Mark confirms it.

## 8. Builder's latitude (decided here as "your call")

These are left to the builder:
- the attach-call name and exact hook point (§4.1), within the stated requirement;
- the colour-setter form (§4.3);
- the selected-light marker (§3.2);
- the surface lift amount (§3.3);
- the action names (§5);
- stepper ranges (§3.4);
- whether the hull-pick helper moves to a shared module;
- whether 3D click-selection of lights is added.

## 9. Risks and open points

- **DCMPv2's loader guard** (§4.2) is unverified. If it doesn't guard `None`, removal
  needs the fallback.
- **Severed or articulated parts.** A light the SPV adds to a part of a rigged ship
  needs the existing re-send-on-pose path to pick it up. It does if it is in the set
  with a physical parent; check this on the Bird of Prey's wings.
- **Hologram-mode depth.** The running-light pass is depth-tested against the scene.
  In hologram mode the hull is hidden, so the lights may need the hologram's depth or
  none. Verify they are neither buried nor floating in front of the far side of the
  hull.

## Build

Branch `feat/spv-running-lights`, commits in order:

- `146e85377` docs(spv): running lights add/place/edit design
- `5d5ba6602` docs(spv): running lights implementation plan (12 tasks)
- `c8c4a901c` feat(appc): attach queue for Dauntless-created hardpoint templates (DAUNTLESS_ENV 2)
- `e8d8c71ff` feat(spv): hardpoint override writer emits running-light create/edit/remove blocks
- `0411f44bb` fix(spv): stable light emit order and Python 1.5 keyword-safe identifiers
- `122c3adb7` fix(spv): reject partial running-light specs; make stability test non-vacuous
- `849bae536` feat(spv): mod hardpoint writer routes running-light edits to the managed block
- `43b2e0d3e` feat(spv): stock hardpoint saves take effect on the next mission load
- `fb9f84ee9` feat(spv): draw the hologram ship's running lights in viewer mode
- `60a35fdd2` feat(spv): pure running-light editor helpers
- `b3f5a5af5` feat(spv): running-lights pane mixin - staging, rows, select, save, Physical tab
- `143278ed3` fix(spv): any other selection takes the gizmo off a running light
- `045058ddd` feat(spv): RunningLightTarget edit adapter - move, coords, mirror, pipette, lock
- `9744f8207` feat(spv): running-light add / place / edit / remove flow
- `2daa345da` feat(spv): live running-light preview + restore on close
- `7713e28f3` fix(spv): articulated re-send no longer overwrites the running-light preview
- `683c0bef0` feat(spv): running-light rows, Add modal with Type dropdown, light form and menu
- `9283e09d1` fix(spv): menu close keeps a just-opened modal's overlay; edit keeps colour
