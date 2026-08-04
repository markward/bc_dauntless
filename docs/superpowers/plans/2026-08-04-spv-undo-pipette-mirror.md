# SPV Undo / Pipette / Mirror Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a third action-button row to the SPV bottom-right tool cluster — Undo, Pipette, and Mirror — operating on the staged-edit layer.

**Architecture:** All logic lives in the Python panel (`ship_property_viewer_panel.py`), layered on the existing `_pending_*` staging model. Undo is a snapshot stack captured around each mutation; Pipette is a one-shot eyedropper that composes the existing setters; Mirror flips the selected element across the ship's X centerline. A fourth task wires the CEF row (HTML/JS/CSS) and the click-bbox constant.

**Tech Stack:** Python 3 (pytest), CEF (HTML/JS/CSS), no C++ changes.

**Design doc:** `docs/superpowers/specs/2026-08-04-spv-undo-pipette-mirror-design.md`

## Global Constraints

- **Pending-only undo.** Save clears the undo history; there is no cross-Save undo.
- **No redo** state or button (deferred). The snapshot stack must not grow a redo stack.
- **Reuse existing setters/mirror math** — `_set_transform_target_pos`, `_set_axis_absolute`, `_set_orientation_absolute`, `_set_scale_field`, `_rotate_clipboard_kind`, `_rotate_target`, `_scale_kind_and_fields`. Factor `rotate_mirror`'s body into a shared `_mirror_target_rotation` rather than duplicating it.
- **Emitter edits restage the whole compacted list** (`_pending_emitter[i] = lst`) — never a sparse `(i, j)` key, never an index gap (`baked_emitters` stops at the first gap on reload).
- **CEF is mouse-only** — buttons only, no keyboard bindings.
- Production render path and byte-identity of unchanged saves must be unaffected (pure authoring UI).
- Test gate: `scripts/check_tests.sh` (build + pytest + ctest vs `tests/known_failures.txt`).

---

