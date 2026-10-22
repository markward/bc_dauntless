# SPV Running Lights Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Ship Property Viewer can add, place, edit, move, mirror and remove ship running lights, saved to stock overrides or the mod's own hardpoint file. Stock saves take effect on the next mission load.

**Architecture:**
- **Runtime.** A Dauntless-only attach queue gets SPV-created `BlinkingLightProperty`
  templates into the ship's property set; BC's `LoadPropertySet` only adds names it
  lists.
- **Writer.** Both hardpoint writers model running lights as a new kind of entry.
- **SPV.** A new `RunningLightsPaneMixin` (like `DecalsPaneMixin`) owns the staging and
  the add/place flow, with a `RunningLightTarget` edit adapter.
- **Native.** In viewer mode the renderer draws the hologram ship's lights on a wall
  clock.

**Tech Stack:** Python 3.11 (engine, SPV), C++17 + GL 4.1 (renderer, pybind11 bindings), CEF page JS/CSS, pytest, gtest/ctest.

**Spec:** `docs/superpowers/specs/2026-10-22-spv-running-lights-design.md` (read it first; section refs below are to it).

## Global Constraints

- **Branch / worktree:** `feat/spv-running-lights` in
  `.claude/worktrees/spv-running-lights`. Commit there with explicit pathspecs only.
- ⛔ **No destructive git** (CLAUDE.md "Shared checkout"):
  - never `git checkout -- / restore / stash / clean / reset --hard / add -A / add .`;
  - to mutate a file for a probe: `cp` to back it up, `cp` to restore, then `diff`.
- ⛔ **Run only the focused test files named in your task.** Never `tests/`,
  `tests/unit`, `tests/ui` whole, and never `scripts/check_tests.sh` (CLAUDE.md "Test
  gate").
  - Python: `uv run pytest <files> -q`.
  - C++: `cmake --build build -j && ctest --test-dir build -R <regex>`.
- **Worktree build** (the first task that needs C++ does it, once):
  ```
  U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none
  cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug \
    -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U \
    -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION
  ```
  - Never change BUILD_TYPE.
  - Never run cmake from `native/`.
- **Units:** running-light positions are **unscaled GU, body frame** (the
  emitter-light convention). Never name a variable `*_m`.
- **Python 1.5** for every emitted hardpoint line:
  - no f-strings, no `True`/`False`, no `import X as Y`;
  - `%f`/`repr` floats only;
  - finite numbers only.
- **`App.DAUNTLESS_ENV` becomes `2`.** Every running-light block emits the guard
  `env_guard(2)`. Existing part blocks keep `env_guard()` (level 1).
- **No per-kind ladders** in `ship_property_viewer_panel.py`, `spv_decals_pane.py`,
  `ship_property_viewer.py` (`tests/unit/test_spv_no_kind_ladders.py`). Kind behaviour
  lives in adapters or the new mixin.
- **Production byte-identical** when the SPV is closed and no ship has Dauntless-created
  lights.
- **Lights are never targetable:** they are never descriptors and never pins.
- **Canonical light spec dict:**
  ```
  {"name": str, "position": (x, y, z), "color": (r, g, b), "radius": float, "period": float, "duration": float}
  ```
  `duration <= 0` means steady.
- **Action strings:** `ship-property-viewer/rl/<verb>[:<json>]`, with JSON args, since
  names contain spaces. The verbs, fixed for all tasks:
  - `rl/place_begin:{spec}`
  - `rl/place_cancel`
  - `rl/edit:{"name":…,"spec":{…}}`
  - `rl/remove:{"name":…}`
  - `rl/select:{"name":…}`
  - `rl/toggle_group`

## Review Focus

1. **A name with quotes, unicode or Python keywords** ("Port \"Nav\"", "class", "Ünïcode")
   must round-trip through both writers as a safe identifier plus a string literal.
   *Test owner: Task 2* (`test_light_name_is_quoted_and_identifier_safe`).
2. **Adding a light whose name already exists in the ship's file** (a mod light or a
   saved one) must be refused, never silently create a duplicate template.
   *Test owner: Task 6* (`test_validate_rejects_taken_name`) and Task 9
   (`test_place_begin_refuses_taken_name`).
3. **Removing a light that was created earlier and saved** must delete its create
   entry, not emit a `RemoveTemplate` for a light the file itself creates.
   *Test owner: Task 2* (`test_remove_of_created_light_drops_entry`).
4. **Undo across placement:** after placing a light, Undo removes it, and Undo of an edit
   restores the previous colour and position. *Test owner: Task 9*
   (`test_undo_removes_placed_light`).
5. **A ship that had no lights at spawn, opened in the SPV with lights added, then
   closed** must leave native with no lights for that ship (no orphan preview).
   *Test owner: Task 10* (`test_close_clears_preview_for_unlit_ship`).

---

### Task 1: Attach queue for Dauntless-created templates + `DAUNTLESS_ENV = 2`

**Files:**
- Create: `engine/appc/attach_templates.py`
- Modify: `App.py:339-347` (`DAUNTLESS_ENV = 2`, expose `DauntlessAttachTemplate`)
- Modify: `engine/appc/sdk_overrides.py` (Hardpoints branch)
- Test: `tests/unit/test_attach_templates.py`; update `tests/unit/test_dauntless_env_marker.py` if it pins `1`

