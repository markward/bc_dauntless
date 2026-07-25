> **SUPERSEDED (2026-07-25)** by `2026-07-25-spv-hardpoint-value-override-editing.md`.
> The rename MVP + managed-block writer were abandoned: the override files are
> engine-generated (not hand-authored), so the file is restructured into a
> machine-owned expanded form and the MVP value is `SetRadius`, not rename.
> Committed Tasks 1–2 (`18a6a820`, `c1d3cf19`) are replaced by the new plan.

# SPV Subsystem Rename + Staged Hardpoint-Override Editing — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a right-click **Rename** action to the Ship Property Viewer's subsystem list whose edits are staged (live preview) and persisted to `engine/appc/hardpoint_overrides.py` only on an explicit Save, through a routing seam ready for modded ships.

**Architecture:** A pure text writer rewrites a delimited "managed-overrides" block inside each `_<leaf>` function in `hardpoint_overrides.py`. A routing module maps a live ship → its override target (game file today; mods later). The SPV panel stages renames in Python (live `SetName` + pending map) and, on Save, hands the pending changes to the routed target. CEF renders the context menu, rename modal, and Save/confirm UI.

**Tech Stack:** Python 3 (engine + pytest), C++/pybind11 host bindings (no change here), CEF (HTML/CSS/JS overlay).

## Global Constraints

- **Spec:** `docs/superpowers/specs/2026-07-24-spv-subsystem-rename-and-override-editing-design.md`.
- **Dev-only:** the SPV is constructed only under `--developer`; production render/logic must stay byte-identical. No new behavior may run without the panel open.
- **Shared checkout:** stage commits with **explicit pathspecs** only. Never `git add -A`, never destructive git. See CLAUDE.md.
- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs `tests/known_failures.txt`). Must stay green (only the 7 baselined headless-GL FrameTests may fail).
- **No source corruption:** the writer must validate its output parses (`ast.parse`) and write atomically (`os.replace`); a malformed edit aborts without touching the file.
- **Units/naming:** follow existing conventions (`engine/units.py`, column-vector rotations) — not exercised here but do not regress.

---

## File Structure

**New files:**
- `engine/appc/hardpoint_override_writer.py` — pure functions to parse/render the managed block and splice renames into module text. No I/O.
- `engine/appc/override_routing.py` — `hardpoint_leaf_for_ship`, `HardpointOverridesFileTarget` (does the file I/O around the writer), `resolve_override_target`.
- `tests/unit/test_hardpoint_override_writer.py`
- `tests/unit/test_override_routing.py`

**Modified files:**
- `engine/ui/ship_property_viewer_panel.py` — staging state, `rename`/`save`/`overlay_open` dispatch, payload fields, input suppression while a modal is open.
- `tests/ui/test_ship_property_viewer_panel.py` — staging/save/dirty tests.
- `native/assets/ui-cef/index.html` — context-menu container, rename modal, save bar.
- `native/assets/ui-cef/js/ship_property_viewer.js` — right-click menu, modal, save/confirm, dirty markers, payload consumption.
- `native/assets/ui-cef/css/ship_property_viewer.css` — styles for the above.

---

## Task 1: Managed-block parse + render (pure)

**Files:**
- Create: `engine/appc/hardpoint_override_writer.py`
- Test: `tests/unit/test_hardpoint_override_writer.py`

**Interfaces:**
- Produces:
  - `BLOCK_START: str`, `BLOCK_END: str` (the exact marker lines, 4-space indented).
  - `render_managed_block(mapping: "collections.OrderedDict[str, str]") -> str` — renders the delimited block; `mapping` is original-stock-name → current-name.
  - `parse_managed_block(text: str) -> "collections.OrderedDict[str, str]"` — inverse; scans any text for the block and returns original → current.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_hardpoint_override_writer.py
from collections import OrderedDict
import engine.appc.hardpoint_override_writer as w


def test_render_then_parse_round_trips():
    m = OrderedDict([("Port Impulse", "Left Impulse"),
                     ("Star Impulse", "Right Impulse")])
    block = w.render_managed_block(m)
    # Delimited and indented as a function body.
    assert block.startswith(w.BLOCK_START)
    assert block.rstrip().endswith(w.BLOCK_END)
    assert '    p = find("Port Impulse")' in block
    assert '        p.SetName("Left Impulse")' in block
    # Wrapped in unrelated indented lines, parse recovers exactly the mapping.
    wrapped = '    # glow above\n' + block + '\n    # more below\n'
    assert w.parse_managed_block(wrapped) == m