### Task 1: Undo snapshot stack

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_undo.py` (create)

**Interfaces:**
- Consumes: `_pending_radius`, `_pending_light`, `_pending_emitter`, `_pending_pos` (existing staged dicts); `_effective_emitter`, `_selected_emitter`, `_descriptors`; the existing `dispatch_event`, `_begin_axis_drag`, `_begin_scale_drag`, `_begin_ring_drag`, `_end_axis_drag`, `save` handler, `render_payload`.
- Produces: `self._undo_stack` (list of snapshots); `_snapshot_pending()`, `_restore_pending(snap)`, `undo()`; the `"undo"` dispatch action; payload key `"can_undo"`. Later tasks rely on the `dispatch_event` wrapper so their mutations auto-record one undo entry each.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_ship_property_viewer_undo.py`. Use the existing SPV panel test fixtures as a reference for constructing a panel with descriptors (see `tests/ui/test_ship_property_viewer_panel_emitter.py` for the fixture pattern — a `ship_getter` returning a fake ship and `build_descriptors`, or the panel's own helpers). The test drives a subsystem-radius edit and asserts undo restores it:

```python
def test_undo_restores_prior_radius(spv_panel):
    p = spv_panel
    # Select a subsystem and stage a radius edit via the public dispatch.
    p.dispatch_event("select_pin:0")
    assert 0 not in p._pending_radius
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    assert p._pending_radius[0] == 3.0
    assert p._undo_stack, "a real mutation records one undo entry"
    p.dispatch_event("undo")
    assert 0 not in p._pending_radius, "undo restored the pre-edit state"
    assert not p._undo_stack


def test_noop_dispatch_records_nothing(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")     # selection is not an edit
    p.dispatch_event("scale_copy")       # clipboard only, no pending change
    assert not p._undo_stack


def test_can_undo_in_payload(spv_panel):
    p = spv_panel
    p.open()
    import json
    p.dispatch_event("select_pin:0")
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    js = p.render_payload()
    assert js is not None
    data = json.loads(js[js.index("(") + 1: js.rindex(")")])
    assert data["can_undo"] is True
```

Add a fixture `spv_panel` at the top of the file that builds a panel with at least one descriptor that has an emitter-capable subsystem. Mirror the construction used in `tests/ui/test_ship_property_viewer_panel_emitter.py`; if that file exposes a reusable helper, import it instead of duplicating.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer_undo.py -v`
Expected: FAIL — `_undo_stack` attribute missing / `"undo"` action unhandled / `can_undo` absent.

- [ ] **Step 3: Add snapshot state + helpers**

In `__init__` (near the other clipboard fields ~line 190) add:

```python
self._undo_stack: list = []
# Transient snapshot captured at drag-begin, committed at drag-end.
self._drag_undo_before = None
```

Add the same two resets to `open()` and `close()` (alongside the `_coord_clipboard = None` resets).

Add the helpers (place them near `_active_transform_target`):

```python
def _snapshot_pending(self):
    """Deep copy of the four staged-edit dicts — one undo unit."""
    import copy
    return (copy.deepcopy(self._pending_radius),
            copy.deepcopy(self._pending_light),
            copy.deepcopy(self._pending_emitter),
            copy.deepcopy(self._pending_pos))

def _restore_pending(self, snap) -> None:
    """Replace the four staged-edit dicts from a snapshot, drop a now-stale
    emitter selection, and force a CEF re-push."""
    import copy
    r, l, e, p = snap
    self._pending_radius = copy.deepcopy(r)
    self._pending_light = copy.deepcopy(l)
    self._pending_emitter = copy.deepcopy(e)
    self._pending_pos = copy.deepcopy(p)
    if self._selected_emitter is not None:
        i, j = self._selected_emitter
        if not (0 <= i < len(self._descriptors)) \
                or self._effective_emitter(i, j) is None:
            self._selected_emitter = None
    self._last_pushed = None

def undo(self) -> None:
    if self._undo_stack:
        self._restore_pending(self._undo_stack.pop())
```

- [ ] **Step 4: Wrap the dispatcher (diff-guarded)**

Rename the existing `def dispatch_event(self, action: str) -> bool:` body to `def _dispatch_event_inner(self, action: str) -> bool:` (rename the method only; leave its body untouched). Add the `"undo"` action near the top of `_dispatch_event_inner`:

```python
if action == "undo":
    self.undo()
    return True
```

Add the wrapper above it:

```python
_NO_UNDO_ACTIONS = ("undo", "save", "cancel")

def dispatch_event(self, action: str) -> bool:
    if action in self._NO_UNDO_ACTIONS or action.startswith("overlay:"):
        return self._dispatch_event_inner(action)
    before = self._snapshot_pending()
    result = self._dispatch_event_inner(action)
    if before != self._snapshot_pending():
        self._undo_stack.append(before)
    return result
```

(`_NO_UNDO_ACTIONS` is a class attribute; define it at class body level.)

- [ ] **Step 5: Bracket drags + clear on Save**

In `_begin_axis_drag`, `_begin_scale_drag`, and `_begin_ring_drag`, at the start of each, add:

```python
self._drag_undo_before = self._snapshot_pending()
```

In `_end_axis_drag`, after the drag is finalised, add:

```python
if self._drag_undo_before is not None:
    if self._drag_undo_before != self._snapshot_pending():
        self._undo_stack.append(self._drag_undo_before)
    self._drag_undo_before = None
```

In the `save` handler, immediately after the staged dicts are cleared on a successful write (where `_pending_radius`/`_pending_light`/`_pending_emitter`/`_pending_pos` are reset), add:

```python
self._undo_stack.clear()
self._drag_undo_before = None
```

- [ ] **Step 6: Payload**

In `render_payload`, add `"can_undo": bool(self._undo_stack)` to the `payload` dict, and add `len(self._undo_stack)` to the `snapshot` tuple (so the button state re-pushes when the stack flips between empty and non-empty).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_undo.py -v`
Expected: PASS.

- [ ] **Step 8: Add drag + save coverage, verify**

Add to the test file:

```python
def test_drag_records_one_undo_entry(spv_panel):
    p = spv_panel
    p.active_tool = "transform"
    p.dispatch_event("select_pin:0")
    p._begin_axis_drag(0, 0.0)          # press
    p._apply_axis_drag(0.5)             # move (stages a position edit)
    p._end_axis_drag()                  # release
    assert len(p._undo_stack) == 1


def test_save_clears_undo(spv_panel, monkeypatch):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event('set_radius:{"i":0,"value":3.0}')
    # Make save a no-write success (leaf unresolved) OR stub the writer; the
    # point is the post-clear branch runs. Follow the save-path stubbing used
    # in the existing panel save tests.
    p.dispatch_event("save")
    assert not p._undo_stack
```

If `_apply_axis_drag` needs a camera/gizmo the headless fixture lacks, use `_begin_axis_drag_for_test` (already in the panel) or stage the position directly via `set_subsystem_position` between begin/end — the assertion is on the undo entry count, not the drag mechanics. Match whatever the existing gizmo-drag tests do.

Run: `uv run pytest tests/ui/test_ship_property_viewer_undo.py -v`
Expected: PASS.

- [ ] **Step 9: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_undo.py
git commit -m "feat(spv): undo snapshot stack over staged edits"
```

---

### Task 2: Pipette eyedropper

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_pipette.py` (create)

**Interfaces:**
- Consumes: `_active_transform_target`, `_transform_target_pos`, `_set_transform_target_pos`, `_effective_emitter`, `_effective_emitters`, `_effective_light`, `_effective_pos`, `_rotate_clipboard_kind`, `_rotate_target`, `_set_axis_absolute`, `_set_orientation_absolute`, `_scale_kind_and_fields`, `_set_scale_field`, the Task 1 `dispatch_event` wrapper, `handle_key_esc`, `render_payload`.
- Produces: `self._pipette_armed` (bool); the `"pipette"` action; source-pick interception in `_dispatch_event_inner`; `_apply_pipette(src)` + `_target_pos_of(target)`; payload keys `"pipette_armed"`, `"has_selection"`.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_ship_property_viewer_pipette.py` (reuse the `spv_panel` fixture pattern from Task 1; if useful, promote the fixture to `tests/ui/conftest.py`). Cover arming, source consumption, and per-aspect copy. Assume the fixture ship has a subsystem index 0 with a strip emitter and index 1 with another strip emitter (add emitters in-test via `add_emitter` if needed):

```python
def test_pipette_requires_selection(spv_panel):
    p = spv_panel
    p.dispatch_event("deselect")
    p.dispatch_event("pipette")
    assert p._pipette_armed is False   # nothing selected → cannot arm


def test_pipette_copies_position_without_changing_selection(spv_panel):
    p = spv_panel
    # Two subsystems: give #1 a distinct position, select #0 as target.
    p.set_subsystem_position(1, (5.0, 0.0, 0.0))
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    p.dispatch_event("select_pin:1")   # #1 is the SOURCE
    assert p._pipette_armed is False
    assert p.selected_index == 0        # selection unchanged
    assert p._effective_pos(0) == (5.0, 0.0, 0.0)
    assert p._undo_stack               # one undo entry for the apply


def test_pipette_source_equals_target_is_noop(spv_panel):
    p = spv_panel
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    p.dispatch_event("select_pin:0")
    assert p._pipette_armed is False
    assert not p._undo_stack
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer_pipette.py -v`
Expected: FAIL — `_pipette_armed` missing / `"pipette"` unhandled.

- [ ] **Step 3: State + arming + interception**

In `__init__` add `self._pipette_armed = False`; reset it to `False` in `open()` and `close()`.

Add the `"pipette"` action to `_dispatch_event_inner`:

```python
if action == "pipette":
    if self._pipette_armed:
        self._pipette_armed = False
    elif self._active_transform_target() is not None:
        self._pipette_armed = True
    self._last_pushed = None
    return True
```

At the **top** of `_dispatch_event_inner` (before the `select_*` handlers), intercept the source pick while armed:

```python
if self._pipette_armed:
    src = None
    if action.startswith("select_pin:"):
        try:
            idx = int(action.split(":", 1)[1])
        except ValueError:
            idx = -1
        if 0 <= idx < len(self._descriptors):
            src = ("subsystem", idx)
    elif action.startswith("select_light:"):
        try:
            idx = int(action.split(":", 1)[1])
        except ValueError:
            idx = -1
        if 0 <= idx < len(self._descriptors) and self._has_light(idx):
            src = ("light", idx)
    elif action.startswith("select_emitter:"):
        try:
            arg = json.loads(action.split(":", 1)[1])
            i = int(arg["i"]); j = int(arg["j"])
        except (ValueError, KeyError, TypeError):
            i = j = -1
        if 0 <= i < len(self._descriptors) and self._effective_emitter(i, j) is not None:
            src = ("emitter", i, j)
    # Any select_* while armed consumes the pick (valid → apply); any other
    # action, or an invalid pick, cancels the arm and falls through.
    if action.startswith(("select_pin:", "select_light:", "select_emitter:")):
        self._pipette_armed = False
        self._last_pushed = None
        if src is not None:
            self._apply_pipette(src)
        return True
    self._pipette_armed = False
    self._last_pushed = None
    # fall through to normal handling of the non-select action
```

- [ ] **Step 4: Apply + helpers**

Add `_target_pos_of` and refactor `_transform_target_pos` to delegate:

```python
def _target_pos_of(self, target):
    """Body-frame (x, y, z) of an arbitrary transform target, or None."""
    if target is None:
        return None
    if target[0] == "emitter":
        _, i, j = target
        spec = self._effective_emitter(i, j)
        return tuple(float(c) for c in spec["position"]) if spec else None
    kind, i = target
    if kind == "light":
        spec = self._effective_light(i)
        return tuple(float(c) for c in spec["position"]) if spec else None
    return tuple(float(c) for c in self._effective_pos(i))
```

Change `_transform_target_pos` to `return self._target_pos_of(self._active_transform_target())`.

Add the apply method:

```python
def _apply_pipette(self, src) -> None:
    """Copy every aspect the target can hold from `src` onto the current
    selection (the target). Incompatible aspects are silently skipped."""
    tgt = self._active_transform_target()
    if tgt is None or src == tgt:
        return
    # 1. Position (always) — set on the active target.
    spos = self._target_pos_of(src)
    if spos is not None:
        self._set_transform_target_pos(spos)
    # 2. Rotation — only when both share a rotate kind.
    if self._rotate_target() is not None \
            and self._src_rotate_target(src) is not None \
            and self._rotate_clipboard_kind(src) == self._rotate_clipboard_kind(tgt):
        kind = self._rotate_clipboard_kind(src)
        if kind == "cylinder_axis":
            axis = self._src_axis(src)
            if axis is not None:
                self._set_axis_absolute(tgt, axis)
        else:  # box_orientation / cone_orientation
            fu = self._src_orientation(src)
            if fu is not None:
                self._set_orientation_absolute(tgt, fu[0], fu[1])
    # 3. Scale — only when both share a scale kind.
    skind, sfields = self._scale_kind_and_fields(src)
    tkind, _ = self._scale_kind_and_fields(tgt)
    if skind == tkind:
        for idx, f in enumerate(sfields):
            self._set_scale_field(idx, f["value"])
    # 4. Colour + intensity — emitter → emitter only.
    if src[0] == "emitter" and tgt[0] == "emitter":
        ssp = self._effective_emitter(src[1], src[2])
        if ssp is not None:
            _, ti, tj = tgt
            lst = list(self._effective_emitters(ti))
            if 0 <= tj < len(lst):
                spec = dict(lst[tj])
                spec["color"] = tuple(ssp["color"])
                spec["intensity"] = float(ssp["intensity"])
                lst[tj] = spec
                self._pending_emitter[ti] = lst
                self._last_pushed = None
```

Add the small source-reader helpers used above (they read `src`'s axis / orientation / rotate-eligibility, mirroring `rotate_copy`'s logic but for an arbitrary target):

```python
def _src_rotate_target(self, src):
    """src if it is rotate-capable (cylinder/box light, strip/cone emitter),
    else None — mirrors _rotate_target but for an explicit target."""
    if src[0] == "emitter":
        spec = self._effective_emitter(src[1], src[2])
        return src if spec and spec.get("kind") in ("strip", "cone") else None
    if src[0] == "light":
        spec = self._effective_light(src[1])
        return src if spec and spec.get("shape") in ("Cylinder", "Box") else None
    return None

def _src_axis(self, src):
    if src[0] == "emitter":
        spec = self._effective_emitter(src[1], src[2]) or {}
    else:
        spec = self._effective_light(src[1]) or {}
    return tuple(spec.get("axis") or (0.0, -1.0, 0.0)) if spec else None

def _src_orientation(self, src):
    """(forward, up) for a box light or cone emitter source, else None."""
    if src[0] == "emitter":
        spec = self._effective_emitter(src[1], src[2]) or {}
        if spec.get("kind") == "cone":
            from engine.appc.light_emitters import _derive_up
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            return (tuple(fwd), tuple(spec.get("up") or _derive_up(fwd)))
        return None
    spec = self._effective_light(src[1]) or {}
    if spec.get("shape") == "Box":
        fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
        return (tuple(fwd), tuple(up))
    return None
```

- [ ] **Step 5: ESC disarm + payload**

In `handle_key_esc`, at the very top after the `if not self._visible: return` guard, add:

```python
if self._pipette_armed:
    self._pipette_armed = False
    self._last_pushed = None
    return
```

In `render_payload`, add `"pipette_armed": self._pipette_armed` and `"has_selection": self._active_transform_target() is not None` to `payload`, and add both (`self._pipette_armed`, and the has-selection bool) to the `snapshot` tuple.

- [ ] **Step 6: Run tests + add aspect coverage**

Add tests for rotation/scale/colour copy and skip-on-mismatch, plus ESC:

```python
def test_pipette_copies_scale_on_matching_kind(spv_panel):
    p = spv_panel
    # both #0 and #1 are subsystems → scale kind "radius" matches
    p.dispatch_event('set_radius:{"i":1,"value":7.0}')
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    p.dispatch_event("select_pin:1")
    assert p._effective_radius(0, None) == 7.0


def test_pipette_esc_disarms(spv_panel):
    p = spv_panel
    p.open()
    p.dispatch_event("select_pin:0")
    p.dispatch_event("pipette")
    assert p._pipette_armed is True
    p.handle_key_esc()
    assert p._pipette_armed is False
    assert p.is_open()   # ESC only disarmed; did not close the panel
```

Add colour/intensity emitter→emitter and rotation-mismatch-skip tests following the same shape (arm on a target, pick an incompatible-shape source, assert the incompatible aspect was NOT changed while position WAS). Use `add_emitter` dispatches to give subsystems emitters of specific kinds.

Run: `uv run pytest tests/ui/test_ship_property_viewer_pipette.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_pipette.py tests/ui/conftest.py
git commit -m "feat(spv): pipette eyedropper copies transform/rotation/scale/colour"
```

(Include `tests/ui/conftest.py` only if you promoted the fixture there.)

---

### Task 3: Mirror whole-element

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_mirror.py` (create)

**Interfaces:**
- Consumes: `_active_transform_target`, `_transform_target_pos`, `_set_transform_target_pos`, `_rotate_target`, `_effective_emitter`, `_effective_light`, `_set_axis_absolute`, `_set_orientation_absolute`, the existing `rotate_mirror` handler body, Task 1's `dispatch_event` wrapper.
- Produces: `_mirror_target_rotation(rt)` (extracted from `rotate_mirror`); the `"mirror_element"` action.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_ship_property_viewer_mirror.py`:

```python
def test_mirror_element_negates_position_x(spv_panel):
    p = spv_panel
    p.set_subsystem_position(0, (3.0, 1.0, 2.0))
    p.dispatch_event("select_pin:0")
    p.dispatch_event("mirror_element")
    assert p._effective_pos(0) == (-3.0, 1.0, 2.0)
    assert p._undo_stack


def test_mirror_element_flips_strip_emitter_axis_x(spv_panel):
    p = spv_panel
    # give subsystem 0 a strip emitter with a known axis
    p.dispatch_event('add_emitter:{"i":0,"kind":"strip"}')
    i, j = p._selected_emitter
    p._set_axis_absolute(("emitter", i, j), (0.6, 0.8, 0.0))
    p.dispatch_event("mirror_element")
    spec = p._effective_emitter(i, j)
    ax = spec["axis"]
    assert ax[0] < 0 and abs(ax[1] - 0.8) < 1e-6   # X negated, Y kept


def test_mirror_element_point_emitter_moves_position_only(spv_panel):
    p = spv_panel
    p.dispatch_event('add_emitter:{"i":0,"kind":"point"}')
    i, j = p._selected_emitter
    p.set_emitter_position(i, j, (2.0, 0.0, 0.0))
    before = dict(p._effective_emitter(i, j))
    p.dispatch_event("mirror_element")
    after = p._effective_emitter(i, j)
    assert after["position"][0] == -2.0
    assert after["color"] == before["color"]        # colour unchanged
    assert after["intensity"] == before["intensity"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer_mirror.py -v`
Expected: FAIL — `"mirror_element"` unhandled.

- [ ] **Step 3: Extract `_mirror_target_rotation` and reuse it in `rotate_mirror`**

Extract the body of the existing `rotate_mirror` handler (the block that mirrors the axis/orientation of the rotate target across X) into a method:

```python
def _mirror_target_rotation(self, t) -> None:
    """Reflect the rotate target `t`'s orientation across the ship X axis
    (starboard): negate X of the axis (cylinder/strip) or of both forward
    and up (box/cone), then set it absolutely."""
    if t[0] == "emitter":
        _, i, j = t
        spec = self._effective_emitter(i, j) or {}
        if spec.get("kind") == "cone":
            from engine.appc.light_emitters import _derive_up
            fwd = spec.get("axis") or (0.0, -1.0, 0.0)
            up = spec.get("up") or _derive_up(fwd)
            self._set_orientation_absolute(t, (-fwd[0], fwd[1], fwd[2]),
                                           (-up[0], up[1], up[2]))
        else:
            axis = list(spec.get("axis") or (0.0, -1.0, 0.0))
            axis[0] = -axis[0]
            self._set_axis_absolute(t, axis)
    else:
        _, i = t
        spec = self._effective_light(i) or {}
        if spec.get("shape") == "Box":
            fwd, up = spec.get("orientation") or ((0.0, 1.0, 0.0), (0.0, 0.0, 1.0))
            self._set_orientation_absolute(i, (-fwd[0], fwd[1], fwd[2]),
                                           (-up[0], up[1], up[2]))
        else:
            axis = list(spec.get("axis") or (0.0, -1.0, 0.0))
            axis[0] = -axis[0]
            self._set_axis_absolute(t, axis)
```

Replace the `rotate_mirror` handler body with:

```python
if action == "rotate_mirror":
    t = self._rotate_target()
    if t is not None:
        self._mirror_target_rotation(t)
    return True
```

(Behaviour must be identical to the current `rotate_mirror` — the existing rotate-mirror tests must still pass.)

- [ ] **Step 4: Add the `mirror_element` action**

In `_dispatch_event_inner`:

```python
if action == "mirror_element":
    t = self._active_transform_target()
    if t is not None:
        pos = self._transform_target_pos()
        if pos is not None:
            self._set_transform_target_pos((-pos[0], pos[1], pos[2]))
        rt = self._rotate_target()
        if rt is not None:
            self._mirror_target_rotation(rt)
    return True
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_mirror.py tests/ui/ -k "rotate_mirror or mirror" -v`
Expected: PASS, and the existing `rotate_mirror` tests still green (regression guard on the extraction).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_mirror.py
git commit -m "feat(spv): mirror-element flips selected node across starboard"
```

---

### Task 4: Toolbox action-button row (constants + HTML/JS/CSS)

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py` (layout constants only)
- Modify: `native/assets/ui-cef/index.html`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`
- Test: `tests/ui/test_ship_property_viewer_action_row.py` (create)

**Interfaces:**
- Consumes: `TOOLS_BTN_PT`, `TOOLS_GAP_PT`, `TOOLS_H_PT`, `TRANSFORM_H_PT`, `_cursor_over_tools`; payload keys `can_undo`, `pipette_armed`, `has_selection` (Tasks 1–2).
- Produces: `ACTION_H_PT`; a grown `TOOLS_CLUSTER_H_PT`; the `#spv-action-tools` row; `shipPropertyViewerUndo/Pipette/Mirror` JS; button-state wiring.

- [ ] **Step 1: Write the failing test**

Create `tests/ui/test_ship_property_viewer_action_row.py`:

```python
from engine.ui import ship_property_viewer_panel as m


def test_cluster_height_includes_action_row():
    expected = (m.TOOLS_H_PT + m.TOOLS_GAP_PT + m.TRANSFORM_H_PT
                + m.TOOLS_GAP_PT + m.ACTION_H_PT)
    assert m.TOOLS_CLUSTER_H_PT == expected


def test_cursor_over_tools_covers_new_row():
    # A point in the top row of the 3-row cluster (bottom-right) is inside.
    fb_w, fb_h, dsf = 1600.0, 900.0, 1.0
    # y at the very top of the cluster (top action row), x within the buttons.
    y_top = fb_h - m.TOOLS_MARGIN_PT - m.TOOLS_CLUSTER_H_PT + 2
    x_in = fb_w - m.TOOLS_MARGIN_PT - m.TOOLS_W_PT / 2
    assert m.ShipPropertyViewerPanel._cursor_over_tools(x_in, y_top, dsf, fb_w, fb_h)


HTML = "native/assets/ui-cef/index.html"
JS = "native/assets/ui-cef/js/ship_property_viewer.js"


def test_html_has_action_buttons():
    text = open(HTML).read()
    assert 'id="spv-action-tools"' in text
    for bid in ("spv-action-undo", "spv-action-pipette", "spv-action-mirror"):
        assert 'id="%s"' % bid in text


def test_js_defines_action_handlers():
    text = open(JS).read()
    for fn in ("shipPropertyViewerUndo", "shipPropertyViewerPipette",
               "shipPropertyViewerMirror"):
        assert fn in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/ui/test_ship_property_viewer_action_row.py -v`
Expected: FAIL — `ACTION_H_PT` missing; HTML/JS ids absent.

- [ ] **Step 3: Grow the layout constants**

In `ship_property_viewer_panel.py`, after `TOOLS_CLUSTER_H_PT` (~line 63):

```python
# Action-tools row (#spv-action-tools: Undo / Pipette / Mirror), stacked
# directly above #spv-transform-tools with the same TOOLS_GAP_PT.
ACTION_H_PT = TOOLS_BTN_PT
TOOLS_CLUSTER_H_PT = (TOOLS_H_PT + TOOLS_GAP_PT + TRANSFORM_H_PT
                      + TOOLS_GAP_PT + ACTION_H_PT)
```

Replace the existing `TOOLS_CLUSTER_H_PT = TOOLS_H_PT + TOOLS_GAP_PT + TRANSFORM_H_PT` line with the block above (define `ACTION_H_PT` before the reassignment).

- [ ] **Step 4: HTML — the action row**

In `native/assets/ui-cef/index.html`, directly above `<div id="spv-transform-tools">` (~line 205), add:

```html
      <!-- Action tools (undo / pipette / mirror). Momentary buttons stacked
           above #spv-transform-tools. Undo/Mirror disable without a target;
           Pipette shows .active while armed for a source pick. -->
      <div id="spv-action-tools">
        <button id="spv-action-undo" class="spv-tool"
                title="Undo" onclick="shipPropertyViewerUndo()">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M9 7L4 12l5 5"/><path d="M4 12h11a5 5 0 0 1 0 10h-1"/>
          </svg>
        </button>
        <button id="spv-action-pipette" class="spv-tool"
                title="Pipette: copy transform from another element"
                onclick="shipPropertyViewerPipette()">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M19 5a2 2 0 0 0-3 0l-2 2-1-1-2 2 6 6 2-2-1-1 2-2a2 2 0 0 0 0-3z"/>
            <path d="M12 8l-7 7v3h3l7-7"/>
          </svg>
        </button>
        <button id="spv-action-mirror" class="spv-tool"
                title="Mirror to the other side"
                onclick="shipPropertyViewerMirror()">
          <svg viewBox="0 0 24 24" width="22" height="22" fill="none"
               stroke="currentColor" stroke-width="2" stroke-linecap="round"
               stroke-linejoin="round">
            <path d="M12 3v18"/><path d="M7 8l-4 4 4 4"/><path d="M17 8l4 4-4 4"/>
          </svg>
        </button>
      </div>
```

- [ ] **Step 5: JS — handlers + button state**

In `native/assets/ui-cef/js/ship_property_viewer.js`, add near the other tool helpers (~line 706):

```javascript
// Action-tools row (Undo / Pipette / Mirror). Same event channel as the
// toggles above; Python re-pushes the payload so button state mirrors panel
// state (can_undo / pipette_armed / has_selection).
window.shipPropertyViewerUndo = function () {
    dauntlessEvent('ship-property-viewer/undo');
};
window.shipPropertyViewerPipette = function () {
    dauntlessEvent('ship-property-viewer/pipette');
};
window.shipPropertyViewerMirror = function () {
    dauntlessEvent('ship-property-viewer/mirror_element');
};
```

In `setShipPropertyViewer(data)`, near the other button-state updates (~line 58–69), add:

```javascript
var undoBtn = document.getElementById('spv-action-undo');
if (undoBtn) {
    undoBtn.disabled = data.can_undo !== true;
    undoBtn.classList.toggle('spv-tool--disabled', data.can_undo !== true);
}
var pipetteBtn = document.getElementById('spv-action-pipette');
if (pipetteBtn) {
    pipetteBtn.classList.toggle('active', data.pipette_armed === true);
    var pipDisabled = data.has_selection !== true && data.pipette_armed !== true;
    pipetteBtn.disabled = pipDisabled;
    pipetteBtn.classList.toggle('spv-tool--disabled', pipDisabled);
}
var mirrorBtn = document.getElementById('spv-action-mirror');
if (mirrorBtn) {
    mirrorBtn.disabled = data.has_selection !== true;
    mirrorBtn.classList.toggle('spv-tool--disabled', data.has_selection !== true);
}
```

- [ ] **Step 6: CSS — row + disabled style**

In `native/assets/ui-cef/css/ship_property_viewer.css`, add `#spv-action-tools` styled identically to `#spv-transform-tools` (find that selector and copy its flex/position rules, adjusting the `bottom` offset so it stacks above the transform row by `TOOLS_CLUSTER_H_PT`'s math — i.e. bottom = 12 + 40 + 6 + 40 + 6 = 104px; confirm against how `#spv-transform-tools`'s bottom is derived and add one more row + gap). Add a disabled style:

```css
.spv-tool--disabled,
.spv-tool:disabled {
    opacity: 0.35;
    pointer-events: none;
}
```

Match the existing `.spv-tool.active` styling for the armed pipette (already defined for the transform-tools radio; reuse it).

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_action_row.py -v`
Expected: PASS.

- [ ] **Step 8: Full gate**

Run: `scripts/check_tests.sh`
Expected: OK — no new failures (1 known baselined). No C++ changed, so ctest is unaffected.

- [ ] **Step 9: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/css/ship_property_viewer.css tests/ui/test_ship_property_viewer_action_row.py
git commit -m "feat(spv): undo/pipette/mirror toolbox row UI"
```

---

## Self-review notes

- **Spec coverage:** Undo (Task 1), Pipette (Task 2), Mirror (Task 3), UI row + bbox (Task 4) — every design section maps to a task.
- **Type consistency:** target tuples are `("subsystem", i)` / `("light", i)` / `("emitter", i, j)` throughout; rotate kinds are `cylinder_axis` / `box_orientation` / `cone_orientation`; scale kinds come from `_scale_kind_and_fields`. Pipette and Mirror reuse the exact setter signatures already in the panel.
- **Ordering:** Task 1's `dispatch_event` wrapper must land before Tasks 2–3 so their mutations auto-record one undo entry; Task 4's UI consumes payload fields added in Tasks 1–2. Execute in order.
- **Risk:** the `rotate_mirror` extraction in Task 3 must be behaviour-identical — the existing rotate-mirror tests are the regression guard.