**Interfaces:**
- Produces:
  - `attach_templates.queue(prop) -> None`, also bound as `App.DauntlessAttachTemplate`;
  - `attach_templates.drain() -> list`;
  - `attach_templates.wrap_load_property_set(module, props: list) -> None`;
  - `App.DAUNTLESS_ENV == 2`.
- **Hook order** in `on_sdk_module_exec` for `ships.Hardpoints.<leaf>`, after the
  existing apply and snapshot:
  ```
  queued = attach_templates.drain()
  if queued: attach_templates.wrap_load_property_set(module, queued)
  ```
  Mod files queue during their own exec. Stock overrides queue inside `apply`. Both
  happen before this point.
- **The wrapper** replaces `module.LoadPropertySet` with a function that:
  - calls the original;
  - then calls `pObj.AddToSet("Scene Root", prop)` for each queued prop not already in
    the set (identity check over `GetPropertyList()`).
  It is installed fresh per exec, so it needs no idempotence sentinel.

- [ ] **Step 1: Write failing tests** in `tests/unit/test_attach_templates.py`:
  - `test_queued_light_is_added_after_load_property_set`:
    - a fake module with `LoadPropertySet(pObj)` that adds only "Hull";
    - queue a `BlinkingLightProperty("Port")` and wrap;
    - call `module.LoadPropertySet(pset)`;
    - assert `[p.GetName() for p in pset.GetPropertiesByType(App.CT_BLINKING_LIGHT_PROPERTY)] == ["Port"]`.
  - `test_drain_empties_queue`: assert that `drain()` twice returns `[...]`, then `[]`.
  - `test_unqueued_registered_template_is_not_attached`: register a
    `BlinkingLightProperty("Strobe")` without queueing (the Kessok case); after
    LoadPropertySet it is absent.
  - `test_already_present_prop_not_added_twice`.
  - `test_dauntless_env_is_2`: `App.DAUNTLESS_ENV == 2` and
    `App.DauntlessAttachTemplate is attach_templates.queue`.
  - `test_kessoklight_build_unchanged` (integration, SDK-backed):
    - build the stock Kessok Light property set through the real loader path (follow
      `tests/unit/test_running_lights.py`'s SDK-backed pattern);
    - assert no `BlinkingLightProperty` in the set.
- [ ] **Step 2: Run them; expect them to fail.** Run
  `uv run pytest tests/unit/test_attach_templates.py -q`. Expect ImportError or
  AssertionError.
- [ ] **Step 3: Implement** the module, the `App.py` changes and the hook.
  - Update the `DAUNTLESS_ENV` comment block to note level 2 = running-light blocks
    (spec 2026-10-22 §4.1).
- [ ] **Step 4: Run** the new file plus `tests/unit/test_dauntless_env_marker.py` and
  `tests/unit/test_running_lights.py`. Expect PASS.
- [ ] **Step 5: Commit**
  `git add engine/appc/attach_templates.py App.py engine/appc/sdk_overrides.py tests/unit/test_attach_templates.py tests/unit/test_dauntless_env_marker.py && git commit -m "feat(appc): attach queue for Dauntless-created hardpoint templates (DAUNTLESS_ENV 2)"`

### Task 2: Stock override writer — running-light entries

**Files:**
- Modify: `engine/appc/hardpoint_override_writer.py`
- Test: `tests/unit/test_hardpoint_override_writer_lights.py` (new)
- Re-run: `tests/unit/test_hardpoint_overrides_canonical.py`, `tests/unit/test_hardpoint_override_writer*.py`

**Interfaces:**
- Consumes: `App.DauntlessAttachTemplate` (Task 1); `env_guard(2)`.
- Produces:
  - **Model key** `_LIGHTS_KEY = "__lights__"` beside `__parts__`:
    `{name: entry}`. An entry is `{"op": "create"|"edit"|"remove", <spec fields>}`.
    Spec fields are `position`, `color`, `radius`, `period`, `duration`; an `edit`
    entry carries only the fields being set.
  - **Edit tuple** `(name, "__running_light__", {"spec": spec_or_None, "new": bool})`,
    handled by `apply_edit` → `set_running_light(models, leaf, name, spec, new)`:
    - spec `None` and name has a `create` entry → delete the entry;
    - spec `None` otherwise → `{"op": "remove"}`;
    - name has a `create` entry → replace its fields;
    - `new` → `create`;
    - else → `edit` with all fields.
  - **Emission order** inside a ship's function:
    1. `import App` (when any parts or lights);
    2. create blocks;
    3. subsystem `find` blocks;
    4. edit/remove light blocks;
    5. part blocks.
    Create blocks must come first so a later `find(name)` (`SetPhysicalParent` from the
    Physical tab) sees the new template.
  - **Exact emitted create block** (8-space body under the guard; the variable comes
    from `_ident_for(name)`):
    ```
        if hasattr(App, "DAUNTLESS_ENV") and App.DAUNTLESS_ENV >= 2:
            port_nav_light = App.BlinkingLightProperty_Create("Port Nav Light")
            port_nav_light.SetPosition(0.5, 1.0, -0.25)
            port_nav_light_color = App.TGColorA()
            port_nav_light_color.SetRGBA(1.0, 0.25, 0.2, 1.0)
            port_nav_light.SetColor(port_nav_light_color)
            port_nav_light.SetRadius(1.0)
            port_nav_light.SetPeriod(3.0)
            port_nav_light.SetDuration(0.5)
            App.g_kModelPropertyManager.RegisterLocalTemplate(port_nav_light)
            App.DauntlessAttachTemplate(port_nav_light)
    ```
  - **Edit block:**
    - `p = find("<name>")`, then under `if p is not None:` the same setter lines for the
      fields present;
    - colour via a local `c = App.TGColorA(); c.SetRGBA(...); p.SetColor(c)`;
    - guarded `>= 2`.
  - **Remove block:** guarded `>= 2`;
    `p = find("<name>")` / `if p is not None:` /
    `App.g_kModelPropertyManager.RemoveTemplate(p)`.
  - **`_RecordingApp` grows:**
    - `DAUNTLESS_ENV = 2`;
    - `BlinkingLightProperty_Create`, which records into the lights map;
    - `TGColorA`, which returns a recorder whose `SetRGBA` args are captured;
    - `DauntlessAttachTemplate`, a no-op;
    - `g_kModelPropertyManager.RemoveTemplate(p)`, which records a remove for the
      recorder's name.
    `record_fn` rebuilds `__lights__` entries from those recordings, so
    `emit(read_models(m)) == source` holds.
  - **Identifier collision:** two names mapping to the same `_ident_for` value get `_2`,
    `_3` suffixes in emission order. This is new: lights are user-named.

- [ ] **Step 1: Write failing tests:**
  - `test_create_light_emits_exact_block`: compare against the block above.
  - `test_create_light_round_trips`: `read_models_from_source(emit(m)) == m`.
  - `test_edit_light_emits_find_block_with_colour`.
  - `test_remove_of_created_light_drops_entry`: create, then
    `(name, "__running_light__", {"spec": None, "new": False})` → no `__lights__` key in
    the emit.
  - `test_remove_of_existing_light_emits_remove_template`.
  - `test_create_blocks_precede_find_blocks`: a light plus `SetPhysicalParent` on the
    same name; the create line index is less than the `find("<name>")` line index.
  - `test_light_name_is_quoted_and_identifier_safe`: names `'Port "Nav"'`, `"class"`,
    `"Ünïcode"`, `"a b"` and `"a-b"` (colliding identifiers); emit parses and round-trips.
  - `test_emitted_lights_are_py15_safe`: no `True`/`False`/f-strings in the light
    blocks; reuse the existing py15 check helper if `test_mod_hardpoint_e2e.py` has one.
  - `test_executing_emit_attaches_light`: exec the emitted overrides text against the
    real App shim; run `apply(leaf)` after registering a template manager state; assert
    `attach_templates.drain()` holds the created property with the right
    colour/radius/period/duration.
- [ ] **Step 2: Run them; expect failure.**
  `uv run pytest tests/unit/test_hardpoint_override_writer_lights.py -q`
- [ ] **Step 3: Implement** `set_running_light`, the `apply_edit` branch, the recording
  hooks, the emitters and the identifier de-dup.
- [ ] **Step 4: Run** the new file plus
  `tests/unit/test_hardpoint_overrides_canonical.py` and the three
  `tests/unit/test_hardpoint_override_writer*.py`. Expect PASS. The committed
  `hardpoint_overrides.py` is unchanged: no lights yet, and part guards stay at level 1.
- [ ] **Step 5: Commit** the writer and the test file.

### Task 3: Mod hardpoint writer — light edits go to the managed block

**Files:**
- Modify: `engine/appc/mod_hardpoint_writer.py`
- Test: `tests/unit/test_mod_hardpoint_lights.py` (new); re-run `tests/unit/test_mod_hardpoint_block.py`, `_inplace.py`, `_e2e.py`, `_target.py`

**Interfaces:**
- Consumes: Task 2's model and `__running_light__` edit tuple.
- **Rules:**
  - `_non_empty` counts `__lights__`.
  - `rewrite` routes every `__running_light__` edit to the block model (`apply_edit`) and
    never in place.
  - The mod's own `LoadPropertySet` is never touched.
  - The outer block guard stays `env_guard()` (level 1); the light blocks inside carry
    their own `>= 2` guard.
- **Fixtures** use a **synthetic** mod hardpoint text written in the test: two
  `BlinkingLightProperty_Create` entries in BC's TGPoint3/TGColorA idiom, plus a
  `LoadPropertySet` with `if (prop != None)` guards. Never copy values from the
  LC Intrepid or DCMPv2 files.

- [ ] **Step 1: Write failing tests:**
  - `test_add_light_goes_to_block_and_loads`:
    - `rewrite` with a new light;
    - exec the result under the real shim;
    - run its `LoadPropertySet` through the Task 1 wrapper (call
      `sdk_overrides.on_sdk_module_exec` with a module built from the text, or replicate
      drain+wrap);
    - the new light is in the set.
  - `test_remove_mod_light_absent_after_load`: the mod's own light is gone from the set
    after its guarded `LoadPropertySet`.
  - `test_edit_mod_light_colour_and_position`.
  - `test_author_lines_untouched`: every byte outside the managed block is unchanged.
  - `test_stock_bc_skips_light_blocks`: follow `test_mod_hardpoint_e2e.py`'s
    stock-BC-App pattern; the file runs, and no Dauntless call is made.
- [ ] **Step 2: Run them; expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus the four existing mod-hardpoint test files.
  Expect PASS.
- [ ] **Step 5: Commit.**

### Task 4: Stock saves take effect on the next mission load (§3.7)

**Files:**
- Modify: `engine/appc/override_routing.py` (`HardpointOverridesFileTarget`)
- Test: `tests/unit/test_override_routing.py` (add cases)

**Interfaces:**
- `HardpointOverridesFileTarget(path=_PATH, live_module=None)`:
  - when `live_module` is None and `path` is the real `_PATH`, it uses
    `engine.appc.hardpoint_overrides`;
  - for any other path it refreshes nothing unless a module is passed.
- **After a successful `os.replace`:**
  - compile and exec the new text into a fresh namespace;
  - only on success, set `live_module.OVERRIDES = ns["OVERRIDES"]`.
  The module's `apply` reads the global `OVERRIDES`, so the next `CreateShip` uses the
  new functions.
- **If the refresh raises:** re-raise as `RuntimeError("saved, but reload failed: ...")`
  so the SPV's Save toast shows it. The live module must stay untouched (no partial
  state).