def test_names_with_quotes_are_escaped_and_recovered():
    m = OrderedDict([('A "special" name', 'B\\C')])
    block = w.render_managed_block(m)
    assert w.parse_managed_block(block) == m
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q`
Expected: FAIL (module `hardpoint_override_writer` does not exist).

- [ ] **Step 3: Write minimal implementation**

```python
# engine/appc/hardpoint_override_writer.py
"""Pure text tooling to maintain a delimited 'managed-overrides' block inside
each _<leaf>(find) function in engine/appc/hardpoint_overrides.py.

The block is regenerated wholesale from an original-stock-name -> current-name
mapping, so edits are idempotent and re-nameable. Only names are supported
today; the block's shape (find(original) then guarded setter calls) is chosen so
future glow/light setters can join each subsystem's group.
"""
from __future__ import annotations

import json
import re
from collections import OrderedDict

BLOCK_START = "    # >>> dauntless-overrides (managed) >>>"
BLOCK_END = "    # <<< dauntless-overrides <<<"


def render_managed_block(mapping: "OrderedDict[str, str]") -> str:
    lines = [BLOCK_START]
    for original, current in mapping.items():
        lines.append("    p = find(%s)" % json.dumps(original))
        lines.append("    if p is not None:")
        lines.append("        p.SetName(%s)" % json.dumps(current))
    lines.append(BLOCK_END)
    return "\n".join(lines)


_FIND_RE = re.compile(r'p = find\((".*")\)\s*$')
_SETNAME_RE = re.compile(r'p\.SetName\((".*")\)\s*$')


def parse_managed_block(text: str) -> "OrderedDict[str, str]":
    mapping: "OrderedDict[str, str]" = OrderedDict()
    in_block = False
    pending = None
    for line in text.splitlines():
        stripped = line.strip()
        if stripped == BLOCK_START.strip():
            in_block = True
            continue
        if stripped == BLOCK_END.strip():
            in_block = False
            continue
        if not in_block:
            continue
        mf = _FIND_RE.match(stripped)
        if mf:
            pending = json.loads(mf.group(1))
            continue
        ms = _SETNAME_RE.match(stripped)
        if ms and pending is not None:
            mapping[pending] = json.loads(ms.group(1))
            pending = None
    return mapping
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_override_writer.py tests/unit/test_hardpoint_override_writer.py
git commit -m "feat(overrides): managed-block render/parse for hardpoint renames"
```

---

## Task 2: Splice renames into module text

**Files:**
- Modify: `engine/appc/hardpoint_override_writer.py`
- Test: `tests/unit/test_hardpoint_override_writer.py`

**Interfaces:**
- Consumes: `render_managed_block`, `parse_managed_block`, `BLOCK_START`, `BLOCK_END` (Task 1).
- Produces:
  - `apply_renames(module_text: str, leaf: str, renames: "list[tuple[str, str]]") -> str`
    — `renames` is a list of `(loaded_name, new_name)`. Resolves each `loaded_name`
    to its original stock name via the leaf's existing managed block, updates the
    mapping (dropping entries where `new_name == original`), regenerates the block,
    and splices it into `_<leaf>(find)` (creating the function and its `OVERRIDES`
    entry if absent). Raises `ValueError` if the result does not `ast.parse`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/unit/test_hardpoint_override_writer.py
import ast
import pytest

_BASE = '''\
def apply(leaf):
    pass


def _galaxy(find):
    p = find("Sensor Array")
    if p is not None:
        p.SetGlowRegionRadius(0, 0.28)


OVERRIDES = {
    "galaxy": _galaxy,
}
'''


def _get_overrides(module_text):
    ns = {}
    exec(compile(module_text, "<test>", "exec"), ns)  # noqa: S102
    return ns


def test_rename_extends_existing_function_and_preserves_hand_code():
    out = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    # Hand-authored glow line untouched.
    assert 'p.SetGlowRegionRadius(0, 0.28)' in out
    # Managed block present with the rename.
    assert w.parse_managed_block(out) == {"Port Impulse": "Left Impulse"}
    # Still valid Python.
    ast.parse(out)


def test_re_rename_updates_same_entry_keyed_by_original():
    once = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    # The loaded name is now "Left Impulse"; renaming again must update, not add.
    twice = w.apply_renames(once, "galaxy", [("Left Impulse", "Backup Impulse")])
    assert w.parse_managed_block(twice) == {"Port Impulse": "Backup Impulse"}


def test_second_subsystem_adds_a_group():
    once = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    twice = w.apply_renames(once, "galaxy", [("Star Impulse", "Right Impulse")])
    assert w.parse_managed_block(twice) == {
        "Port Impulse": "Left Impulse",
        "Star Impulse": "Right Impulse",
    }


def test_rename_back_to_original_removes_entry():
    once = w.apply_renames(_BASE, "galaxy", [("Port Impulse", "Left Impulse")])
    back = w.apply_renames(once, "galaxy", [("Left Impulse", "Port Impulse")])
    assert w.parse_managed_block(back) == {}


def test_creates_function_and_overrides_entry_when_absent():
    out = w.apply_renames(_BASE, "akira", [("Bridge", "Command Deck")])
    ns = _get_overrides(out)
    assert "akira" in ns["OVERRIDES"]
    assert w.parse_managed_block(out) == {"Bridge": "Command Deck"}
    ast.parse(out)


def test_malformed_result_raises_without_returning_text():
    with pytest.raises(ValueError):
        w.apply_renames("this is ( not python", "galaxy",
                        [("A", "B")])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q`
