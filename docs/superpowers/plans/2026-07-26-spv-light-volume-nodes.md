# SPV Light Volumes as Selectable Child Nodes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a subsystem's light volume (index-0 glow region) a first-class, selectable child node in the SPV list — selectable on its own (shows only its glow wireframe), add-able on any subsystem, editable and removable via right-click.

**Architecture:** A subsystem "has a light" when its *effective light* (pending → saved → baked) at index 0 is a real region (spec) rather than absent/removed. The panel gains a second, mutually-exclusive `selected_light_index`; a "Light Volume" child row renders under any subsystem that has one. Add/Edit/Remove all stage into the existing `_pending_light` dict (a value is a spec, or `None` = removed), and Save routes specs to `set_region(0, calls)` and removals to `set_region(0, [])`. The writer's `emit` drops empty subsystem blocks so a removal can't produce invalid Python.

**Tech Stack:** Python 3 (engine + pytest), CEF (HTML/CSS/JS), no C++ change.

## Global Constraints

- **Design:** `docs/superpowers/specs/2026-07-26-spv-light-volume-nodes-design.md`.
- **Dev-only:** the SPV is constructed only under `--developer`; production render/logic stays byte-identical. `ShipGlowController` (in-scene glow) is NOT changed — authored lights on non-impulse/warp/sensor subsystems preview in the SPV only.
- **Machine-owned file:** `engine/appc/hardpoint_overrides.py` stays 100% emitter output; `emit(read_models(module)) == source` must still hold.
- **Crash-safe writes:** emitted text must `ast.parse`; a removal must never emit an `if p is not None:` with no body.
- **Region spec is "baked-shaped"** everywhere: `radius=(r,)`, `extent=(aft,fore)`, `scale=(sx,sy,sz)`, `position`/`axis` 3-tuples, `shape` a plain string.
- **One light per subsystem** (index 0). Add is offered only when the subsystem has no effective light.
- **Shared checkout:** stage commits with EXPLICIT pathspecs only. NEVER `git add -A`/`.`/`checkout`/`restore`/`stash`/`reset --hard`/`clean`. Leave any other session's uncommitted files alone.
- **Test gate:** `scripts/check_tests.sh` green; `tests/known_failures.txt` is the authority (currently the one baselined `PowerDisplay` pytest failure).
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

- `engine/appc/hardpoint_override_writer.py` — `emit`/`_emit_function` drop empty subsystem blocks (Task 1).
- `engine/ui/ship_property_viewer.py` — `build_descriptors` computes `light`/`light_region` for ALL subsystems (Task 2).
- `engine/ui/ship_property_viewer_panel.py` — effective-light model, `selected_light_index`, add/remove/edit/select_light, save routing, `pending_light_specs`, `_subsystem_rows` light child, `subsystem_pins` (Task 3).
- `engine/ui/glow_region_overlay.py` — a `None` pending value hides that subsystem's region (Task 4).
- `engine/host_loop.py` — glow overlay `selected_name` from the light selection; sphere from the subsystem selection (Task 4).
- `native/assets/ui-cef/{index.html,js/ship_property_viewer.js,css/ship_property_viewer.css}` — recursive list render + light node + Add/Edit/Remove context items (Task 5).
- Tests: `tests/unit/test_hardpoint_override_writer.py`, `tests/ui/test_ship_property_viewer.py`, `tests/ui/test_ship_property_viewer_panel.py`, `tests/unit/test_glow_region_overlay.py`.

---

## Task 1: Writer — emit drops empty subsystem blocks

**Files:**
- Modify: `engine/appc/hardpoint_override_writer.py` (`_emit_function`)
- Test: `tests/unit/test_hardpoint_override_writer.py`

**Interfaces:**
- Consumes: existing `set_region`, `read_models`, `emit`.
- Produces: `emit` renders a subsystem with an empty call list as *nothing* (the block is omitted); a `_<leaf>` whose subsystems are all empty emits `return`. `set_region(models, leaf, sub, 0, [])` therefore clears a region and the file still parses + round-trips.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_hardpoint_override_writer.py
def test_set_region_empty_calls_clears_and_emit_drops_block():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
        p.SetGlowRegionRadius(0, 0.25)
    p = find("B")
    if p is not None:
        p.SetRadius(0.5)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [])          # remove A's only region
    text = w.emit(models)
    ast.parse(text)                                # valid python (no empty `if:` body)
    assert 'find("A")' not in text                 # A's block dropped entirely
    assert 'find("B")' in text                     # B preserved
    m2 = _module(text)
    assert w.read_models(m2) == {"x": {"B": [("SetRadius", (0.5,))]}}
    assert w.emit(w.read_models(m2)) == text        # canonical fixed point


