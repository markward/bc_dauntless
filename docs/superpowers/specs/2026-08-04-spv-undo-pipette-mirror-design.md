# SPV Toolbox — Undo / Pipette / Mirror (design)

**Date:** 2026-08-04
**Status:** approved (Mark), ready for implementation plan
**Area:** Ship Property Viewer (`engine/ui/ship_property_viewer_panel.py`,
`engine/ui/ship_property_viewer.py`, CEF assets)

## Goal

Add a third action-button row to the SPV's bottom-right tool cluster with
three whole-element operations:

1. **Undo** — step back through the staged (unsaved) authoring edits.
2. **Pipette** — eyedropper: sample another element's transform, rotation,
   scale, colour, and intensity onto the currently-selected element.
3. **Mirror** — flip the selected element to its port↔starboard twin in one
   click.

Undo and Mirror are momentary buttons; Pipette arms a one-shot source pick.
Everything operates on the **staged edit** layer (the four `_pending_*`
dicts) — nothing touches the live sim, and Save remains the only path that
writes `hardpoint_overrides.py`.

## Non-goals

- **Redo.** Explicitly deferred ("3-button row for now"). The undo design is
  a snapshot stack that a redo button can be added onto later with minimal
  work, but no redo state or button ships in this project.
- **Cross-Save undo.** Save is a hard commit that clears the undo history.
- Keyboard shortcuts (Ctrl+Z). CEF is mouse-only here; buttons only.
- Any change to the persistence format, the renderer, or the live light path.

## Background — the existing staging model

Authoring edits are staged into four dicts on the panel, keyed by descriptor
index, and flushed to disk only on Save:

- `_pending_radius[i]` → float
- `_pending_light[i]` → glow-region spec dict, or `None` (removed sentinel)
- `_pending_emitter[i]` → the **full compacted list** of emitter specs for
  that subsystem (whole-list-per-subsystem staging; never a sparse `(i,j)`)
- `_pending_pos[i]` → body-frame `(x, y, z)` tuple

All discrete edits funnel through `dispatch_event(action)`. Continuous drags
(move / scale / rotate-ring) mutate through `_apply_axis_drag` /
`_apply_scale_drag` / `_apply_ring_drag`, driven from `handle_input`, and are
bracketed by `_begin_*_drag` (press) and `_end_axis_drag` (release).

The current transform target is resolved by `_active_transform_target()` →
`("emitter", i, j)` | `("light", i)` | `("subsystem", i)` | `None`, following
the mutually-exclusive selection state (`_selected_emitter`,
`_selected_light_index`, `selected_index`).

Colour + intensity are fields on **light-emitter** specs only (point / strip /
cone). Glow-region light *volumes* do not carry them in the SPV.

## 1. Undo — snapshot stack over the pending dicts

### State

- `self._undo_stack: list` — a list of pending-state snapshots, each captured
  immediately **before** a mutation. Initialised `[]` in `__init__`; reset to
  `[]` in `open()` and `close()`.
- `self._drag_undo_before` — a transient snapshot captured at drag-begin, or
  `None`. Reset in `open()`/`close()` and after each drag commits.

### Snapshot helpers

```python
def _snapshot_pending(self):
    """Deep copy of the four staged-edit dicts (undo unit). Cheap: the dicts
    hold a handful of small tuples/dicts/lists."""
    import copy
    return (copy.deepcopy(self._pending_radius),
            copy.deepcopy(self._pending_light),
            copy.deepcopy(self._pending_emitter),
            copy.deepcopy(self._pending_pos))

def _restore_pending(self, snap):
    """Replace the four staged-edit dicts from a snapshot, drop any now-stale
    selection reference, and force a CEF re-push."""
    import copy
    r, l, e, p = snap
    self._pending_radius = copy.deepcopy(r)
    self._pending_light = copy.deepcopy(l)
    self._pending_emitter = copy.deepcopy(e)
    self._pending_pos = copy.deepcopy(p)
    # An emitter (i, j) selection may now point past the restored list.
    if self._selected_emitter is not None:
        i, j = self._selected_emitter
        if not (0 <= i < len(self._descriptors)) \
                or self._effective_emitter(i, j) is None:
            self._selected_emitter = None
    self._last_pushed = None
```

