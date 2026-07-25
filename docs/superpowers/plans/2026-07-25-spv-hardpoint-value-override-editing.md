# SPV Hardpoint Value Override Editing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let the Ship Property Viewer edit a subsystem's radius and persist it into a machine-owned `engine/appc/hardpoint_overrides.py`, staged behind an explicit Save.

**Architecture:** The override file becomes fully machine-owned — one function per ship, one expanded block per subsystem, plain Appc setter calls. A pure writer recovers each ship's model by *executing* its function against a recording `find`, applies an edit, and re-emits the whole file deterministically. A routing seam maps ship → override target. The SPV stages edits and, on Save, hands them to the routed target.

**Tech Stack:** Python 3 (engine + pytest), CEF (HTML/CSS/JS), no C++ change.

**Supersedes:** `2026-07-24-spv-subsystem-rename-and-override-editing.md` (rename/managed-block plan — abandoned). This plan REPLACES the contents of `engine/appc/hardpoint_override_writer.py` and `tests/unit/test_hardpoint_override_writer.py` created by that plan's committed Tasks 1–2 (`18a6a820`, `c1d3cf19`).

## Global Constraints

- **Design:** `docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md`.
- **Dev-only:** the SPV is constructed only under `--developer`; production render/logic stays byte-identical. No behavior runs without the panel open. The live sim is NOT mutated by a staged edit.
- **Machine-owned file:** after conversion, `hardpoint_overrides.py` is 100% emitter output. `emit(read_models(module)) == file_source` must hold (canonical fixed point).
- **Behavior preserved by conversion:** the converted file must issue the exact same per-subsystem setter calls as the original (verified by comparing recorded models).
- **Crash-safe writes:** emitted text must `ast.parse`; write atomically (`os.replace`); a failure aborts without touching the file.
- **Shared checkout:** stage commits with EXPLICIT pathspecs only. Never `git add -A`/`git checkout`/`restore`/`stash`/`reset --hard`/`clean`.
- **Test gate:** `scripts/check_tests.sh` green (only the 7 baselined headless-GL FrameTests may fail).
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

---

## File Structure

**Replaced:**
- `engine/appc/hardpoint_override_writer.py` — REWRITTEN: recording proxy, `read_models`, `set_setter`, `emit`. No file I/O.
- `tests/unit/test_hardpoint_override_writer.py` — REWRITTEN for the new API.

**Modified:**
- `engine/appc/hardpoint_overrides.py` — converted to canonical machine-owned form (Task 2).
- `engine/ui/ship_property_viewer.py` — add `radius` to the property readout.
- `engine/ui/ship_property_viewer_panel.py` — staging state, dispatch, payload, overlay-suppress.
- `tests/ui/test_ship_property_viewer_panel.py` — staging/save/dirty tests.
- `native/assets/ui-cef/{index.html,js/ship_property_viewer.js,css/ship_property_viewer.css}` — context menu, radius modal, Save bar, dirty markers, radius readout.

**New:**
- `engine/appc/override_routing.py` — leaf resolver, file target, `resolve_override_target`.
- `tests/unit/test_hardpoint_overrides_canonical.py`, `tests/unit/test_override_routing.py`.

---

## Task 1: Override writer — execute-to-model + emit (pure)

**Files:**
- Rewrite: `engine/appc/hardpoint_override_writer.py`
- Rewrite: `tests/unit/test_hardpoint_override_writer.py`

**Interfaces:**
- Produces:
  - `read_models(module) -> dict` — `{leaf: {subsystem: [(setter, args), ...]}}` by executing each `module.OVERRIDES[leaf]` against a recording `find`. Plain dicts (insertion-ordered); values are lists of `(setter_name, args_tuple)`.
  - `set_setter(models, leaf, subsystem, setter, args) -> None` — replace the subsystem's existing call with the same setter (and same region-index for `SetGlowRegion*`), else append; creates the leaf/subsystem entries if absent.
  - `emit(models) -> str` — deterministic full-module source (`apply` preamble + one `_<leaf>` per leaf + `OVERRIDES` dict). Raises `SyntaxError` (via `ast.parse`) if the result would not parse.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_hardpoint_override_writer.py
import ast
import types
import engine.appc.hardpoint_override_writer as w


def _module(src):
    m = types.ModuleType("fake_overrides")
    exec(compile(src, "<fake>", "exec"), m.__dict__)   # noqa: S102
    return m


_SRC = '''
def _galaxy(find):
    for name in ("Port Impulse", "Star Impulse"):
        p = find(name)
        if p is not None:
            p.SetGlowRegionShape(0, "Cylinder")
            p.SetGlowRegionRadius(0, 0.25)
    p = find("Center Impulse")
    if p is not None:
        p.SetGlowRegionRadius(0, 0.25)
        p.SetRadius(0.25)

OVERRIDES = {"galaxy": _galaxy}
'''


