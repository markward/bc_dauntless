# Subsystem Physical Parents Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a subsystem or running light name the mesh part it lives on (`SetPhysicalParent`). Where one is set, every "which part is this on" consumer uses it, and the SPV gets a Physical tab to review and set it.

**Architecture:** A new resolver module, `engine/appc/physical_parents.py`, is the one answer to "which part is this authored property on". The answer is the explicit name if it is set and valid, else today's `part_severance.part_for_mount`. It also holds an SPV preview overlay, so staged edits take effect live. Consumers pass the property through the existing early-outs, so unrigged ships never reach it. The SPV stages edits like its other pending dicts and saves through the existing writer. The writer gains a removal edit.

**Tech Stack:** Python 3.11 (engine, pytest), CEF page JS/HTML/CSS (`native/assets/ui-cef/`), node harness for JS tests. No C++ changes.

**Spec:** `docs/superpowers/specs/2026-10-17-subsystem-physical-parents-design.md` (APPROVED). Read it alongside this plan; section numbers below are the spec's.

## Global Constraints

- Work only in worktree `.claude/worktrees/physical-parents`, branch `feat/physical-parents`. **Banned git:** `checkout -- <path>`, `checkout .`, `restore`, `stash`, `clean`, `reset --hard`, `add -A`, `add .`. Stage explicit paths only. To mutate a file temporarily: `cp` back up, mutate, run, `cp` restore, `diff` to prove identical.
- One-time worktree setup before Task 1 (from project memory; each step was a real failure when skipped):
  `uv sync --extra dev`
  `U=~/.local/share/uv/python/cpython-3.11.15-macos-aarch64-none; cmake -B build -S . -DCMAKE_BUILD_TYPE=Debug -DPython3_EXECUTABLE=$PWD/.venv/bin/python3 -DPython3_ROOT_DIR=$U -DPython3_FIND_FRAMEWORK=NEVER -DPython3_FIND_STRATEGY=LOCATION && cmake --build build -j`
  (`settings.json` and `mods/` are already copied in.)
- Run tests with `uv run pytest …`. Before the branch is called done: `scripts/check_tests.sh` exits 0 with no new failure and no new skip. Never baseline a failure.
- UI wording: **Functional**, **Physical**, **AUTO**, **SET**, **Move to**, **Reset to Auto**, **Move all to**, **Reset all to Auto**. The word "guess" appears in no UI string.
- Setter name: `SetPhysicalParent(name)` / `GetPhysicalParent()`. `None` means unset (Auto).
- Emitted hardpoint text must be Python 1.5-safe: no `True`/`False`, no `import X as Y`, no f-strings; `None` is fine.
- `DAUNTLESS_ENV` stays `1`.
- Zero change for any ship without physical parents: every existing test passes unmodified.
- Emitter lights keep their own-position placement and never read the subsystem's physical parent (spec §6, §12).
- No C++ / renderer changes. No running-light hologram markers. No decal changes.
- Commit after each task; message ends with `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.

## Review Focus

1. **Hot path on unrigged ships.** Most ships have no rig. The resolver must not run (no model query, no warning) when `articulation.posed_part_names(ship)` is empty. → Task 3 test `test_unrigged_ship_never_resolves`.
2. **SPV Cancel leaking into the game.** A Move to followed by Cancel must leave the in-game placement exactly as before. → Task 5 test `test_cancel_drops_pending_preview`.
3. **Missing-part warning spam.** Per-frame consumers (running lights, mounts) hit a missing name every frame; the warning must fire once per (leaf, name). → Task 2 test `test_missing_warns_once`.
4. **Part names with spaces and quotes must survive saving.** `left wing01`, `rom wing top left`, or a modeller's `Bob's wing` must round-trip through both writers as valid Python 1.5. → Task 4 test `test_physical_parent_name_with_quote_round_trips`.
5. **Undo of a bulk action.** One "Move all to" or "Reset all to Auto" is one undo step, and undoing it restores every child's previous value, SET ones included. → Task 5 test `test_move_all_is_one_undo_step`.