### Recording discrete edits — wrap the dispatcher (diff-guarded)

Rename the current `dispatch_event` body to `_dispatch_event_inner`, and add a
thin wrapper that snapshots around every dispatch **except** the actions that
must not create (or must clear) history:

```python
_NO_UNDO_ACTIONS = ("undo", "save", "cancel")

def dispatch_event(self, action: str) -> bool:
    # undo/save/cancel are handled without recording (undo mutates pending
    # itself; save clears history; cancel closes the panel).
    if action in self._NO_UNDO_ACTIONS or action.startswith("overlay:"):
        return self._dispatch_event_inner(action)
    before = self._snapshot_pending()
    result = self._dispatch_event_inner(action)
    after = self._snapshot_pending()
    if before != after:
        self._undo_stack.append(before)
    return result
```

The diff-guard (`before != after`) means only dispatches that actually change
the staged edits record an undo entry — selects, toggles, `set_tool`, the
Copy actions (clipboard only), and no-op/invalid dispatches record nothing.
This captures **every** discrete mutation — radius, light, emitter add/remove,
position, all nudge/paste/mirror/uniform actions, and the new
`pipette`/`mirror_element` — with zero per-handler edits.

### Recording drags — one entry per drag

A drag never passes through `dispatch_event`, so it is bracketed explicitly:

- In each of `_begin_axis_drag`, `_begin_scale_drag`, `_begin_ring_drag`:
  `self._drag_undo_before = self._snapshot_pending()`.
- In `_end_axis_drag` (the single release path for all three drag kinds):
  after the drag finalises, if `self._drag_undo_before is not None` and it
  differs from the current pending state, append it to `_undo_stack`; then
  clear `_drag_undo_before = None`.

One drag = one undo entry.

### `undo()` and dispatch

```python
def undo(self) -> None:
    if self._undo_stack:
        self._restore_pending(self._undo_stack.pop())
```

`_dispatch_event_inner` gains: `if action == "undo": self.undo(); return True`.

### Save clears history

In the existing `save` handler, after the staged dicts are cleared on a
successful write, also `self._undo_stack.clear()` and
`self._drag_undo_before = None`. (Save is already excluded from recording by
`_NO_UNDO_ACTIONS`.)

### Payload

`render_payload` adds `"can_undo": bool(self._undo_stack)`, and includes
`len(self._undo_stack)` (or the bool) in the change-detection `snapshot`
tuple so the button's enabled state re-pushes when it flips.

## 2. Pipette — eyedropper sampling onto the current selection

### State

- `self._pipette_armed: bool` — `False` by default; reset in `open()`/
  `close()`. `True` between clicking the Pipette button and the next element
  pick (or a cancel).

### Arming (the `"pipette"` action)

- If already armed → disarm (toggle off).
- Else, if `_active_transform_target()` is not `None` (a target is selected)
  → arm. If nothing is selected → no-op (button is disabled in that state).
- `_last_pushed = None` on any change (button visual).

### Intercepting the source pick

At the **top** of `_dispatch_event_inner`, before the normal `select_*`
handlers, when `self._pipette_armed`:

- `select_pin:idx` → source `("subsystem", idx)`
- `select_light:idx` → source `("light", idx)`
- `select_emitter:{i,j}` → source `("emitter", i, j)`

Resolve and validate the source target, call `self._apply_pipette(src)`,
disarm, and return `True` **without changing the current selection**. Any
other action while armed (e.g. `deselect` from clicking empty space, a
toggle, ESC) → disarm and fall through to normal handling (the pick is
cancelled, nothing is copied).

The 3D view routes a pin click through `pick_at` →
`dispatch_event("select_pin:idx")`, so 3D subsystem pins work as pipette
sources by construction; tree-row clicks provide light/emitter sources.

### `_apply_pipette(src)` — per-aspect, copy-what-both-support