def test_read_models_captures_calls_per_subsystem():
    m = _module(_SRC)
    models = w.read_models(m)
    assert list(models) == ["galaxy"]
    g = models["galaxy"]
    # Loop expanded into two subsystems, each with its recorded calls.
    assert g["Port Impulse"] == [("SetGlowRegionShape", (0, "Cylinder")),
                                 ("SetGlowRegionRadius", (0, 0.25))]
    assert g["Star Impulse"] == [("SetGlowRegionShape", (0, "Cylinder")),
                                 ("SetGlowRegionRadius", (0, 0.25))]
    assert g["Center Impulse"] == [("SetGlowRegionRadius", (0, 0.25)),
                                   ("SetRadius", (0.25,))]


def test_set_setter_replaces_radius_not_duplicates():
    m = _module(_SRC)
    models = w.read_models(m)
    w.set_setter(models, "galaxy", "Center Impulse", "SetRadius", (0.5,))
    calls = models["galaxy"]["Center Impulse"]
    assert calls.count(("SetRadius", (0.5,))) == 1
    assert not any(s == "SetRadius" and a == (0.25,) for s, a in calls)
    # Glow untouched.
    assert ("SetGlowRegionRadius", (0, 0.25)) in calls


def test_set_setter_adds_block_when_subsystem_absent():
    m = _module(_SRC)
    models = w.read_models(m)
    w.set_setter(models, "galaxy", "Sensor Array", "SetRadius", (0.3,))
    assert models["galaxy"]["Sensor Array"] == [("SetRadius", (0.3,))]


def test_emit_round_trips_and_is_a_fixed_point():
    m = _module(_SRC)
    models = w.read_models(m)
    text = w.emit(models)
    ast.parse(text)                                   # valid python
    m2 = _module(text)
    assert w.read_models(m2) == models                # behavior preserved
    assert w.emit(w.read_models(m2)) == text          # deterministic fixed point


def test_emit_glow_index_distinguished_by_set_setter():
    m = _module('''
def _x(find):
    p = find("A")
    if p is not None:
        p.SetGlowRegionRadius(0, 0.1)
        p.SetGlowRegionRadius(1, 0.2)
OVERRIDES = {"x": _x}
''')
    models = w.read_models(m)
    w.set_setter(models, "x", "A", "SetGlowRegionRadius", (1, 0.9))  # edit index 1 only
    calls = models["x"]["A"]
    assert ("SetGlowRegionRadius", (0, 0.1)) in calls
    assert ("SetGlowRegionRadius", (1, 0.9)) in calls
    assert ("SetGlowRegionRadius", (1, 0.2)) not in calls
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q`
Expected: FAIL (new API not present; the file still holds the old managed-block code).

- [ ] **Step 3: Write the implementation (replace the whole file)**

```python
# engine/appc/hardpoint_override_writer.py
"""Pure tooling to read, edit, and emit engine/appc/hardpoint_overrides.py.

The override file is machine-owned: one function per ship, one block per
subsystem, plain Appc setter calls. We recover a ship's model by EXECUTING its
function against a recording `find` (the functions are pure straight-line setter
calls), edit the model, and re-emit the whole file deterministically.

Design: docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md
"""
from __future__ import annotations

import ast
import json

# Setters whose first argument is a region index (so an edit targets one index).
_INDEXED_PREFIX = "SetGlowRegion"


class _Recorder:
    """Proxy returned by the recording find; records every method call as
    (name, args) into the shared list. Truthy + not-None so `if p is not None`
    guards always pass."""

    def __init__(self, calls):
        self._calls = calls

    def __getattr__(self, name):
        def rec(*args):
            self._calls.append((name, args))
            return None
        return rec


def _make_find(per_sub):
    def find(name):
        return _Recorder(per_sub.setdefault(name, []))
    return find


def read_models(module) -> dict:
    """{leaf: {subsystem: [(setter, args), ...]}} by executing each override fn."""
    models: dict = {}
    for leaf, fn in module.OVERRIDES.items():
        per_sub: dict = {}
        fn(_make_find(per_sub))
        models[leaf] = per_sub
    return models


def _replace_key(setter, args):
    if setter.startswith(_INDEXED_PREFIX) and args:
        return (setter, args[0])      # same setter AND same region index
    return (setter,)


def set_setter(models, leaf, subsystem, setter, args) -> None:
    per_sub = models.setdefault(leaf, {})
    calls = per_sub.setdefault(subsystem, [])
    key = _replace_key(setter, args)
    for i, (s, a) in enumerate(calls):
        if _replace_key(s, a) == key:
            calls[i] = (setter, tuple(args))
            return
    calls.append((setter, tuple(args)))