Expected: FAIL (`apply_renames` not defined).

- [ ] **Step 3: Write the implementation**

```python
# append to engine/appc/hardpoint_override_writer.py
import ast as _ast


def _function_span(text: str, leaf: str):
    """Return (start_idx, end_idx) of the `def _<leaf>(find):` block in text,
    or None. end_idx is the index just past the function body (at the next
    top-level `def ` / `OVERRIDES` / EOF)."""
    header = "def _%s(find):" % leaf
    start = text.find("\n" + header)
    if start < 0:
        if text.startswith(header):
            start = 0
        else:
            return None
    else:
        start += 1  # skip the leading newline
    # Body ends at the next top-level statement (column-0 def/OVERRIDES) or EOF.
    rest = text[start + len(header):]
    m = re.search(r'\n(?=def |OVERRIDES\b)', rest)
    end = len(text) if m is None else start + len(header) + m.start() + 1
    return (start, end)


def _resolve_original(existing: "OrderedDict[str, str]", loaded_name: str) -> str:
    """The row shows the loaded name (a current override target or a stock
    name). Map it back to the original stock key."""
    for original, current in existing.items():
        if current == loaded_name:
            return original
    return loaded_name


def apply_renames(module_text: str, leaf: str,
                  renames: "list[tuple[str, str]]") -> str:
    span = _function_span(module_text, leaf)
    if span is None:
        module_text = _create_function(module_text, leaf)
        span = _function_span(module_text, leaf)
    start, end = span
    body = module_text[start:end]

    mapping = parse_managed_block(body)
    for loaded_name, new_name in renames:
        original = _resolve_original(mapping, loaded_name)
        if new_name == original:
            mapping.pop(original, None)
        else:
            mapping[original] = new_name

    # Strip any existing managed block from the body, then append the fresh one
    # at the end of the function (after hand-authored glow lookups).
    body_wo = _strip_managed_block(body)
    body_wo = body_wo.rstrip("\n")
    if mapping:
        new_body = body_wo + "\n" + render_managed_block(mapping) + "\n"
    else:
        new_body = body_wo + "\n"

    out = module_text[:start] + new_body + module_text[end:]
    try:
        _ast.parse(out)
    except SyntaxError as e:
        raise ValueError("hardpoint_overrides rewrite would not parse: %s" % e)
    return out


def _strip_managed_block(body: str) -> str:
    lines = body.splitlines(keepends=True)
    out, skipping = [], False
    for line in lines:
        s = line.strip()
        if s == BLOCK_START.strip():
            skipping = True
            continue
        if s == BLOCK_END.strip():
            skipping = False
            continue
        if not skipping:
            out.append(line)
    return "".join(out)


def _create_function(text: str, leaf: str) -> str:
    """Insert an empty `def _<leaf>(find):` before `OVERRIDES = {` and register
    it in the dict."""
    fn = "\ndef _%s(find):\n    pass\n\n" % leaf
    anchor = text.find("\nOVERRIDES = {")
    if anchor < 0:
        # No dict yet: append both.
        return text.rstrip("\n") + "\n" + fn + 'OVERRIDES = {\n    "%s": _%s,\n}\n' % (leaf, leaf)
    text = text[:anchor] + "\n" + fn + text[anchor + 1:]
    # Register in the dict literal (insert before its closing brace).
    entry = '    "%s": _%s,\n' % (leaf, leaf)
    close = text.find("\n}", text.find("OVERRIDES = {"))
    return text[:close + 1] + entry + text[close + 1:]
```

Note: `_create_function` inserts a `pass` body; `apply_renames` then strips nothing and appends the managed block, leaving `pass` followed by the block (valid). Keep the `pass` — a function with only a managed block that later empties (all renames reverted) must still be syntactically valid.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_hardpoint_override_writer.py -q`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/hardpoint_override_writer.py tests/unit/test_hardpoint_override_writer.py
git commit -m "feat(overrides): splice renames into _<leaf> managed block"
```

---

## Task 3: Routing seam + file target

**Files:**
- Create: `engine/appc/override_routing.py`
- Test: `tests/unit/test_override_routing.py`

**Interfaces:**
- Consumes: `apply_renames` (Task 2).
- Produces:
  - `hardpoint_leaf_for_ship(ship) -> "str | None"` — `ship.GetScript()` → import → `GetShipStats()["HardpointFile"]`; None-safe.
  - `class HardpointOverridesFileTarget` with `path: str` and `write(leaf: str, renames: "list[tuple[str, str]]") -> None` — reads `path`, calls `apply_renames`, writes atomically (`os.replace`).
  - `resolve_override_target(ship) -> HardpointOverridesFileTarget` — returns the engine-owned target for all (game) ships today. A `# future: modded ships` branch documents the seam.

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_override_routing.py
import engine.appc.override_routing as r
import engine.appc.hardpoint_override_writer as w


class _FakeStatsMod:
    @staticmethod
    def GetShipStats():
        return {"HardpointFile": "galaxy"}


class _FakeShip:
    def __init__(self, script):
        self._s = script

    def GetScript(self):
        return self._s


def test_leaf_for_ship_reads_hardpointfile(monkeypatch):
    monkeypatch.setattr(r.importlib, "import_module",
                        lambda name: _FakeStatsMod)
    assert r.hardpoint_leaf_for_ship(_FakeShip("ships.Galaxy")) == "galaxy"


def test_leaf_for_ship_none_safe():
    assert r.hardpoint_leaf_for_ship(_FakeShip("")) is None
    assert r.hardpoint_leaf_for_ship(object()) is None


def test_file_target_writes_rename(tmp_path):
    f = tmp_path / "hardpoint_overrides.py"
    f.write_text('def apply(leaf):\n    pass\n\n\nOVERRIDES = {\n}\n')
    target = r.HardpointOverridesFileTarget(str(f))
    target.write("galaxy", [("Port Impulse", "Left Impulse")])
    text = f.read_text()
    assert w.parse_managed_block(text) == {"Port Impulse": "Left Impulse"}


def test_resolve_returns_file_target(monkeypatch):
    monkeypatch.setattr(r.importlib, "import_module",
                        lambda name: _FakeStatsMod)
    t = r.resolve_override_target(_FakeShip("ships.Galaxy"))
    assert isinstance(t, r.HardpointOverridesFileTarget)
```

- [ ] **Step 2: Run tests to verify they fail**

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

_HARDPOINT_OVERRIDES_PATH = os.path.join(
    os.path.dirname(__file__), "hardpoint_overrides.py")


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
    def __init__(self, path: str = _HARDPOINT_OVERRIDES_PATH) -> None:
        self.path = path

    def write(self, leaf: str, renames: "list[tuple[str, str]]") -> None:
        with open(self.path, "r", encoding="utf-8") as fh:
            text = fh.read()
        new_text = _writer.apply_renames(text, leaf, renames)  # raises on bad
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(new_text)
        os.replace(tmp, self.path)


def resolve_override_target(ship) -> HardpointOverridesFileTarget:
    # future: if the ship comes from a modded directory, return a target that
    # writes into that mod's files instead. For now, all ships -> game file.
    return HardpointOverridesFileTarget()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_override_routing.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/override_routing.py tests/unit/test_override_routing.py
git commit -m "feat(overrides): ship->override-target routing seam + file target"
```

---

## Task 4: Panel staging, dispatch, and payload

**Files:**
- Modify: `engine/ui/ship_property_viewer_panel.py`
- Test: `tests/ui/test_ship_property_viewer_panel.py`

**Interfaces:**
- Consumes: `resolve_override_target`, `hardpoint_leaf_for_ship` (Task 3); the panel's existing `render_payload`, `dispatch_event`, `open`/`close`, `_descriptors`, `handle_input`.
- Produces (new panel behavior):
  - Staging state `self._pending: "dict[int, str]"` (descriptor index → new name) and
    `self._baseline: "dict[int, str]"` (index → loaded name captured at first stage).
  - `self._overlay_open: bool` — true while a CEF context menu or modal is open;
    `handle_input` suppresses orbit/pick while true.
  - `dispatch_event` handles: `rename:<json>` (`{"i": int, "name": str}`),
    `save`, `overlay:<0|1>`.
  - `render_payload` adds `pending_count: int` and, per subsystem row, `dirty: bool`.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/ui/test_ship_property_viewer_panel.py
import json as _json


class _RenameShip:
    def GetScript(self):
        return "ships.Galaxy"


def _descriptor(name, idx):
    return {"name": name, "icon_id": 0, "world_pos": (0, 0, 0),
            "state": "healthy", "targetable": True, "condition_pct": 100,
            "parent_index": None, "properties": {"name": name}}


def test_rename_stages_live_and_marks_dirty(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    # A live subsystem whose SetName we can observe via the descriptor name.
    renamed = {}

    class _Sub:
        def __init__(self, n): self._n = n
        def GetName(self): return self._n
        def SetName(self, n): self._n = n; renamed["last"] = n

    subs = [_Sub("Port Impulse")]
    # build_descriptors reads the live sub name each call.
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_descriptor(s.GetName(), i)
                                      for i, s in enumerate(subs)])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RenameShip())
    # Give the panel access to the live sub objects for SetName.
    p._live_subsystems = lambda: subs   # test seam; see impl note
    p.open()
    ok = p.dispatch_event("rename:" + _json.dumps({"i": 0, "name": "Left Impulse"}))
    assert ok is True
    assert renamed["last"] == "Left Impulse"        # applied live
    data = _payload_data(p.render_payload())
    assert data["pending_count"] == 1
    assert data["subsystems"][0]["dirty"] is True
    assert data["subsystems"][0]["name"] == "Left Impulse"