```python
def _apply_pipette(self, src) -> None:
    tgt = self._active_transform_target()
    if tgt is None or src == tgt:
        return
    # 1. Position — body-frame; every target type has a position.
    spos = self._target_pos_of(src)          # helper: reads src's effective pos
    if spos is not None:
        self._set_transform_target_pos(spos)  # operates on the active target
    # 2. Rotation — only when both sides share a rotate kind.
    self._pipette_rotation(src, tgt)
    # 3. Scale — only when both sides share a scale kind.
    self._pipette_scale(src, tgt)
    # 4. Colour + intensity — emitter → emitter only.
    self._pipette_color_intensity(src, tgt)
```

Aspect gating rules:

- **Position** — always copied (body-frame). This is the "target jumps onto
  the source's mount" behaviour Mark approved.
- **Rotation** — copied only if `_rotate_clipboard_kind(src)` ==
  `_rotate_clipboard_kind(tgt)` **and** both are rotate-capable
  (`_rotate_target`-eligible). Reuse the existing absolute-set path:
  `cylinder_axis` → `_set_axis_absolute(tgt, src_axis)`; `box_orientation` /
  `cone_orientation` → `_set_orientation_absolute(tgt, fwd, up)`. Mismatched
  shapes (e.g. box source, cone target) skip rotation. Point emitters,
  spheres, and subsystems have no rotation → skipped.
- **Scale** — read `_scale_kind_and_fields(src)`; if its kind equals
  `_scale_kind_and_fields(tgt)`'s kind, apply each field via
  `_set_scale_field(idx, value)` (which targets the active selection).
  Mismatched shapes skip scale.
- **Colour + intensity** — only when both `src` and `tgt` are
  `("emitter", …)`. Copy `spec["color"]` and `spec["intensity"]` onto the
  target emitter via a whole-list restage of `_pending_emitter[i]` (dense
  index invariant).

Each aspect is independent; incompatible aspects are silently skipped (never
an error). The whole `_apply_pipette` runs inside one `_dispatch_event_inner`
call → **one** undo entry.

### Helpers

- `_target_pos_of(target)` — like `_transform_target_pos` but for an
  arbitrary target tuple (reads the effective emitter/light/subsystem
  position). `_transform_target_pos` can be refactored to delegate to this.

### ESC + payload

- `handle_key_esc`: if `self._pipette_armed`, set `_pipette_armed = False`,
  `_last_pushed = None`, and return (one-shot disarm, before any overlay/panel
  close).
- `render_payload` adds `"pipette_armed": self._pipette_armed` and
  `"has_selection": self._active_transform_target() is not None`, both folded
  into the change-detection `snapshot`.

## 3. Mirror — whole-element port↔starboard flip

### The `"mirror_element"` action

Operates on `_active_transform_target()` regardless of the active tool:

```python
if action == "mirror_element":
    t = self._active_transform_target()
    if t is not None:
        pos = self._transform_target_pos()
        if pos is not None:                       # position: negate X
            self._set_transform_target_pos((-pos[0], pos[1], pos[2]))
        rt = self._rotate_target()                # rotation: mirror basis
        if rt is not None:
            self._mirror_target_rotation(rt)
        # scale: magnitudes unchanged → no-op; colour/intensity unchanged
    return True
```

- **Position** — negate X (starboard axis), matching `coord_mirror`.
- **Rotation** — reflect the orientation across X: negate the X component of
  the axis (cylinder / strip) or of both forward and up (box / cone), then
  re-set absolutely. This is exactly the math in the current `rotate_mirror`
  handler; extract it into `_mirror_target_rotation(rt)` and have **both**
  `rotate_mirror` and `mirror_element` call it (DRY; no behaviour change to
  the existing per-tool Mirror button).
- **Scale** — extents are magnitudes; a plane reflection leaves them
  unchanged. No-op.
- **Colour / intensity** — unchanged.

`_rotate_target()` keys off the selection, not the active tool, so
`mirror_element` works whichever (or no) tool is active. Runs inside one
`_dispatch_event_inner` → **one** undo entry.