def test_emit_all_empty_subsystems_emits_return():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionShape(0, "Sphere")
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_region(models, "x", "A", 0, [])
    text = w.emit(models)
    ast.parse(text)
    m2 = _module(text)
    assert w.read_models(m2) == {"x": {}}           # empty function, still callable
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q -k "empty"`
Expected: FAIL — `_emit_function` emits `p = find("A")` / `if p is not None:` with no body → `ast.parse` raises `SyntaxError` (or the assertions fail).

- [ ] **Step 3: Implement the empty-block skip**

In `engine/appc/hardpoint_override_writer.py`, replace `_emit_function`:

```python
def _emit_function(leaf, per_sub) -> str:
    out = ["def _%s(find):" % leaf, '    """%s."""' % leaf]
    non_empty = [(s, c) for s, c in per_sub.items() if c]
    if not non_empty:
        out.append("    return")
    else:
        for subsystem, calls in non_empty:
            out.append("    p = find(%s)" % _lit(subsystem))
            out.append("    if p is not None:")
            for setter, args in calls:
                out.append("        p.%s(%s)"
                           % (setter, ", ".join(_lit(a) for a in args)))
    return "\n".join(out)
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py tests/unit/test_hardpoint_overrides_canonical.py -q`
Expected: PASS (new + existing; the canonical file has no empty blocks so its fixed point is unchanged).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_override_writer.py tests/unit/test_hardpoint_override_writer.py
git commit -m "feat(overrides): emit drops empty subsystem blocks (region removal)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: Descriptors — light_region for any subsystem

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (`build_descriptors` light post-pass)
- Test: `tests/ui/test_ship_property_viewer.py`

**Interfaces:**
- Consumes: existing `_light_region_spec`, `baked_glow_regions`.
- Produces: every subsystem descriptor carries `"light_region"` (its baked region-0 spec if present, else a from-scratch Sphere default) and `"light": bool` = whether a baked region 0 exists. The `glow_bearing_subsystem_ids` gate is removed (any subsystem is light-capable).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/ui/test_ship_property_viewer.py
def test_any_subsystem_gets_light_region_and_baked_flag(monkeypatch):
    import engine.ui.ship_property_viewer as spv

    class _Prop:                      # a baked Sphere region-0 data-bag
        def __init__(self, baked):
            self._baked = baked
        # baked_glow_regions reads via read_indexed_setter_args on _data;
        # stub baked_glow_regions instead for a focused unit test.

    class _Sub:
        def __init__(self, name, baked):
            self._n, self._baked = name, baked
        def GetName(self): return self._n
        def GetPosition(self):
            from engine.appc.math import TGPoint3
            return TGPoint3(0.0, 0.0, 0.0)
        def GetProperty(self): return object()
        def GetParentSubsystem(self): return None

    lit = _Sub("Lit", baked=True)
    dark = _Sub("Dark", baked=False)

    monkeypatch.setattr(spv, "_iter_subsystems", lambda ship: [lit, dark])
    monkeypatch.setattr(spv, "subsystem_world_position",
                        lambda sub, ship: __import__("engine.appc.math", fromlist=["TGPoint3"]).TGPoint3(0, 0, 0))
    # baked_glow_regions returns a region for `lit` only.
    import engine.ui.ship_property_viewer as _spvmod
    monkeypatch.setattr(_spvmod, "glow_bearing_subsystem_ids", lambda ship: set(), raising=False)

    def _baked(prop):
        return [{"shape": "Sphere", "position": (0, 0, 0), "axis": None,
                 "radius": (0.3,), "extent": None, "scale": None}] \
            if prop is lit_prop else []
    # Simpler: monkeypatch the module-level baked_glow_regions used by _light_region_spec.
```

(Because `build_descriptors` walks the real subsystem enumeration, prefer a
focused test of the extracted helper. Concretely, split the light annotation
into a testable pure helper and test THAT — see Step 3 — then a thin
integration assertion.)

Replace the above sketch with these two concrete tests:

```python
# tests/ui/test_ship_property_viewer.py
from engine.ui.ship_property_viewer import _light_annotation


def test_light_annotation_baked_region_present(monkeypatch):
    import engine.ui.ship_property_viewer as spv
    monkeypatch.setattr(spv, "baked_glow_regions",
                        lambda prop: [{"shape": "Cylinder", "position": (1.0, 0.0, 0.0),
                                       "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                                       "extent": (0.0, 2.0), "scale": None}])

    class _Sub:
        def GetProperty(self): return object()
        def GetName(self): return "Lit"
    has, region = _light_annotation(_Sub())
    assert has is True
    assert region["shape"] == "Cylinder"
    assert region["radius"] == (0.25,)


def test_light_annotation_no_baked_region_default(monkeypatch):
    import engine.ui.ship_property_viewer as spv
    monkeypatch.setattr(spv, "baked_glow_regions", lambda prop: [])

    class _Sub:
        def GetProperty(self): return object()
        def GetName(self): return "Dark"
        def GetPosition(self):
            from engine.appc.math import TGPoint3
            return TGPoint3(0.0, 0.0, 0.0)
    has, region = _light_annotation(_Sub())
    assert has is False
    assert region["shape"] == "Sphere"          # from-scratch default for Add
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py -q -k light_annotation`
Expected: FAIL (`_light_annotation` undefined).

- [ ] **Step 3: Implement `_light_annotation` + rewrite the post-pass**