- **If the write fails:** nothing is refreshed.

- [ ] **Step 1: Write failing tests:**
  - `test_write_refreshes_live_overrides`:
    - a tmp overrides file plus a fake `types.ModuleType` with an `OVERRIDES`/`apply`
      copied from the header;
    - write an edit for leaf "galaxy";
    - `fake.OVERRIDES["galaxy"]` is a new function, and calling `fake.apply("galaxy")`
      with a recording manager records the new setter.
  - `test_failed_write_leaves_live_overrides`: monkeypatch `_writer.emit` to raise;
    `fake.OVERRIDES` is the same object.
  - `test_other_path_does_not_touch_real_module`: write to a tmp path with no
    `live_module`; `engine.appc.hardpoint_overrides.OVERRIDES` is the same object as
    before.
- [ ] **Step 2: Run; expect failure.** Run
  `uv run pytest tests/unit/test_override_routing.py -q`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `tests/unit/test_override_routing.py` plus
  `tests/ui/test_ship_property_viewer_save_persistence.py`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 5: Native — draw the hologram ship's running lights in viewer mode

**Files:**
- Modify: `native/src/renderer/include/renderer/running_light_store.h`, `native/src/renderer/running_light_store.cc`
- Modify: `native/src/host/host_bindings.cc` (viewer-mode block after the hologram draw, ~line 2120)
- Test: `native/tests/renderer/running_light_test.cc`