def test_save_routes_baseline_and_new_then_clears(monkeypatch):
    import engine.ui.ship_property_viewer_panel as mod
    calls = []

    class _Target:
        def write(self, leaf, renames): calls.append((leaf, renames))

    monkeypatch.setattr(mod, "resolve_override_target", lambda ship: _Target())
    monkeypatch.setattr(mod, "hardpoint_leaf_for_ship", lambda ship: "galaxy")

    class _Sub:
        def __init__(self, n): self._n = n
        def GetName(self): return self._n
        def SetName(self, n): self._n = n

    subs = [_Sub("Port Impulse")]
    monkeypatch.setattr(mod, "build_descriptors",
                        lambda ship: [_descriptor(s.GetName(), i)
                                      for i, s in enumerate(subs)])
    p = ShipPropertyViewerPanel(ship_getter=lambda: _RenameShip())
    p._live_subsystems = lambda: subs
    p.open()
    p.dispatch_event("rename:" + _json.dumps({"i": 0, "name": "A"}))
    p.dispatch_event("rename:" + _json.dumps({"i": 0, "name": "B"}))  # re-rename
    p.dispatch_event("save")
    # Baseline is the loaded name at first stage ("Port Impulse"); target "B".
    assert calls == [("galaxy", [("Port Impulse", "B")])]
    assert _payload_data(p.render_payload())["pending_count"] == 0