In `engine/ui/ship_property_viewer.py`, add near `_light_region_spec`:

```python
def _light_annotation(sub):
    """(has_baked_light, light_region) for a subsystem. `light_region` is the
    baked region-0 spec if the subsystem has one, else a from-scratch Sphere
    default (used to pre-fill Add Light Volume). Any subsystem is light-capable
    now — no impulse/warp/sensor gate."""
    prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
    has = bool(baked_glow_regions(prop))
    return has, _light_region_spec(sub)
```

Replace the light post-pass in `build_descriptors` (the block that imports
`glow_bearing_subsystem_ids` and sets `light`/`light_region` for gated indices)
with an ungated re-walk:

```python
    # Post-pass: annotate every subsystem descriptor with its light volume.
    # `light` = a baked region 0 exists; `light_region` = that baked spec or a
    # from-scratch default (any subsystem is light-capable — see the light-node
    # design). Re-walk in the SAME order + skip rule as the build loop.
    di = 0
    for sub in _iter_subsystems(ship):
        local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
        if local is None:
            continue
        has, region = _light_annotation(sub)
        out[di]["light"] = has
        out[di]["light_region"] = region
        di += 1
```

Remove the now-unused `from engine.appc.subsystem_glow import
glow_bearing_subsystem_ids` import in `build_descriptors` (leave the
`glow_bearing_subsystem_ids` function itself in `subsystem_glow.py` — it is still
used elsewhere; grep to confirm before deleting anything).

- [ ] **Step 4: Run to verify they pass + no descriptor-test regressions**

Run: `uv run pytest tests/ui/test_ship_property_viewer.py tests/unit/test_subsystem_glow.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer.py tests/ui/test_ship_property_viewer.py
git commit -m "feat(spv): any subsystem gets a light_region + baked-light flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Panel — effective-light model, light selection, add/remove/edit, tree, pins

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel.py`

**Interfaces:**
- Consumes: `region_spec_to_calls`, `resolve_override_target`, `hardpoint_leaf_for_ship`; descriptor `light`/`light_region` (Task 2).
- Produces:
  - `self._selected_light_index: int | None`; reset in open/close; mutually exclusive with `selected_index`.
  - `_effective_light(idx)` → spec dict, or `None` (absent or removed); `_has_light(idx)` → bool.
  - `dispatch_event`: `select_light:<i>`, `add_light:<i>`, `remove_light:<i>` (plus the existing `set_light`, `select_pin`, `deselect`).
  - `pending_light_specs()` → `{name: spec_or_None}` (None = hide, for a removed light).
  - `_subsystem_rows` appends a `{kind:"light", light_of, name:"Light Volume", light_region, dirty}` child to any subsystem with an effective light; each subsystem row carries `has_light`.
  - `subsystem_pins()` shows only the parent pin when a light is selected.
  - `render_payload` payload/snapshot include `selected_light_index`.

- [ ] **Step 1: Write the failing panel tests**

```python
# append to tests/ui/test_ship_property_viewer_panel.py
def _dark_descriptor(name):
    d = _rad_descriptor(name)
    d["light"] = False
    d["light_region"] = {"shape": "Sphere", "position": (1.0, 0.0, 0.0),
                         "axis": (0.0, -1.0, 0.0), "radius": (0.25,),
                         "extent": (0.0, 2.0), "scale": (0.25, 0.25, 0.25)}
    return d


def test_add_light_stages_default_and_selects_it(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_dark_descriptor("Phaser Bank")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    assert p._has_light(0) is False
    assert p.dispatch_event("add_light:0") is True
    assert p._has_light(0) is True
    assert p._selected_light_index == 0
    assert p.selected_index is None                 # mutual exclusion
    assert p.pending_light_specs()["Phaser Bank"]["shape"] == "Sphere"


def test_add_light_rejected_when_already_lit(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])  # baked light
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    assert p._has_light(0) is True
    assert p.dispatch_event("add_light:0") is False


def test_remove_light_hides_node_and_clears_selection(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("select_light:0")
    assert p._selected_light_index == 0
    assert p.dispatch_event("remove_light:0") is True
    assert p._has_light(0) is False
    assert p._selected_light_index is None
    # Overlay must HIDE the baked region: name maps to None.
    assert "Center Impulse" in p.pending_light_specs()
    assert p.pending_light_specs()["Center Impulse"] is None


def test_select_pin_and_light_are_mutually_exclusive(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("select_pin:0")
    assert p.selected_index == 0 and p._selected_light_index is None
    assert p.selected_subsystem_sphere() is not None    # sphere while subsystem selected
    p.dispatch_event("select_light:0")
    assert p._selected_light_index == 0 and p.selected_index is None
    assert p.selected_subsystem_sphere() is None         # no sphere while light selected


def test_tree_has_light_child_and_add_flag(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    rows = p._subsystem_rows()
    row = rows[0]
    assert row["has_light"] is True
    kids = [c for c in row.get("children", []) if c.get("kind") == "light"]
    assert len(kids) == 1
    assert kids[0]["light_of"] == 0 and kids[0]["name"] == "Light Volume"


def test_pins_show_only_parent_when_light_selected(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("A"), _light_descriptor("B")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("select_light:1")
    pins = p.subsystem_pins()
    assert len(pins) == 1                    # only the parent of the selected light


def test_save_routes_removal_as_empty_region(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits): calls.append((leaf, edits))

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("remove_light:0")
    p.dispatch_event("save")
    assert calls == [("galaxy", [("Center Impulse", "__region__", 0, [])])]
```

