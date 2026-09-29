# SPV Edit-Target Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement every SPV editing tool once, against one per-kind
`EditTarget` adapter. The tools are Move, Rotate and Scale, plus their
Copy/Paste, Mirror, Pipette and gizmo drags. Existing kinds must behave
identically, and decals gain per-tool Copy/Paste and Mirror.

**Architecture:**
- A new module, `engine/ui/spv_edit_targets.py`, holds one adapter class
  per kind. Each adapter is a thin view over the panel's existing
  staged-edit dicts.
- The panel resolves the live selection to an adapter via `_edit_target()`.
  Each tool handler is then written once, against the adapter.
- Per-kind code moves **verbatim** from `ship_property_viewer_panel.py` and
  `spv_decals_pane.py` into the adapters.
- A characterisation suite, written first against the current code, pins
  existing behaviour.

**Tech Stack:** Python 3 (`engine/ui/`), CEF JS
(`native/assets/ui-cef/js/ship_property_viewer.js`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-29-spv-edit-target-refactor-design.md`

## Global Constraints

**Behaviour and scope**
- The existing kinds' behaviour is preserved exactly. The kind ×
  capability table in spec §2 is the contract.
- Clipboard compatibility tags must not change:
  - coord: `"mount"` (shared by subsystem, light and emitter),
    `"part_anchor"`, `"part_pose"`;
  - rotate: `pose_euler`, `cone_orientation`, `box_orientation`,
    `cylinder_axis` (shared by cylinder light and strip emitter);
  - scale: the existing `(kind, fields)` tuple;
  - new for decals: `"decal"` for all three.
- Adapters own NO state. They read and write the panel's `_pending_*` /
  `_saved_*` dicts, `_spv` part state, and the decal working list.
- Nothing changes in staging, `_snapshot_pending` / `_restore_pending`,
  the undo stack, save routing, picking or selection events.

**Tests**
- Existing test **assertions must not change**. Imports, helper calls and
  fixture wiring may change. If a step would need an assertion changed,
  STOP and report `BLOCKED` with the test name. The controller does NOT
  rule on this itself: it goes to Mark, with the test, the assertion and
  why the refactor would change it, and execution waits for his decision.
- Per-kind maths moves verbatim (relocated, not rewritten). Live-tuned
  numbers stay byte-identical.

**Decal behaviour**
- Decal Mirror creates `<mask>_N`, where N is the first free N ≥ 2, with
  the same `mask` and `shape`.
- Geometry: reflect `origin`, `u_axis`, `v_axis` and `normal` across X=0,
  then negate `u_axis` and set `origin` to the reflected old origin plus
  the reflected old `u_axis`, so that `(u×v)·n < 0` holds.
- It becomes the selection, and is refused inline at 16 placements.
- Decal paste: Scale width goes through `decal_editor.set_width(p, w,
  mask_aspect)`. Roll uses the 3-arg `roll_angle(p, ship_forward,
  ship_up)`.

**Project rules**
- Python never spells `game`/`sdk` as a path segment and never captures a
  path at import.
- Banned git: `git checkout -- <path>`, `git checkout .`, `git restore`,
  `git stash`, `git clean`, `git reset --hard`, `git add -A`, `git add .`.
  Stage explicit paths only. For a temporary mutation, back up and restore
  with `cp` and prove the restore with `diff`.
- NEVER stage or modify
  `native/assets/replacements/data/Models/Ships/Ambassador/Masks/decals.json`.
  It holds Mark's uncommitted live saves.
- Never launch `./build/dauntless`.

**Test commands**
- SPV selection:
  `uv run pytest tests/ui tests/unit tests/host -q -k "decal or spv or ship_property"`
- Plus `uv run pytest tests/unit/test_path_indirection.py -q`

## Review Focus

1. **Selection switching.** Selecting a light while a decal is selected,
   or a decal while a part pose is selected, must leave exactly one
   adapter live. The top-right panel must show the new target's values.
2. **Locked mounts.** A locked subsystem mount still refuses a gizmo grab
   and nudges after routing through the adapter (`locked`).
3. **Undo per gesture.** An adapter-routed drag still pushes exactly ONE
   undo entry, and none if nothing changed.
4. **Pose-state switching.** A part pose edited under state `red`, then
   switched to `warp`, must show the `warp` values. The adapter key
   carries the state, so the adapter must not be cached across a state
   change.
5. **Decal Mirror of a decal already on the centreline.** Its reflected
   copy overlaps the original. This is allowed and still a new placement,
   but it must stay readable from outside and not be degenerate.

---

## File Structure

- **Create `engine/ui/spv_edit_targets.py`.** Holds `EditTarget` (a base
  class with `None`/no-op defaults) and the adapters:
  - `MountTarget`, `LightTarget`, `EmitterTarget`, `PartAnchorTarget`,
    `PartPoseTarget`, `DecalTarget`;
  - `edit_target_for(panel) -> EditTarget | None`.
- **Modify `engine/ui/ship_property_viewer_panel.py`.** Tool producers,
  handlers, drags and gizmos route through `_edit_target()`. The per-kind
  ladders are deleted as each tool migrates.
- **Modify `engine/ui/spv_decals_pane.py`.** Its tool hooks
  (`_decal_transform_coords`, `_decal_rotate_values`,
  `_decal_scale_values`, `_decal_panel_nudge`, `_decal_gizmo`,
  `_decal_begin_drag`, `_decal_apply_*_drag`) move into `DecalTarget`. The
  sidebar, actions and override stay.
- **Modify `native/assets/ui-cef/js/ship_property_viewer.js`.** In
  `spvShowPanel`, stop hiding the action row when `decal === true`. Keep
  stepper labelling.
- **Create `tests/ui/test_spv_edit_target_characterisation.py`.** The
  behaviour pins.
- **Create `tests/ui/test_spv_decal_clipboard_mirror.py`.** The new decal
  capabilities.

---

### Task 1: Characterisation suite and interface skeleton

**Files:**
- Create: `tests/ui/test_spv_edit_target_characterisation.py`
- Create: `engine/ui/spv_edit_targets.py` (skeleton only)

**Interfaces:**
- Produces:

```python
class EditTarget:
    """Thin per-kind view over ShipPropertyViewerPanel's staged state
    (spec 2026-09-29-spv-edit-target-refactor §3). Owns no state."""
    kind: str = ""                      # "subsystem"|"light"|"emitter"|"part_anchor"|"part_pose"|"decal"
    def __init__(self, panel, key: tuple): self.panel, self.key = panel, key
    @property
    def locked(self) -> bool: return False
    # Move
    def position(self) -> tuple: raise NotImplementedError
    def set_position(self, xyz: tuple) -> None: raise NotImplementedError
    def gizmo_frame(self): return None           # (origin_world, axes) or None
    # Rotate
    def rotate_spec(self): return None           # dict {fields, clipboard_kind} | None
    def get_rotation(self): return None
    def set_rotation(self, value) -> None: pass
    def rotate_nudge(self, field: str, delta: float) -> None: pass
    def ring_drag_begin(self, *args): return None
    def ring_drag_apply(self, state, angle: float) -> None: pass
    # Scale
    def scale_spec(self): return None            # dict {kind, fields, step_scale} | None
    def get_scale(self): return None
    def set_scale_field(self, name: str, value: float) -> None: pass
    def scale_drag_begin(self, *args): return None
    def scale_drag_apply(self, state, *args) -> None: pass
    # Clipboards
    def coord_kind(self) -> str: return ""
    def rotate_kind(self): return None
    def scale_kind(self): return None
    # Mirror / pipette
    def mirror(self) -> None: pass
    def pipette_fields_from(self, src: "EditTarget") -> tuple: return ()

def edit_target_for(panel):  # filled in Task 2
    return None
```

- [ ] **Step 1: Read the current code paths the suite must pin.** They are
  in `engine/ui/ship_property_viewer_panel.py`:
  - `_active_transform_target` (~1244), `_target_pos_of` (~1344),
    `_set_transform_target_pos` (~1374);
  - `transform_coords` (~1485), `_scale_kind_and_fields` (~1510),
    `scale_values` (~1572), `_set_scale_field` (~1592);
  - `_rotate_target` (~1658), `_mirror_target_rotation` (~1687),
    `rotate_values` (~1737), `_rotate_clipboard_kind` (~1771),
    `_rotate_axis` (~1791);
  - `_apply_pipette` (~1442);
  - the drag begin/apply methods (~2070–2390);
  - the `*_nudge` / `*_copy` / `*_paste` / `*_mirror` / `mirror_element`
    handlers (~3508–3680).

  Reuse the existing fixtures in
  `tests/ui/test_ship_property_viewer_panel_coords.py`, `_scale.py`,
  `_rotate.py`, `_pipette.py` and `_emitter.py`, and in
  `tests/ui/test_spv_part_gizmos.py` and `tests/ui/test_spv_decals_pane.py`,
  to build a panel with one target of each kind.

- [ ] **Step 2: Write the characterisation tests.** Write one parametrised
  test module over these ten cases:

```python
CASES = ["subsystem", "light_sphere", "light_cylinder", "light_box",
         "emitter_point", "emitter_strip", "emitter_cone",
         "part_anchor", "part_pose", "decal"]
```

  For each case, the builder selects the target and asserts **literal
  expected values** (computed once from the current code and written into
  the test, not recomputed from the code at test time):
  - `panel.transform_coords()`, `panel.rotate_values()` and
    `panel.scale_values()`, as whole dicts;
  - the staged value after `coord_nudge:x:+1`, after one `rotate_nudge`
    on each rotate field, and after one `scale_nudge` on each scale field;
  - `coord_copy` then select a second target of each other case then
    `coord_paste`, recording whether it is applied or refused;
  - the same for scale and rotate;
  - the staged values after `coord_mirror`, `rotate_mirror` and
    `mirror_element`;
  - pipette: arming on the case and picking each other case, recording
    which fields changed;
  - one axis drag, one scale drag and one ring drag via the existing
    `_begin_*` / `_apply_*` / `_end_axis_drag`, recording the staged
    result and that exactly one undo entry was pushed.

  Also pin Review Focus 1–4:
  - switching selection between kinds updates all three payloads;
  - a locked mount refuses a nudge and a grab;
  - a no-op drag pushes no undo entry;
  - a part pose under state `red` versus `warp` shows each state's values.

  Where the current code produces a known gap for decals (no clipboard,
  no mirror), pin the gap. Task 6 changes exactly those decal
  expectations, and the ledger records it.

- [ ] **Step 3: Run it against the CURRENT code.**

  Run: `uv run pytest tests/ui/test_spv_edit_target_characterisation.py -q`

  Expected: every test PASSES. A characterisation suite that fails on
  unchanged code has recorded a wrong expectation, so fix the expectation,
  never the code.

- [ ] **Step 4: Add the skeleton.** Create `engine/ui/spv_edit_targets.py`
  containing exactly the `Interfaces` block above, plus a module
  docstring. Nothing imports it yet.

- [ ] **Step 5: Run the SPV selection.** All green.

- [ ] **Step 6: Commit.**

```bash
git add tests/ui/test_spv_edit_target_characterisation.py engine/ui/spv_edit_targets.py
git commit -m "test(spv): characterisation suite for every tool x kind; EditTarget skeleton"
```

### Task 2: Move tool through the adapters

**Files:**
- Modify: `engine/ui/spv_edit_targets.py`
- Modify: `engine/ui/ship_property_viewer_panel.py` (`_active_transform_target`,
  `_target_pos_of`, `_set_transform_target_pos`, `transform_coords`,
  `_coord_clipboard_kind`, the `coord_*` handlers, `_begin_axis_drag` /
  `_apply_axis_drag`, `transform_gizmo`, `_current_target_is_locked_mount`)
- Test: `tests/unit/test_spv_edit_targets.py` (new)

**Interfaces:**
- Consumes: `EditTarget` from Task 1.
- Produces:
  - `edit_target_for(panel) -> EditTarget | None`. It maps today's
    `_active_transform_target()` tuple to an adapter.
  - `ShipPropertyViewerPanel._edit_target()`, which returns
    `edit_target_for(self)` freshly on every call and is never cached.
  - Adapter classes `MountTarget(("subsystem", i))`,
    `LightTarget(("light", i))`, `EmitterTarget(("emitter", i, j))`,
    `PartAnchorTarget(("part_anchor", name))` and
    `PartPoseTarget(("part_pose", name, state))`, each implementing
    `position`, `set_position`, `gizmo_frame`, `coord_kind` and `locked`.

- [ ] **Step 1: Write the failing unit tests** in
  `tests/unit/test_spv_edit_targets.py`:

```python
def test_edit_target_for_maps_each_active_target(panel_with_all_kinds):
    p = panel_with_all_kinds
    for select, cls, key in [
        (p.select_subsystem_for_test, MountTarget, ("subsystem", 0)),
        (p.select_light_for_test, LightTarget, ("light", 0)),
        (p.select_emitter_for_test, EmitterTarget, ("emitter", 0, 0)),
    ]:
        select()
        t = p._edit_target()
        assert isinstance(t, cls) and t.key == key

def test_coord_kind_tags_unchanged(panel_with_all_kinds):
    ...  # MountTarget/LightTarget/EmitterTarget -> "mount"; anchor -> "part_anchor"; pose -> "part_pose"

def test_edit_target_is_not_cached_across_pose_state(panel_with_part_pose):
    p = panel_with_part_pose
    p.set_part_state_for_test("red");  a = p._edit_target()
    p.set_part_state_for_test("warp"); b = p._edit_target()
    assert a.key[2] == "red" and b.key[2] == "warp"
```

  Build `panel_with_all_kinds` and `panel_with_part_pose` from the Task 1
  characterisation builders. The `*_for_test` names above stand for
  whatever selection calls those builders use; use the real event
  dispatches (`select_pin:0`, `select_light:0`, …).

- [ ] **Step 2: Run the tests and watch them fail.**

  Run: `uv run pytest tests/unit/test_spv_edit_targets.py -q`

  Expected: FAIL (`edit_target_for` returns None).

- [ ] **Step 3: Implement the adapters.**
  - Move each branch of `_target_pos_of` and `_set_transform_target_pos`
    **verbatim** into the matching adapter's `position` and
    `set_position`.
  - Move the origin and axes computation for each kind in
    `transform_gizmo` into `gizmo_frame`.
  - Move `_coord_clipboard_kind`'s branches into `coord_kind`.
  - Move `_current_target_is_locked_mount` into `MountTarget.locked`.

  Then rewrite the panel methods to call `self._edit_target()`, returning
  `None` or no-op when it is `None`. The panel methods to rewrite:
  - `transform_coords`
  - the `coord_nudge`, `coord_copy`, `coord_paste` and `coord_mirror`
    handlers
  - `_begin_axis_drag` and `_apply_axis_drag`
  - `transform_gizmo`

  Delete the now-unused ladders.

  Keep the decal early returns (`_decal_transform_coords`,
  `_decal_panel_nudge("coord", …)`, and the `_decal_gizmo` pre-empt)
  exactly where they are. Decals migrate in Task 6.

- [ ] **Step 4: Run the new tests, the characterisation suite and the SPV
  selection.** All PASS, with no characterisation expectation edited.

- [ ] **Step 5: Commit.**

```bash
git add engine/ui/spv_edit_targets.py engine/ui/ship_property_viewer_panel.py tests/unit/test_spv_edit_targets.py
git commit -m "refactor(spv): Move tool through per-kind EditTarget adapters"
```

### Task 3: Scale tool through the adapters

**Files:**
- Modify: `engine/ui/spv_edit_targets.py`
- Modify: `engine/ui/ship_property_viewer_panel.py`, covering:
  - `_scale_kind_and_fields`
  - `_scale_target`
  - `scale_values`
  - `_set_scale_field`
  - the `scale_nudge`, `scale_copy`, `scale_paste` and `scale_uniform`
    handlers
  - `_begin_scale_drag` and `_apply_scale_drag`, including the cone
    handle→field map
  - `scale_gizmo`
- Test: `tests/unit/test_spv_edit_targets.py`

**Interfaces:**
- Consumes: `_edit_target()` from Task 2.
- Produces: `scale_spec()`, `get_scale()`, `set_scale_field()`,
  `scale_drag_begin()`, `scale_drag_apply()` and `scale_kind()` on every
  adapter.
  - Part adapters return `None` from `scale_spec()`, as today's kind
    `"none"` is empty.
  - `scale_kind()` returns the same `(kind, fields)` tuple
    `_scale_kind_and_fields` returns today.

- [ ] **Step 1: Write the failing tests.** For each non-decal case,
  `panel._edit_target().scale_kind()` equals the tuple the characterisation
  suite recorded for that case. Also, `PartAnchorTarget.scale_spec()` is
  `None`.
- [ ] **Step 2: Run the tests and watch them fail.**
- [ ] **Step 3: Move the per-kind branches verbatim into the adapters.**
  Rewrite the panel's scale methods against `_edit_target()`, then delete
  the ladders. The decal scale early returns stay until Task 6.
- [ ] **Step 4: Run the new tests, the characterisation suite and the SPV
  selection.** All PASS, and no expectation is edited.
- [ ] **Step 5: Commit.**
  `refactor(spv): Scale tool through EditTarget adapters`

### Task 4: Rotate tool through the adapters

**Files:**
- Modify: `engine/ui/spv_edit_targets.py`
- Modify: `engine/ui/ship_property_viewer_panel.py`, covering:
  - `_rotate_target`, `rotate_values`, `_rotate_clipboard_kind` and
    `_rotate_axis`
  - `_mirror_target_rotation`
  - the `rotate_nudge`, `rotate_copy`, `rotate_paste` and `rotate_mirror`
    handlers
  - `_begin_ring_drag` and `_apply_ring_drag_angle`, including the part
    pose's `part_pose.hinge_pose` about the posed anchor
  - `rotate_gizmo`
- Test: `tests/unit/test_spv_edit_targets.py`

**Interfaces:**
- Consumes: `_edit_target()`.
- Produces, on every adapter: `rotate_spec()`, `get_rotation()`,
  `set_rotation()`, `rotate_nudge()`, `ring_drag_begin()`,
  `ring_drag_apply()` and `rotate_kind()`.
  - `rotate_kind()` returns today's tags exactly: `pose_euler`,
    `cone_orientation`, `box_orientation`, `cylinder_axis` or `None`.
  - Rotation mirroring moves into each adapter's `mirror()`. This is
    rotation-only for now; Task 5 folds position in.

- [ ] **Step 1: Write the failing tests.** Add `rotate_kind()` per case,
  and pin these two cases:
  - A cylinder light and a strip emitter both return `"cylinder_axis"`.
  - A sphere light, a point emitter, a subsystem and a part anchor return
    `None` from `rotate_spec()`.
- [ ] **Step 2: Run the tests and watch them fail.**
- [ ] **Step 3: Implement.** Move the branches verbatim, rewrite the
  panel's rotate methods, and delete the ladders. The decal rotate early
  returns stay until Task 6.
- [ ] **Step 4: Run the new tests, the characterisation suite and the SPV
  selection.** All PASS.
- [ ] **Step 5: Commit** with message
  `refactor(spv): Rotate tool through EditTarget adapters`.

### Task 5: Pipette and Mirror Element through the adapters

**Files:**
- Modify: `engine/ui/spv_edit_targets.py`.
- Modify: `engine/ui/ship_property_viewer_panel.py`:
  - `_apply_pipette` (~1442);
  - the pipette arm/pick logic in `_dispatch_event_inner` (~3185–3229);
  - the `mirror_element` handler.
- Test: `tests/unit/test_spv_edit_targets.py`.

**Interfaces:**
- Consumes: position, rotate and scale on the adapters (Tasks 2–4).
- Produces:
  - **`pipette_fields_from(src) -> tuple[str, ...]`**, drawn from
    `("position", "rotation", "scale", "colour")`:
    - position: always;
    - rotation: iff `src.rotate_kind() == self.rotate_kind()` and it is
      not `None`;
    - scale: iff `scale_kind` matches;
    - colour: emitter → emitter only.
    - Part and decal adapters return `()` as a TARGET, and are never
      offered as a source (unchanged).
  - **`mirror()`**, the combined reflection in place: position x-flip plus
    each kind's rotation mirror from Task 4.

- [ ] **Step 1: Write the failing tests.** For every ordered pair of
  non-part, non-decal cases, `tgt.pipette_fields_from(src)` equals the set
  of fields the characterisation suite recorded as changing.
- [ ] **Step 2: Run the tests and watch them fail.**
- [ ] **Step 3: Implement.** Move the branches verbatim, then rewrite
  `_apply_pipette` as:

```python
def _apply_pipette(self, src, tgt):
    for field in tgt.pipette_fields_from(src):
        if field == "position":
            tgt.set_position(src.position())
        elif field == "rotation":
            tgt.set_rotation(src.get_rotation())
        elif field == "scale":
            for name, value in src.get_scale().items():
                tgt.set_scale_field(name, value)
        elif field == "colour":
            tgt.set_colour(src.colour())   # EmitterTarget only
```

  - `EmitterTarget` gains `colour()` and `set_colour()`, moved from the
    current emitter-to-emitter colour copy.
  - The `mirror_element` handler becomes `t = self._edit_target();
    t.mirror()` when `t` is truthy.
  - The arm/pick logic resolves adapters instead of raw tuples. Its rule
    that part nodes never arm the pipette stays.
- [ ] **Step 4: Run the new tests, the characterisation suite and the SPV
  selection.** All PASS.
- [ ] **Step 5: Commit.** Message:
  `refactor(spv): Pipette and Mirror Element through EditTarget adapters`.

### Task 6: `DecalTarget`, and decal Copy/Paste/Mirror

**Files:**
- Modify: `engine/ui/spv_edit_targets.py` (`DecalTarget`)
- Modify: `engine/ui/spv_decals_pane.py`
  - Move `_decal_transform_coords`, `_decal_rotate_values`,
    `_decal_scale_values`, `_decal_panel_nudge`, `_decal_gizmo`,
    `_decal_begin_drag` and `_decal_apply_axis_drag` / `_apply_scale_drag`
    / `_apply_ring_drag` into `DecalTarget`, then delete them from the
    pane.
  - Add a `_decal_mirror_selected()` helper.
- Modify: `engine/ui/ship_property_viewer_panel.py`
  - `edit_target_for` returns a `DecalTarget(("decal", name))` when
    `_decal_selected` is set.
  - Remove the decal early returns from the producers, handlers, gizmo
    and drags.
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
  - `spvShowPanel`: stop hiding the action row when `decal === true`.
    Keep the stepper labels driven by `step_scale`.
- Modify: `tests/ui/test_spv_edit_target_characterisation.py`. Only the
  `decal` case's clipboard and mirror expectations change, from the
  pinned gaps to the new behaviour. Record this in the commit message.
- Create: `tests/ui/test_spv_decal_clipboard_mirror.py`

**Interfaces:**
- Consumes: the Task 2–5 adapter surface; `decal_editor` (`Placement`,
  `centre`, `set_centre`, `set_width`, `roll`, `roll_angle`, `mask_of`,
  `chirality_ok`, `width`); the pane's `_decal_aspect(mask)`,
  `_decal_working`, `_decal_selected`, `_decal_sync_override()` and
  `_decal_error`.
- Produces, on `DecalTarget`:
  - `coord_kind()`, `rotate_kind()` and `scale_kind()` each return
    `"decal"`.
  - `pipette_fields_from()` returns `()`.
  - `mirror()` is implemented as in Step 3.

- [ ] **Step 1: Write the failing tests** in
  `tests/ui/test_spv_decal_clipboard_mirror.py`:

```python
def test_decal_coord_copy_paste_moves_centre(pane_with_two_decals):
    p = pane_with_two_decals            # "pylon" and "pylon_2", both mask "pylon"
    p.dispatch_event("decal-select:pylon"); p.dispatch_event("coord_copy")
    p.dispatch_event("decal-select:pylon_2"); p.dispatch_event("coord_paste")
    assert centre(p._decal_by_name("pylon_2")) == pytest.approx(centre(p._decal_by_name("pylon")))

def test_decal_scale_paste_is_aspect_locked(pane_with_two_decals_different_masks):
    ...  # paste width from a 2:1 mask decal onto a 4:1 mask decal -> |u|/|v| == 4

def test_decal_rotate_paste_copies_roll(pane_with_two_decals):
    ...  # roll_angle(dst, FWD, UP) == roll_angle(src, FWD, UP) (3-arg form)

def test_decal_paste_refused_onto_light_and_vice_versa(panel_with_decal_and_light):
    ...  # can_paste False both ways; staged state unchanged

def test_decal_mirror_creates_readable_copy_sharing_mask(pane_with_two_decals):
    p = pane_with_two_decals
    p.dispatch_event("decal-select:pylon"); p.dispatch_event("mirror_element")
    new = p._decal_by_name("pylon_3")
    src = p._decal_by_name("pylon")
    assert mask_of(new) == "pylon" and chirality_ok(new)
    cs, cn = centre(src), centre(new)
    assert cn == pytest.approx((-cs[0], cs[1], cs[2]))
    assert p._decal_selected == "pylon_3"

def test_decal_mirror_on_centreline_is_readable_and_not_degenerate(pane_with_centreline_decal):
    ...  # Review Focus 5

def test_decal_mirror_refused_at_16(pane_with_16_decals):
    ...  # no new placement; p._decal_error set

def test_each_paste_and_mirror_is_one_undo_step(pane_with_two_decals):
    ...  # undo stack length +1 per action; undo restores
```

- [ ] **Step 2: Run the tests and watch them fail.**

  Run: `uv run pytest tests/ui/test_spv_decal_clipboard_mirror.py -q`

- [ ] **Step 3: Implement.** Move the decal hooks into `DecalTarget`
  verbatim. `DecalTarget.mirror()`:

```python
def mirror(self):
    pane = self.panel
    if len(pane._decal_working) >= 16:
        pane._decal_error = "Mirror refused: 16 placements is the maximum"
        return
    p = pane._decal_by_name(self.key[1])
    fx = lambda v: (-v[0], v[1], v[2])
    o, u, v, n = fx(p.origin), fx(p.u_axis), fx(p.v_axis), fx(p.normal)
    new_origin = (o[0] + u[0], o[1] + u[1], o[2] + u[2])
    new_u = (-u[0], -u[1], -u[2])
    mask = decal_editor.mask_of(p)
    name = pane._decal_free_name(mask)      # "<mask>_N", first free N >= 2
    q = dataclasses.replace(p, name=name, mask=mask, origin=new_origin,
                            u_axis=new_u, v_axis=v, normal=n)
    pane._decal_working.append(q)
    pane._decal_selected = name
    pane._decal_sync_override()
```

  `_decal_free_name` is the auto-naming helper that `decal-add` already
  uses. Reuse it, and rename it only if it has a different name.

- [ ] **Step 4: Run all of these; all PASS.**
  - The new tests.
  - The characterisation suite, with only the decal clipboard and mirror
    expectations updated.
  - The SPV selection.
  - `uv run pytest tests/ui -q -k cef` for the JS harness.

- [ ] **Step 5: Commit.**

```bash
git add engine/ui/spv_edit_targets.py engine/ui/spv_decals_pane.py engine/ui/ship_property_viewer_panel.py native/assets/ui-cef/js/ship_property_viewer.js tests/ui/test_spv_edit_target_characterisation.py tests/ui/test_spv_decal_clipboard_mirror.py
git commit -m "feat(spv): decals as an EditTarget; per-tool Copy/Paste and Mirror for decals"
```

### Task 7: Clean-up, ladder guard, docs, gate

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` and
  `engine/ui/spv_decals_pane.py`, to delete dead helpers.
- Create: `tests/unit/test_spv_no_kind_ladders.py`.
- Modify: `CLAUDE.md`, the Ship Property Viewer row.

- [ ] **Step 1: Write the ladder guard test.** It parses the two panel
  modules with `ast` and fails if any `if`/`elif` compares a target kind
  string against these literals:
  `"subsystem"`, `"light"`, `"emitter"`, `"part_anchor"`, `"part_pose"`,
  `"decal"`.

  Kind dispatch belongs only in `spv_edit_targets.py`. Selection code that
  legitimately matches event prefixes, such as `select_light:`, is not a
  kind comparison. Match on `==` or `in` against a bare kind literal, not
  on `startswith`.

```python
import ast, pathlib
KINDS = {"subsystem", "light", "emitter", "part_anchor", "part_pose", "decal"}
FILES = ["engine/ui/ship_property_viewer_panel.py", "engine/ui/spv_decals_pane.py"]

def _kind_compares(tree):
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare):
            for c in [node.left, *node.comparators]:
                if isinstance(c, ast.Constant) and c.value in KINDS:
                    yield node.lineno

def test_no_per_kind_ladders_outside_edit_targets():
    root = pathlib.Path(__file__).resolve().parents[2]
    hits = {f: list(_kind_compares(ast.parse((root / f).read_text())))
            for f in FILES}
    assert all(not v for v in hits.values()), hits
```

- [ ] **Step 2: Run the guard, then delete the leftovers it names.** Run it
  and delete every leftover it names: dead helpers and remaining ladders.
  If a hit is genuinely not per-kind tool dispatch, restructure it so it no
  longer compares against a kind literal. Don't add an exemption list.
- [ ] **Step 3: Update the `CLAUDE.md` Ship Property Viewer row.** Add this
  sentence: "Every tool (Move/Rotate/Scale, Copy/Paste, Mirror, Pipette,
  gizmo drags) is written once against a per-kind `EditTarget` adapter in
  `engine/ui/spv_edit_targets.py`; a new editable kind implements an
  adapter, never a new branch in the panel." Keep within the
  `tests/docs` budget: `uv run pytest tests/docs -q`.
- [ ] **Step 4: Run the gate.**

  Run: `scripts/check_tests.sh`, in the foreground.

  Expected: `OK — no new failures`.
- [ ] **Step 5: Commit.**

```bash
git add engine/ui/ship_property_viewer_panel.py engine/ui/spv_decals_pane.py tests/unit/test_spv_no_kind_ladders.py CLAUDE.md
git commit -m "refactor(spv): remove leftover per-kind ladders; guard; docs"
```