def test_overlay_open_suppresses_orbit(monkeypatch):
    p = _open_panel_for_input()
    p.dispatch_event("overlay:1")
    host = _FakeHost()
    yaw0 = p.camera.yaw
    host._cursor = (600.0, 300.0); host._down = True
    p.handle_input(host)
    host._cursor = (650.0, 350.0)
    p.handle_input(host)
    assert p.camera.yaw == yaw0        # no orbit while an overlay is open
```

Implementation note for the `_live_subsystems` seam: `build_descriptors` already
iterates the live ship's subsystems but returns dicts. Add a small
`self._live_subsystems()` helper on the panel that returns the list of live
subsystem objects in the **same order** as `_descriptors`, so a descriptor index
maps to a live object for `SetName`. In tests it is monkeypatched; in production
it re-runs the panel's own subsystem enumeration.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: FAIL (`rename`/`save`/`overlay` unhandled; no `dirty`/`pending_count`).

- [ ] **Step 3: Write the implementation**

In `engine/ui/ship_property_viewer_panel.py`:

Add imports near the top:

```python
from engine.appc.override_routing import (
    resolve_override_target, hardpoint_leaf_for_ship,
)
```

In `__init__`, alongside the other toggles:

```python
        # Staged renames: descriptor index -> new name (self._pending) and the
        # loaded name captured at first stage (self._baseline), so Save persists
        # (original_stock_name, final_name). Reset every open/close.
        self._pending: dict = {}
        self._baseline: dict = {}
        # True while a CEF context menu / rename modal is open: handle_input
        # suppresses orbit + pin-pick so clicks on that chrome don't reach 3D.
        self._overlay_open = False
```

Reset all three in both `open()` and `close()` (add next to the existing
`self._expanded_groups = set()` lines):

```python
        self._pending = {}
        self._baseline = {}
        self._overlay_open = False
```

Add the live-subsystem seam (place near `descriptors()`):

```python
    def _live_subsystems(self):
        """Live subsystem objects in the same order as self._descriptors, so a
        descriptor index maps to the object whose SetName we call. Mirrors
        build_descriptors' enumeration."""
        ship = self._ship_getter()
        if ship is None:
            return []
        from engine.ui.ship_property_viewer import _iter_subsystems
        out = []
        for sub in _iter_subsystems(ship):
            local = sub.GetPosition() if hasattr(sub, "GetPosition") else None
            if local is None:
                continue
            out.append(sub)
        # Object emitters have no SetName target; pad so indices past the
        # damageable subsystems resolve to None.
        while len(out) < len(self._descriptors):
            out.append(None)
        return out