---

### Task 1: Property setter

**Files:**
- Modify: `engine/appc/properties.py` (class `TGModelProperty`, near `SetPosition`, ~:36)
- Test: `tests/unit/test_physical_parent_property.py` (create)

**Interfaces:**
- Produces: `TGModelProperty.SetPhysicalParent(name: str | None) -> None`, `TGModelProperty.GetPhysicalParent() -> str | None`. Inherited by every property class, including `BlinkingLightProperty` and object-emitter properties.

- [ ] **Step 1: Write the failing tests**

```python
from engine.appc.properties import TGModelProperty, BlinkingLightProperty

def test_unset_is_none():
    assert TGModelProperty("Port Cannon").GetPhysicalParent() is None

def test_set_then_get():
    p = TGModelProperty("Port Cannon"); p.SetPhysicalParent("left wing")
    assert p.GetPhysicalParent() == "left wing"

def test_none_unsets():
    p = TGModelProperty("Port Cannon"); p.SetPhysicalParent("left wing")
    p.SetPhysicalParent(None)
    assert p.GetPhysicalParent() is None

def test_is_a_real_method_not_the_data_bag():
    p = TGModelProperty("x"); p.SetPhysicalParent("hull")
    assert "PhysicalParent" not in {k[0] for k in p._data}
    assert "SetPhysicalParent" in TGModelProperty.__dict__

def test_running_light_inherits_it():
    p = BlinkingLightProperty("Nav 1"); p.SetPhysicalParent("wing left")
    assert p.GetPhysicalParent() == "wing left"

def test_value_is_coerced_to_plain_str():
    p = TGModelProperty("x"); p.SetPhysicalParent(_StrSub("hull"))
    assert type(p.GetPhysicalParent()) is str
```
(`_StrSub` = a local `class _StrSub(str): pass`. Check `BlinkingLightProperty`'s constructor signature in `properties.py:242` and construct it the way the existing tests in `tests/unit/test_blinking_light_property.py` do.)

- [ ] **Step 2: Run, expect FAIL** — `uv run pytest tests/unit/test_physical_parent_property.py -v` (the data-bag test fails today).
- [ ] **Step 3: Implement** — `self._physical_parent = None` in `__init__`; the setter stores `None` or `str(name)`.
- [ ] **Step 4: Run, expect PASS**, plus `uv run pytest tests/unit/test_blinking_light_property.py -q`.
- [ ] **Step 5: Commit** `feat(physical-parents): SetPhysicalParent on TGModelProperty`.

---

### Task 2: Resolver module + preview overlay

**Files:**
- Create: `engine/appc/physical_parents.py`
- Modify: `tests/conftest.py` (`_reset_leakable_engine_globals`, next to the `_articulation.reset()` block ~:1001)
- Test: `tests/unit/test_physical_parents.py` (create)

**Interfaces:**
- Consumes: `articulation.part_boxes_for(leaf)` (keys = the model's candidate part names, `{}` when no model is known), `part_severance.part_for_mount(leaf, point, iid=None)`.
- Produces:
  - `property_of(obj) -> property` — `obj.GetProperty()` when it has one, else `obj`.
  - `class PropRef(NamedTuple): name: str; baked: str | None` with `GetName()` and `GetPhysicalParent()`. Used where only a name and baked value are in hand (SPV, running lights).
  - `explicit_parent(leaf, prop) -> str | None` — the preview overlay's value for `(leaf, prop.GetName())` if present (a `None` there means "Auto"), else `prop.GetPhysicalParent()`.
  - `is_missing(leaf, name) -> bool` — True only when a model is known (`part_boxes_for(leaf)` non-empty) and `name` is not among its parts.
  - `part_for_property(leaf, prop, point, iid=None) -> str | None` — spec §5. Leaf is lower-cased like `part_for_mount` does.
  - `source_for(leaf, prop) -> "set" | "auto" | "missing"`.
  - `set_preview(leaf, overrides: dict[str, str | None]) -> None` (replaces that leaf's overlay), `clear_preview(leaf=None) -> None`, `reset() -> None` (overlay + warned set).

- [ ] **Step 1: Write the failing tests.** Use `monkeypatch.setitem(articulation._derived_boxes, leaf, {...})` and patch `part_severance.part_for_mount`, following the `native` fixture in `tests/unit/test_part_for_mount.py`.
  - `test_unset_falls_through_to_part_for_mount`: returns exactly what the patched `part_for_mount` returns, and it was called once with `(leaf, point, iid)`.
  - `test_set_wins`: `SetPhysicalParent("birdofprey")` with boxes containing it → `"birdofprey"`; `part_for_mount` not called.
  - `test_missing_falls_to_auto`: boxes lack the name → the `part_for_mount` answer.
  - `test_missing_warns_once` (Review Focus 3): 100 calls → exactly one stderr line (capsys) containing the leaf, the property name and the missing part name.
  - `test_headless_trusts_name`: `part_boxes_for` → `{}` → the explicit name is returned.
  - `test_preview_overrides_baked` / `test_preview_none_means_auto` / `test_clear_preview_restores_baked`.
  - `test_preview_is_per_leaf`: an overlay on leaf A does not affect leaf B.
  - `test_source_for`: set / auto / missing cases.
  - `test_property_of_unwraps_subsystem`: a double with `GetProperty()` → its property; a bare property → itself.
- [ ] **Step 2: Run, expect FAIL** (module missing).
- [ ] **Step 3: Implement** the module per the Interfaces block. Add `physical_parents.reset()` to the conftest autouse reset, inside its own `try/except Exception: pass` like its neighbours.
- [ ] **Step 4: Run, expect PASS.**
- [ ] **Step 5: Commit** `feat(physical-parents): resolver and SPV preview overlay`.

---

### Task 3: Switch the mount, target-offset, severance and running-light consumers

**Files:**
- Modify: `engine/appc/articulation.py` (`part_transform_point` :704, `_live_part` :755)
- Modify: `engine/appc/subsystems.py` (`subsystem_world_position` :49, `target_offset_world` :86)
- Modify: `engine/appc/part_severance.py` (`is_authored_mount` :502, `_destroy_subsystems_on_part` :517)
- Modify: `engine/appc/running_lights.py` (`RunningLightSpec` :16, `lights_for` :29)
- Modify: `engine/host_loop.py` (`_part_pose_at` :1677, `_articulated_running_lights` :728). **Not** `_articulate_emitter_light`.
- Test: `tests/unit/test_physical_parent_consumers.py` (create)

**Interfaces:**
- Consumes: Task 2 `part_for_property`, `property_of`, `PropRef`.
- Produces:
  - `part_transform_point(ship, point, part=None, *, authored=True, prop=None)`. In `_live_part`, after the `posed_part_names` early-out, when `name is None`, `authored`, and `prop is not None`: `name = physical_parents.part_for_property(leaf_for(ship), prop, point)`. Otherwise the existing path is unchanged.
  - `part_severance.authored_mount_subsystem(ship, point, eps=1e-5) -> subsystem | None`. `is_authored_mount` becomes `authored_mount_subsystem(...) is not None`.
  - `RunningLightSpec` gains `name: str = ""` and `physical_parent: str | None = None`, both after the existing fields. `as_tuple()` is unchanged (still 9 values).
  - `host_loop._part_pose_at(ship, iid, position, prop=None)`. With `prop`, it resolves through `part_for_property` instead of `part_for_mount`. Still after the `names` early-out.

- [ ] **Step 1: Write the failing tests.** Use a BoP-shaped fixture: rig parts `left wing`, `left wing01`; boxes for `birdofprey`, `head`, `left wing`, `left wing01`; and a patched `part_for_mount` that returns `left wing` for `Impulse Engines` (-0.235, -0.219, -0.047), as measured in spec §1.
  - `test_unset_mount_unchanged`: `subsystem_world_position` equals today's value (compute it with physical parents unset, before and after the change).
  - `test_set_mount_ignores_wing_pose`: SET `birdofprey` with the wing posed → the mount is not transformed.
  - `test_set_mount_follows_named_wing`: a body-point subsystem SET to `left wing` → transformed by the wing pose.
  - `test_target_offset_uses_locked_subsystems_parent`: a lock offset equal to a SET subsystem's mount follows the SET part.
  - `test_severing_wing_spares_set_body_systems`: sever `left wing` → `Impulse Engines` SET `birdofprey` keeps its condition, `Port Cannon` (AUTO on `left wing`) goes to 0 (spec §8.4).
  - `test_running_light_set_part_follows_it`: a light whose position resolves to the hull, SET to `wing left`, is carried by the wing pose in `_articulated_running_lights`.
  - `test_running_light_spec_tuple_unchanged`: `as_tuple()` length 9, same values as before.
  - `test_emitter_light_ignores_subsystem_parent`: subsystem SET `birdofprey`, its emitter light authored on the wing → `_articulate_emitter_light` still carries it with the wing.
  - `test_unrigged_ship_never_resolves` (Review Focus 1): no rig, SET name → identity, and the patched `part_for_property` / `part_for_mount` are never called.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
  - `subsystem_world_position` passes `prop=physical_parents.property_of(sub)`.
  - `target_offset_world` gets the sub from `authored_mount_subsystem` and passes its property. `authored=` stays as today.
  - `_destroy_subsystems_on_part` compares `part_for_property(leaf, property_of(sub), point, iid)`.
  - `lights_for` fills `name=prop.GetName()` and `physical_parent=prop.GetPhysicalParent()`.
  - `_articulated_running_lights` passes `prop=PropRef(s.name, s.physical_parent)`.
- [ ] **Step 4: Run, expect PASS**, then the zero-change suite: `uv run pytest tests/unit/test_part_for_mount.py tests/unit/test_articulation.py tests/unit/test_articulation_fresh_part.py tests/unit/test_subsystem_part_parenting.py tests/unit/test_target_offset_articulation.py tests/unit/test_part_severance.py tests/unit/test_running_lights.py tests/unit/test_running_lights_host_push.py tests/unit/test_hull_bounds_parts.py tests/unit/test_hull_breakup.py -q`. All pass unmodified.
- [ ] **Step 5: Commit** `feat(physical-parents): mounts, severance and running lights honour SET`.

---

### Task 4: Writer — set, None and remove, for both targets

**Files:**
- Modify: `engine/appc/hardpoint_override_writer.py` (`apply_edit` :173, emission ~:248-292)
- Modify: `engine/appc/mod_hardpoint_writer.py` (`rewrite` :292, `emit_block` :72; reuse `find_setter_call` :150)
- Modify (if needed for the `__unset__` pass-through): `engine/appc/override_routing.py` (`HardpointOverridesFileTarget.write` :42, `ModHardpointFileTarget.write` :81)
- Test: `tests/unit/test_physical_parent_writer.py` (create)

**Interfaces:**
- Produces edit shapes the SPV (Task 5) emits:
  - SET → `(name, "SetPhysicalParent", (part,))`. This already works through `set_setter`.
  - Reset → `(name, "__unset__", "SetPhysicalParent")`.
- Behaviour:
  - Stock target: `__unset__` removes that setter from the property's call list. A property left with no calls emits no `find()` block.
  - Mod target: if the author's own text (outside the managed block) has a top-level `SetPhysicalParent` call for that property (`find_setter_call`), the managed block gets `SetPhysicalParent(None)`. Otherwise the block's call is removed. The author's text is never rewritten.

- [ ] **Step 1: Write the failing tests** (follow `tests/unit/test_hardpoint_override_writer*.py` and `tests/unit/test_mod_hardpoint_block.py` for fixtures):
  - `test_stock_set_emits_call`: the emitted text contains `p.SetPhysicalParent("birdofprey")`, with no guard on it.
  - `test_stock_unset_removes_call` and `test_stock_unset_drops_empty_block`.
  - `test_mod_set_lands_inside_guarded_block`.
  - `test_mod_unset_without_author_call_removes`.
  - `test_mod_unset_with_author_call_writes_none`: the author text has `PortCannon.SetPhysicalParent("left wing")` → the block gets `SetPhysicalParent(None)`, and the author line is byte-identical.
  - `test_physical_parent_name_with_quote_round_trips` (Review Focus 4): a name with a space and an apostrophe; exec the emitted text and read it back (`read_models_from_source`); the value is the same.
  - `test_emitted_text_is_py15_safe`: no `True`, `False` or ` as ` in emitted lines containing `SetPhysicalParent`.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** The tuple shape is fixed above; how each target applies it is the implementer's call.
- [ ] **Step 4: Run, expect PASS**, plus `uv run pytest tests/unit -k "hardpoint or override or mod_hardpoint or dauntless_env" -q`.
- [ ] **Step 5: Commit** `feat(physical-parents): writer set/None/remove for stock and mod targets`.

---

### Task 5: SPV panel state, actions, payload, save, undo

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Modify: `engine/appc/running_lights.py`: add `light_properties(ship) -> list` (the `BlinkingLightProperty` objects `lights_for` iterates, with the same skip rule).
- Test: `tests/ui/test_spv_physical_tab.py` (create; follow `tests/ui/test_ship_property_viewer_panel_part.py` and `tests/ui/spv_test_fixtures.py`)

**Interfaces:**
- Consumes: Tasks 2 and 4. Parts come from the panel's existing `_fetch_model_part_nodes()` (:540): names of `candidate` nodes, in node order.
- Produces (consumed by Task 6's JS):
  - State: `self._systems_tab` (`"functional"` default | `"physical"`); `self._pending_physical: dict[str, str | None]` and `self._saved_physical` (key = property name; `None` = Reset to Auto).
  - Row key: `"sub:<descriptor index>"` or `"light:<running-light name>"`.
  - Actions, all under `ship-property-viewer/`. Each payload is JSON after the colon:
    - `physical/tab:{"tab":"functional"|"physical"}`
    - `physical/move:{"key":K,"part":P}`
    - `physical/reset:{"key":K}`
    - `physical/move_all:{"missing":M,"part":P}`
    - `physical/reset_all:{"missing":M}`
  - Payload key `physical`:
    ```
    {"tab": str,
     "parts": [str],
     "groups": [{"part": str, "missing": bool,
                 "rows": [{"key": str, "name": str,
                           "kind": "subsystem"|"running_light",
                           "source": "auto"|"set",
                           "chosen": bool, "index": int|None}]}]}
    ```
    Missing groups come first, then one group per part in `parts` order (including empty ones). Rows within a group follow descriptor order, then running lights in property order.
- Rules:
  - `move` with `P` equal to the row's current AUTO part writes SET (confirm, spec §7.3). On a SET row, the same part is a no-op.
  - `move_all` / `reset_all` touch only rows whose explicit value equals missing name `M`.
  - Each action is one undo step through the existing `dispatch_event` bracket.
  - Physical actions are allowed while the mount-lock gate (:2426-2473) is active. Exempt the `physical/` prefix there.
  - After every action, `physical_parents.set_preview(leaf, {**self._saved_physical, **self._pending_physical})`. Do it in `dispatch_event` beside `_decal_sync_override()`.
  - Cancel discards `_pending_physical`, then re-syncs.
  - Save adds `(name, "SetPhysicalParent", (p,))` or `(name, "__unset__", "SetPhysicalParent")` per pending entry, moves pending into saved, and counts each in `_pending_edits()`.
  - Include `_pending_physical` in `_snapshot_pending` / `_restore_pending` (:1205-1251) and in `render_payload`'s snapshot tuple.
  - `_effective_world_pos` (:1168) passes `prop=physical_parents.PropRef(name, baked)` so the selected pin agrees with the pins. Carry `baked` on each descriptor as `"physical_parent"` from `build_descriptors` (`ship_property_viewer.py:215`, via `property_of(sub).GetPhysicalParent()`).
  - Physical edits never set a Functional row's `dirty` flag.

- [ ] **Step 1: Write the failing tests:**
  - `test_physical_groups_auto_rows_by_part`: BoP-shaped fixture, all AUTO → each descriptor under its patched `part_for_mount` part; empty parts still listed.
  - `test_move_sets_and_regroups`: `physical/move` `Impulse Engines` → `birdofprey` → the row is under `birdofprey` with `"source":"set"`, and the preview overlay has it.
  - `test_move_to_current_auto_part_confirms`: source becomes `"set"` and a pending entry exists.
  - `test_reset_to_auto`: pending `None`; the row shows `"auto"`.
  - `test_missing_group_first_and_bulk_actions`: baked SET `left wing01` with that part absent → the first group is `{"part":"left wing01","missing":true}`. `move_all` to `right wing outer` empties it. `reset_all` instead → every child is AUTO.
  - `test_move_all_is_one_undo_step` (Review Focus 5).
  - `test_cancel_drops_pending_preview` (Review Focus 2): after Cancel, `physical_parents.explicit_parent` equals the baked value.
  - `test_save_emits_edits_and_tally`: Save calls the target with the expected tuples; the tally counts each pending entry once.
  - `test_running_lights_listed`: two `BlinkingLightProperty` lights appear as `"kind":"running_light"` rows. `move` with a `light:` key stages by light name.
  - `test_physical_actions_allowed_under_pose_lock`.
  - `test_tab_switch_is_not_an_edit`: `physical/tab` leaves `_pending_edits()` empty.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS**, plus `uv run pytest tests/ui -k "ship_property_viewer or spv" -q`.
- [ ] **Step 5: Commit** `feat(physical-parents): SPV physical state, actions, save and undo`.

---

### Task 6: SPV CEF — tab strip, Physical list, context menus

**Files:**
- Modify: `native/assets/ui-cef/index.html` (`#spv-syslist` ~:352; `#spv-ctxmenu` :544)
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js` (`setShipPropertyViewer` :20, `spvShowMenuItems` :451)
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`
- Test: `tests/ui/test_spv_physical_tab_cef.py` (create; static checks plus node harness, following `tests/ui/test_spv_part_tree_cef.py`)

**Interfaces:**
- Consumes: Task 5's `physical` payload and actions.
- Produces DOM:
  - `<div id="spv-systabs" class="spv-tabs">` holding two `.spv-tab` elements, **directly after** `.spv-syslist__header` and before `#spv-syslist-body`. The active tab has `.spv-tab--active`.
  - `#spv-physical-body` (sibling of `#spv-syslist-body`, shown only on the Physical tab).
  - `renderSPVPhysical(physical)`.
- Look, from the approved mockup (exact values):
  - `.spv-tabs`: background `rgba(10,10,16,.97)`; `border-left: 4px solid rgb(216,94,86)`; `border-bottom: 1px solid rgba(255,230,160,.25)`.
  - `.spv-tab`: centered; padding `5px 0 4px`; 12px; letter-spacing `.12em`; uppercase; colour `rgba(235,225,255,.5)`; `border-bottom: 2px solid transparent`.
  - `.spv-tab--active`: colour `#ffd`; background `rgba(255,214,90,.12)`; `border-bottom-color: rgb(255,200,60)`.
  - Part rows reuse `.spv-sys-row` with a caret and a white name. Child rows reuse `.spv-sys-row--child`.
  - Tags `.spv-src`: 10px, letter-spacing `.08em`, uppercase. `.spv-src--auto` `rgba(235,225,255,.38)`; `.spv-src--set` `rgb(255,200,60)`. Missing-group part name `rgb(255,140,120)`, prefixed `⚠ ` and suffixed ` (missing)`.
  - **No `spv-sys-row--dirty` class on any Physical row** (spec §7.2).
- Context menu:
  - A child row gets **Move to ▸** (a submenu listing `parts`; the current part is ticked `✓`; it is clickable on AUTO rows and inert on SET rows) and **Reset to Auto** (inert on AUTO rows).
  - A missing-group header gets **Move all to ▸** and **Reset all to Auto**.
  - The submenu is a second `.spv-ctxmenu` element positioned at the parent menu's right edge. Every new item is hidden by `spvShowMenuItems` defaults.
  - Identities travel in `data-*` attributes, never inside `on*` JS string literals (see the `spvPartRowHtml` comment for why).
- A row click on a `subsystem` row fires `select_pin:<index>`, like the Functional tab. A `running_light` row only marks itself chosen (no pin).

- [ ] **Step 1: Write the failing tests:**
  - Static: `test_tab_strip_under_header`: in `index.html`, `spv-systabs` appears after `spv-syslist__header` and before `spv-syslist-body`.
  - Static: `test_no_guess_wording` across HTML/JS/CSS, case-insensitive, only within the new physical code.
  - Static: `test_new_menu_items_hidden_by_default`.
  - Node harness: `test_render_groups_and_tags`: a payload with a missing group and two parts → the DOM order is missing group, then parts; tags read AUTO/SET; no row carries `spv-sys-row--dirty`.
  - Node harness: `test_move_to_dispatches_json`: clicking submenu part `birdofprey` for key `sub:3` → `dauntlessEvent('ship-property-viewer/physical/move:{"key":"sub:3","part":"birdofprey"}')`.
  - Node harness: `test_names_are_escaped`: a part named `a"b<c` renders as text and dispatches the exact name.
  - The existing `tests/ui/test_cef_js_syntax.py` still passes.
- [ ] **Step 2: Run, expect FAIL.**
- [ ] **Step 3: Implement.** Check that the SPV left-column click guard (`LEFT_COL_*` / `TITLEBAR_H_PT` in `ship_property_viewer_panel.py`) still covers the taller column; the column grows with its contents.
- [ ] **Step 4: Run, expect PASS**, plus `uv run pytest tests/ui -k "cef or spv" -q`.
- [ ] **Step 5: Commit** `feat(physical-parents): SPV Functional/Physical tabs and menus`.
- [ ] **Step 6: Hand to Mark for the in-game look** before any gate run (project rule: UI look first, gate last). Command: `cd .claude/worktrees/physical-parents && ./build/dauntless --developer`, then pause → Ship Property Viewer on a Bird of Prey. Fold his visual feedback into this task before Task 7.

---

### Task 7: Docs + gate

**Files:**
- Modify: `docs/superpowers/specs/2026-09-23-ship-part-articulation-design.md`: under OQ-13 add one line: "Superseded by `2026-10-17-subsystem-physical-parents-design.md`."
- Modify: `engine/appc/part_severance.py`: in the `part_for_mount` docstring's "KNOWN LIMITATION" paragraph, point to `physical_parents.part_for_property` as the fix.
- Modify: `CLAUDE.md`: one table row, "Physical parents", naming `engine/appc/physical_parents.py`, `SetPhysicalParent`, the spec path, and the two traps: (1) emitter lights never read it; (2) the `physical/` actions are exempt from the pose lock.
- Modify: the spec's Status line → add "Implemented on feat/physical-parents, not live-verified" until Mark checks it.

- [ ] **Step 1:** Make the doc edits.
- [ ] **Step 2:** Run `uv run pytest tests/docs -q` (doc-consistency tests).
- [ ] **Step 3:** Run the gate: `scripts/check_tests.sh`. Expected: exit 0, no unbaselined failure or skip.
- [ ] **Step 4: Commit** `docs(physical-parents): supersede OQ-13, CLAUDE.md row`.