# ── Emission ────────────────────────────────────────────────────────────────

_HEADER = '''"""Machine-owned hardpoint overrides — edited by the Ship Property Viewer.

Do NOT hand-edit: the SPV regenerates this file on save. One function per ship,
one block per subsystem, plain Appc setter calls.
Design: docs/superpowers/specs/2026-07-25-spv-hardpoint-value-override-editing-design.md
"""


def apply(leaf):
    """Run a ship's override function from the SDK-loader hook, if any."""
    fn = OVERRIDES.get(leaf)
    if fn is None:
        return
    import App

    mgr = App.g_kModelPropertyManager

    def find(name):
        return mgr.FindByName(name, App.TGModelPropertyManager.LOCAL_TEMPLATES)

    fn(find)'''


def _lit(v) -> str:
    if isinstance(v, str):
        return json.dumps(v)          # valid double-quoted Python string literal
    if isinstance(v, bool):
        return "True" if v else "False"
    if isinstance(v, float):
        return repr(v)
    return str(v)


def _emit_function(leaf, per_sub) -> str:
    out = ["def _%s(find):" % leaf, '    """%s."""' % leaf]
    if not per_sub:
        out.append("    return")
    else:
        for subsystem, calls in per_sub.items():
            out.append("    p = find(%s)" % _lit(subsystem))
            out.append("    if p is not None:")
            for setter, args in calls:
                out.append("        p.%s(%s)"
                           % (setter, ", ".join(_lit(a) for a in args)))
    return "\n".join(out)


def _emit_overrides(leaves) -> str:
    out = ["OVERRIDES = {"]
    for leaf in leaves:
        out.append('    "%s": _%s,' % (leaf, leaf))
    out.append("}")
    return "\n".join(out)


def emit(models) -> str:
    chunks = [_HEADER]
    for leaf, per_sub in models.items():
        chunks.append(_emit_function(leaf, per_sub))
    chunks.append(_emit_overrides(models.keys()))
    text = "\n\n\n".join(chunks) + "\n"
    ast.parse(text)                    # raises SyntaxError on a bad emit
    return text
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_override_writer.py tests/unit/test_hardpoint_override_writer.py
git commit -m "feat(overrides): execute-to-model + deterministic emit writer (replaces managed-block)"
```

---

## Task 2: Convert hardpoint_overrides.py to canonical form

**Files:**
- Modify (regenerate): `engine/appc/hardpoint_overrides.py`
- Create: `tests/unit/test_hardpoint_overrides_canonical.py`

**Interfaces:**
- Consumes: `read_models`, `emit` (Task 1).
- Produces: a machine-owned `hardpoint_overrides.py` that is a canonical fixed point (`emit(read_models(module)) == source`), preserving every subsystem's setter calls.

- [ ] **Step 1: Write the failing test (canonical fixed point)**

```python
# tests/unit/test_hardpoint_overrides_canonical.py
import engine.appc.hardpoint_overrides as ho
from engine.appc import hardpoint_override_writer as w


def test_file_is_canonical_emitter_output():
    with open(ho.__file__, "r", encoding="utf-8") as fh:
        source = fh.read()
    assert w.emit(w.read_models(ho)) == source


def test_apply_and_overrides_are_intact():
    assert callable(ho.apply)
    assert "galaxy" in ho.OVERRIDES
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_hardpoint_overrides_canonical.py -q`
Expected: FAIL — the current file uses loops/banners, so `emit(read_models(...))` differs from the source.

- [ ] **Step 3: Capture behavior BEFORE, convert, verify behavior UNCHANGED**

Run this one-shot conversion+verification script (scratch file — do not commit it):

```python
# /tmp/convert_overrides.py
import importlib
import engine.appc.hardpoint_overrides as ho
from engine.appc import hardpoint_override_writer as w

before = w.read_models(ho)                      # {leaf: {sub: [calls]}}
text = w.emit(before)

with open(ho.__file__, "w", encoding="utf-8") as fh:
    fh.write(text)

importlib.reload(ho)
after = w.read_models(ho)

# Behavior equivalence: same per-subsystem setter calls (key order irrelevant).
def norm(models):
    return {leaf: {sub: list(calls) for sub, calls in per.items()}
            for leaf, per in models.items()}