**Interfaces:**
- `RunningLightStore::build_sprites_for(scenegraph::InstanceId id, const scenegraph::World&, float time, const RunningLightDials&, const glm::vec3& cam_eye, float proj11, int viewport_h, float level_override) const`
  builds the sprites of `id` only, using `level_override` instead of the stored level.
  `build_sprites` is unchanged; share the per-light loop between the two.
- **In `host_bindings.cc` viewer mode:**
  - when `g_running_lights_enabled && g_running_light_pass && g_hologram_ship.active`,
    build for `g_hologram_ship.instance` with `level_override = 1.0f`;
  - the time is wall-clock seconds from a `std::chrono::steady_clock` origin captured
    once (the sim is frozen in the SPV, so `g_decal_game_time` would not blink);
  - render with the existing pass.
- **Depth:** the hologram is translucent and pins draw with depth test off. Draw the
  lights after the hologram:
  - when `g_spv_hull_mode` is on, the opaque hull wrote depth, so use the pass's normal
    depth test;
  - otherwise disable depth test for this draw.
  If `RunningLightPass::render` has no depth flag, add a `bool depth_test = true`
  parameter (mirroring `PhaserPass::render`'s).
- **Production:** the non-viewer path is untouched.

- [ ] **Step 0 (once): configure and build the worktree** with the Global Constraints
  cmake line, then `cmake --build build -j`.
- [ ] **Step 1: Write failing gtests:**
  - `RunningLightStore.BuildSpritesForOnlyThatInstance`: two instances, each with one
    light; `build_sprites_for(a, …)` returns 1 sprite at a's light.
  - `RunningLightStore.BuildSpritesForUsesLevelOverride`: stored level 0, override 1;
    the sprite is non-black.
  - `RunningLightStore.BuildSpritesForUnknownInstanceIsEmpty`.
- [ ] **Step 2: Run; expect failure.**
  `cmake --build build -j && ctest --test-dir build -R RunningLightStore`
- [ ] **Step 3: Implement** the store method, the pass flag and the viewer-mode block.
- [ ] **Step 4: Run** `ctest --test-dir build -R "RunningLight"`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 6: Pure running-light editor helpers

**Files:**
- Create: `engine/ui/running_light_editor.py`
- Test: `tests/unit/test_running_light_editor.py`

**Interfaces (all pure, no host calls):**
- **Constants:**
  - `DEFAULT_COLOR = (1.0, 1.0, 1.0)`
  - `DEFAULT_RADIUS = 1.0`
  - `DEFAULT_PERIOD = 3.0`
  - `DEFAULT_DURATION = 0.5`
  - `RADIUS_RANGE = (0.1, 5.0)`
  - `PERIOD_RANGE = (0.5, 10.0)`
  - `DURATION_MIN = 0.1`
  - `STEADY_PERIOD = 3.0`
- `default_name(taken: set) -> str` returns "Running Light N", the lowest N ≥ 1 not
  taken.
- `mirror_name(name: str, taken: set) -> str` swaps a leading word:
  - "Port" ↔ "Star", and "Starboard" → "Port". Case-sensitive on the leading word;
    "Port" always becomes "Star" (BC mod convention).
  - With no swap, use the first free `"<name> N"`, N ≥ 2.
  - If the swapped name is taken, use the first free `"<swapped> N"`, N ≥ 2.
- `validate_spec(spec: dict, taken: set) -> dict` returns a normalised copy (floats,
  tuples) or raises `ValueError` with a human message:
  - the name must be non-empty after strip and not in `taken`;
  - all numbers finite;
  - radius in `RADIUS_RANGE`;
  - colour components in [0, 1];
  - if `duration > 0`: period in `PERIOD_RANGE` and `DURATION_MIN ≤ duration ≤ period`;
  - if `duration ≤ 0`: duration is stored as `0.0`, and the period as given, else
    `STEADY_PERIOD`.
- `spec_from_property(prop) -> dict` builds the canonical dict from a live
  `BlinkingLightProperty`.

- [ ] **Step 1: Write failing tests** for each function, including:
  - `test_validate_rejects_taken_name`
  - `test_validate_rejects_duration_over_period`
  - `test_steady_zeroes_duration`
  - `test_mirror_name_swaps_port_star`
  - `test_mirror_name_numbers_taken_swap` (`"Star Dorsal Nav Static"` with the Port
    twin taken → `"Port Dorsal Nav Static 2"`)
  - `test_default_name_fills_gaps`
  - `test_nan_rejected`
- [ ] **Step 2: Run; expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run; expect PASS.**
- [ ] **Step 5: Commit.**

### Task 7: Panel mixin — staging, list rows, payload, select, save, Physical tab

**Files:**
- Create: `engine/ui/spv_running_lights_pane.py` (`RunningLightsPaneMixin`)
- Modify: `engine/ui/ship_property_viewer_panel.py`:
  - class bases `ShipPropertyViewerPanel(RunningLightsPaneMixin, DecalsPaneMixin, Panel)`;
  - open/close reset;
  - `_snapshot_pending` / `_restore_pending`;
  - the `render_payload` snapshot and `pending_count`;
  - `_pending_edits`;
  - `_subsystem_rows` (append the mixin's rows);
  - the Save edits plus saved overlay;
  - `_physical_entries`;
  - dispatch routing of `rl/`.
- Test: `tests/ui/test_spv_running_lights_pane.py` (new); re-run `tests/unit/test_spv_no_kind_ladders.py`, `tests/ui/test_spv_edit_target_characterisation.py`, `tests/ui/test_ship_property_viewer_undo.py`, `tests/ui/test_spv_physical_tab.py`, `tests/ui/test_ship_property_viewer_save_persistence.py`

**Interfaces:**
- **Mixin state:**
  - `_rl_baked: dict` (name → spec, insertion order = property-set order; snapshotted at
    `open()` via `running_lights.light_properties(ship)` + `spec_from_property`);
  - `_pending_running_light: dict` (name → spec | None);
  - `_saved_running_light: dict` (same shape; cleared with `_clear_saved_edits`);
  - `_rl_selected: Optional[str]`;
  - `_rl_group_expanded: bool`.
- **Methods:**
  - `_rl_effective() -> list[dict]`: baked overlaid with saved, then pending, in
    insertion order; `None` removes.
  - `_rl_names() -> set`
  - `_rl_spec(name) -> Optional[dict]`
  - `_rl_stage(name, spec_or_None)`: sets `_last_pushed = None`.
  - `_rl_rows() -> list[dict]`
  - `_rl_save_edits() -> list` of `(name, "__running_light__", {"spec":…, "new": name not in _rl_baked})`.
  - `_rl_dirty_names() -> list`
  - `_dispatch_rl_action(action) -> bool`, for `rl/select`, `rl/toggle_group`; Task 9
    adds the rest.
- **Rows** appended by `_subsystem_rows` after the descriptor rows:
  - the group row, only when `_rl_effective()` is non-empty:
    `{"kind": "rl_group", "name": "Running Lights", "expanded": _rl_group_expanded, "children": [light rows]}`;
  - each light row:
    `{"kind": "running_light", "name", "spec", "dirty": name in _pending_running_light, "chosen": name == _rl_selected}`;
  - then always `{"kind": "rl_add", "name": "+ Add"}`.
  None of these carries `index`.
- **Selection:**
  - `rl/select:{"name"}` sets `_rl_selected` and clears `selected_index`,
    `_selected_light_index`, `_selected_emitter`, the part-node selection and the decal
    selection;
  - every other select clears `_rl_selected` (extend the existing clear in
    `dispatch_event`);
  - `_active_transform_target()` returns `("running_light", name)` when `_rl_selected`
    is set (checked after the emitter branch). Task 8 adds the adapter.
- **Save:**
  - `hardpoints_pending` includes `_pending_running_light`;
  - `edits += self._rl_save_edits()`;
  - on success `_saved_running_light.update(pending)` and pending is cleared.
- **Counts:** `pending_count` adds `len(_pending_running_light)`; `_pending_edits` lists
  each staged light name with count 1.
- **Physical tab:** `_physical_entries` builds its light entries from `_rl_effective()`
  (key `"light:<name>"`, kind `running_light`, position from the spec) instead of the
  open-time `_physical_lights` snapshot. Pending removals vanish; pending adds appear.

- [ ] **Step 1: Write failing tests.** Use a fake ship with two baked
  `BlinkingLightProperty` entries in its property set; reuse the `spv_test_fixtures`
  `_Ship` pattern.
  - `test_rows_append_group_and_add_row`: the last two top-level rows are `rl_group`
    (2 children) and `rl_add`.
  - `test_no_group_row_without_lights`: only `rl_add` is appended.
  - `test_stage_remove_hides_light_from_rows_and_physical`.
  - `test_select_running_light_clears_other_selections`: also asserts
    `_active_transform_target() == ("running_light", name)`.
  - `test_undo_restores_running_light_staging`.
  - `test_save_routes_running_light_edits`: monkeypatch `resolve_override_target` to a
    recorder; assert the edit tuples and the `new` flags.
  - `test_pending_count_and_confirm_list_include_lights`.
  - `test_payload_carries_running_light_rows`: the JSON payload from `render_payload()`
    contains the `rl_group` row with its spec. This is the payload-field lesson from
    Edit Light.
- [ ] **Step 2: Run; expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus the five re-run files listed above. Expect PASS.
  The characterisation suite must stay green unchanged. If an undo-snapshot shape
  assertion pins the tuple length, update only that line and say so in the commit
  message.
- [ ] **Step 5: Commit.**

### Task 8: `RunningLightTarget` edit adapter (move, coords, mirror, pipette, lock)

**Files:**
- Modify: `engine/ui/spv_edit_targets.py` (new class, `_ADAPTERS["running_light"]`)
- Modify: `engine/ui/ship_property_viewer_panel.py`:
  - pipette source keys: an `rl/select:` while armed yields source `("running_light", name)`;
  - `_MOUNT_SELECT_ACTIONS` gains `"rl/select:"`, `"rl/place_begin:"`, `"rl/edit:"`,
    `"rl/remove:"`;
  - the decal-clear tuple in `dispatch_event` gains `"rl/select:"`.
- Test: `tests/unit/test_spv_running_light_target.py` (new); re-run `tests/unit/test_spv_edit_targets.py`, `tests/ui/test_ship_property_viewer_pipette.py`, `tests/ui/test_ship_property_viewer_mirror.py`, `tests/ui/test_spv_lock_scope.py`, `tests/unit/test_spv_no_kind_ladders.py`

**Interfaces:**
- **`RunningLightTarget(EditTarget)`:**
  - `kind = "running_light"`; key `("running_light", name)`;
  - `locked`: `not panel._mount_editing_enabled()`;
  - `position()` / `set_position(xyz)`: stages a copy of the effective spec with the new
    position;
  - `gizmo_frame()`: `world_from_body(ship, pos)` + `gizmo_axes(...)`, as
    `EmitterTarget`;
  - `axis_drag_begin(axis, grab_param)`: as `EmitterTarget`;
  - `coord_kind() -> "mount"`;
  - no rotate or scale (base defaults return None);
  - `colour() -> spec`, `set_colour(spec)`: copies colour, radius, period, duration,
    never name or position;
  - `pipette_fields_from(src)`: `("position", "colour")` when `src.kind == self.kind`,
    else `("position",)`. Because of `_apply_pipette`, a light's "colour" aspect carries
    all four look fields.
  - `mirror_position()`: no-op. The coord Mirror is hidden for lights, as for decals;
    `payload_extras` returns `{"can_mirror": False}`.
  - `mirror()`:
    - creates a new light with `mirror_name(...)` at (−x, y, z), copying the look;
    - selects it (`_rl_selected`);
    - if the source has an explicit physical parent (pending, else saved, else baked),
      stages the copy's parent as `panel._physical_auto_part(mirrored_pos)`, or leaves
      it Auto when that returns None.
    A light has no stored normal, so nearest-mesh resolution stands in for the decal
    re-trace. This implements spec §3.2.
- **Selected-light marker (spec §3.2).** A 2.5 px dot can be in its "off" phase, so a
  selected light shows the existing translucent selection sphere.
  - Add `EditTarget.selection_sphere(self)`; the base returns None.
  - `RunningLightTarget` returns `{"center": world_from_body(ship, pos), "radius": max(3 × size_gu_per_radius × spec["radius"], 0.05)}`.
    Match the dict shape `selected_subsystem_sphere()` already returns; read it first.
  - `selected_subsystem_sphere()` falls back to `self._edit_target().selection_sphere()`
    when it would otherwise return None. No kind check in the panel.
  - Test: `test_selected_light_shows_selection_sphere`.
- **Other kinds' pipette** need no change: a light source onto a subsystem copies
  position, through their existing `pipette_fields_from` checks on `coord_kind`.
  Verify, and if not, add the minimal adapter-side change.

- [ ] **Step 1: Write failing tests:**
  - `test_move_stages_position`
  - `test_coord_paste_between_light_and_subsystem`
  - `test_mirror_creates_named_twin_and_selects_it`
  - `test_mirror_derives_parent_when_source_explicit` (monkeypatch
    `_physical_auto_part`)
  - `test_mirror_leaves_auto_when_source_auto`
  - `test_pipette_light_to_light_copies_look_and_position`
  - `test_pipette_light_to_subsystem_copies_position_only`
  - `test_locked_refuses_rl_actions` (force `_mount_editing_enabled` False)
  - `test_rotate_and_scale_inert`
- [ ] **Step 2: Run; expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus the five re-run files. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 9: Add / place / edit / remove flow

**Files:**
- Modify: `engine/ui/spv_running_lights_pane.py`
- Modify: `engine/ui/ship_property_viewer_panel.py`:
  - `pick_at` calls `self._rl_click(x, y, viewport)` first and returns if True;
  - `handle_key_esc` gains a placing-cancel branch right after the pipette branch;
  - `render_payload` snapshot plus payload key `"running_lights"`.
- Test: `tests/ui/test_spv_running_lights_flow.py` (new)

**Interfaces:**
- **State:** `_rl_placing: Optional[dict]` (a validated spec awaiting its click) and
  `_rl_error: Optional[str]`.
- **Actions:**
  - **`rl/place_begin:{spec}`:**
    - Call `validate_spec(spec, taken=self._rl_taken_names())`.
      `_rl_taken_names()` = effective light names ∪ every descriptor `name` ∪
      `_model_part_names()`. All templates share one `FindByName` namespace, so a light
      named "Hull" would shadow the hull.
    - On `ValueError`, set `_rl_error` and refuse.
    - On success, set `_rl_placing` and clear `_rl_error`.
    - Placing is not an edit, so no undo entry.
  - **`rl/place_cancel`:** clears `_rl_placing` and `_rl_error`.
  - **`rl/edit:{"name","spec"}`:**
    - validate with `taken = names - {name}`;
    - the name is fixed, so the spec's name is forced to `name`;
    - stage.
  - **`rl/remove:{"name"}`:**
    - stage `None` for a baked or saved light; for a pending-only add, drop it from
      `_pending_running_light`;
    - clear `_rl_selected` if it was this light.
- **`_rl_click(x, y, viewport) -> bool`:**
  - returns False when not placing;
  - otherwise snapshots for undo and calls `self._decal_hull_hit(x, y, viewport)`;
  - on a miss, sets `_rl_error` to the decal `MISS_HINT` text and returns True, staying
    in placing mode;
  - on a hit (`pb` NIF body point, `nb` normal, `mesh`):
    - position (unscaled GU) = `pb × instance_scale(ship)` plus a lift along `nb` of
      `running_light_dials.current()["size_gu_per_radius"] × spec["radius"]`;
    - the test pins the frame: `world_from_body(ship, position)` equals the hit's world
      point plus the lift;
    - stages the light, selects it and clears `_rl_placing`;
    - if `_decal_shape_of_mesh(mesh)` names a part shape, finds the articulated part
      whose name is in the mesh's `node_chain` (`_decal_meshes` entry,
      `_decal_part_names`) and stages `_pending_physical[name] = part`;
    - appends the undo snapshot.
- **Payload** `"running_lights"`:
  ```
  {"placing": name|None, "error": str|None, "hint": "Click the hull to place <name> · Esc cancels"|None, "next_name": default_name(...), "defaults": {color, radius, period, duration}, "ranges": {...}}
  ```

- [ ] **Step 1: Write failing tests.** Mock `_decal_hull_hit` and `instance_scale`.
  - `test_place_begin_then_click_stages_and_selects`
  - `test_place_position_converts_nif_to_gu_with_lift`
  - `test_click_miss_keeps_placing_with_hint`
  - `test_esc_cancels_placing_before_closing_panel`
  - `test_place_begin_refuses_taken_name` (both a light name and a subsystem name such
    as "Hull")
  - `test_place_begin_refuses_invalid_timing`
  - `test_edit_keeps_name_and_restages`
  - `test_remove_pending_add_drops_it`
  - `test_remove_baked_stages_none`
  - `test_undo_removes_placed_light`
  - `test_click_on_part_mesh_stages_physical_parent` (rigged fake)
  - `test_click_on_unrigged_stages_no_parent`
  - `test_payload_running_lights_block`
- [ ] **Step 2: Run; expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus `tests/ui/test_spv_running_lights_pane.py`,
  `tests/ui/test_spv_decals_pane.py` and `tests/unit/test_spv_no_kind_ladders.py`.
  Expect PASS.
- [ ] **Step 5: Commit.**

### Task 10: Live preview in the SPV + restore on close

**Files:**
- Modify: `engine/ui/spv_running_lights_pane.py` (`_rl_sync_preview`, `_rl_restore_preview`)
- Modify: `engine/ui/ship_property_viewer_panel.py`:
  - call `_rl_sync_preview()` at the end of `dispatch_event`, beside
    `_decal_sync_override()`, and after `open()`;
  - call `_rl_restore_preview()` in `close()`;
  - new constructor kwarg `on_running_lights_closed=None`.
- Modify: `engine/host_loop.py`. Where the SPV panel is constructed, pass
  `on_running_lights_closed=lambda ship, iid: _restore_running_lights(r, session, ship, iid)`.
  The new helper:
  - if `iid in session.ship_running_lights`, re-sends `session.ship_running_light_specs[iid][1]`
    with its phase;
  - else calls `r.set_running_lights(iid, [], 0.0)`.
- Test: `tests/ui/test_spv_running_lights_preview.py` (new); `tests/unit/test_running_lights_host_push.py` (add the restore case)

**Interfaces:**
- **`_rl_sync_preview()`:**
  - when visible and the iid resolves, sends
    `engine.renderer.set_running_lights(iid, [spec_tuple…], phase)`;
  - `spec_tuple` is `(px,py,pz, r,g,b, radius, period, duration)` from `_rl_effective()`;
  - `phase` is `running_lights.phase_for(ship)`;
  - sends only when the tuple list changed since the last push (cache
    `_rl_last_preview`);
  - an empty effective list sends `[]`.
- **`_rl_restore_preview()`:** calls the injected callback with `(ship, iid)` when a
  preview was pushed this session, then clears the cache.

- [ ] **Step 1: Write failing tests.** Monkeypatch `engine.renderer.set_running_lights`.
  - `test_open_pushes_effective_lights`
  - `test_edit_repushes_once`: two identical dispatches give one push.
  - `test_remove_last_light_pushes_empty`
  - `test_close_calls_restore_callback`
  - Host-push file:
    - `test_close_clears_preview_for_unlit_ship`: an empty list for an iid absent from
      `session.ship_running_lights`;
    - `test_close_resends_spawn_lights_for_lit_ship`.
- [ ] **Step 2: Run; expect failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** both files plus `tests/unit/test_running_lights.py`. Expect PASS.
- [ ] **Step 5: Commit.**

### Task 11: CEF page — "+ Add" row, Add modal with dropdown, Running Light form, row kinds, menu

**Files:**
- Modify: `native/assets/ui-cef/index.html`:
  - a new `#spv-add` modal (`spv-modal-backdrop` > `spv-modal`) holding a page-drawn
    dropdown, plus a form container;
  - new context-menu items `#spv-ctx-rledit` "Edit…" and `#spv-ctx-rlremove` "Remove",
    hidden by default.
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`:
  - `.spv-add-row`;
  - `.spv-dd`, `.spv-dd__btn`, built from existing tokens.
  Reuse `spv-modal*`, `spv-ctxmenu*`, `spv-stepper*`, `spv-shape-btn`,
  `spv-wheel-row`, `spv-modal__input`. **No new visual language** (Mark: mockups based
  on existing UI).
- Test: `tests/ui/test_spv_running_lights_cef.py` (new; follow `tests/ui/test_spv_physical_tab_cef.py`'s static checks + node harness)

**Behaviour (spec §2 is the authority; the approved mockup layout):**
- **Rows:** `spvRowHtml` handles three new kinds.
  - `rl_group`:
    - caret toggles via `rl/toggle_group`;
    - shut eye;
    - no bar.
  - `running_light`:
    - child row with shut eye;
    - click → `rl/select:{"name"}`;
    - right-click → menu showing only Edit… / Remove.
  - `rl_add`: always last; click opens `#spv-add`.
  Names travel in `data-*` attributes, never inside `on*` string literals (see the
  `spvPartRowHtml` comment).
- **Add modal:**
  - title "Add";
  - a Type dropdown drawn in the page (button + `spv-ctxmenu` list; open/closed is
    JS-local), with an entry per registered type;
  - picking a type renders that type's form below the dropdown (no Next button).
  - **Registry:** `var SPV_ADD_TYPES = {running_light: {label: "Running Light", render: fn, collect: fn, submitAction: "rl/place_begin"}}`.
    The next type adds an entry, not a branch.
- **Running Light form**, top to bottom:
  1. Name: `spv-modal__input`, prefilled with `running_lights.next_name`; text-capture
     contract via `data-panel` (already on `#spv-root`).
  2. A 140 px `ColourWheel` canvas.
  3. Size stepper.
  4. `Steady | Blinking` (`spv-shape-btn`).
  5. When Blinking, "Every" and "On for" steppers.
  6. Cancel, and a primary button "Place on hull".
  - Defaults and ranges come from the payload.
  - Steady hides both timing rows.
- **Edit:**
  - the same modal titled "Edit Running Light", dropdown hidden;
  - name shown read-only;
  - values from the row's `spec`;
  - the primary button is "Apply" → `rl/edit:{name, spec}`.
- **Remove** → `rl/remove:{name}`.
- **Placing hint:** while `running_lights.placing` is set, show `running_lights.hint` in
  `#spv-toast`'s style. Show `running_lights.error` in the decal error style.
- **Overlay:** opening the modal or menu sends `overlay:1`; closing sends `overlay:0`
  (existing `spvOpenMenuAt` / `spvHideOverlays` helpers). Python's Esc closes the
  overlay first.

- [ ] **Step 1: Write failing tests:**
  - Static:
    - `#spv-add` exists and is hidden;
    - the menu items exist and are hidden;
    - the CSS has no colours outside the existing palette (grep the new rules for hex /
      rgb values already used in the file).
  - Node harness:
    - `rl_group`/`running_light`/`rl_add` rows render with the shut eye on light rows;
    - clicking `rl_add` opens the modal;
    - choosing Running Light renders the form;
    - Steady hides the timing rows;
    - Place on hull dispatches `ship-property-viewer/rl/place_begin:` + JSON with the
      wheel colour and stepper values;
    - Edit dispatches `rl/edit` with the name unchanged;
    - the right-click menu on a light shows only Edit/Remove.
- [ ] **Step 2: Run; expect failure.** Run
  `uv run pytest tests/ui/test_spv_running_lights_cef.py -q`.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** the new file plus `tests/ui/test_spv_physical_tab_cef.py`,
  `tests/ui/test_spv_decals_pane_cef.py` and `tests/ui/test_spv_part_tree_cef.py`.
  Expect PASS.
- [ ] **Step 5: Commit.**

### Task 12: Docs

**Files:**
- Modify: `CLAUDE.md`, in the "Ship running lights" row:
  - append "Authored in the SPV: + Add → Running Light, saved via the attach queue (`engine/appc/attach_templates.py`, `DAUNTLESS_ENV` 2)";
  - add the spec path.
- Modify: `CLAUDE.md` "Ship Property Viewer" row: one clause noting "+ Add" (typed Add
  modal) and that stock saves now apply on the next mission load.
- Modify: `docs/superpowers/specs/2026-10-22-spv-running-lights-design.md`: set Status to
  "built, awaiting live verification" and list the commits.

- [ ] **Step 1:** Make the edits. Keep each table row's existing style; no new rows.
- [ ] **Step 2:** Run `uv run pytest tests/docs/test_doc_consistency.py -q`. Expect PASS.
- [ ] **Step 3:** Commit.