Note: `_light_descriptor` (existing) has `light: True` + `light_region`; treat it
as a baked light. Update any existing test that asserted the *subsystem* row
carries `light_region` (that moved to the light child) — see Step 4.

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q -k "add_light or remove_light or mutually_exclusive or light_child or parent_when_light or removal_as_empty"`
Expected: FAIL (new API not present).

- [ ] **Step 3: Implement the panel changes**

In `__init__`, next to `self._selected_light_index` does not exist yet — add near `self.selected_index`:

```python
        # Selected LIGHT volume (descriptor index of the subsystem whose light
        # is selected), mutually exclusive with selected_index. Shows only that
        # light's glow wireframe; the parent radius sphere is hidden.
        self._selected_light_index: Optional[int] = None
```

Reset it in `open()` and `close()` next to `self.selected_index = None`:

```python
        self._selected_light_index = None
```

Add the effective-light resolver + helper (near `_effective_radius`):

```python
    def _effective_light(self, index):
        """Effective index-0 light spec for a descriptor: a staged (unsaved)
        edit wins, then a saved-this-session edit, else the baked region — with
        `None` meaning 'no light' (absent, or a staged/saved removal)."""
        if index in self._pending_light:
            return self._pending_light[index]      # spec dict, or None (removed)
        if index in self._saved_light:
            return self._saved_light[index]
        d = self._descriptors[index]
        return d.get("light_region") if d.get("light") else None

    def _has_light(self, index) -> bool:
        return (0 <= index < len(self._descriptors)
                and self._effective_light(index) is not None)
```

Replace `pending_light_specs` so removed lights map to `None` (hide sentinel):

```python
    def pending_light_specs(self) -> dict:
        """{subsystem_name: spec|None} overriding the baked overlay. A spec draws
        the staged/saved light; None hides a removed one. Saved then pending so a
        fresh stage wins."""
        out: dict = {}
        for source in (self._saved_light, self._pending_light):
            for i, spec in source.items():
                if 0 <= i < len(self._descriptors):
                    out[self._descriptors[i]["name"]] = spec
        return out