assert norm(before) == norm(after), "conversion changed setter behavior!"
print("OK: %d ships converted, setter calls identical" % len(after))
```

Run: `uv run python /tmp/convert_overrides.py`
Expected: `OK: N ships converted, setter calls identical`.

This rewrites `engine/appc/hardpoint_overrides.py` in place. Read the resulting
file to sanity-check: one `def _<leaf>(find):` per ship, expanded per-subsystem
blocks, the `apply`/`OVERRIDES` scaffolding intact.

- [ ] **Step 4: Run the full override + canonical test set**

Run: `uv run pytest tests/unit/test_hardpoint_overrides_canonical.py tests/unit/test_ship_data_overrides.py -q`
Expected: PASS (canonical fixed point holds; existing override-application tests still pass — the applied setter calls are unchanged).

Also confirm nothing else that imports `hardpoint_overrides` broke:
Run: `uv run pytest tests/unit/test_ship_data_overrides.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_overrides.py tests/unit/test_hardpoint_overrides_canonical.py
git commit -m "refactor(overrides): convert hardpoint_overrides.py to canonical machine-owned form"
```

---

## Task 3: Routing seam + file target

**Files:**
- Create: `engine/appc/override_routing.py`
- Create: `tests/unit/test_override_routing.py`

**Interfaces:**
- Consumes: `read_models`, `set_setter`, `emit` (Task 1).
- Produces:
  - `hardpoint_leaf_for_ship(ship) -> "str | None"` — `ship.GetScript()` → import → `GetShipStats()["HardpointFile"]`; None-safe.
  - `class HardpointOverridesFileTarget` with `write(leaf, edits) -> None` where `edits` is a list of `(subsystem, setter, args)`. Reloads the file, applies each edit via `set_setter`, `emit`s, writes atomically.
  - `resolve_override_target(ship) -> HardpointOverridesFileTarget`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_override_routing.py
import engine.appc.override_routing as r
from engine.appc import hardpoint_override_writer as w


class _StatsMod:
    @staticmethod
    def GetShipStats():
        return {"HardpointFile": "galaxy"}


class _Ship:
    def __init__(self, script):
        self._s = script

    def GetScript(self):
        return self._s


def test_leaf_for_ship_reads_hardpointfile(monkeypatch):
    monkeypatch.setattr(r.importlib, "import_module", lambda name: _StatsMod)
    assert r.hardpoint_leaf_for_ship(_Ship("ships.Galaxy")) == "galaxy"


def test_leaf_for_ship_none_safe():
    assert r.hardpoint_leaf_for_ship(_Ship("")) is None
    assert r.hardpoint_leaf_for_ship(object()) is None


def test_file_target_persists_radius_edit(tmp_path):
    f = tmp_path / "hardpoint_overrides.py"
    f.write_text(w.emit({"galaxy": {"Center Impulse": [("SetRadius", (0.25,))]}}))
    target = r.HardpointOverridesFileTarget(str(f))
    target.write("galaxy", [("Center Impulse", "SetRadius", (0.5,))])
    # Re-read the file and confirm the value changed (and only once).
    import types
    m = types.ModuleType("x"); exec(f.read_text(), m.__dict__)  # noqa: S102
    models = w.read_models(m)
    assert models["galaxy"]["Center Impulse"] == [("SetRadius", (0.5,))]


def test_resolve_returns_file_target(monkeypatch):
    monkeypatch.setattr(r.importlib, "import_module", lambda name: _StatsMod)
    assert isinstance(r.resolve_override_target(_Ship("ships.Galaxy")),
                      r.HardpointOverridesFileTarget)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_override_routing.py -q`
Expected: FAIL (`override_routing` not defined).

- [ ] **Step 3: Write the implementation**

```python
# engine/appc/override_routing.py
"""Route a ship's hardpoint override edits to the right destination.

Today every (game) ship routes to the engine-owned aggregated file
engine/appc/hardpoint_overrides.py. The seam exists so modded ships can later
route to their own files without the SPV/UI changing.
"""
from __future__ import annotations

import importlib
import os

from engine.appc import hardpoint_override_writer as _writer

_PATH = os.path.join(os.path.dirname(__file__), "hardpoint_overrides.py")


def hardpoint_leaf_for_ship(ship) -> "str | None":
    getter = getattr(ship, "GetScript", None)
    if getter is None:
        return None
    try:
        script_name = getter()
    except Exception:
        return None
    if not script_name:
        return None
    try:
        mod = importlib.import_module(script_name)
        leaf = mod.GetShipStats().get("HardpointFile")
    except Exception:
        return None
    return leaf or None


class HardpointOverridesFileTarget:
    def __init__(self, path: str = _PATH) -> None:
        self.path = path

    def write(self, leaf, edits) -> None:
        """edits: list of (subsystem, setter, args). Reload → apply → emit → atomic."""
        import types
        with open(self.path, "r", encoding="utf-8") as fh:
            src = fh.read()
        module = types.ModuleType("_ho_load")
        exec(compile(src, self.path, "exec"), module.__dict__)  # noqa: S102
        models = _writer.read_models(module)
        for subsystem, setter, args in edits:
            _writer.set_setter(models, leaf, subsystem, setter, args)
        text = _writer.emit(models)          # raises on a bad emit
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, self.path)


def resolve_override_target(ship) -> HardpointOverridesFileTarget:
    # future: modded ships → a target writing into the mod's files.
    return HardpointOverridesFileTarget()
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/unit/test_override_routing.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/override_routing.py tests/unit/test_override_routing.py
git commit -m "feat(overrides): ship->target routing seam + file target (write via emit)"
```