```

In `handle_input`, guard at the top (after `if self.camera is None: return`):

```python
        if self._overlay_open:
            return
```

In `render_payload`, add `pending_count` to the payload and include it in the
snapshot so a stage/save re-pushes:

```python
        snapshot = (self._visible, len(self._descriptors), self.selected_index,
                    self.show_glow_regions, self.show_weapon_arcs,
                    self.show_hull_texture,
                    tuple(sorted(self._pending.items())),
                    tuple(sorted(self._expanded_groups)))
        ...
        payload = {
            ...
            "show_hull": self.show_hull_texture,
            "pending_count": len(self._pending),
            "subsystems": self._subsystem_rows(),
        }
```

In `_subsystem_rows` (where each row dict is built), add the dirty flag keyed by
descriptor index:

```python
            row["dirty"] = (index in self._pending)
```

(Use whatever the row's descriptor index variable is called in that method; it
is the same index used for `select_pin`.)

Add the dispatch handlers in `dispatch_event` (before the final `return False`):

```python
        if action.startswith("overlay:"):
            self._overlay_open = action.endswith("1")
            return True
        if action.startswith("rename:"):
            try:
                arg = json.loads(action.split(":", 1)[1])
                idx = int(arg["i"]); new_name = str(arg["name"])
            except (ValueError, KeyError, TypeError):
                return False
            if not (0 <= idx < len(self._descriptors)):
                return False
            live = self._live_subsystems()
            sub = live[idx] if idx < len(live) else None
            if sub is None:
                return False
            loaded = self._baseline.get(idx, self._descriptors[idx]["name"])
            self._baseline[idx] = loaded
            if new_name == loaded:
                self._pending.pop(idx, None)      # reverted to loaded
                self._baseline.pop(idx, None)
            else:
                self._pending[idx] = new_name
            sub.SetName(new_name)                  # live preview
            # Re-read descriptors so the list shows the new name.
            self._descriptors = build_descriptors(self._ship_getter())
            self._last_pushed = None
            return True
        if action == "save":
            if not self._pending:
                return True
            ship = self._ship_getter()
            leaf = hardpoint_leaf_for_ship(ship)
            if leaf:
                renames = [(self._baseline[i], self._pending[i])
                           for i in sorted(self._pending)]
                try:
                    resolve_override_target(ship).write(leaf, renames)
                except Exception as e:
                    from engine import dev_mode
                    dev_mode.log_swallowed("spv rename save", e)
            self._pending = {}
            self._baseline = {}
            self._last_pushed = None
            return True
```

Note: rebuilding `self._descriptors` after a rename keeps descriptor indices
stable only if the enumeration order is stable (it is — subsystem order does not
change on rename). The `dirty` flags therefore stay aligned.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/ui/test_ship_property_viewer_panel.py -q`
Expected: PASS (new + existing tests).

- [ ] **Step 5: Commit**

```bash
git add engine/ui/ship_property_viewer_panel.py tests/ui/test_ship_property_viewer_panel.py
git commit -m "feat(spv): stage subsystem renames + route Save to hardpoint overrides"
```

---

## Task 5: CEF context menu, rename modal, and Save bar

**Files:**
- Modify: `native/assets/ui-cef/index.html`
- Modify: `native/assets/ui-cef/js/ship_property_viewer.js`
- Modify: `native/assets/ui-cef/css/ship_property_viewer.css`

**Interfaces:**
- Consumes: `setShipPropertyViewer(data)` payload now carrying `data.pending_count`
  and `data.subsystems[i].dirty`; `dauntlessEvent('ship-property-viewer/<action>')`
  for `rename:<json>`, `save`, `overlay:1`/`overlay:0`.
- Produces: no Python interface; verified via the gate build + manual `--developer`
  check.

This task is UI wiring with no unit tests (the SPV JS is not unit-tested in this
repo — consistent with existing `ship_property_viewer.js`). Verification is the
gate build plus a live `--developer` check.

- [ ] **Step 1: Add DOM containers (index.html)**

Inside `#spv-root`, after `#spv-popover`, add a context menu, a rename modal, and
a save bar:

```html
      <!-- Right-click context menu for subsystem rows (positioned in JS). -->
      <div id="spv-ctxmenu" class="spv-ctxmenu" style="display:none;">
        <div class="spv-ctxmenu__item" onclick="shipPropertyViewerCtxRename()">Rename…</div>
      </div>
      <!-- Rename modal (centred). -->
      <div id="spv-rename" class="spv-modal-backdrop" style="display:none;">
        <div class="spv-modal">
          <div class="spv-modal__title">Rename subsystem</div>
          <input id="spv-rename-input" class="spv-modal__input" type="text" />
          <div class="spv-modal__row">
            <button class="spv-modal__btn" onclick="shipPropertyViewerRenameCancel()">Cancel</button>
            <button class="spv-modal__btn spv-modal__btn--primary" onclick="shipPropertyViewerRenameApply()">Apply</button>
          </div>
        </div>
      </div>
      <!-- Save bar (shown when edits are pending). -->
      <div id="spv-savebar" class="spv-savebar" style="display:none;">
        <button class="spv-savebar__btn" onclick="shipPropertyViewerSave()">
          Save changes (<span id="spv-savecount">0</span>)
        </button>
      </div>
      <!-- Save confirmation. -->
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

- [ ] **Step 2: Wire JS (ship_property_viewer.js)**

Add right-click handling to `spvRowHtml` (add `oncontextmenu`), and the menu /
modal / save handlers. Track the right-clicked row index and the current
subsystems list in module-scope vars. Key points:
- `oncontextmenu` calls `event.preventDefault()` (suppress the browser menu),
  records `spvCtxIndex`/`spvCtxName`, positions `#spv-ctxmenu` at the cursor,
  shows it, and fires `overlay:1`.
- Rename opens `#spv-rename`, pre-fills the input with `spvCtxName`, focuses it.
- Apply fires `rename:{"i":spvCtxIndex,"name":<input>}`, closes the modal, fires
  `overlay:0`.
- Cancel / click-away / ESC close menu+modal and fire `overlay:0`.
- In `setShipPropertyViewer`, toggle `#spv-savebar` on `data.pending_count > 0`,
  set `#spv-savecount`, and add a `spv-sys-row--dirty` class when
  `row.dirty === true`.
- Save opens `#spv-confirm` listing pending rows; Confirm fires `save` and closes.

```javascript
// module-scope
var spvCtxIndex = null, spvCtxName = "";

function spvHideOverlays() {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    document.getElementById('spv-rename').style.display = 'none';
    document.getElementById('spv-confirm').style.display = 'none';
    dauntlessEvent('ship-property-viewer/overlay:0');
}
window.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') spvHideOverlays();
});
document.addEventListener('click', function (e) {
    // Click outside the context menu closes it (menu items stopPropagation).
    var menu = document.getElementById('spv-ctxmenu');
    if (menu.style.display !== 'none' && !menu.contains(e.target)) {
        menu.style.display = 'none';
        // don't fire overlay:0 here if a modal is still open
        if (document.getElementById('spv-rename').style.display === 'none'
            && document.getElementById('spv-confirm').style.display === 'none') {
            dauntlessEvent('ship-property-viewer/overlay:0');
        }
    }
});

window.shipPropertyViewerRowMenu = function (event, index, name) {
    event.preventDefault();
    event.stopPropagation();
    spvCtxIndex = index; spvCtxName = name;
    var menu = document.getElementById('spv-ctxmenu');
    menu.style.left = event.clientX + 'px';
    menu.style.top = event.clientY + 'px';
    menu.style.display = 'block';
    dauntlessEvent('ship-property-viewer/overlay:1');
    return false;
};
window.shipPropertyViewerCtxRename = function () {
    document.getElementById('spv-ctxmenu').style.display = 'none';
    var inp = document.getElementById('spv-rename-input');
    inp.value = spvCtxName;
    document.getElementById('spv-rename').style.display = 'flex';
    inp.focus(); inp.select();
};
window.shipPropertyViewerRenameApply = function () {
    var name = document.getElementById('spv-rename-input').value;
    if (name && name !== spvCtxName) {
        dauntlessEvent('ship-property-viewer/rename:'
                       + JSON.stringify({i: spvCtxIndex, name: name}));
    }
    spvHideOverlays();
};
window.shipPropertyViewerRenameCancel = function () { spvHideOverlays(); };
window.shipPropertyViewerSave = function () {
    document.getElementById('spv-confirm').style.display = 'flex';
    dauntlessEvent('ship-property-viewer/overlay:1');
};
window.shipPropertyViewerConfirmSave = function () {
    dauntlessEvent('ship-property-viewer/save');
    spvHideOverlays();
};
window.shipPropertyViewerConfirmCancel = function () { spvHideOverlays(); };
```

In `spvRowHtml`, add to the row div:
```javascript
    + ' oncontextmenu="return shipPropertyViewerRowMenu(event, ' + row.index
    + ', &quot;' + escapeHtmlSPV(row.name || '') + '&quot;)"'
```
and add `spv-sys-row--dirty` to the row class when `row.dirty === true`.

In `setShipPropertyViewer`, after the button toggles:
```javascript
    var bar = document.getElementById('spv-savebar');
    var n = data.pending_count || 0;
    document.getElementById('spv-savecount').textContent = n;
    if (bar) bar.style.display = n > 0 ? 'block' : 'none';
```