```

In `dispatch_event`, extend `select_pin` to clear the light selection, add
`select_light`, `add_light`, `remove_light`, and make `deselect` clear both.
Place these with the other handlers:

```python
        if action.startswith("select_light:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if not (0 <= idx < len(self._descriptors)) or not self._has_light(idx):
                return False
            self._selected_light_index = idx
            self.selected_index = None
            self._expanded_groups.add(self._descriptors[idx].get("name", ""))
            self._last_pushed = None
            return True
        if action.startswith("add_light:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if not (0 <= idx < len(self._descriptors)) or self._has_light(idx):
                return False
            base = self._descriptors[idx].get("light_region") or {}
            self._pending_light[idx] = dict(base)     # from-scratch default spec
            self._selected_light_index = idx
            self.selected_index = None
            self._expanded_groups.add(self._descriptors[idx].get("name", ""))
            self._last_pushed = None
            return True
        if action.startswith("remove_light:"):
            try:
                idx = int(action.split(":", 1)[1])
            except ValueError:
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            self._pending_light[idx] = None           # removed sentinel
            if self._selected_light_index == idx:
                self._selected_light_index = None
            self._last_pushed = None
            return True
```

In the existing `select_pin` handler, add `self._selected_light_index = None`
after setting `self.selected_index = idx`. In `deselect`, clear both:

```python
        if action == "deselect":
            if self.selected_index is None and self._selected_light_index is None:
                return False
            self.selected_index = None
            self._selected_light_index = None
            self._last_pushed = None
            return True
```

In the `save` handler, route removals as empty calls (change the light-edit
comprehension):

```python
            edits += [(self._descriptors[i]["name"], "__region__", 0,
                       region_spec_to_calls(0, spec) if spec is not None else [])
                      for i, spec in sorted(self._pending_light.items())]
```

(The empty-guard `if not self._pending_radius and not self._pending_light` and
the `_saved_light.update(...)` on success already exist — a removal is a
`_pending_light` entry with value `None`, so it counts as pending and is saved.)

Rewrite `selected_subsystem_sphere` guard: it already returns None unless
`selected_index` is set, and `selected_index` is cleared whenever a light is
selected — so no change is needed. (Confirm by reading it; add a one-line comment
that a selected light suppresses the sphere via the mutual-exclusion invariant.)

Rewrite `subsystem_pins` to handle the light selection:

```python
    def subsystem_pins(self) -> List[tuple]:
        # Light selected -> show only its parent subsystem's pin (anchor icon);
        # the glow wireframe is the focus. Subsystem selected -> only that pin.
        # Nothing selected -> all pins.
        if self._selected_light_index is not None:
            i = self._selected_light_index
            if 0 <= i < len(self._descriptors):
                d = self._descriptors[i]
                return [(d["world_pos"], d["icon_id"], False)]
            return []
        sel = self.selected_index
        if sel is not None and 0 <= sel < len(self._descriptors):
            d = self._descriptors[sel]
            return [(d["world_pos"], d["icon_id"], True)]
        return [(d["world_pos"], d["icon_id"], False) for d in self._descriptors]
```

In `_subsystem_rows`: (a) set `has_light` on each subsystem row and drop the old
`light`/`light_region` row fields; (b) after linking parents, append a light
child to each subsystem that has one; (c) set `expanded` on ANY row with children
(not just top-level). Replace the row-build + the final expand loop:

```python
        rows: List[dict] = []
        by_index: dict = {}
        for i, d in enumerate(self._descriptors):
            row = _row(i, d)
            row["dirty"] = (i in self._pending_radius) or (i in self._pending_light)
            row["radius"] = self._effective_radius(
                i, d.get("properties", {}).get("radius"))
            row["has_light"] = self._has_light(i)
            by_index[i] = row
            parent = by_index.get(d.get("parent_index"))
            if parent is not None:
                parent["children"].append(row)
            else:
                rows.append(row)
        # Light-volume child node under any subsystem that has one.
        for i in range(len(self._descriptors)):
            if self._has_light(i):
                by_index[i]["children"].append({
                    "kind": "light",
                    "name": "Light Volume",
                    "light_of": i,
                    "light_region": self._effective_light(i),
                    "dirty": (i in self._pending_light),
                })
        for row in by_index.values():
            if row["children"]:
                row["expanded"] = row["name"] in self._expanded_groups
        return rows
```

In `render_payload`: add `selected_light_index` to BOTH the snapshot tuple and
the payload dict (so a light selection re-pushes and the CEF can highlight the
node):

```python
        snapshot = (self._visible, len(self._descriptors), self.selected_index,
                    self._selected_light_index,
                    self.show_glow_regions, self.show_weapon_arcs,
                    self.show_hull_texture,
                    tuple(sorted(self._pending_radius.items())),
                    tuple(sorted(self._pending_light)),
                    tuple(sorted(self._saved_radius.items())),
                    tuple(sorted(self._expanded_groups)))
        ...
            "selected_index": self.selected_index,
            "selected_light_index": self._selected_light_index,
```

(If `_saved_radius` isn't already in the snapshot, adding it is harmless and
correct. Keep the existing terms; just insert `self._selected_light_index`.)

- [ ] **Step 4: Update the existing light-row tests**

Existing tests assert the *subsystem* row carries `light`/`light_region`
(`test_subsystem_row_carries_light_flag_and_region`,
`test_row_light_region_reflects_pending_after_edit`,
`test_non_light_subsystem_row_has_no_light`). Those fields moved to the light
child. Rewrite them to assert the **light child** instead:

```python
def test_light_child_carries_region(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    child = _payload_data(p.render_payload())["subsystems"][0]["children"][0]
    assert child["kind"] == "light"
    assert child["light_region"]["shape"] == "Cylinder"


def test_light_child_reflects_pending_after_edit(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_light_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _LightShip())
    p.open()
    p.dispatch_event("set_light:" + _json.dumps(
        {"i": 0, "shape": "Box", "sx": 0.5, "sy": 0.6, "sz": 0.7}))
    child = _payload_data(p.render_payload())["subsystems"][0]["children"][0]
    assert child["light_region"]["shape"] == "Box"


def test_dark_subsystem_row_has_no_light_child(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_dark_descriptor("Phaser Bank")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    row = _payload_data(p.render_payload())["subsystems"][0]
    assert row["has_light"] is False
    assert [c for c in row.get("children", []) if c.get("kind") == "light"] == []
```

Delete the three superseded tests. Keep `set_light`/`save`/`_saved_light`/radius
tests as-is (a `set_light` on a subsystem index still stages into
`_pending_light[i]` and now also makes `_has_light(i)` true).

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: PASS (new + updated + existing).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel.py
git commit -m "feat(spv): light-volume node model — select/add/remove + tree child

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Overlay + host_loop — light-driven glow, hide on remove

**Files:**
- Modify: `engine/ui/glow_region_overlay.py` (`build_glow_region_overlay` None handling)
- Modify: `engine/host_loop.py` (glow `selected_name` from light selection)
- Test: `tests/unit/test_glow_region_overlay.py`

**Interfaces:**
- Consumes: `pending_light_specs()` (may contain `None`), `selected_light_index`.
- Produces: a `None` pending value draws nothing for that subsystem (hides the baked region); host_loop drives the glow overlay's `selected_name` from the light selection and the sphere from the subsystem selection.

- [ ] **Step 1: Write the failing test**

```python
# add to tests/unit/test_glow_region_overlay.py
def test_pending_none_hides_baked_region(monkeypatch):
    monkeypatch.setattr(gro, "_iter_subsystems", lambda ship: ship._subs)
    monkeypatch.setattr(gro, "_position_tuple", lambda sub: (0.0, 0.0, 0.0))
    # A baked cylinder that WOULD draw if not hidden.
    monkeypatch.setattr(gro, "baked_region_ops",
                        lambda prop, pos, name: [("cylinder", (0.0, 0.0, 0.0),
                                                  (0.0, 0.0, 1.0), 0.25, 2.0)])
    ship = _Ship([_Sub("Center Impulse", object())])
    pending = {"Center Impulse": None}          # staged removal
    cyls, boxes = gro.build_glow_region_overlay(ship, show_all=True, pending=pending)
    assert cyls == [] and boxes == []           # hidden, not the baked region
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_glow_region_overlay.py -q -k pending_none`
Expected: FAIL — the current code calls `resolve_baked_region(None, pos)` → `AttributeError`, or draws the baked region.

- [ ] **Step 3: Implement None handling**

In `engine/ui/glow_region_overlay.py`, in the pending branch of
`build_glow_region_overlay`:

```python
        if name in pending:
            spec = pending[name]
            op = resolve_baked_region(spec, pos) if spec is not None else None
            ops = [op] if op is not None else []
        else:
            prop = sub.GetProperty() if hasattr(sub, "GetProperty") else None
            ops = baked_region_ops(prop, pos, name)
```

- [ ] **Step 4: Drive host_loop from the light selection**

In `engine/host_loop.py`, the SPV viewer-mode block: the glow overlay's
`selected_name` must come from the light selection (so selecting a subsystem no
longer shows its glow — that is now the light node's job). Add a panel helper for
the selected light's subsystem name and use it:

In `ship_property_viewer_panel.py` add:

```python
    def selected_light_name(self) -> Optional[str]:
        """GetName() of the subsystem whose light is selected, or None."""
        i = self._selected_light_index
        if i is not None and 0 <= i < len(self._descriptors):
            return self._descriptors[i].get("name")
        return None
```

In `host_loop.py`, change the `build_glow_region_overlay(...)` call's
`selected_name` argument:

```python
                _cyls, _boxes = build_glow_region_overlay(
                    player,
                    selected_name=ship_property_viewer.selected_light_name(),
                    show_all=ship_property_viewer.show_glow_regions,
                    pending=ship_property_viewer.pending_light_specs())
```

(The `selected_subsystem_sphere()` / `set_debug_spheres` call is unchanged — it
already returns None while a light is selected because `selected_index` is None.)

- [ ] **Step 5: Run overlay tests + gate**

```bash
uv run pytest tests/unit/test_glow_region_overlay.py -q
scripts/check_tests.sh
```
Expected: PASS / green.

- [ ] **Step 6: Commit**

```bash
git add engine/ui/glow_region_overlay.py engine/host_loop.py engine/ui/ship_property_viewer_panel.py tests/unit/test_glow_region_overlay.py
git commit -m "feat(spv): light selection drives the glow wireframe; removal hides it

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: CEF — recursive list, light node, Add/Edit/Remove menus

**Files:**
- Modify: `native/assets/ui-cef/index.html` (context-menu items)
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`

**Interfaces:**
- Consumes: `setShipPropertyViewer(data)` — subsystem rows now carry `has_light` and a `children` list that may include a `{kind:"light", light_of, name, light_region, dirty}` node; `data.selected_light_index`.
- Produces: no Python interface. Verified by the gate build + live `--developer` check.

This task is UI wiring; the SPV JS is not unit-tested. Verification is the gate
build plus a live check.

- [ ] **Step 1: Context-menu items (index.html)**

Replace the `#spv-ctxmenu` body so the three light items exist (JS shows/hides
per node):

```html
      <div id="spv-ctxmenu" class="spv-ctxmenu" style="display:none;">
        <div id="spv-ctx-radius" class="spv-ctxmenu__item" onclick="shipPropertyViewerCtxRadius()">Set Radius…</div>
        <div id="spv-ctx-addlight" class="spv-ctxmenu__item" style="display:none;" onclick="shipPropertyViewerCtxAddLight()">Add Light Volume</div>
        <div id="spv-ctx-light" class="spv-ctxmenu__item" style="display:none;" onclick="shipPropertyViewerCtxLight()">Edit Light…</div>
        <div id="spv-ctx-removelight" class="spv-ctxmenu__item" style="display:none;" onclick="shipPropertyViewerCtxRemoveLight()">Remove Light Volume</div>
      </div>
```

- [ ] **Step 2: JS — recursive render + light node + node-aware menu**

Replace `spvRowHtml` / `renderSPVSubsystemList` / `spvSeedRowRadius` and the
right-click handler with node-kind-aware versions. A light row has `kind:"light"`
and `light_of`; it fires `select_light`, and its right-click shows Edit/Remove.

```javascript
// A light-volume node's working seed lives on the row (row.light_region), keyed
// by its parent subsystem index (row.light_of). Track the right-clicked node so
// the context menu knows which items to show.
var spvCtxKind = 'subsystem';       // 'subsystem' | 'light'
var spvCtxLightOf = null;           // parent subsystem index for a light node

function spvSeedRow(row) {
    if (row.kind === 'light') {
        if (row.light_region) spvRowLight[row.light_of] = row.light_region;
        return;
    }
    if (row.radius != null) spvRowRadii[row.index] = row.radius;
    // subsystem row no longer carries light_region; Add uses light_of default
    // captured from its own light child if present (seeded above).
}

// Recursive render: a row, then (if expanded) its children at any depth.
function spvRenderRows(rows, out, selectedIndex, selectedLight, depth) {
    for (var i = 0; i < rows.length; i++) {
        var row = rows[i] || {};
        spvSeedRow(row);
        out.push(spvRowHtml(row, selectedIndex, selectedLight, depth));
        if (row.expanded && (row.children || []).length) {
            spvRenderRows(row.children, out, selectedIndex, selectedLight, depth + 1);
        }
    }
}

function renderSPVSubsystemList(rows, selectedIndex, selectedLight) {
    var body = document.getElementById('spv-syslist-body');
    if (!body) return;
    var out = [];
    spvRenderRows(rows, out, selectedIndex, selectedLight, 0);
    body.innerHTML = out.join('');
}

function spvRowHtml(row, selectedIndex, selectedLight, depth) {
    var isLight = (row.kind === 'light');
    var chosen = isLight ? (selectedLight === row.light_of)
                         : (selectedIndex === row.index);
    var hasChildren = (row.children || []).length > 0;
    var lead;
    if (hasChildren) {
        lead = '<span class="spv-sys-caret" onclick="event.stopPropagation();'
             + 'shipPropertyViewerGroupToggle(' + row.index + ')">'
             + (row.expanded ? '&#9662;' : '&#9656;') + '</span>';
    } else {
        lead = '<span class="spv-sys-caret spv-sys-caret--none"></span>';
    }
    var clickJs = isLight
        ? ('shipPropertyViewerLightRow(' + row.light_of + ', ' + chosen + ')')
        : ('shipPropertyViewerRow(' + row.index + ', ' + chosen + ')');
    var menuJs = isLight
        ? ('return shipPropertyViewerLightMenu(event, ' + row.light_of + ')')
        : ('return shipPropertyViewerRowMenu(event, ' + row.index + ', '
           + (row.has_light === true) + ')');
    var extra = isLight ? ' spv-sys-row--light' : '';
    var indent = ' style="padding-left:' + (10 + depth * 14) + 'px"';
    var body = '<span class="spv-sys-row__name">' + escapeHtmlSPV(row.name || '') + '</span>';
    if (!isLight) {
        var eye = row.targetable ? SPV_EYE_OPEN : SPV_EYE_SHUT;
        var eyeCls = row.targetable ? '' : ' spv-sys-row__eye--shut';
        var bar = (typeof row.condition_pct === 'number')
            ? '<span class="spv-sys-row__bar" style="--bar-pct:'
              + Math.max(0, Math.min(100, row.condition_pct)) + '%"></span>' : '';
        body += bar + '<span class="spv-sys-row__eye' + eyeCls + '">' + eye + '</span>';
    }
    return '<div class="spv-sys-row' + (depth > 0 ? ' spv-sys-row--child' : '')
         + (chosen ? ' spv-sys-row--chosen' : '')
         + (row.dirty === true ? ' spv-sys-row--dirty' : '') + extra + '"' + indent
         + ' onclick="' + clickJs + '"'
         + ' oncontextmenu="' + menuJs + '">'
         + lead + body + '</div>';
}

// Light node row click: select this light (or deselect if already selected).
window.shipPropertyViewerLightRow = function (lightOf, chosen) {
    dauntlessEvent('ship-property-viewer/' +
                   (chosen ? 'deselect' : ('select_light:' + lightOf)));
};

// Right-click a subsystem row: Set Radius always; Add Light Volume only when the
// subsystem has no light yet.
window.shipPropertyViewerRowMenu = function (event, index, hasLight) {
    event.preventDefault(); event.stopPropagation();
    spvCtxKind = 'subsystem'; spvCtxIndex = index; spvCtxLightOf = null;
    spvCtxRadius = (spvRowRadii[index] !== undefined) ? spvRowRadii[index] : 0;
    spvShowMenuItems({radius: true, addlight: !hasLight, light: false, removelight: false});
    spvOpenMenuAt(event);
    return false;
};

// Right-click a light node: Edit + Remove.
window.shipPropertyViewerLightMenu = function (event, lightOf) {
    event.preventDefault(); event.stopPropagation();
    spvCtxKind = 'light'; spvCtxLightOf = lightOf; spvCtxIndex = lightOf;
    spvShowMenuItems({radius: false, addlight: false, light: true, removelight: true});
    spvOpenMenuAt(event);
    return false;
};

function spvShowMenuItems(show) {
    var map = {radius: 'spv-ctx-radius', addlight: 'spv-ctx-addlight',
               light: 'spv-ctx-light', removelight: 'spv-ctx-removelight'};
    Object.keys(map).forEach(function (k) {
        var el = document.getElementById(map[k]);
        if (el) el.style.display = show[k] ? 'block' : 'none';
    });
}
function spvOpenMenuAt(event) {
    var menu = document.getElementById('spv-ctxmenu');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';
    dauntlessEvent('ship-property-viewer/overlay:1');
}

// Add Light Volume (subsystem context) → stage a default, then Python selects it.
window.shipPropertyViewerCtxAddLight = function () {
    dauntlessEvent('ship-property-viewer/add_light:' + spvCtxIndex);
    spvHideOverlays();
};
// Remove Light Volume (light-node context).
window.shipPropertyViewerCtxRemoveLight = function () {
    dauntlessEvent('ship-property-viewer/remove_light:' + spvCtxLightOf);
    spvHideOverlays();
};
```

`shipPropertyViewerCtxLight` (Edit) already reads `spvRowLight[spvCtxIndex]`;
since `spvCtxIndex` is set to `light_of` for a light node, and `spvSeedRow` seeds
`spvRowLight[light_of]` from the light child's `light_region`, the modal
pre-fills correctly. In `setShipPropertyViewer`, pass the light selection to the
list render:

```javascript
    renderSPVSubsystemList(data.subsystems || [],
        (typeof data.selected_index === 'number') ? data.selected_index : null,
        (typeof data.selected_light_index === 'number') ? data.selected_light_index : null);
```

- [ ] **Step 3: CSS (ship_property_viewer.css)**

Add a light-node accent (small, distinct from the dirty marker):

```css
.spv-sys-row--light .spv-sys-row__name { color: #ffd9a0; font-style: italic; }
.spv-sys-row--light.spv-sys-row--chosen { background: rgba(255, 180, 90, 0.22); }
```

- [ ] **Step 4: Build + gate + live check**

```bash
cmake --build build -j        # CEF assets are runtime-loaded; build only to run the gate cleanly
scripts/check_tests.sh
```
Expected: gate green.

Live-verify under `--developer` on the Galaxy:
1. Expand a subsystem group; a lit subsystem (e.g. Center Impulse) shows a
   **Light Volume** child. Select it → only its orange glow wireframe (no radius
   sphere); the parent icon stays.
2. Right-click the light node → **Edit Light…** (shape/size) updates the wire live;
   **Remove Light Volume** → the child disappears and the wireframe is gone.
3. Right-click a subsystem with no light (e.g. a phaser bank) → **Add Light
   Volume** → a Light Volume child appears, selected, showing a default sphere
   wireframe; edit it.
4. **Save** → confirm → inspect `hardpoint_overrides.py`: added/edited regions
   written, removed regions gone (their block dropped if now empty).

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/css/ship_property_viewer.css
git commit -m "feat(spv): light-volume tree node + Add/Edit/Remove context menus

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Self-Review

**Spec coverage:**
- Any subsystem light-capable → Task 2 (ungated `_light_annotation`).
- One per subsystem → Task 3 (`add_light` rejected when `_has_light`).
- Light as its own selection, sphere suppressed → Task 3 (`_selected_light_index`, mutual exclusion) + Task 4 (glow `selected_name` from the light; sphere unchanged).
- Add / Edit / Remove unified via effective light (pending/saved/baked, `None`=removed) → Task 3; Save routes removals as `set_region(0, [])` → Task 3; writer drops empty blocks → Task 1.
- Light child node in the tree, recursive render → Task 3 (`_subsystem_rows`) + Task 5 (recursive JS).
- Overlay hides a removed light (`None` sentinel) → Task 3 (`pending_light_specs`) + Task 4 (overlay None-handling).
- Context menus (Add on subsystem / Edit+Remove on light) → Task 5.
- In-scene glow unchanged for non-standard subsystems → no `ShipGlowController` edit (Global Constraints).

**Placeholder scan:** none — Task 2's Step 1 sketch is explicitly replaced by two
concrete `_light_annotation` tests; every other step has real code/commands.

**Type consistency:** effective light is a spec dict or `None` throughout
(`_effective_light`, `_pending_light`, `_saved_light`, `pending_light_specs`); the
overlay treats `None` as hide (Task 4). `region_spec_to_calls(0, spec)` for a spec
vs `[]` for a removal — both are the 4-tuple `(name,"__region__",0,calls)`
consumed by the Task-6 (already-merged) target. Row fields: subsystem row carries
`has_light` (Task 3) consumed by `shipPropertyViewerRowMenu(hasLight)` (Task 5);
light child carries `kind`/`light_of`/`light_region` (Task 3) consumed by
`spvRowHtml`/`spvSeedRow`/`shipPropertyViewerLightMenu` (Task 5).

**Out-of-scope confirmed absent:** no multi-region (index>0), no
ShipGlowController change, no position/axis editor.