---

## Task 4: Panel staging, dispatch, payload, radius readout

**Files:**
- Modify: `engine/ui/ship_property_viewer.py` (add `radius` to the readout)
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel.py`

**Interfaces:**
- Consumes: `resolve_override_target`, `hardpoint_leaf_for_ship` (Task 3); the panel's existing `open`/`close`/`dispatch_event`/`render_payload`/`handle_input`/`_subsystem_rows`.
- Produces:
  - `self._pending_radius: dict[int, float]` (descriptor index → staged radius), `self._overlay_open: bool`. Reset in `open`/`close`.
  - `dispatch_event`: `set_radius:<json {"i": int, "value": float}>`, `save`, `overlay:<0|1>`.
  - `render_payload`: `pending_count: int`; each subsystem row gains `dirty: bool`; the selected subsystem's `properties["radius"]` reflects the pending value when staged.

- [ ] **Step 1: Add `radius` to the property readout (ship_property_viewer.py)**

In `_properties_for` (engine/ui/ship_property_viewer.py), add a radius field:

```python
        "radius":    _safe(getattr(sub, "GetRadius", lambda: None)),
```

(Place it after `"condition"`. Keeps the readout showing the live radius.)

- [ ] **Step 2: Write the failing panel tests**

```python
# append to tests/ui/test_ship_property_viewer_panel.py
import json as _json


class _RadiusShip:
    def GetScript(self):
        return "ships.Galaxy"


def _rad_descriptor(name):
    return {"name": name, "icon_id": 0, "world_pos": (0, 0, 0),
            "state": "healthy", "targetable": True, "condition_pct": 100,
            "parent_index": None,
            "properties": {"name": name, "radius": 0.25}}


def test_set_radius_stages_pending_and_marks_dirty(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    ok = p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    assert ok is True
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1
    assert data["subsystems"][0]["dirty"] is True
    # Readout reflects the staged value (no live mutation needed).
    p.selected_index = 0
    p._last_pushed = None
    assert _payload_data(p.render_payload())["selected"]["properties"]["radius"] == 0.5


def test_save_routes_edits_and_clears(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, edits): calls.append((leaf, edits))

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    p.dispatch_event("save")
    assert calls == [("galaxy", [("Center Impulse", "SetRadius", (0.5,))])]
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_overlay_open_suppresses_orbit():
    p = _open_panel_for_input()
    p.dispatch_event("overlay:1")
    host = _FakeHost()
    yaw0 = p.camera.yaw
    host._cursor = (600.0, 300.0); host._down = True
    p.handle_input(host)
    host._cursor = (650.0, 350.0)
    p.handle_input(host)
    assert p.camera.yaw == yaw0


def test_close_without_save_discards_pending(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_rad_descriptor("Center Impulse")])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RadiusShip())
    p.open()
    p.dispatch_event("set_radius:" + _json.dumps({"i": 0, "value": 0.5}))
    p.close()
    p.open()
    assert _payload_data(p.render_payload())["pending_count"] == 0
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: FAIL (`set_radius`/`save`/`overlay` unhandled; no `pending_count`/`dirty`).

- [ ] **Step 4: Implement in ship_property_viewer_panel.py**

Add near the top:

```python
from engine.appc.override_routing import (
    resolve_override_target, hardpoint_leaf_for_ship,
)
```

In `__init__`, with the other toggles:

```python
        # Staged radius edits: descriptor index -> new radius. Reset every
        # open/close. Not applied to the live sim (radius has no in-session
        # visual); persisted on Save, applied on the next ship build.
        self._pending_radius: dict = {}
        # True while a CEF context menu / modal is open: handle_input suppresses
        # orbit + pick so clicks on that chrome don't reach the 3D view.
        self._overlay_open = False
```

Reset both in `open()` and `close()` (next to `self._expanded_groups = set()`):

```python
        self._pending_radius = {}
        self._overlay_open = False
```

In `handle_input`, right after `if self.camera is None: return`:

```python
        if self._overlay_open:
            return
```

In `render_payload`, extend the snapshot and payload:

```python
        snapshot = (self._visible, len(self._descriptors), self.selected_index,
                    self.show_glow_regions, self.show_weapon_arcs,
                    self.show_hull_texture,
                    tuple(sorted(self._pending_radius.items())),
                    tuple(sorted(self._expanded_groups)))
        ...
        payload = {
            ...
            "show_hull": self.show_hull_texture,
            "pending_count": len(self._pending_radius),
            "subsystems": self._subsystem_rows(),
        }
```

When building `selected` in `render_payload`, overlay the pending radius so the
readout shows the staged value:

```python
        selected = None
        if self.selected_index is not None and \
                0 <= self.selected_index < len(self._descriptors):
            selected = dict(self._descriptors[self.selected_index])
            if self.selected_index in self._pending_radius:
                props = dict(selected.get("properties", {}))
                props["radius"] = self._pending_radius[self.selected_index]
                selected["properties"] = props
```

In `_subsystem_rows`, add the dirty flag on each row (using the row's descriptor
index — the same index used for `select_pin`):

```python
            row["dirty"] = (index in self._pending_radius)
```

Add dispatch handlers in `dispatch_event` before the final `return False`:

```python
        if action.startswith("overlay:"):
            self._overlay_open = action.endswith("1")
            return True
        if action.startswith("set_radius:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                idx = int(arg["i"]); value = float(arg["value"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            self._pending_radius[idx] = value
            self._last_pushed = None
            return True
        if action == "save":
            if not self._pending_radius:
                return True
            ship = self._ship_getter()
            leaf = hardpoint_leaf_for_ship(ship)
            if leaf:
                edits = [(self._descriptors[i]["name"], "SetRadius", (v,))
                         for i, v in sorted(self._pending_radius.items())]
                try:
                    resolve_override_target(ship).write(leaf, edits)
                except Exception as e:
                    from engine import dev_mode
                    dev_mode.log_swallowed("spv radius save", e)
            self._pending_radius = {}
            self._last_pushed = None
            return True
```

- [ ] **Step 5: Run to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: PASS (new + existing tests).

- [ ] **Step 6: Commit**

```bash
git add engine/ui/ship_property_viewer.py engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel.py
git commit -m "feat(spv): stage subsystem radius edits + route Save to hardpoint overrides"
```

---

## Task 5: CEF context menu, radius modal, Save bar

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`

**Interfaces:**
- Consumes: `setShipPropertyViewer(data)` now carrying `data.pending_count`,
  `data.subsystems[i].dirty`, and `data.selected.properties.radius`;
  `dauntlessEvent('ship-property-viewer/<action>')` for `set_radius:<json>`,
  `save`, `overlay:1`/`overlay:0`.
- Produces: no Python interface. Verified by the gate build + live `--developer` check.

This task is UI wiring; the SPV JS is not unit-tested in this repo. Verification
is the gate build plus a live `--developer` check.

- [ ] **Step 1: DOM containers (index.html), inside `#spv-root` after `#spv-popover`**

```html
      <div id="spv-ctxmenu" class="spv-ctxmenu" style="display:none;">
        <div class="spv-ctxmenu__item" onclick="shipPropertyViewerCtxRadius()">Set Radius…</div>
      </div>
      <div id="spv-radius" class="spv-modal-backdrop" style="display:none;">
        <div class="spv-modal">
          <div class="spv-modal__title">Set Radius</div>
          <input id="spv-radius-input" class="spv-modal__input" type="number" step="0.01" />
          <div class="spv-modal__row">
            <button class="spv-modal__btn" onclick="shipPropertyViewerRadiusCancel()">Cancel</button>
            <button class="spv-modal__btn spv-modal__btn--primary" onclick="shipPropertyViewerRadiusApply()">Apply</button>
          </div>
        </div>
      </div>
      <div id="spv-savebar" class="spv-savebar" style="display:none;">
        <button class="spv-savebar__btn" onclick="shipPropertyViewerSave()">
          Save changes (<span id="spv-savecount">0</span>)
        </button>
      </div>
      <div id="spv-confirm" class="spv-modal-backdrop" style="display:none;">
        <div class="spv-modal">
          <div class="spv-modal__title">Amend hardpoint_overrides.py?</div>
          <div id="spv-confirm-body" class="spv-modal__body"></div>
          <div class="spv-modal__row">
            <button class="spv-modal__btn" onclick="shipPropertyViewerConfirmCancel()">Cancel</button>
            <button class="spv-modal__btn spv-modal__btn--primary" onclick="shipPropertyViewerConfirmSave()">Save</button>
          </div>
        </div>
      </div>
```

- [ ] **Step 2: JS wiring (ship_property_viewer.js)**