- [ ] **Step 3: Style (ship_property_viewer.css)**

Add styles reusing the panel palette: `.spv-ctxmenu` (absolute, dark bg, gold
border, `pointer-events:auto`, `z-index` above the list), `.spv-ctxmenu__item`
(hover highlight), `.spv-modal-backdrop` (fixed, full-viewport, centred flex,
`pointer-events:auto`), `.spv-modal` (dark card, cp-* palette), `.spv-modal__input`,
`.spv-modal__btn` / `--primary`, `.spv-savebar` (fixed bottom-centre, above the
tools cluster), `.spv-sys-row--dirty` (a subtle left accent / asterisk so changed
rows read as unsaved).

```css
.spv-ctxmenu {
    position: fixed;
    background: rgba(10, 10, 16, 0.98);
    border: 1px solid rgba(255, 230, 160, 0.5);
    pointer-events: auto;
    z-index: 70;
    min-width: 120px;
}
.spv-ctxmenu__item {
    padding: 6px 14px; color: #ffd; cursor: pointer; font-size: 13px;
}
.spv-ctxmenu__item:hover { background: rgba(255, 214, 90, 0.25); }

.spv-modal-backdrop {
    position: fixed; inset: 0; display: flex;
    align-items: center; justify-content: center;
    background: rgba(0, 0, 0, 0.45); pointer-events: auto; z-index: 75;
}
.spv-modal {
    background: rgb(20, 22, 28); border: 1px solid rgb(80, 88, 100);
    min-width: 280px; padding: 0 0 12px;
}
.spv-modal__title {
    background: linear-gradient(90deg, rgb(216, 94, 86), rgb(216, 132, 80));
    color: #ffd; padding: 6px 14px; text-transform: uppercase;
    letter-spacing: 1px; font-size: 13px;
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

.spv-savebar {
    position: fixed; left: 50%; bottom: 12px; transform: translateX(-50%);
    pointer-events: auto; z-index: 65;
}
.spv-savebar__btn {
    background: rgba(255, 214, 90, 0.9); border: 1px solid rgba(255, 240, 180, 0.9);
    color: rgb(40, 24, 8); padding: 6px 16px; cursor: pointer;
    font-family: inherit; font-size: 13px; letter-spacing: 0.04em;
}
.spv-sys-row--dirty { box-shadow: inset 3px 0 0 rgb(255, 200, 60); }
```

- [ ] **Step 4: Build + gate + live check**

```bash
cmake --build build -j            # CEF assets are runtime-loaded; no shader reconfigure needed
scripts/check_tests.sh
```
Expected: gate green (only the 7 baselined FrameTests may fail).

Then live-verify under `--developer`: open the Ship Property Viewer, right-click a
subsystem row → **Rename…** → change the name → **Apply** (row shows the new name +
dirty accent, Save bar shows "Save changes (1)") → **Save changes** → confirm →
inspect `engine/appc/hardpoint_overrides.py` for the managed block, and reload to
confirm the rename persists.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/ship_property_viewer.js native/assets/ui-cef/css/ship_property_viewer.css
git commit -m "feat(spv): right-click Rename menu, modal, and staged Save UI"
```

---

## Self-Review

**Spec coverage:**
- Right-click menu + Rename → Task 5 (UI) + Task 4 (dispatch).
- Live preview via `SetName` → Task 4.
- Staged, no auto-write; explicit Save + confirm → Task 4 (`save`) + Task 5 (confirm modal).
- Routing seam (`resolve_override_target`, leaf key) → Task 3.
- Generalized managed-overrides block writer → Tasks 1–2.
- Load-time application unchanged → no task needed (existing `apply(leaf)` runs the block).
- Crash-safe atomic write + `ast.parse` guard → Task 2 (`ValueError`) + Task 3 (`os.replace`).
- Mouse: overlay-open suppresses orbit/pick → Task 4 (`_overlay_open`) + Task 5 (`overlay:` events).
- Risks (canonical-name coupling, dev-only) → documented in spec; no guard by design.

**Placeholder scan:** none — every step has concrete code or exact commands.

**Type consistency:** `apply_renames(module_text, leaf, renames)` with `renames:
list[tuple[str,str]]` is produced in Task 2 and consumed identically in Task 3
(`target.write` forwards the same list) and Task 4 (builds `(baseline, new)`
tuples). `render_managed_block`/`parse_managed_block` signatures match across
Tasks 1–2. Payload keys `pending_count` and per-row `dirty` are produced in Task
4 and consumed in Task 5.

**Out-of-scope confirmed absent:** no glow/light edit UI, no mod target
implementation — only the seam and generalized block shape.
