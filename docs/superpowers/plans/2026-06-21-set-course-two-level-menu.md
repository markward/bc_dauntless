# Two-Level Set Course Menu — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the `SettingCoursePanel` placeholder with a two-column master-detail menu listing every galaxy system (left) and the selected system's warp points (right), with live-active items bold and warp-point selection UI-only.

**Architecture:** Three data sources reconciled by `system_id_for_set`: all systems from `sector_model.json`; all warp points from a baked catalog folded into the same JSON; bold/active from the live SDK Set Course menu the panel already holds. Built in three phases: engine fix → galaxy helper + catalog → panel + CEF.

**Tech Stack:** Python 3 (engine, baker), pytest, CEF + vanilla JS/HTML/CSS. No new dependencies.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-06-21-set-course-two-level-menu-design.md`.
- Do **not** modify any file under `sdk/Build/scripts/` — SDK is ground truth.
- `STMenu.GetSubmenuW` must become **strict** (return existing-or-`None`). `AddChild` already registers submenus in `_submenus` by label (`engine/appc/characters.py:138-139`), so explicitly-added menus are still found; only auto-vivify-on-miss is removed.
- `App.SetClass_MakeDisplayName(name)` must return a real `str` (never a `_NamedStub`); the baker and the live overlay both use it, so labels align.
- Galaxy-helper extraction is a **pure move with re-export**: `sky_projection.py` re-imports the moved names so `sp.load_sector_model` / `sp.vantage_for_set` and the existing `tests/engine/appc/test_sky_projection_*` keep working unchanged.
- Warp-point catalog is **folded into `engine/appc/sector_model.json`** as a `warp_points` list per system; the sky projection ignores it. Both bakers preserve each other's data.
- Panel name stays `setting-course`. New events: `select-system:<id>`, `select-warp:<id>` (plus existing `cancel`). Active match is by `(system_id, warp_label)`.
- Out of scope: the warp action / navigation; persisting selection across launches.
- Run targeted tests with `uv run pytest <path> -v` (never the unguarded full suite). `host_loop` import check needs `PYTHONPATH=build/python`.

---

## Phase 1 — Engine fix (make the SDK menu populate)

### Task 1: `SetClass_MakeDisplayName`

**Files:**
- Modify: `engine/appc/sets.py` (add function)
- Modify: `App.py` (export it from the `engine.appc.sets` import)
- Test: `tests/unit/test_set_display_name.py`

**Interfaces:**
- Produces: `engine.appc.sets.SetClass_MakeDisplayName(set_name) -> str`, also reachable as `App.SetClass_MakeDisplayName`. `"Vesuvi4" -> "Vesuvi 4"`, `"Albirea" -> "Albirea"`, always `str`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_set_display_name.py`:

```python
"""App.SetClass_MakeDisplayName — readable label for a set/region name."""
import App
from engine.appc.sets import SetClass_MakeDisplayName


def test_trailing_digits_get_a_space():
    assert SetClass_MakeDisplayName("Vesuvi4") == "Vesuvi 4"
    assert SetClass_MakeDisplayName("Starbase12") == "Starbase 12"


def test_no_digits_unchanged():
    assert SetClass_MakeDisplayName("Albirea") == "Albirea"


def test_always_returns_str():
    assert isinstance(SetClass_MakeDisplayName(12345), str)


def test_exposed_on_App_as_real_callable():
    # Not a _NamedStub fallthrough.
    out = App.SetClass_MakeDisplayName("Vesuvi6")
    assert out == "Vesuvi 6"
    assert isinstance(out, str)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_set_display_name.py -v`
Expected: FAIL — `ImportError` (no `SetClass_MakeDisplayName` in `sets`) and the App test returns a `_NamedStub`.

- [ ] **Step 3: Implement**

In `engine/appc/sets.py`, add near the other module-level `SetClass_*` helpers (add `import re` at the top if not already imported):

```python
import re  # at top of file if absent


def SetClass_MakeDisplayName(set_name):
    """App.SetClass_MakeDisplayName — human-readable label for a set/region
    name. Insert a space before a trailing digit run: 'Vesuvi4' -> 'Vesuvi 4'.
    Always a real str (never a _NamedStub), so the baked catalog and the live
    SDK menu produce identical labels for the same set."""
    return re.sub(r"(?<=\D)(\d+)$", r" \1", str(set_name))
```

In `App.py`, add `SetClass_MakeDisplayName` to the existing import (line ~73):

```python
from engine.appc.sets import (
    SetClass, SetManager, SetClass_Create, SetClass_GetNull,
    SetClass_MakeDisplayName,
)
```