Module-scope state + handlers. Track the right-clicked row (index, name, current
radius from that row's data). Key behaviors: `oncontextmenu` `preventDefault` +
position the menu + fire `overlay:1`; Set Radius opens the modal pre-filled with
the current radius; Apply fires `set_radius:{i,value}`; ESC / click-away / Cancel
close and fire `overlay:0`; the Save bar toggles on `pending_count>0`; dirty rows
get `spv-sys-row--dirty`; the popover shows a `radius` row.

```javascript
var spvCtxIndex = null, spvCtxRadius = 0, spvRowRadii = {};

function spvHideOverlays() {
    ['spv-ctxmenu', 'spv-radius', 'spv-confirm'].forEach(function (id) {
        var el = document.getElementById(id); if (el) el.style.display = 'none';
    });
    dauntlessEvent('ship-property-viewer/overlay:0');
}
window.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') spvHideOverlays();
});
document.addEventListener('click', function (e) {
    var menu = document.getElementById('spv-ctxmenu');
    if (menu && menu.style.display !== 'none' && !menu.contains(e.target)) {
        menu.style.display = 'none';
        if (document.getElementById('spv-radius').style.display === 'none'
            && document.getElementById('spv-confirm').style.display === 'none') {
            dauntlessEvent('ship-property-viewer/overlay:0');
        }
    }
});

window.shipPropertyViewerRowMenu = function (event, index) {
    event.preventDefault(); event.stopPropagation();
    spvCtxIndex = index;
    spvCtxRadius = (spvRowRadii[index] !== undefined) ? spvRowRadii[index] : 0;
    var menu = document.getElementById('spv-ctxmenu');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';
    dauntlessEvent('ship-property-viewer/overlay:1');
    return false;
};
window.shipPropertyViewerCtxRadius = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    var inp = document.getElementById('spv-radius-input');
    inp.value = spvCtxRadius;
    document.getElementById('spv-radius').style.display = 'flex';
    inp.focus(); inp.select();
};
window.shipPropertyViewerRadiusApply = function () {
    var v = parseFloat(document.getElementById('spv-radius-input').value);
    if (!isNaN(v)) {
        dauntlessEvent('ship-property-viewer/set_radius:'
                       + JSON.stringify({i: spvCtxIndex, value: v}));
    }
    spvHideOverlays();
};
window.shipPropertyViewerRadiusCancel = function () { spvHideOverlays(); };
window.shipPropertyViewerSave = function () {
    document.getElementById('spv-confirm').style.display = 'flex';
    dauntlessEvent('ship-property-viewer/overlay:1');
};
window.shipPropertyViewerConfirmSave = function () {
    dauntlessEvent('ship-property-viewer/save'); spvHideOverlays();
};
window.shipPropertyViewerConfirmCancel = function () { spvHideOverlays(); };
```

In `spvRowHtml`, add `oncontextmenu` and the dirty class, and record the row's
radius into `spvRowRadii` (from the descriptor — pass it through the row payload
if not already present; the row already carries `index`). Since the row payload
does not include radius, capture it from the selected popover instead: simplest —
store `spvRowRadii[row.index]` when present on the row. Add `radius` to each
subsystem row in `_subsystem_rows` (Python) OR read it from the popover. To keep
Task 4 unchanged, add to the row div:

```javascript
    + ' oncontextmenu="return shipPropertyViewerRowMenu(event, ' + row.index + ')"'
```
and add `spv-sys-row--dirty` to the row class when `row.dirty === true`.

In `setShipPropertyViewer`, after the existing button toggles: drive the Save
bar, and render the popover radius row.

```javascript
    var bar = document.getElementById('spv-savebar');
    var n = data.pending_count || 0;
    document.getElementById('spv-savecount').textContent = n;
    if (bar) bar.style.display = n > 0 ? 'block' : 'none';
```

The popover already renders `selected.properties` as key/value rows (radius is
just another property key), so the readout shows radius with no popover change.
Capture the selected subsystem's radius for the modal pre-fill:

```javascript
    if (data.selected && data.selected.properties
        && data.selected.properties.radius !== undefined
        && typeof data.selected_index === 'number') {
        spvRowRadii[data.selected_index] = parseFloat(data.selected.properties.radius);
    }
```

(This pre-fills the modal from the selected subsystem; right-clicking a row that
isn't selected yet still opens the modal — defaulting to 0 — which the user
overwrites. Acceptable for the MVP.)

- [ ] **Step 3: CSS (ship_property_viewer.css)**

Add the context-menu, modal, save-bar, and dirty-row styles (reuse the cp-*
palette):

```css
.spv-ctxmenu {
    position: fixed; background: rgba(10, 10, 16, 0.98);
    border: 1px solid rgba(255, 230, 160, 0.5);
    pointer-events: auto; z-index: 70; min-width: 130px;
}
.spv-ctxmenu__item { padding: 6px 14px; color: #ffd; cursor: pointer; font-size: 13px; }
.spv-ctxmenu__item:hover { background: rgba(255, 214, 90, 0.25); }
.spv-modal-backdrop {
    position: fixed; inset: 0; display: flex; align-items: center;
    justify-content: center; background: rgba(0, 0, 0, 0.45);
    pointer-events: auto; z-index: 75;
}
.spv-modal { background: rgb(20, 22, 28); border: 1px solid rgb(80, 88, 100); min-width: 280px; padding: 0 0 12px; }
.spv-modal__title {
    background: linear-gradient(90deg, rgb(216, 94, 86), rgb(216, 132, 80));
    color: #ffd; padding: 6px 14px; text-transform: uppercase; letter-spacing: 1px; font-size: 13px;
}
.spv-modal__input {
    width: calc(100% - 28px); margin: 12px 14px; padding: 6px 8px;
    background: rgba(0, 0, 0, 0.4); border: 1px solid rgba(255, 230, 160, 0.4);
    color: #ffd; font-family: inherit; font-size: 14px;
}
.spv-modal__body { color: #cdd3dc; padding: 10px 14px; font-size: 13px; }
.spv-modal__row { display: flex; justify-content: flex-end; gap: 8px; padding: 0 14px; }
.spv-modal__btn {
    background: rgba(0, 0, 0, 0.35); border: 1px solid rgba(255, 230, 160, 0.4);
    color: #ffd; padding: 5px 14px; cursor: pointer; font-family: inherit;
}
.spv-modal__btn--primary { background: rgba(255, 214, 90, 0.85); color: rgb(40, 24, 8); }
.spv-savebar { position: fixed; left: 50%; bottom: 12px; transform: translateX(-50%); pointer-events: auto; z-index: 65; }
.spv-savebar__btn {
    background: rgba(255, 214, 90, 0.9); border: 1px solid rgba(255, 240, 180, 0.9);
    color: rgb(40, 24, 8); padding: 6px 16px; cursor: pointer; font-family: inherit; font-size: 13px;
}
.spv-sys-row--dirty { box-shadow: inset 3px 0 0 rgb(255, 200, 60); }
```

- [ ] **Step 4: Build + gate + live check**

```bash
cmake --build build -j            # CEF assets are runtime-loaded; no shader reconfigure
scripts/check_tests.sh
```
Expected: gate green (only the 7 baselined FrameTests may fail).

Live-verify under `--developer`: open the Ship Property Viewer, select Center
Impulse (readout shows `radius 0.25`), right-click the row → **Set Radius…** →
enter `0.5` → **Apply** (row shows dirty accent, readout shows 0.5, Save bar shows
"Save changes (1)") → **Save changes** → confirm → open
`engine/appc/hardpoint_overrides.py` and confirm `_galaxy`'s `Center Impulse`
block now has `p.SetRadius(0.5)` → reload the mission and confirm the radius
persists.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/css/ship_property_viewer.css
git commit -m "feat(spv): right-click Set Radius menu, modal, and staged Save UI"
```

---

## Self-Review

**Spec coverage:**
- Machine-owned expanded file structure → Task 2 (conversion) + Task 1 (emit format).
- Execute-to-model writer → Task 1.
- Convert all ships, behavior-preserved, canonical fixed point → Task 2.
- Routing seam (leaf resolver, file target, resolver) → Task 3.
- Right-click menu + Set Radius modal + staged Save/confirm → Task 5 (UI) + Task 4 (dispatch).
- Radius in readout → Task 4 (Step 1) + Task 5 (popover already renders properties).
- Staged, no auto-write, no live mutation → Task 4 (`set_radius` records pending only; `save` persists).
- Overlay-open suppresses orbit → Task 4 (`_overlay_open`) + Task 5 (`overlay:` events).
- Crash-safe atomic write + `ast.parse` guard → Task 1 (`emit` parses) + Task 3 (`os.replace`).
- Load-time application unchanged → Task 2 keeps `apply`/`OVERRIDES`.

**Placeholder scan:** none — every step has concrete code or exact commands.

**Type consistency:** `read_models`/`set_setter`/`emit` signatures are defined in
Task 1 and consumed identically in Task 2 (`emit(read_models(...))`) and Task 3
(`set_setter` in a loop then `emit`). `edits` is `list[(subsystem, setter, args)]`
produced in Task 4 (`(name, "SetRadius", (v,))`) and consumed in Task 3
(`for subsystem, setter, args in edits`). Payload keys `pending_count`, per-row
`dirty`, and `properties.radius` are produced in Task 4 and consumed in Task 5.

**Out-of-scope confirmed absent:** no glow-edit UI, no 3D radius viz, no mod
target — only the seam and the general writer that will carry them later.