This is the whole-element flip, distinct from the existing per-tool Mirror
buttons (each flips only the active tool's single aspect).

## 4. UI — the new action-button row

### Layout constants (`ship_property_viewer_panel.py`)

Add a third row above the transform-tools row and grow the click bbox:

```python
ACTION_H_PT = TOOLS_BTN_PT   # #spv-action-tools row height
TOOLS_CLUSTER_H_PT = (TOOLS_H_PT + TOOLS_GAP_PT + TRANSFORM_H_PT
                      + TOOLS_GAP_PT + ACTION_H_PT)
```

`_cursor_over_tools` already derives its bbox from `TOOLS_CLUSTER_H_PT`, so
the new row is covered automatically (clicks there won't start an orbit/pin
pick).

### HTML (`native/assets/ui-cef/index.html`)

New `<div id="spv-action-tools">` above `#spv-transform-tools`, three
`.spv-tool` buttons:

- `#spv-action-undo` → `onclick="shipPropertyViewerUndo()"`, title "Undo"
  (curved back-arrow glyph).
- `#spv-action-pipette` → `onclick="shipPropertyViewerPipette()"`, title
  "Pipette: copy transform from another element" (eyedropper glyph).
- `#spv-action-mirror` → `onclick="shipPropertyViewerMirror()"`, title
  "Mirror to the other side" (mirror/flip glyph).

### JS (`native/assets/ui-cef/js/ship_property_viewer.js`)

```javascript
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

In `setShipPropertyViewer(data)`:

- Undo button: `disabled = !data.can_undo`, mirror a `--disabled` class.
- Pipette button: `.active` toggled by `data.pipette_armed === true`;
  `disabled = !data.has_selection && !data.pipette_armed`.
- Mirror button: `disabled = !data.has_selection`.

### CSS (`native/assets/ui-cef/css/ship_property_viewer.css`)

`#spv-action-tools` mirrors `#spv-transform-tools` (same flex row, button
size, gap), stacked directly above it with `TOOLS_GAP_PT` spacing. Add a
disabled style (dimmed, `pointer-events:none`) and reuse the existing
`.spv-tool.active` style for the armed pipette.

## Testing

Python (pytest), all headless against the panel:

- **Undo stack:** a nudge/paste/mirror records exactly one entry; undo
  restores the prior pending state byte-for-byte; a no-op dispatch records
  nothing; a drag (begin→apply→end) records exactly one entry; Save clears
  the stack; `can_undo` reflects stack emptiness.
- **Pipette:** arming requires a selection; the next `select_*` is consumed
  as source without changing selection; position always copies; rotation and
  scale copy only on matching kinds and skip on mismatch; colour+intensity
  copy emitter→emitter and are skipped otherwise; source == target is a
  no-op; one undo entry per apply; ESC disarms.
- **Mirror:** position X negates; a cylinder/strip axis mirrors X; a box/cone
  basis mirrors X on forward+up; scale and colour/intensity are unchanged;
  a point-emitter/sphere/subsystem mirrors position only; one undo entry;
  `_mirror_target_rotation` shared with `rotate_mirror` leaves the existing
  per-tool Mirror behaviour identical.
- **Payload/bbox:** `can_undo`/`pipette_armed`/`has_selection` appear and are
  in the change-detection snapshot; `TOOLS_CLUSTER_H_PT` grows by one row +
  gap and `_cursor_over_tools` covers the new row.

Gate: `scripts/check_tests.sh` (build + pytest + ctest vs
`tests/known_failures.txt`). No C++ changes expected, so ctest is unaffected.

## Global constraints

- Pending-only undo; **Save clears history**; no cross-Save undo.
- No redo state or button (deferred).
- Reuse existing setters/mirror math (`_set_transform_target_pos`,
  `_set_axis_absolute`, `_set_orientation_absolute`, `_set_scale_field`,
  `_rotate_clipboard_kind`, `_rotate_target`); factor `rotate_mirror`'s body
  into `_mirror_target_rotation` rather than duplicating it.
- Emitter edits always restage the **whole compacted list**
  (`_pending_emitter[i] = lst`) — never a sparse `(i, j)` key, never an index
  gap (`baked_emitters` stops at the first gap on reload).
- CEF is mouse-only; buttons only, no keyboard bindings.
- Production render path and byte-identity of unchanged saves must be
  unaffected — this is pure SPV authoring UI.