(If that import is currently a single line, expand it to include the new name.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_set_display_name.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sets.py App.py tests/unit/test_set_display_name.py
git commit -m "feat(set-course): implement SetClass_MakeDisplayName for region labels"
```

---

### Task 2: `GetSubmenuW` strict — populate warp points

**Files:**
- Modify: `engine/appc/characters.py:160-169` (`GetSubmenuW`)
- Modify: `tests/unit/test_characters.py` (rewrite the auto-vivify pinning test)
- Test: `tests/integration/test_set_course_population.py` (new)

**Interfaces:**
- Consumes: `SetClass_MakeDisplayName` (Task 1) — warp-point labels now render.
- Produces: registering a system builds `Set Course → system → warp-point` subtree in the live `TacticalControlWindow` menu; `GetSubmenuW(absent)` returns `None`.

- [ ] **Step 1: Write the failing integration test**

Create `tests/integration/test_set_course_population.py`:

```python
"""With strict GetSubmenuW, a system registration populates the live SDK Set
Course menu with system -> warp-point children carrying real labels."""
import sys

import App
from engine.appc.windows import TacticalControlWindow
from engine.appc.target_menu import _reset_target_menu_singleton
from engine.core.game import Game, Episode, Mission, _set_current_game
from engine.appc.tg_ui.st_widgets import SortedRegionMenu


def _make_game():
    g = Game(); e = Episode(); m = Mission()
    e.SetCurrentMission(m); g.SetCurrentEpisode(e)
    return g


def _set_course_menu():
    helm = TacticalControlWindow.GetInstance().GetMenuList()[0]
    return next((c for c in helm._children
                 if isinstance(c, SortedRegionMenu)), None)


def test_system_registration_populates_warp_points():
    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    _set_current_game(_make_game())
    sys.modules.pop("Bridge.HelmMenuHandlers", None)
    sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as helm
    helm.CreateMenus()

    import Systems.Vesuvi.Vesuvi as vesuvi
    vesuvi.CreateMenus()

    sc = _set_course_menu()
    assert sc is not None
    vesuvi_node = next((c for c in sc._children
                        if c.GetLabel() == "Vesuvi"), None)
    assert vesuvi_node is not None, "Vesuvi system not under Set Course"
    warp_labels = [w.GetLabel() for w in vesuvi_node._children]
    assert len(warp_labels) >= 3, warp_labels
    # Labels are real strings from SetClass_MakeDisplayName, not stubs.
    for lbl in warp_labels:
        assert isinstance(lbl, str)
        assert "MakeDisplayName" not in lbl
    _set_current_game(None)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/integration/test_set_course_population.py -v`
Expected: FAIL — `Vesuvi` node has 0 children (auto-vivify makes the SDK skip population).

- [ ] **Step 3: Make `GetSubmenuW` strict**

In `engine/appc/characters.py`, replace lines 160-169:

```python
    def GetSubmenuW(self, label) -> "STMenu | None":
        out = self._submenus.get(str(label))
        if out is None:
            # Bridge menus auto-vivify submenus on first lookup so the
            # tree-build patterns in BridgeHandlers don't need to
            # pre-create every node.  Mirrors Appc behaviour.
            out = STMenu(str(label))
            self._submenus[str(label)] = out
            self._children.append(out)
        return out
```

with:

```python
    def GetSubmenuW(self, label) -> "STMenu | None":
        # Strict: return the existing submenu or None, matching real Appc.
        # Bridge menu trees are built by explicit Create + AddChild (which
        # registers the child in _submenus by label, above), not by
        # auto-vivifying on lookup. Systems/Utils.py:67 depends on
        # None-when-absent to run its warp-point population loop.
        return self._submenus.get(str(label))
```

- [ ] **Step 4: Rewrite the pinning unit test**

In `tests/unit/test_characters.py`, replace `test_menu_get_submenu_w_auto_vivifies` (the body that asserts auto-vivify) with strict semantics:

```python
def test_menu_get_submenu_w_is_strict():
    """GetSubmenuW returns the existing submenu or None (real Appc semantics);
    explicitly-added submenus are found, absent ones are not."""
    menu = STTopLevelMenu("Top")
    assert menu.GetSubmenuW("Helm") is None
    helm = STMenu("Helm")
    menu.AddChild(helm)
    assert menu.GetSubmenuW("Helm") is helm
```

- [ ] **Step 5: Run the new tests + full menu-suite regression**

Run: `uv run pytest tests/integration/test_set_course_population.py tests/unit/test_characters.py -v`
Expected: PASS.

Run the menu/bridge regression gate (must all stay green):

```
uv run pytest tests/unit/test_tg_ui_st_widgets.py tests/unit/test_crew_menu_panel.py \
  tests/unit/test_crew_menu_turn.py tests/unit/test_crew_menu_hotkeys.py \
  tests/unit/test_crew_ack.py tests/unit/test_reset_sdk_globals_menus.py \
  tests/unit/test_crew_menu_set_course_override.py tests/unit/test_setting_course_panel.py \
  tests/integration/test_helm_menu_creation.py tests/integration/test_m1basic_initialize.py -q
```
Expected: PASS (all). If any fails, a real caller relied on auto-vivify — STOP and report (the audit found a genuine dependency).

- [ ] **Step 6: Audit + commit**

Grep for create-context reliance and confirm none break:
`grep -rn "GetSubmenuW" sdk/Build/scripts --include=*.py | grep -i "AddChild\|=" ` — spot-check that callers either pre-`AddChild` or treat `None` as "create". (The regression gate is the real guard.)

```bash
git add engine/appc/characters.py tests/unit/test_characters.py tests/integration/test_set_course_population.py
git commit -m "fix(menus): strict GetSubmenuW so SDK Set Course populates warp points"
```

---

## Phase 2 — Galaxy helper + warp-point catalog

### Task 3: Extract `sector_model.py` + add helpers

**Files:**
- Create: `engine/appc/sector_model.py`
- Modify: `engine/appc/sky_projection.py` (remove moved names, re-import them)
- Test: `tests/unit/test_sector_model.py`

**Interfaces:**
- Produces (in `engine.appc.sector_model`): `load_sector_model()`, `system_id_for_set(name)`, `vantage_for_set(pSet, model=None)`, `display_label(system_id) -> str`, `warp_points_for(system_id, model=None) -> list[dict]`, `is_real_system(system_id) -> bool` (False for `multi*`), plus `_MODEL_PATH`, `_MEMBER_TO_PARENT`.
- `sky_projection` re-exports `load_sector_model`, `system_id_for_set`, `vantage_for_set`, `_MODEL_PATH`, `_MEMBER_TO_PARENT` so `sp.<name>` and existing callers/tests are unchanged.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_sector_model.py`:

```python
from engine.appc import sector_model as sm


def test_load_has_systems():
    model = sm.load_sector_model()
    assert isinstance(model.get("systems"), list)
    assert len(model["systems"]) >= 30


def test_system_id_for_set_normalizes():
    assert sm.system_id_for_set("Vesuvi6") == "vesuvi"
    assert sm.system_id_for_set("Starbase12") == "tauceti"  # member -> parent


def test_display_label_overrides_and_titlecase():
    assert sm.display_label("vesuvi") == "Vesuvi"
    assert sm.display_label("xientrades") == "Xi Entrades"
    assert sm.display_label("omegadraconis") == "Omega Draconis"


def test_is_real_system_excludes_multi():
    assert sm.is_real_system("vesuvi") is True
    assert sm.is_real_system("multi1") is False


def test_warp_points_for_absent_is_empty():
    # A system id with no baked warp_points yields [].
    assert sm.warp_points_for("does-not-exist") == []


def test_sky_projection_reexports_still_work():
    from engine.appc import sky_projection as sp
    assert sp.load_sector_model() is sm.load_sector_model()
    assert sp.system_id_for_set("Vesuvi6") == "vesuvi"
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_sector_model.py -v`
Expected: FAIL — no module `engine.appc.sector_model`.

- [ ] **Step 3: Create `sector_model.py` and move the names**

Create `engine/appc/sector_model.py`:

```python
"""Persistent galaxy data model + identity helpers.

Owns sector_model.json (galaxy systems/nebulae/starclouds + the baked
per-system warp_points catalog). The sky renderer (sky_projection.py) and the
Set Course popup both consume this; neither depends on the other.
"""
import json
import re
from functools import lru_cache
from pathlib import Path

_MODEL_PATH = Path(__file__).with_name("sector_model.json")

# Synthetic members folded under one star (mirrors the extractor).
_MEMBER_TO_PARENT = {"drydock": "tauceti", "starbase12": "tauceti"}

# Display-name overrides where title-casing the id is wrong.
_LABEL_OVERRIDES = {
    "xientrades": "Xi Entrades",
    "omegadraconis": "Omega Draconis",
    "tauceti": "Tau Ceti",
    "deepspace": "Deep Space",
}


@lru_cache(maxsize=1)
def load_sector_model():
    try:
        return json.loads(_MODEL_PATH.read_text())
    except (OSError, ValueError):
        return {"systems": [], "nebulae": [], "starclouds": []}


def system_id_for_set(set_name):
    name = str(set_name).lower()
    if name in _MEMBER_TO_PARENT:
        return _MEMBER_TO_PARENT[name]
    base = re.sub(r"\d+$", "", name)        # "vesuvi6" -> "vesuvi"
    return _MEMBER_TO_PARENT.get(base, base)


def vantage_for_set(pSet, model=None):
    if pSet is None:
        return None
    model = model or load_sector_model()
    sysid = system_id_for_set(pSet.GetName())
    for s in model.get("systems", []):
        if s["id"] == sysid:
            return s["position"]
    return None


def display_label(system_id):
    sid = str(system_id)
    if sid in _LABEL_OVERRIDES:
        return _LABEL_OVERRIDES[sid]
    return sid.replace("_", " ").title()


def is_real_system(system_id):
    """multi* ids are map scaffolding, not user-facing destinations."""
    return not str(system_id).startswith("multi")


def warp_points_for(system_id, model=None):
    model = model or load_sector_model()
    for s in model.get("systems", []):
        if s["id"] == system_id:
            return list(s.get("warp_points", []))
    return []
```

In `engine/appc/sky_projection.py`, **remove** the moved definitions (`_MODEL_PATH`, `_MEMBER_TO_PARENT`, `load_sector_model`, `system_id_for_set`, `vantage_for_set`, lines ~13-43) and the now-unused `json`/`lru_cache` imports if they are only used by the moved code (keep `re`, `math`, `zlib` — still used by projection). Add at the top (after the remaining imports):

```python
from engine.appc.sector_model import (
    _MODEL_PATH, _MEMBER_TO_PARENT,
    load_sector_model, system_id_for_set, vantage_for_set,
)
```

Verify `project_sky` / `_project_feature` still reference `system_id_for_set` / `load_sector_model` via these re-imported names (no change needed — same module namespace).

- [ ] **Step 4: Run sector_model tests + existing sky tests**

Run: `uv run pytest tests/unit/test_sector_model.py tests/engine/appc/ -v`
Expected: PASS (new tests + all existing `test_sky_projection_*`).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/sector_model.py engine/appc/sky_projection.py tests/unit/test_sector_model.py
git commit -m "refactor(galaxy): extract sector_model helper from sky_projection"
```

---

### Task 4: Warp-point catalog baker + regenerated JSON

**Files:**
- Create: `tools/bake_set_course_catalog.py`
- Modify: `tools/bake_sector_model.py` (preserve `warp_points` on rebake)
- Modify: `engine/appc/sector_model.json` (regenerated, now with `warp_points`)
- Test: `tests/integration/test_bake_set_course_catalog.py`

**Interfaces:**
- Consumes: Task 1 (`SetClass_MakeDisplayName`), Task 2 (strict `GetSubmenuW`), Task 3 (`system_id_for_set`).
- Produces: `tools.bake_set_course_catalog.build_catalog() -> dict[str, list[{"id","label"}]]` (keyed by galaxy system id) and `bake(out_path=...)` that folds `warp_points` into `sector_model.json`.

- [ ] **Step 1: Write the failing test**

Create `tests/integration/test_bake_set_course_catalog.py`:

```python
"""The catalog baker registers all systems headlessly and folds warp_points
into the sector model."""
import json

import tools.bake_set_course_catalog as baker


def test_build_catalog_has_systems_and_warp_points():
    catalog = baker.build_catalog()
    assert len(catalog) >= 30
    total = sum(len(v) for v in catalog.values())
    assert total >= 80
    # Labels are real (from SetClass_MakeDisplayName), each warp has id + label.
    sample = next(iter(catalog.values()))
    assert sample and "id" in sample[0] and "label" in sample[0]
    assert "MakeDisplayName" not in sample[0]["label"]


def test_fold_into_model_preserves_systems(tmp_path):
    src = {"systems": [{"id": "vesuvi", "position": [1, 2, 3]}],
           "nebulae": [], "starclouds": []}
    p = tmp_path / "sector_model.json"
    p.write_text(json.dumps(src))
    catalog = {"vesuvi": [{"id": "vesuvi-4", "label": "Vesuvi 4"}]}
    baker.fold_into_model(catalog, p)
    out = json.loads(p.read_text())
    v = out["systems"][0]
    assert v["position"] == [1, 2, 3]          # untouched
    assert v["warp_points"] == [{"id": "vesuvi-4", "label": "Vesuvi 4"}]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/integration/test_bake_set_course_catalog.py -v`
Expected: FAIL — no module `tools.bake_set_course_catalog`.

- [ ] **Step 3: Implement the baker**

Create `tools/bake_set_course_catalog.py`:

```python
"""Bake the full Set Course warp-point catalog into sector_model.json.

Offline step. Runs every SDK system's CreateMenus() against an isolated
Helm/Set-Course menu (needs the strict GetSubmenuW fix) and records each
system's warp points. Folds the result into sector_model.json as a
`warp_points` list per system; the sky projection ignores it.

Usage: uv run python tools/bake_set_course_catalog.py
"""
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYS_DIR = ROOT / "sdk" / "Build" / "scripts" / "Systems"
OUT = ROOT / "engine" / "appc" / "sector_model.json"


def _slug(label):
    return re.sub(r"[^a-z0-9]+", "-", str(label).lower()).strip("-")


def build_catalog():
    """Return {galaxy_system_id: [{"id","label"}, ...]} for every system."""
    import App  # noqa: F401  (ensures SDK import path + App shim are set up)
    from engine.appc.windows import TacticalControlWindow
    from engine.appc.target_menu import _reset_target_menu_singleton
    from engine.core.game import Game, Episode, Mission, _set_current_game
    from engine.appc.tg_ui.st_widgets import SortedRegionMenu
    from engine.appc.sector_model import system_id_for_set

    TacticalControlWindow._instance = None
    _reset_target_menu_singleton()
    g = Game(); e = Episode(); m = Mission()
    e.SetCurrentMission(m); g.SetCurrentEpisode(e)
    _set_current_game(g)
    sys.modules.pop("Bridge.HelmMenuHandlers", None)
    sys.modules.pop("HelmMenuHandlers", None)
    import Bridge.HelmMenuHandlers as helm
    helm.CreateMenus()

    names = sorted(d for d in os.listdir(SYS_DIR)
                   if (SYS_DIR / d / (d + ".py")).is_file())
    failed = {}
    for n in names:
        try:
            mod = __import__("Systems.%s.%s" % (n, n), fromlist=[n])
            if hasattr(mod, "CreateMenus"):
                mod.CreateMenus()
        except Exception as exc:                       # noqa: BLE001
            failed[n] = "%s: %s" % (type(exc).__name__, str(exc)[:80])

    helm_menu = TacticalControlWindow.GetInstance().GetMenuList()[0]
    sc = next((c for c in helm_menu._children
               if isinstance(c, SortedRegionMenu)), None)
    catalog, unmatched = {}, []
    model_ids = {s["id"] for s in
                 __import__("engine.appc.sector_model", fromlist=["x"])
                 .load_sector_model().get("systems", [])}
    if sc is not None:
        for node in sc._children:
            sid = system_id_for_set(node.GetLabel())
            if sid not in model_ids:
                unmatched.append((node.GetLabel(), sid))
            wps = [{"id": _slug(c.GetLabel()), "label": c.GetLabel()}
                   for c in getattr(node, "_children", [])]
            catalog.setdefault(sid, []).extend(wps)
    _set_current_game(None)
    if failed:
        print("[catalog] %d systems failed: %s" % (len(failed), failed))
    if unmatched:
        print("[catalog] %d unmatched system ids (add overrides): %s"
              % (len(unmatched), unmatched))
    print("[catalog] %d systems, %d warp points"
          % (len(catalog), sum(len(v) for v in catalog.values())))
    return catalog


def fold_into_model(catalog, out_path=OUT):
    model = json.loads(Path(out_path).read_text())
    for s in model.get("systems", []):
        wps = catalog.get(s["id"])
        if wps is not None:
            s["warp_points"] = wps
    Path(out_path).write_text(json.dumps(model, indent=2) + "\n")
    return model


def main():
    fold_into_model(build_catalog())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Make `bake_sector_model.py` preserve `warp_points`**

In `tools/bake_sector_model.py`, change `build_sector_model` so systems carry forward any existing `warp_points` from the current `sector_model.json`. Replace the `systems = [...]` comprehension with:

```python
    existing = {}
    try:
        for s in json.loads(DEFAULT_OUT.read_text()).get("systems", []):
            if "warp_points" in s:
                existing[s["id"]] = s["warp_points"]
    except (OSError, ValueError):
        pass
    systems = []
    for s in map_data.get("systems", []):
        entry = {"id": s["id"], "position": s["position"]}
        if s["id"] in existing:
            entry["warp_points"] = existing[s["id"]]
        systems.append(entry)
```

- [ ] **Step 5: Run the tests, then regenerate the committed JSON**

Run: `uv run pytest tests/integration/test_bake_set_course_catalog.py -v`
Expected: PASS.

Regenerate the artifact and sanity-check:

```bash
uv run python tools/bake_set_course_catalog.py
```
Expected: prints `[catalog] N systems, ~95 warp points` (N ≥ 30); `git diff --stat` shows `engine/appc/sector_model.json` changed with `warp_points` added.

- [ ] **Step 6: Commit**

```bash
git add tools/bake_set_course_catalog.py tools/bake_sector_model.py \
  engine/appc/sector_model.json tests/integration/test_bake_set_course_catalog.py
git commit -m "feat(set-course): bake full warp-point catalog into sector_model.json"
```

---

## Phase 3 — Panel + CEF

### Task 5: `SettingCoursePanel` two-level logic

**Files:**
- Modify: `engine/ui/setting_course_panel.py` (replace placeholder body)
- Modify: `tests/unit/test_setting_course_panel.py` (replace placeholder tests)

**Interfaces:**
- Consumes: `engine.appc.sector_model` (`load_sector_model`, `system_id_for_set`, `display_label`, `is_real_system`, `warp_points_for`).
- `open(course_menu=None)` keeps storing the live Set Course `SortedRegionMenu`.
- Render payload shape: `{visible, selected_system, systems:[{id,label,active}], warp_points:[{id,label,active,selected}]}`.
- Events: `select-system:<id>`, `select-warp:<id>`, `cancel`.

- [ ] **Step 1: Write the failing tests**

Replace the body of `tests/unit/test_setting_course_panel.py` with:

```python
"""SettingCoursePanel — two-level system/warp-point menu."""
import json

from engine.ui.setting_course_panel import SettingCoursePanel


class _FakeMenu:
    """Stand-in for an STMenu/SortedRegionMenu node."""
    def __init__(self, label, children=None):
        self._label = label
        self._children = children or []
    def GetLabel(self):
        return self._label


def _payload(js):
    assert js.startswith("setSettingCoursePanel(") and js.endswith(");")
    return json.loads(js[len("setSettingCoursePanel("):-2])


def _live_menu():
    # Vesuvi active with one active warp point "Vesuvi 4".
    return _FakeMenu("Set Course", [
        _FakeMenu("Vesuvi", [_FakeMenu("Vesuvi 4")]),
    ])


def test_lists_all_systems_with_active_flag():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    data = _payload(p.render_payload())
    ids = [s["id"] for s in data["systems"]]
    assert "vesuvi" in ids
    assert len(ids) >= 30
    assert "multi1" not in ids
    vesuvi = next(s for s in data["systems"] if s["id"] == "vesuvi")
    assert vesuvi["active"] is True
    other = next(s for s in data["systems"] if s["id"] != "vesuvi")
    assert other["active"] is False


def test_select_system_reveals_warp_points_with_active_overlay():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.render_payload()
    assert p.dispatch_event("select-system:vesuvi") is True
    data = _payload(p.render_payload())
    assert data["selected_system"] == "vesuvi"
    labels = [w["label"] for w in data["warp_points"]]
    assert "Vesuvi 4" in labels
    active = next(w for w in data["warp_points"] if w["label"] == "Vesuvi 4")
    assert active["active"] is True  # in the live menu


def test_select_warp_records_ui_only_selection():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:vesuvi")
    p.render_payload()
    wp_id = _payload_first_warp_id(p)
    assert p.dispatch_event("select-warp:" + wp_id) is True
    data = _payload(p.render_payload())
    sel = next(w for w in data["warp_points"] if w["id"] == wp_id)
    assert sel["selected"] is True


def _payload_first_warp_id(p):
    p2 = _payload(p.render_payload())
    return p2["warp_points"][0]["id"]


def test_open_resets_selection():
    p = SettingCoursePanel()
    p.open(course_menu=_live_menu())
    p.dispatch_event("select-system:vesuvi")
    p.open(course_menu=_live_menu())
    data = _payload(p.render_payload())
    assert data["selected_system"] is None


def test_unknown_action_returns_false():
    p = SettingCoursePanel()
    assert p.dispatch_event("frobnicate") is False
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_setting_course_panel.py -v`
Expected: FAIL (placeholder panel has no systems/warp logic).

- [ ] **Step 3: Implement the two-level panel**

Replace `engine/ui/setting_course_panel.py` with:

```python
"""SettingCoursePanel — two-level Set Course menu.

Left column lists every galaxy system (from sector_model); selecting one
reveals its warp points (from the baked catalog) in the right column.
Systems and warp targets the running game currently has in its live SDK Set
Course menu are marked active (bold). Warp-point selection is UI-only.

Spec: docs/superpowers/specs/2026-06-21-set-course-two-level-menu-design.md
"""
from __future__ import annotations

import json
from typing import Optional

from engine.appc import sector_model as sm
from engine.ui.panel import Panel


class SettingCoursePanel(Panel):
    def __init__(self) -> None:
        super().__init__()
        self._visible = False
        self._course_menu = None
        self._selected_system: Optional[str] = None
        self._selected_warp: Optional[str] = None
        self._last_pushed: Optional[str] = None
        self._systems = [
            s["id"] for s in sm.load_sector_model().get("systems", [])
            if sm.is_real_system(s["id"])
        ]
        self._systems.sort(key=sm.display_label)

    @property
    def name(self) -> str:
        return "setting-course"

    def is_open(self) -> bool:
        return self._visible

    def open(self, course_menu=None) -> None:
        self._course_menu = course_menu
        self._selected_system = None
        self._selected_warp = None
        self._visible = True

    def close(self) -> None:
        self._visible = False

    def handle_key_esc(self) -> None:
        if self._visible:
            self.close()

    # --- live-menu overlay -------------------------------------------------
    def _active_system_ids(self) -> set:
        out = set()
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                out.add(sm.system_id_for_set(node.GetLabel()))
            except Exception:
                pass
        return out

    def _active_warp_labels(self, system_id) -> set:
        for node in getattr(self._course_menu, "_children", []) or []:
            try:
                if sm.system_id_for_set(node.GetLabel()) == system_id:
                    return {c.GetLabel() for c in getattr(node, "_children", [])}
            except Exception:
                pass
        return set()

    def render_payload(self) -> Optional[str]:
        active_systems = self._active_system_ids()
        systems = [{"id": sid, "label": sm.display_label(sid),
                    "active": sid in active_systems}
                   for sid in self._systems]
        warp_points = []
        if self._selected_system is not None:
            active_warps = self._active_warp_labels(self._selected_system)
            for wp in sm.warp_points_for(self._selected_system):
                warp_points.append({
                    "id": wp["id"], "label": wp["label"],
                    "active": wp["label"] in active_warps,
                    "selected": wp["id"] == self._selected_warp,
                })
        payload = json.dumps({
            "visible": self._visible,
            "selected_system": self._selected_system,
            "systems": systems if self._visible else [],
            "warp_points": warp_points,
        })
        if payload == self._last_pushed:
            return None
        self._last_pushed = payload
        return "setSettingCoursePanel(" + payload + ");"

    def dispatch_event(self, action: str) -> bool:
        if action == "cancel":
            self.close()
            return True
        if action.startswith("select-system:"):
            self._selected_system = action[len("select-system:"):]
            self._selected_warp = None
            return True
        if action.startswith("select-warp:"):
            self._selected_warp = action[len("select-warp:"):]
            return True
        return False

    def invalidate(self) -> None:
        self._last_pushed = None
```

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/unit/test_setting_course_panel.py -v`
Expected: PASS.

Also confirm the crew-menu override + host_loop wiring still import:
Run: `uv run pytest tests/unit/test_crew_menu_set_course_override.py -q && PYTHONPATH=build/python uv run python -c "import engine.host_loop; print('ok')"`
Expected: PASS / `ok`.

- [ ] **Step 5: Commit**

```bash
git add engine/ui/setting_course_panel.py tests/unit/test_setting_course_panel.py
git commit -m "feat(set-course): two-level system/warp-point panel logic"
```

---

### Task 6: CEF two-column assets

**Files:**
- Modify: `native/assets/ui-cef/index.html` (`#setting-course-panel` body)
- Modify: `native/assets/ui-cef/js/setting_course_panel.js` (render two columns)
- Modify: `native/assets/ui-cef/css/configuration_panel.css` (two-column + bold/selected)

> No automated test — CEF render is verified in-game (handoff). `node --check` guards JS syntax.

- [ ] **Step 1: Replace the modal body in `index.html`**

In `native/assets/ui-cef/index.html`, replace the inner `cp-content` of `#setting-course-panel` (the `<div class="cp-content">…</div>` currently holding the placeholder body) with:

```html
        <div class="cp-content sc-columns">
          <ul id="setting-course-systems" class="sc-col"></ul>
          <ul id="setting-course-warps" class="sc-col"></ul>
        </div>
```

Leave the `cp-header` ("Set Course"), the `cp-footer` OK button (`dauntlessEvent('setting-course/cancel')`), and the `<script src="js/setting_course_panel.js">` tag unchanged.

- [ ] **Step 2: Rewrite the render function**

Replace `native/assets/ui-cef/js/setting_course_panel.js` with:

```javascript
// Two-level Set Course menu render fn. Driven by Python:
//   setSettingCoursePanel({visible, selected_system, systems, warp_points});
//   setSettingCoursePanel({visible:false});
// System rows fire setting-course/select-system:<id>; warp rows fire
// setting-course/select-warp:<id>; OK/ESC fire setting-course/cancel.
// Reuses cp-* chrome; sc-* classes add the two-column layout.

function escapeHtmlSC(s) {
    return String(s)
        .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

function _scRow(item, evt, extraClass) {
    const cls = 'sc-row'
        + (item.active ? ' sc-row--active' : '')
        + (item.selected ? ' sc-row--selected' : '')
        + (item.id === undefined ? '' : '')
        + (extraClass ? ' ' + extraClass : '');
    return '<li class="' + cls + '" data-id="' + escapeHtmlSC(item.id) + '"'
        + ' onclick="dauntlessEvent(\'' + evt + ':\' + this.getAttribute(\'data-id\'))">'
        + escapeHtmlSC(item.label) + '</li>';
}

function setSettingCoursePanel(state) {
    const root = document.getElementById('setting-course-panel');
    if (!root) return;
    if (!state || state.visible !== true) {
        root.style.display = 'none';
        return;
    }
    const sysEl = document.getElementById('setting-course-systems');
    if (sysEl) {
        sysEl.innerHTML = (state.systems || []).map(function (s) {
            const sel = (s.id === state.selected_system);
            return _scRow({id: s.id, label: s.label, active: s.active,
                           selected: sel}, 'setting-course/select-system');
        }).join('');
    }
    const warpEl = document.getElementById('setting-course-warps');
    if (warpEl) {
        warpEl.innerHTML = (state.warp_points || []).map(function (w) {
            return _scRow(w, 'setting-course/select-warp');
        }).join('');
    }
    root.style.display = 'flex';
}
```

- [ ] **Step 3: Add the two-column CSS**

Append to `native/assets/ui-cef/css/configuration_panel.css`:

```css
/* Set Course two-column body (reuses cp-* chrome). */
.sc-columns { display: flex; gap: 0; }
.sc-col {
    list-style: none; margin: 0; padding: 6px 0;
    flex: 1 1 50%; overflow-y: auto; max-height: 320px;
}
.sc-col + .sc-col { border-left: 1px solid rgba(255, 255, 255, 0.12); }
.sc-row {
    padding: 4px 14px; cursor: pointer; color: #cdd3dc;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.sc-row:hover { background: rgba(173, 132, 255, 0.15); }
.sc-row--active { font-weight: 700; color: #fff; }
.sc-row--selected { background: rgb(37, 26, 64); }
```

- [ ] **Step 4: Sanity-check**

Run: `node --check native/assets/ui-cef/js/setting_course_panel.js && echo "JS ok"`
Expected: `JS ok`.

Run: `grep -n "setting-course-systems\|setting-course-warps\|sc-columns" native/assets/ui-cef/index.html native/assets/ui-cef/css/configuration_panel.css`
Expected: the new ids/classes are present.

- [ ] **Step 5: Commit**

```bash
git add native/assets/ui-cef/index.html native/assets/ui-cef/js/setting_course_panel.js native/assets/ui-cef/css/configuration_panel.css
git commit -m "feat(set-course): two-column CEF menu (systems | warp points)"
```

---

### Task 7: Manual in-game verification (handoff)

**Files:** none. Performed by the user / live run.

- [ ] CEF/Python changes need no C++ rebuild (assets load from source); relaunch `./build/dauntless`.
- [ ] Load a mission that registers systems (e.g. an Episode 6/7 mission), open Helm → Set Course.
- [ ] Confirm the modal lists all systems (left); the active mission system(s) appear **bold**.
- [ ] Click a system → its warp points appear (right); active warp targets are **bold**.
- [ ] Click a warp point → it highlights (UI-only). OK/ESC close the modal.

---

## Self-Review

- **Spec coverage:** A1→Task 2, A2→Task 1, B→Task 3, C→Task 4, D→Task 5, E→Task 6, manual→Task 7. AC1 (all systems + reveal warp points)→Task 5/6; AC2 (select warp UI-only)→Task 5/6; AC3 (bold active)→Task 5 overlay + Task 6 `sc-row--active`. All covered.
- **Placeholder scan:** no TBD/TODO; every code step has full code.
- **Type/name consistency:** `setSettingCoursePanel`, `setting-course/select-system`, `setting-course/select-warp`, `warp_points`, `system_id_for_set`, `display_label`, `warp_points_for`, `is_real_system`, `SetClass_MakeDisplayName` used identically across tasks. Payload keys (`systems`,`warp_points`,`selected_system`,`active`,`selected`) match between Task 5 (Python) and Task 6 (JS).
- **Ordering:** Task 1 → Task 2 (labels), Tasks 1+2 → Task 4 (baker needs both), Task 3 → Task 4 (system_id_for_set) and Task 5 (helpers), Task 4 → Task 5 (catalog data), Task 5 → Task 6 (payload shape). Sequential within phases; phases gated.
- **Risk:** Task 2's strict change is gated by the full menu-suite regression (Step 5) + audit (Step 6); STOP-and-report if any menu test fails.
```
