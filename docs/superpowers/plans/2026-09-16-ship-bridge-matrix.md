# Ship → Bridge Matrix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Auto-select the player's bridge from a persisted ship→bridge matrix (`bridges.json`) editable from a new Bridges tab in the configuration panel, with QuickBattle as the first consumer and the host able to survive a runtime bridge swap.

**Architecture:** A mode-agnostic service `engine/bridge_selection.py` (bridge registry, ship universe, `BridgePins` over a `SettingsStore` at `bridges.json`) is consulted by a once-installed wrap of `QuickBattle.RecreatePlayer`. The host factors its post-load bridge realisation into `_realize_bridge` and re-runs it per tick whenever the SDK bridge set's config name changes. The configuration panel grows an optional `bridge_pins` collaborator and a Bridges tab; the JS stays dumb.

**Tech Stack:** Python 3 (engine), the SDK's own `LoadBridge.Load` / `QuickBattle.RecreatePlayer`, `engine.settings_store.SettingsStore`, `engine.mods` overlay index, `engine.missions.tgl_reader`, CEF JS/CSS panel (`configuration_panel.js/.css`), pytest.

**Spec:** `docs/superpowers/specs/2026-09-16-ship-bridge-matrix-design.md`

## Global Constraints

- **Never spell `game` or `sdk` as a path segment** in `engine/`, `tools/`, `tests/conftest.py`. Use `paths.sdk_scripts()`, `paths.game_asset(rel)`. Test fixtures that build a fake install tree mark the line `# paths-guard: fake install tree`. (`tests/unit/test_path_indirection.py` enforces.)
- **Never capture a path at import.** No module-level `Path` constant in `bridge_selection.py`; resolve inside functions.
- **Mod index keys are folded and `scripts/`-stripped**: a mod file `scripts/Bridge/FooBridge.py` is indexed as key `bridge/foobridge.py` with `target == "sdk"` and `raw_rel == "Bridge/FooBridge.py"`. A mod ship script is key `ships/<name>.py`. Use `raw_rel` for the author's spelling.
- **Shared checkout — never run destructive git** (`git checkout -- <path>`, `git stash`, `git clean`, `git reset --hard`, `git add -A`/`.`). Stage with explicit pathspecs only. Back up files by `cp`, never by git.
- **Labels are BC's own**: `GalaxyBridge` → `Galaxy`, `SovereignBridge` → `Sovereign`; ships via `data/TGL/Ships.tgl`, stem fallback. No `DBridge`/`EBridge` in UI text.
- **Defaults**: `DEFAULT_PINS = {"Galaxy": "GalaxyBridge", "Sovereign": "SovereignBridge", "Akira": "SovereignBridge"}`, `DEFAULT_BRIDGE = "GalaxyBridge"`.
- **`bridges.json`** lives at `settings_store.default_settings_path().parent / "bridges.json"`, schema `{"version": 1, "pins": {<ship stem>: <bridge script>}}`. Absent file ⇒ defaults; present ⇒ authoritative (even `{}`); Reset deletes the file.
- **Test gate**: `scripts/check_tests.sh` before claiming done. `uv run pytest <file> -v` for a single file. Host tests that need the native module use `pytest.importorskip("_dauntless_host")`.
- **Never assert an SDK call is a no-op from reasoning** — check `docs/stub_heatmap.md` first.
- No native `<select>` in CEF panels.
- Commit messages end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

---

## File map

| File | Responsibility |
|---|---|
| `engine/host_loop.py` | `_realize_bridge` (factored from `_after_mission_loaded`), `_reconcile_bridge_config` per tick, `controller.realized_bridge_config`, `controller.bridge_pins`, hook install in `load_quickbattle`, Bridges tab construction |
| `engine/appc/bridge_set.py` | `BridgeSet.DeleteObjectFromSet` clears `_viewscreen` when the deleted object is it |
| `engine/settings_store.py` | `SettingsStore.has_section`, `SettingsStore.delete_file` |
| `engine/bridge_selection.py` (new) | registry (`STOCK_BRIDGES`, `available_bridges`, `is_available`, `bridge_label`, `_scan_mod_bridges` stub), ship universe (`available_ships`, `ship_label`), `BridgePins`, `default_bridges_path`, `install_quickbattle_hook` |
| `engine/ui/configuration_panel.py` | optional `bridge_pins`; Bridges tab payload, actions, focusables |
| `native/assets/ui-cef/js/configuration_panel.js` | `_cpRenderBridgesBody`, `_cpFocusableList` bridges branch |
| `native/assets/ui-cef/css/configuration_panel.css` | `.cp-bridges-*` rules |
| `tests/host/test_bridge_runtime_swap.py` (new) | Task 1 |
| `tests/unit/test_settings_store.py` | Task 2 additions |
| `tests/unit/test_bridge_selection.py` (new) | Tasks 3–4 |
| `tests/host/test_quickbattle_bridge_hook.py` (new) | Task 5 |
| `tests/unit/test_configuration_panel_bridges.py` (new) | Tasks 6–7 |
| `CLAUDE.md` | one key-reference row |

---

### Task 1: Runtime bridge-swap reconciliation in the host

The riskiest piece goes first (spec §2). `LoadBridge.Load` on an existing bridge set with a different config has never run under our engine; the host realises the bridge only in the post-load hook.

**Files:**
- Modify: `engine/host_loop.py` — class `HostController.__init__` (~`:5194`), `_after_mission_loaded` (~`:7767-7830`), the per-tick block that calls `_realize_comm_sets(controller, r)` (~`:9556`)
- Modify: `engine/appc/bridge_set.py:729-755` (`BridgeSet`)
- Test: `tests/host/test_bridge_runtime_swap.py`

**Interfaces:**
- Produces: `hl._realize_bridge(controller, r) -> None`; `hl._reconcile_bridge_config(controller, r) -> bool` (True when it re-realised); `controller.realized_bridge_config: str` (`""` until the first realise).

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_bridge_runtime_swap.py`:

```python
"""A runtime LoadBridge.Load(<other config>) must be re-realised by the host.

Until the ship->bridge matrix, g_sBridgeType was always "GalaxyBridge", so
LoadBridge.Load's "set exists, different config" branch never ran under our
engine. These tests drive that branch's OUTPUT (a fresh BridgeObjectClass
carrier + fresh ViewScreenObject under a new config name) and assert the
per-tick reconcile re-realises exactly once and only on a config change.
"""
import engine.host_loop as hl


class _FakeRenderer:
    def __init__(self):
        self.created = []
        self.destroyed = []
        self._next = 1
        self.vs_model = None

    def load_model(self, nif_abs, tex_abs):
        return 100 + self._next

    def create_bridge_instance(self, handle):
        iid = ("bridge", self._next); self._next += 1
        self.created.append(iid); return iid

    def create_comm_instance(self, handle):
        iid = ("comm", self._next); self._next += 1
        self.created.append(iid); return iid

    def set_world_transform(self, iid, mat): pass
    def destroy_instance(self, iid): self.destroyed.append(iid)
    def set_viewscreen_model(self, h): self.vs_model = h


def _controller():
    c = hl.HostController()
    return c


def _install_bridge(config, nif, vs_nif):
    """Build (or rebuild, like LoadBridge.Load does) the 'bridge' set."""
    import App
    from engine.appc.bridge_set import (BridgeObjectClass, BridgeSet,
                                        ViewScreenObject)
    s = App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
    if s is None:
        s = BridgeSet()
        App.g_kSetManager.AddSet(s, "bridge")
    s.DeleteObjectFromSet("bridge")
    s.DeleteObjectFromSet("viewscreen")
    s.AddObjectToSet(BridgeObjectClass(nif), "bridge")
    s.SetViewScreen(ViewScreenObject(vs_nif))
    s.SetConfig(config)
    return s


def _fresh_sdk():
    from tools import mission_harness
    mission_harness.setup_sdk()
    hl.reset_sdk_globals()


def test_reconcile_is_a_noop_when_config_unchanged(monkeypatch):
    _fresh_sdk()
    c, r = _controller(), _FakeRenderer()
    _install_bridge("GalaxyBridge", "data/Models/Sets/DBridge/DBridge.nif",
                    "data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    hl._realize_bridge(c, r)
    n_created = len(r.created)

    assert hl._reconcile_bridge_config(c, r) is False
    assert len(r.created) == n_created
    assert c.realized_bridge_config == "GalaxyBridge"


def test_reconcile_rerealises_on_config_change(monkeypatch):
    _fresh_sdk()
    c, r = _controller(), _FakeRenderer()
    _install_bridge("GalaxyBridge", "data/Models/Sets/DBridge/DBridge.nif",
                    "data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    hl._realize_bridge(c, r)
    old_bridge = c.bridge_instance
    old_vs = c.viewscreen_instance

    # What LoadBridge.Load("SovereignBridge") leaves behind: same set, new
    # carrier + viewscreen objects, new config name.
    _install_bridge("SovereignBridge", "data/Models/Sets/EBridge/EBridge.nif",
                    "data/Models/Sets/EBridge/EBridgeViewScreen.nif")

    assert hl._reconcile_bridge_config(c, r) is True
    assert c.realized_bridge_config == "SovereignBridge"
    assert old_bridge in r.destroyed
    assert old_vs in r.destroyed
    assert c.bridge_instance is not None and c.bridge_instance != old_bridge
    assert c.viewscreen_instance is not None and c.viewscreen_instance != old_vs
    # Second tick: nothing more to do.
    assert hl._reconcile_bridge_config(c, r) is False


def test_reconcile_without_a_bridge_set_is_a_noop():
    _fresh_sdk()
    c, r = _controller(), _FakeRenderer()
    assert hl._reconcile_bridge_config(c, r) is False
    assert r.created == []


def test_bridge_set_delete_viewscreen_clears_the_slot():
    """LoadBridge.Load deletes 'viewscreen' by name before the new config's
    CreateBridgeModel installs a new one; the BridgeSet slot must not keep
    handing out the deleted object in between."""
    from engine.appc.bridge_set import BridgeSet, ViewScreenObject
    s = BridgeSet(); s.SetName("bridge")
    vs = ViewScreenObject("x.nif")
    s.SetViewScreen(vs)
    s.DeleteObjectFromSet("viewscreen")
    assert s.GetViewScreen() is None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/host/test_bridge_runtime_swap.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute '_realize_bridge'` (3 tests) and `assert <ViewScreenObject> is None` fails (1 test).

- [ ] **Step 3: Fix `BridgeSet.DeleteObjectFromSet`**

In `engine/appc/bridge_set.py`, inside `class BridgeSet`, after `SetViewScreen`:

```python
    def DeleteObjectFromSet(self, name):
        # LoadBridge.Load deletes "viewscreen" by name before the new config's
        # CreateBridgeModel installs a replacement; drop the slot too so the
        # host never re-realises the deleted object in between.
        if name == "viewscreen":
            self._viewscreen = None
        super().DeleteObjectFromSet(name)
```

- [ ] **Step 4: Add `realized_bridge_config` to `HostController`**

In `engine/host_loop.py`, `HostController.__init__`, directly after the `self.current_bridge_nif_abs: Optional[str] = None` line:

```python
        # The SDK BridgeSet.GetConfig() name the bridge was last realised
        # under. _reconcile_bridge_config compares the live value against it
        # each tick: a runtime LoadBridge.Load("<other>") (QuickBattle's
        # RecreatePlayer with a different g_sBridgeType) rebuilds the "bridge"
        # object + viewscreen and this is how the host notices.
        self.realized_bridge_config: str = ""
```

- [ ] **Step 5: Factor `_realize_bridge` out of `_after_mission_loaded`**

Add a module-level function in `engine/host_loop.py` directly above `def realize_all_sets` (~`:6067`):

```python
def _realize_bridge(controller, r) -> None:
    """Realise the SDK "bridge" set: its config module's sounds, the
    captain's-chair camera parameters, and the model/viewscreen/officer
    render instances. Called from the post-load hook and again by
    _reconcile_bridge_config whenever the set's config name changes at
    runtime (a QuickBattle RecreatePlayer that loads a different bridge).

    Deliberately NOT here: wire_after_mission_load, resolve_officer_menu_
    layout and the hit-reaction re-registration. LoadBridge.Load on an
    existing set neither rebuilds menus nor recreates characters -- it only
    re-ConfigureCharacters them -- so those stay post-load-only.
    """
    global _BRIDGE_CAMERA_EYE, _BRIDGE_CAMERA_MOVE
    global _BRIDGE_ZOOM_MIN, _BRIDGE_ZOOM_MAX, _BRIDGE_ZOOM_TIME, _BRIDGE_ZOOM_CAM
    import App as _App
    _bridge = _App.g_kSetManager.GetSet("bridge")
    # Documented SDK deviation: LoadBridge.Load never calls the bridge config
    # module's LoadSounds() -- see engine/bridge_sounds.py.
    from engine import bridge_sounds
    bridge_sounds.load_bridge_module_sounds(_bridge)
    _cam = _bridge.GetCamera("maincamera") if _bridge is not None else None
    if _cam is not None and hasattr(_cam, "position"):
        # The seated captain eye is the bridge's pushed camera MODE's
        # BasePosition, NOT the camera's .position (GalaxyBridge pushes a
        # PlaceByDirection mode; Sovereign pushes none).
        _mode = (_cam.GetCurrentCameraMode()
                 if hasattr(_cam, "GetCurrentCameraMode") else None)
        _base = _mode.GetAttrPoint("BasePosition") if _mode is not None else None
        if _base is not None:
            _BRIDGE_CAMERA_EYE = (_base.x, _base.y, _base.z)
            _mov = _mode.GetAttrPoint("Movement")
            if _mov is not None:
                _BRIDGE_CAMERA_MOVE = ((_mov.x, _mov.y, _mov.z),
                                       _mode.GetAttrFloat("StartMoveAngle"),
                                       _mode.GetAttrFloat("EndMoveAngle"))
            else:
                _BRIDGE_CAMERA_MOVE = None
        else:
            _BRIDGE_CAMERA_EYE = getattr(_cam, "base_position", None) or _cam.position
            _BRIDGE_CAMERA_MOVE = None
        _BRIDGE_ZOOM_MIN = _cam.GetMinZoom()
        _BRIDGE_ZOOM_MAX = _cam.GetMaxZoom()
        _BRIDGE_ZOOM_TIME = _cam.GetZoomTime()
        _BRIDGE_ZOOM_CAM = _cam
    if _bridge is not None:
        realize_set(controller, r, _bridge, is_bridge=True)
        controller.realized_bridge_config = (
            _bridge.GetConfig() if hasattr(_bridge, "GetConfig") else "")


def _reconcile_bridge_config(controller, r) -> bool:
    """Per-tick: re-realise the bridge if its SDK config name changed since
    the last realise. Returns True when it did. No-op with no bridge set."""
    import App as _App
    _bridge = _App.g_kSetManager.GetSet("bridge")
    if _bridge is None or not hasattr(_bridge, "GetConfig"):
        return False
    if _bridge.GetConfig() == controller.realized_bridge_config:
        return False
    _realize_bridge(controller, r)
    return True
```

Then in `_after_mission_loaded` replace the block from the `global _BRIDGE_CAMERA_EYE, _BRIDGE_CAMERA_MOVE` line through `realize_all_sets(controller, r)` (inclusive) with:

```python
            import App as _App
            # Bridge sounds, camera eye/zoom harvest, and the bridge set's
            # render instances; re-run per tick on a config change by
            # _reconcile_bridge_config.
            _realize_bridge(controller, r)
            # Comm/remote sets with geometry or characters.
            _realize_comm_sets(controller, r)
```

Keep everything after it (`_ensure_target_menu()`, `wire_after_mission_load()`, `resolve_officer_menu_layout()`, the hit-reaction re-registration) unchanged. `realize_all_sets` STAYS — `tests/host/test_realize_set.py` calls it directly (4 sites); it is simply no longer the post-load hook's entry point.

- [ ] **Step 6: Call the reconcile per tick**

In the game loop, immediately before the existing `_realize_comm_sets(controller, r)` call (~`:9556`):

```python
            # A runtime bridge swap (QuickBattle RecreatePlayer under a
            # different g_sBridgeType) rebuilds the SDK "bridge" set's objects
            # under a new config name; re-realise it here.
            _reconcile_bridge_config(controller, r)
```

- [ ] **Step 7: Run the tests**

Run: `uv run pytest tests/host/test_bridge_runtime_swap.py tests/host/test_realize_set.py tests/host/test_quickbattle_boot.py -v`
Expected: all PASS.

- [ ] **Step 8: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0; only the baselined `tests/known_failures.txt` entry fails.

- [ ] **Step 9: Commit**

```bash
git add engine/host_loop.py engine/appc/bridge_set.py tests/host/test_bridge_runtime_swap.py
git commit -m "feat(host): re-realise the bridge when its SDK config changes at runtime

Factor the post-load bridge realisation into _realize_bridge and re-run it
per tick whenever BridgeSet.GetConfig() differs from the last realise, so a
QuickBattle RecreatePlayer that loads a different bridge is rendered.
BridgeSet.DeleteObjectFromSet('viewscreen') now clears the slot.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `SettingsStore.has_section` and `delete_file`

**Files:**
- Modify: `engine/settings_store.py:125-148`
- Test: `tests/unit/test_settings_store.py`

**Interfaces:**
- Produces: `SettingsStore.has_section(section: str) -> bool` (True only when the loaded document has that section as a dict, even an empty one); `SettingsStore.set_section(section: str, mapping: dict) -> None` (replaces the whole section — an empty dict leaves a PRESENT empty section — and saves); `SettingsStore.delete_file() -> None` (unlinks the file if present, resets the in-memory document to `{"version": SCHEMA_VERSION}`; never raises).

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_settings_store.py`:

```python
# ---- has_section / delete_file (bridges.json needs "absent" vs "{}") ------

def test_has_section_distinguishes_absent_from_empty(tmp_path):
    from engine.settings_store import SettingsStore
    p = tmp_path / "s.json"
    p.write_text('{"version": 2, "pins": {}}')
    store = SettingsStore(p); store.load()
    assert store.has_section("pins") is True
    assert store.has_section("graphics") is False


def test_has_section_is_false_for_a_non_dict_value(tmp_path):
    from engine.settings_store import SettingsStore
    p = tmp_path / "s.json"
    p.write_text('{"version": 2, "pins": 3}')
    store = SettingsStore(p); store.load()
    assert store.has_section("pins") is False


def test_delete_file_removes_it_and_clears_memory(tmp_path):
    from engine.settings_store import SettingsStore
    p = tmp_path / "s.json"
    store = SettingsStore(p); store.load()
    store.set("pins", "Galaxy", "GalaxyBridge")
    assert p.exists()
    store.delete_file()
    assert not p.exists()
    assert store.has_section("pins") is False
    assert store.get("pins", "Galaxy") is None


def test_delete_file_when_absent_does_not_raise(tmp_path):
    from engine.settings_store import SettingsStore
    store = SettingsStore(tmp_path / "s.json"); store.load()
    store.delete_file()   # no file yet


def test_set_section_replaces_the_whole_section_and_saves(tmp_path):
    import json
    from engine.settings_store import SettingsStore
    p = tmp_path / "s.json"
    store = SettingsStore(p); store.load()
    store.set("pins", "Galaxy", "GalaxyBridge")
    store.set_section("pins", {"Akira": "SovereignBridge"})
    assert json.loads(p.read_text())["pins"] == {"Akira": "SovereignBridge"}
    store.set_section("pins", {})
    assert json.loads(p.read_text())["pins"] == {}
    assert store.has_section("pins") is True
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_settings_store.py -k "has_section or delete_file or set_section" -v`
Expected: FAIL with `AttributeError: 'SettingsStore' object has no attribute 'has_section'` / `'delete_file'` / `'set_section'`.

- [ ] **Step 3: Implement**

In `engine/settings_store.py`, in `class SettingsStore` after `def has(...)`:

```python
    def has_section(self, section: str) -> bool:
        """True only when the document carries `section` as an object — an
        EMPTY section counts. `_section()` collapses absent and `{}` into the
        same thing, which is right for key lookups and wrong for a store
        whose whole meaning is "file present ⇒ authoritative" (bridges.json)."""
        return isinstance(self._doc.get(section), dict)
```

and after `def reset_section(...)`:

```python
    def set_section(self, section: str, mapping: dict) -> None:
        """Replace a whole section and save. An empty mapping leaves a
        PRESENT, empty section — for bridges.json that is an authoritative
        'no pins', distinct from the absent-section defaults."""
        self._doc[section] = dict(mapping)
        self._save()

    def delete_file(self) -> None:
        """Remove the file and forget its contents. The 'absent ⇒ defaults'
        store (bridges.json) uses this for Reset: emptying the document would
        leave a present-but-empty file, which is an authoritative 'no pins',
        not first-launch. Never raises."""
        self._doc = {"version": SCHEMA_VERSION}
        try:
            self._path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            dev_mode.log_swallowed("SettingsStore.delete_file", exc)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_settings_store.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/settings_store.py tests/unit/test_settings_store.py
git commit -m "feat(settings): SettingsStore.has_section, set_section and delete_file

Needed by a store whose semantics are 'file present => authoritative'.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: `bridge_selection` — bridge registry, ship universe, labels

**Files:**
- Create: `engine/bridge_selection.py`
- Create: `tests/helpers/bridge_fixtures.py` (shared fake-install fixture — `tests/unit/` is NOT a package, so Task 6's test cannot import from `tests/unit/test_bridge_selection.py`; `tests/helpers/` is)
- Modify: `engine/missions/tgl_reader.py` (add `build_tgl_bytes`)
- Test: `tests/unit/test_bridge_selection.py`, `tests/missions/test_tgl_reader_roundtrip.py`

**Interfaces:**
- Produces:
  - `BridgeInfo(script_name: str, label: str)` namedtuple; `STOCK_BRIDGES: tuple[BridgeInfo, ...]`
  - `available_bridges() -> list[BridgeInfo]`; `is_available(script_name) -> bool`; `bridge_label(script_name) -> str`
  - `_scan_mod_bridges() -> list[BridgeInfo]` (stub `[]`)
  - `available_ships() -> list[str]` (stems sorted by label); `ship_label(stem) -> str`
  - `clear_caches() -> None` (tests)

- [ ] **Step 1: Write the failing tests**

First create `tests/helpers/bridge_fixtures.py` (shared with Task 6):

```python
"""Fake BC install + fake mods/ tree for the ship->bridge matrix tests.

`fake_install` points engine.paths at a tmp SDK scripts dir and game data
dir (five stock ship scripts, a Hardpoints/ subdir that must NOT count as a
ship, and a real Ships.tgl); `install_mod` builds a mods/ tree and installs
it through engine.mods.build_index so the overlay path runs for real.
"""
import pytest

from engine import mods, paths
from engine import bridge_selection as bs


def write_tgl(path, strings: dict):
    from engine.missions import tgl_reader
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(tgl_reader.build_tgl_bytes(strings))


@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    sdk_scripts = tmp_path / "sdkroot" / "Build" / "scripts"   # paths-guard: fake install tree
    game_root = tmp_path / "gameroot"                          # paths-guard: fake install tree
    (sdk_scripts / "ships" / "Hardpoints").mkdir(parents=True)
    for stem in ("Galaxy", "Sovereign", "Akira", "BirdOfPrey", "KessokLight"):
        (sdk_scripts / "ships" / f"{stem}.py").write_text("# ship\n")
    (sdk_scripts / "ships" / "__init__.py").write_text("")
    (sdk_scripts / "ships" / "Hardpoints" / "galaxy.py").write_text("# hp\n")
    write_tgl(game_root / "data" / "TGL" / "Ships.tgl",
              {"Galaxy": "Galaxy", "Sovereign": "Sovereign", "Akira": "Akira",
               "BirdOfPrey": "Bird of Prey", "KessokLight": "Light Cruiser"})
    monkeypatch.setattr(paths, "sdk_scripts", lambda: sdk_scripts)
    monkeypatch.setattr(paths, "game_asset", lambda rel: game_root / rel)
    mods.configure(None)
    bs.clear_caches()
    yield sdk_scripts, game_root
    mods.configure(None)
    bs.clear_caches()


def install_mod(tmp_path, name, files: dict):
    root = tmp_path / "mods"
    for rel, text in files.items():
        p = root / name / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    mods.configure(mods.build_index(root))
    bs.clear_caches()
```

Then create `tests/unit/test_bridge_selection.py`:

```python
"""engine.bridge_selection — registry, ship universe, labels."""
import pytest

from engine import bridge_selection as bs
from tests.helpers.bridge_fixtures import fake_install, install_mod   # noqa: F401


# ---- registry ---------------------------------------------------------------

def test_stock_bridges_are_galaxy_and_sovereign_with_bc_labels(fake_install):
    assert bs.available_bridges() == [
        bs.BridgeInfo("GalaxyBridge", "Galaxy"),
        bs.BridgeInfo("SovereignBridge", "Sovereign"),
    ]
    assert bs.is_available("SovereignBridge")
    assert not bs.is_available("VoyagerBridge")


def test_bridge_label_for_an_unknown_bridge_strips_one_trailing_bridge(fake_install):
    assert bs.bridge_label("VoyagerBridge") == "Voyager"
    assert bs.bridge_label("Voyager") == "Voyager"
    assert bs.bridge_label("GalaxyBridge") == "Galaxy"


@pytest.mark.xfail(strict=True,
                   reason="mod bridge scan is the follow-up feature; contract "
                          "fixed by the 2026-09-16 ship-bridge-matrix spec §1")
def test_mod_bridge_scan_keeps_only_modules_defining_CreateBridgeModel(
        fake_install, tmp_path):
    install_mod(tmp_path, "VoyBridge", {
        "scripts/Bridge/VoyagerBridge.py":
            "import App\ndef CreateBridgeModel(pBridgeSet):\n    pass\n",
        "scripts/Bridge/VoyagerMenuHandlers.py":
            "def CreateMenus():\n    pass\n",
        "scripts/Bridge/Characters/Foo.py":
            "def CreateBridgeModel(x):\n    pass\n",   # wrong depth: ignored
    })
    assert bs.available_bridges()[2:] == [bs.BridgeInfo("VoyagerBridge", "Voyager")]
    assert bs.is_available("VoyagerBridge")


# ---- ship universe ------------------------------------------------------------

def test_available_ships_are_top_level_ship_script_stems(fake_install):
    ships = bs.available_ships()
    assert "__init__" not in ships
    assert "galaxy" not in ships            # Hardpoints/galaxy.py is not a ship
    assert set(ships) == {"Galaxy", "Sovereign", "Akira", "BirdOfPrey", "KessokLight"}


def test_available_ships_sorted_by_label(fake_install):
    # labels: Akira, Bird of Prey, Galaxy, Light Cruiser, Sovereign
    assert bs.available_ships() == ["Akira", "BirdOfPrey", "Galaxy",
                                    "KessokLight", "Sovereign"]


def test_ship_label_from_tgl_with_stem_fallback(fake_install):
    assert bs.ship_label("BirdOfPrey") == "Bird of Prey"
    assert bs.ship_label("KessokLight") == "Light Cruiser"
    assert bs.ship_label("LCIntrepid") == "LCIntrepid"


def test_mod_ships_join_the_universe_in_the_authors_spelling(fake_install, tmp_path):
    install_mod(tmp_path, "Intrepid", {
        "scripts/Ships/LCIntrepid.py": "# mod ship\n",
        "scripts/Ships/Hardpoints/lcintrepid.py": "# hp\n",
    })
    assert "LCIntrepid" in bs.available_ships()
    assert "lcintrepid" not in bs.available_ships()


def test_a_mod_override_of_a_stock_ship_is_not_duplicated(fake_install, tmp_path):
    install_mod(tmp_path, "CGSov", {"scripts/ships/sovereign.py": "# replaces\n"})
    assert bs.available_ships().count("Sovereign") == 1
    assert "sovereign" not in bs.available_ships()


def test_missing_ships_tgl_does_not_raise(fake_install):
    _sdk, game_root = fake_install
    (game_root / "data" / "TGL" / "Ships.tgl").unlink()
    bs.clear_caches()
    assert bs.ship_label("Galaxy") == "Galaxy"
```

- [ ] **Step 2: Add a TGL writer (test support) and prove it round-trips**

Append to `engine/missions/tgl_reader.py` — the exact inverse of `_parse` above it (header `<5I` with the count in the 4th field; `count` TOC triples of which only the LAST triple's third field — the key-section byte size — is read; NUL-terminated ASCII keys; `<I` value size in UTF-16 CHARS then `\x00\x00`-terminated UTF-16-LE values; `<I` filename byte size then NUL-terminated ASCII filenames, one per key):

```python
def build_tgl_bytes(strings: dict, sounds: dict | None = None) -> bytes:
    """Inverse of _parse, for tests that need a real TGL on disk. Lives in
    this file so the two layouts cannot drift apart."""
    sounds = sounds or {}
    keys = list(strings)
    key_blob = b"".join(k.encode("ascii") + b"\x00" for k in keys)
    val_blob = b"".join(strings[k].encode("utf-16-le") + b"\x00\x00" for k in keys)
    file_blob = b"".join(sounds.get(k, "").encode("ascii") + b"\x00" for k in keys)
    header = struct.pack(_HEADER_FMT, 0, 0, 0, len(keys), 0)
    toc = b"".join(struct.pack("<3I", 0, 0, len(key_blob)) for _ in keys)
    return (header + toc + key_blob
            + struct.pack("<I", len(val_blob) // 2) + val_blob
            + struct.pack("<I", len(file_blob)) + file_blob)
```

Create `tests/missions/test_tgl_reader_roundtrip.py`:

```python
from engine.missions import tgl_reader


def test_build_tgl_bytes_round_trips_through_parse():
    data = tgl_reader.build_tgl_bytes(
        {"Galaxy": "Galaxy", "BirdOfPrey": "Bird of Prey", "Snd": "x"},
        sounds={"Snd": "sfx/x.wav"})
    got = tgl_reader._parse(data, source="test")
    assert got.strings == {"Galaxy": "Galaxy", "BirdOfPrey": "Bird of Prey", "Snd": "x"}
    assert got.sounds == {"Snd": "sfx/x.wav"}


def test_build_tgl_bytes_empty_parses_to_nothing():
    got = tgl_reader._parse(tgl_reader.build_tgl_bytes({}), source="test")
    assert got.strings == {}
```

Run: `uv run pytest tests/missions/test_tgl_reader_roundtrip.py -v` — expected PASS before moving on.

- [ ] **Step 3: Run to verify the new tests fail**

Run: `uv run pytest tests/unit/test_bridge_selection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'engine.bridge_selection'`.

- [ ] **Step 4: Implement the module (registry + ships + labels only)**

Create `engine/bridge_selection.py`:

```python
"""Which bridge goes with which player ship.

The mode-agnostic answer to "the player is flying <ship>; load which bridge?"
for any game mode that does not dictate one. Campaign and tutorial missions
call LoadBridge.Load("<literal>") themselves and never come here (override
by construction). QuickBattle consults it through install_quickbattle_hook.

Spec: docs/superpowers/specs/2026-09-16-ship-bridge-matrix-design.md

Three derived, never-persisted views -- the bridge registry, the ship
universe, display labels -- and one persisted thing, BridgePins over
bridges.json. Every path is resolved at call time (engine/paths.py rule).
"""
from __future__ import annotations

import re
from collections import namedtuple
from pathlib import Path
from typing import Optional

from engine import dev_mode, mods, paths

BridgeInfo = namedtuple("BridgeInfo", "script_name label")

# BC's own labels: the "Player Bridge" window buttons were the TGL strings
# "Galaxy" and "Sovereign" (data/TGL/QuickBattle/QuickBattle.tgl). The set
# folder names (DBridge / EBridge) never reach the UI.
STOCK_BRIDGES: tuple = (
    BridgeInfo("GalaxyBridge", "Galaxy"),
    BridgeInfo("SovereignBridge", "Sovereign"),
)

_SHIP_KEY_RE = re.compile(r"^ships/([^/]+)\.py$")

_cache: dict = {}


def clear_caches() -> None:
    """Tests only. Production memoises for the life of the process: the mod
    index is built once at boot and the SDK tree does not change mid-run."""
    _cache.clear()


def _cache_key(name: str):
    # Keyed on the mod index identity so a reconfigured overlay (tests, a
    # future hot reload) is never served a stale scan.
    return (name, id(mods.current()))


# ── Bridge registry ────────────────────────────────────────────────────────

def _scan_mod_bridges() -> list:
    """Mod-provided bridge config scripts. STUB: the follow-up feature fills
    this in. Contract (spec §1): walk mods.current().files for keys matching
    ^bridge/[^/]+\\.py$ with target == "sdk"; keep a module only if its source
    TEXT contains "def CreateBridgeModel(" (never import it); label via
    bridge_label(); stock script names are dropped (stock wins), logged once.
    """
    return []


def available_bridges() -> list:
    key = _cache_key("bridges")
    got = _cache.get(key)
    if got is None:
        stock_names = {b.script_name for b in STOCK_BRIDGES}
        got = list(STOCK_BRIDGES) + [b for b in _scan_mod_bridges()
                                     if b.script_name not in stock_names]
        _cache[key] = got
    return list(got)


def is_available(script_name: str) -> bool:
    return any(b.script_name == script_name for b in available_bridges())


def bridge_label(script_name: str) -> str:
    for b in STOCK_BRIDGES:
        if b.script_name == script_name:
            return b.label
    for b in available_bridges():
        if b.script_name == script_name:
            return b.label
    # A bridge we do not know (a removed mod, a hand-edit): strip one
    # trailing "Bridge" so the row still reads as a name.
    if script_name.endswith("Bridge") and len(script_name) > len("Bridge"):
        return script_name[:-len("Bridge")]
    return script_name


# ── Ship universe ──────────────────────────────────────────────────────────

def _stock_ship_stems() -> dict:
    """{folded stem: stem} for every top-level ships/*.py in the SDK."""
    out: dict = {}
    try:
        entries = list((paths.sdk_scripts() / "ships").iterdir())
    except OSError:
        return out
    for p in entries:
        if p.suffix.lower() != ".py" or not p.is_file():
            continue
        if p.stem == "__init__":
            continue
        out[p.stem.lower()] = p.stem
    return out


def _mod_ship_stems() -> dict:
    """{folded stem: author's stem} for every top-level ships/*.py a mod
    provides. Index keys are folded and scripts/-stripped; raw_rel keeps the
    author's spelling, which is what g_sPlayerType / CreatePlayerShip see."""
    out: dict = {}
    for key, mf in mods.current().files.items():
        if mf.target != "sdk":  # paths-guard: kind label
            continue
        m = _SHIP_KEY_RE.match(key)
        if m is None or m.group(1) == "__init__":
            continue
        out[m.group(1)] = Path(mf.raw_rel).stem
    return out


def available_ships() -> list:
    """Script stems of every ship the player could fly, sorted by label.
    A mod override of a stock ship keeps the STOCK spelling (one row)."""
    key = _cache_key("ships")
    got = _cache.get(key)
    if got is None:
        stock = _stock_ship_stems()
        merged = dict(stock)
        for folded, stem in _mod_ship_stems().items():
            if folded not in merged:
                merged[folded] = stem
        got = sorted(merged.values(), key=lambda s: (ship_label(s).lower(), s))
        _cache[key] = got
    return list(got)


def _ship_labels() -> dict:
    key = _cache_key("ship_labels")
    got = _cache.get(key)
    if got is None:
        got = {}
        try:
            from engine.missions.tgl_reader import read_tgl
            got = dict(read_tgl(paths.game_asset("data/TGL/Ships.tgl")).strings)
        except Exception as exc:          # missing/corrupt TGL: stems are fine
            dev_mode.log_swallowed("bridge_selection Ships.tgl", exc)
        _cache[key] = got
    return got


def ship_label(stem: str) -> str:
    """BC's display name for a ship script (Ships.tgl), else the stem."""
    return _ship_labels().get(stem) or stem
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_bridge_selection.py -v`
Expected: all PASS except the xfail (reported `XFAIL`). If the mod-override test fails because `paths.game_asset` is patched with a lambda but `mods.game_override` is consulted — it isn't in this module; if a `mods.classify` step is needed for `build_index`, do NOT add it: `build_index` alone populates `files`.

- [ ] **Step 6: Path-guard check**

Run: `uv run pytest tests/unit/test_path_indirection.py -v`
Expected: PASS (no `game`/`sdk` segments, no import-time paths).

- [ ] **Step 7: Commit**

```bash
git add engine/bridge_selection.py tests/unit/test_bridge_selection.py tests/helpers/bridge_fixtures.py engine/missions/tgl_reader.py tests/missions/test_tgl_reader_roundtrip.py
git commit -m "feat(bridge): bridge registry, ship universe and BC labels

engine/bridge_selection: stock bridges (Galaxy/Sovereign), a mod-scan seam
stubbed with its contract test xfail(strict), the ship universe from SDK +
mod overlay, and Ships.tgl labels with stem fallback.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: `BridgePins` — pins, resolution, `bridges.json`

**Files:**
- Modify: `engine/bridge_selection.py`
- Test: `tests/unit/test_bridge_selection.py`

**Interfaces:**
- Consumes: Task 2's `SettingsStore.has_section` / `delete_file`; Task 3's `is_available`, `bridge_label`, `available_ships`, `ship_label`.
- Produces:
  - `DEFAULT_PINS`, `DEFAULT_BRIDGE`, `default_bridges_path() -> Path`
  - `class DuplicateShip(ValueError)`, `class UnknownBridge(ValueError)`
  - `PinRow = namedtuple("PinRow", "ship ship_label bridge bridge_label ship_missing bridge_missing")`
  - `class BridgePins` with `__init__(store)`, `pins() -> dict`, `resolve(ship) -> str`, `add(ship, bridge)`, `remove(ship)`, `reset()`, `rows() -> list[PinRow]`, `unpinned_ships() -> list[str]`
  - `load_bridge_pins(path=None) -> BridgePins` (constructs + loads the store)

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/test_bridge_selection.py`:

```python
# ---- BridgePins ---------------------------------------------------------------

@pytest.fixture
def pins(fake_install, tmp_path):
    return bs.load_bridge_pins(tmp_path / "bridges.json")


def test_absent_file_yields_the_three_defaults(pins):
    assert pins.pins() == {"Galaxy": "GalaxyBridge",
                           "Sovereign": "SovereignBridge",
                           "Akira": "SovereignBridge"}
    assert pins.pins() is not bs.DEFAULT_PINS      # a copy, never the constant


def test_present_file_is_authoritative_even_when_empty(fake_install, tmp_path):
    p = tmp_path / "bridges.json"
    p.write_text('{"version": 1, "pins": {}}')
    pins = bs.load_bridge_pins(p)
    assert pins.pins() == {}
    assert pins.resolve("Galaxy") == "GalaxyBridge"   # default bridge, not default PIN


def test_resolve_pinned_unpinned_and_default(pins):
    assert pins.resolve("Akira") == "SovereignBridge"
    assert pins.resolve("BirdOfPrey") == "GalaxyBridge"
    assert pins.resolve("") == "GalaxyBridge"
    assert pins.resolve(None) == "GalaxyBridge"


def test_missing_bridge_falls_back_keeps_the_pin_and_logs_once(pins, capsys):
    pins.add("BirdOfPrey", "GalaxyBridge")
    # Simulate a removed mod: hand-edit the file behind the store.
    pins.store.set("pins", "BirdOfPrey", "VoyagerBridge")
    assert pins.resolve("BirdOfPrey") == "GalaxyBridge"
    assert pins.resolve("BirdOfPrey") == "GalaxyBridge"
    assert pins.pins()["BirdOfPrey"] == "VoyagerBridge"      # not pruned
    out = capsys.readouterr().out
    assert out.count("BirdOfPrey -> VoyagerBridge") == 1


def test_add_writes_the_whole_map_so_defaults_persist(pins, tmp_path):
    import json
    pins.add("BirdOfPrey", "SovereignBridge")
    doc = json.loads((tmp_path / "bridges.json").read_text())
    assert doc["pins"] == {"Galaxy": "GalaxyBridge",
                           "Sovereign": "SovereignBridge",
                           "Akira": "SovereignBridge",
                           "BirdOfPrey": "SovereignBridge"}


def test_remove_a_default_sticks(pins, tmp_path):
    pins.remove("Akira")
    again = bs.load_bridge_pins(tmp_path / "bridges.json")
    assert "Akira" not in again.pins()
    assert again.resolve("Akira") == "GalaxyBridge"


def test_add_rejects_duplicate_ship_and_unknown_bridge(pins):
    with pytest.raises(bs.DuplicateShip):
        pins.add("Galaxy", "SovereignBridge")
    with pytest.raises(bs.UnknownBridge):
        pins.add("BirdOfPrey", "VoyagerBridge")
    assert "BirdOfPrey" not in pins.pins()


def test_remove_unknown_ship_is_a_noop(pins):
    pins.remove("NotAShip")
    assert len(pins.pins()) == 3


def test_reset_deletes_the_file_and_restores_defaults(pins, tmp_path):
    pins.remove("Akira")
    assert (tmp_path / "bridges.json").exists()
    pins.reset()
    assert not (tmp_path / "bridges.json").exists()
    assert pins.pins() == bs.DEFAULT_PINS


def test_corrupt_file_is_quarantined_and_defaults_used(fake_install, tmp_path):
    p = tmp_path / "bridges.json"
    p.write_text("{not json")
    pins = bs.load_bridge_pins(p)
    assert pins.pins() == bs.DEFAULT_PINS
    assert (tmp_path / "bridges.json.corrupt").exists()


def test_rows_carry_labels_and_missing_flags(fake_install, tmp_path):
    p = tmp_path / "bridges.json"
    p.write_text('{"version": 1, "pins": {"Galaxy": "GalaxyBridge", '
                 '"LCIntrepid": "VoyagerBridge"}}')
    pins = bs.load_bridge_pins(p)
    rows = pins.rows()
    assert rows[0] == bs.PinRow("Galaxy", "Galaxy", "GalaxyBridge", "Galaxy",
                                False, False)
    assert rows[1] == bs.PinRow("LCIntrepid", "LCIntrepid", "VoyagerBridge",
                                "Voyager", True, True)


def test_rows_are_in_file_order(pins):
    assert [r.ship for r in pins.rows()] == ["Galaxy", "Sovereign", "Akira"]


def test_unpinned_ships_excludes_pinned(pins):
    assert pins.unpinned_ships() == ["BirdOfPrey", "KessokLight"]
    pins.add("BirdOfPrey", "GalaxyBridge")
    assert pins.unpinned_ships() == ["KessokLight"]


def test_default_bridges_path_sits_beside_settings_json():
    from engine import settings_store
    assert bs.default_bridges_path() == (
        settings_store.default_settings_path().parent / "bridges.json")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_selection.py -k "pins or Pins or rows or default_bridges_path or corrupt" -v`
Expected: FAIL with `AttributeError: module 'engine.bridge_selection' has no attribute 'load_bridge_pins'`.

- [ ] **Step 3: Implement**

Append to `engine/bridge_selection.py`:

```python
# ── Pins (persisted: bridges.json) ─────────────────────────────────────────

DEFAULT_PINS: dict = {
    "Galaxy": "GalaxyBridge",
    "Sovereign": "SovereignBridge",
    "Akira": "SovereignBridge",
}
DEFAULT_BRIDGE = "GalaxyBridge"
_PINS_SECTION = "pins"

PinRow = namedtuple("PinRow",
                    "ship ship_label bridge bridge_label ship_missing bridge_missing")


class DuplicateShip(ValueError):
    """add(): the ship already has a pin (edit = remove + add)."""


class UnknownBridge(ValueError):
    """add(): the bridge is not in available_bridges()."""


def default_bridges_path() -> Path:
    """Beside settings.json. Its own file so a player can back up / restore
    bridge pins without dragging graphics settings along (spec decision 6).
    A function, not a constant: the single seam to move for a read-only
    install dir, like settings_store.default_settings_path()."""
    from engine import settings_store
    return settings_store.default_settings_path().parent / "bridges.json"


class BridgePins:
    """The ship->bridge map over a SettingsStore at bridges.json.

    File absent  => a copy of DEFAULT_PINS.
    File present => its "pins" section, authoritative even when {}.
    Keys compare exactly as written: the panel always writes canonical
    script stems, so a restored file behaves as it did when saved.
    """

    def __init__(self, store):
        self.store = store
        self._warned: set = set()

    # -- read --
    def pins(self) -> dict:
        if not self.store.has_section(_PINS_SECTION):
            return dict(DEFAULT_PINS)
        raw = self.store._section(_PINS_SECTION)
        return {str(k): str(v) for k, v in raw.items() if isinstance(v, str)}

    def resolve(self, ship_name) -> str:
        """The bridge config script to load for `ship_name`. Never raises."""
        if not ship_name:
            return DEFAULT_BRIDGE
        bridge = self.pins().get(ship_name)
        if bridge is None:
            return DEFAULT_BRIDGE
        if not is_available(bridge):
            tag = (ship_name, bridge)
            if tag not in self._warned:
                self._warned.add(tag)
                print("[bridge_selection] pin %s -> %s is not available; "
                      "using %s" % (ship_name, bridge, DEFAULT_BRIDGE),
                      flush=True)
            return DEFAULT_BRIDGE
        return bridge

    def rows(self) -> list:
        """Panel rows in file order, with labels and missing flags. Nothing
        is pruned: a not-installed ship or an unavailable bridge is shown,
        not hidden (the file is backed up, restored and hand-edited)."""
        ships = set(available_ships())
        return [PinRow(ship, ship_label(ship), bridge, bridge_label(bridge),
                       ship not in ships, not is_available(bridge))
                for ship, bridge in self.pins().items()]

    def unpinned_ships(self) -> list:
        pinned = set(self.pins())
        return [s for s in available_ships() if s not in pinned]

    # -- write --
    def _write_all(self, mapping: dict) -> None:
        """Write the WHOLE map. The first edit of a fresh install materialises
        the defaults into the file, which is what lets a removed default
        stay removed on the next launch. set_section (not per-key set) so an
        empty map leaves a PRESENT empty section: authoritative "no pins"."""
        self.store.set_section(_PINS_SECTION, dict(mapping))

    def add(self, ship: str, bridge: str) -> None:
        current = self.pins()
        if ship in current:
            raise DuplicateShip(ship)
        if not is_available(bridge):
            raise UnknownBridge(bridge)
        current[ship] = bridge
        self._write_all(current)

    def remove(self, ship: str) -> None:
        current = self.pins()
        if ship not in current:
            return
        del current[ship]
        self._write_all(current)

    def reset(self) -> None:
        """Delete the file: back to genuine first-launch (the defaults)."""
        self.store.delete_file()


def load_bridge_pins(path=None) -> BridgePins:
    from engine.settings_store import SettingsStore
    store = SettingsStore(path if path is not None else default_bridges_path())
    store.load()
    return BridgePins(store)
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_bridge_selection.py tests/unit/test_settings_store.py -v`
Expected: all PASS (one XFAIL).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_selection.py tests/unit/test_bridge_selection.py
git commit -m "feat(bridge): BridgePins over bridges.json with fallback, rows and reset

Absent file => the three defaults; present => authoritative. A pinned
bridge that is not available falls back to GalaxyBridge, logs once, and
stays in the file so the panel can show it as missing.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: QuickBattle hook + host wiring

**Files:**
- Modify: `engine/bridge_selection.py` (add `install_quickbattle_hook`)
- Modify: `engine/host_loop.py` — `HostController.__init__` (~`:5194`), `_MissionLoader.load_quickbattle` (~`:5375`), the settings-store block in `run()` (~`:7954`)
- Test: `tests/host/test_quickbattle_bridge_hook.py`

**Interfaces:**
- Consumes: `BridgePins.resolve`, `load_bridge_pins`.
- Produces: `install_quickbattle_hook(qb_module, pins) -> bool` (True when installed, False when already present); `controller.bridge_pins: BridgePins | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/host/test_quickbattle_bridge_hook.py`:

```python
"""QuickBattle consults the ship->bridge matrix by a once-installed wrap of
RecreatePlayer, so every caller -- Initialize, StartSimulation2,
EndSimulation, ShipDestroyed -- resolves the matrix at the moment of use.
"""
import types

import pytest

from engine import bridge_selection as bs


class _Pins:
    def __init__(self, mapping):
        self.mapping = mapping
        self.calls = []

    def resolve(self, ship):
        self.calls.append(ship)
        return self.mapping.get(ship, "GalaxyBridge")


def _fake_qb():
    """A stand-in QuickBattle module: the globals + RecreatePlayer shape the
    hook touches, plus callers that reach RecreatePlayer through the module
    global exactly as the SDK does."""
    qb = types.ModuleType("QB")
    qb.g_sPlayerType = "Galaxy"
    qb.g_sBridgeType = "GalaxyBridge"
    qb.loaded = []

    def RecreatePlayer():
        qb.loaded.append(qb.g_sBridgeType)
        return "player"
    qb.RecreatePlayer = RecreatePlayer

    def StartSimulation2():
        return qb.RecreatePlayer()          # module-global lookup, like the SDK
    qb.StartSimulation2 = StartSimulation2
    return qb


def test_hook_sets_bridge_type_from_the_matrix_before_the_original_runs():
    qb = _fake_qb()
    pins = _Pins({"Akira": "SovereignBridge"})
    assert bs.install_quickbattle_hook(qb, pins) is True
    qb.g_sPlayerType = "Akira"
    assert qb.RecreatePlayer() == "player"
    assert qb.loaded == ["SovereignBridge"]
    assert qb.g_sBridgeType == "SovereignBridge"


def test_sdk_internal_callers_go_through_the_wrap():
    qb = _fake_qb()
    bs.install_quickbattle_hook(qb, _Pins({"Galaxy": "SovereignBridge"}))
    qb.StartSimulation2()
    assert qb.loaded == ["SovereignBridge"]


def test_a_pin_changed_between_recreations_is_honoured_by_the_second():
    qb = _fake_qb()
    pins = _Pins({"Galaxy": "GalaxyBridge"})
    bs.install_quickbattle_hook(qb, pins)
    qb.RecreatePlayer()
    pins.mapping["Galaxy"] = "SovereignBridge"
    qb.RecreatePlayer()
    assert qb.loaded == ["GalaxyBridge", "SovereignBridge"]


def test_install_is_idempotent():
    qb = _fake_qb()
    pins = _Pins({})
    assert bs.install_quickbattle_hook(qb, pins) is True
    assert bs.install_quickbattle_hook(qb, pins) is False
    qb.RecreatePlayer()
    assert pins.calls == ["Galaxy"]            # resolved once, not twice


def test_install_without_pins_is_a_noop():
    qb = _fake_qb()
    orig = qb.RecreatePlayer
    assert bs.install_quickbattle_hook(qb, None) is False
    assert qb.RecreatePlayer is orig


# ---- live cascade ------------------------------------------------------------

pytest.importorskip("_dauntless_host")


def test_load_quickbattle_installs_the_hook_every_time(monkeypatch, tmp_path):
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    controller.bridge_pins = bs.load_bridge_pins(tmp_path / "bridges.json")

    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB
    assert getattr(QB.RecreatePlayer, "_dauntless_bridge_hook", False)
    # Boot player is a Galaxy => the default pin => GalaxyBridge.
    assert QB.g_sBridgeType == "GalaxyBridge"

    # A mission swap re-imports the SDK; the hook must be back.
    controller.loader.load_quickbattle()
    import QuickBattle.QuickBattle as QB2
    assert getattr(QB2.RecreatePlayer, "_dauntless_bridge_hook", False)


def test_boot_with_a_galaxy_to_sovereign_pin_loads_the_sovereign_bridge(
        monkeypatch, tmp_path):
    from tests.host.test_quickbattle_boot import _fresh_quickbattle_loader
    hl, controller = _fresh_quickbattle_loader(monkeypatch)
    (tmp_path / "bridges.json").write_text(
        '{"version": 1, "pins": {"Galaxy": "SovereignBridge"}}')
    controller.bridge_pins = bs.load_bridge_pins(tmp_path / "bridges.json")

    controller.loader.load_quickbattle()
    import App
    bridge = App.BridgeSet_Cast(App.g_kSetManager.GetSet("bridge"))
    assert bridge.GetConfig() == "SovereignBridge"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/host/test_quickbattle_bridge_hook.py -v`
Expected: FAIL with `AttributeError: module 'engine.bridge_selection' has no attribute 'install_quickbattle_hook'`.

- [ ] **Step 3: Implement the hook**

Append to `engine/bridge_selection.py`:

```python
# ── QuickBattle consumer ───────────────────────────────────────────────────

def install_quickbattle_hook(qb_module, pins) -> bool:
    """Wrap QuickBattle.RecreatePlayer (once) so g_sBridgeType is resolved
    from the matrix at the moment of use.

    RecreatePlayer is the ONE chokepoint every QuickBattle player creation
    funnels through -- Initialize, StartSimulation2, EndSimulation,
    ShipDestroyed -- and it ends with LoadBridge.Load(g_sBridgeType)
    (QuickBattle.py:2928). The SDK calls it as a module global, so replacing
    the attribute reaches the two callers the host never sees. Precedent:
    engine/foundation/quickbattle._ensure_build_dialog_reinjects.

    Returns True when installed, False when already present or `pins` is
    None. Must be called on EVERY load_quickbattle: reset_sdk_globals
    re-imports the module on a mission swap.
    """
    if pins is None:
        return False
    orig = getattr(qb_module, "RecreatePlayer", None)
    if orig is None or getattr(orig, "_dauntless_bridge_hook", False):
        return False

    def _recreate_player_with_matrix_bridge(_orig=orig, _qb=qb_module, _pins=pins):
        _qb.g_sBridgeType = _pins.resolve(getattr(_qb, "g_sPlayerType", None))
        return _orig()

    _recreate_player_with_matrix_bridge._dauntless_bridge_hook = True
    qb_module.RecreatePlayer = _recreate_player_with_matrix_bridge
    return True
```

- [ ] **Step 4: Wire the controller and the loader**

In `engine/host_loop.py`, `HostController.__init__`, after the `self.realized_bridge_config` line from Task 1:

```python
        # The ship->bridge matrix (engine/bridge_selection.BridgePins). None
        # in harnesses that never load it; load_quickbattle then installs no
        # hook and the SDK's own g_sBridgeType default stands.
        self.bridge_pins: Any = None
```

In `_MissionLoader.load_quickbattle`, replace

```python
        import QuickBattle.QuickBattle as _QBGame
        _QBGame.Initialize(game)
```

— careful: the existing code imports `QuickBattle.QuickBattleGame as _QBGame`. Insert BEFORE that `_QBGame.Initialize(game)` line:

```python
        # Ship->bridge matrix: wrap RecreatePlayer before the cascade's
        # Initialize runs it, so even the boot player gets the pinned bridge.
        import QuickBattle.QuickBattle as _QB
        from engine import bridge_selection as _bs
        _bs.install_quickbattle_hook(_QB, self._c.bridge_pins)
```

In `run()`, in the settings block directly after `_store.load()` (~`:7955`):

```python
        from engine import bridge_selection as _bs
        controller.bridge_pins = _bs.load_bridge_pins()
```

**Ordering check:** `load_quickbattle` runs at ~`:7712`, BEFORE the settings block at ~`:7954`. The hook needs `controller.bridge_pins` at boot, so the `load_bridge_pins()` line must go **before** the `boot_quickbattle` branch — put it immediately before `init_audio_backend()` (~`:7708`), and leave the settings block alone. Add a comment there: `# Before load_quickbattle: its RecreatePlayer hook reads controller.bridge_pins.`

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/host/test_quickbattle_bridge_hook.py tests/host/test_quickbattle_boot.py tests/host/test_foundation_quickbattle_e2e.py -v`
Expected: all PASS. If `test_boot_with_a_galaxy_to_sovereign_pin_loads_the_sovereign_bridge` fails inside `LoadBridge.Load`'s different-config branch (`pOldMod.UnloadAnimations()` / `UnloadSounds()` / `GetRemoteCam()`), that is the first real finding of this feature: fix the shim surface it names (check `docs/stub_heatmap.md` first), add a regression test for it in this file, and note it in the commit.

- [ ] **Step 6: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add engine/bridge_selection.py engine/host_loop.py tests/host/test_quickbattle_bridge_hook.py
git commit -m "feat(quickbattle): resolve the player bridge from the matrix on every RecreatePlayer

install_quickbattle_hook wraps QuickBattle.RecreatePlayer once per load so
Initialize, StartSimulation2, EndSimulation and ShipDestroyed all get
g_sBridgeType = pins.resolve(g_sPlayerType) at the moment of use.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Bridges tab — Python side of `ConfigurationPanel`

**Files:**
- Modify: `engine/ui/configuration_panel.py` — `__init__` (~`:116-200`), `close` (~`:216`), `render_payload` (~`:231`), `dispatch_event` (~`:284-425`), `handle_input` (~`:436`), `_focusables` (~`:517`)
- Modify: `engine/host_loop.py` — `ConfigurationPanel(...)` construction (~`:7961`)
- Test: `tests/unit/test_configuration_panel_bridges.py`

**Interfaces:**
- Consumes: `BridgePins.rows/unpinned_ships/add/remove/reset`, `available_bridges`, `DuplicateShip`, `UnknownBridge`, `DEFAULT_BRIDGE`, `bridge_label`.
- Produces: constructor kwarg `bridge_pins=None`; payload key `bridges`; actions `bridge:ship:<stem>`, `bridge:bridge:<script>`, `bridge:add`, `bridge:remove:<stem>`, `reset:bridges`; focusable kinds `("bridge_remove", stem)`, `("bridge_ship", stem)`, `("bridge_pick", script)`, `("ctrl", "bridge_add")`, `("ctrl", "reset_bridges")`.

- [ ] **Step 1: Write the failing tests**

Create `tests/unit/test_configuration_panel_bridges.py`:

```python
"""Bridges tab of ConfigurationPanel: payload, actions, exclusion rule,
per-tab reset scope, focus order, and no-op construction without pins."""
import json
from unittest.mock import Mock

import pytest

from engine.ui.configuration_panel import ConfigurationPanel, SettingsSnapshot
from engine import bridge_selection as bs
from tests.helpers.bridge_fixtures import fake_install   # noqa: F401 (fixture)


def _make(pins=None, tabs=None):
    kwargs = dict(
        tabs=tabs or [("graphics", "Graphics"), ("bridges", "Bridges")],
        initial_settings=SettingsSnapshot(fov_deg=70),
        set_dust=Mock(), set_hdr=Mock(), set_rim=Mock(), set_aa_mode=Mock(),
        set_subtitles=Mock(), set_disable_annoying_dialogue=Mock(),
        set_ai_difficulty=Mock(), set_fov_rad=Mock(), set_shadows=Mock(),
        set_procedural_sky=Mock(), set_filmic=Mock(), set_motion_blur=Mock(),
        set_dof=Mock(), set_volumetric_nebulae=Mock(), set_nebula_lightning=Mock(),
        set_hdr_lens_flare=Mock(), set_ship_light_emitters=Mock(),
        set_camera_shake=Mock(), set_ambient_gradient=Mock(),
        bridge_pins=pins,
    )
    return ConfigurationPanel(**kwargs)


def _body(panel):
    return json.loads(panel.render_payload()[len("setConfigurationPanel("):-2])


@pytest.fixture
def pins(fake_install, tmp_path):
    return bs.load_bridge_pins(tmp_path / "bridges.json")


def test_without_pins_no_bridges_block_and_tab_dispatch_is_inert():
    p = _make(pins=None)
    p.open()
    assert "bridges" not in _body(p)
    assert p.dispatch_event("bridge:add") is False


def test_payload_lists_pins_unpinned_ships_and_bridges(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    b = _body(p)["bridges"]
    assert [r["ship"] for r in b["pins"]] == ["Galaxy", "Sovereign", "Akira"]
    assert b["pins"][2] == {"ship": "Akira", "ship_label": "Akira",
                            "bridge": "SovereignBridge", "bridge_label": "Sovereign",
                            "ship_missing": False, "bridge_missing": False}
    assert [s["id"] for s in b["ships"]] == ["BirdOfPrey", "KessokLight"]
    assert b["ships"][0]["label"] == "Bird of Prey"
    assert b["bridges_available"] == [{"id": "GalaxyBridge", "label": "Galaxy"},
                                      {"id": "SovereignBridge", "label": "Sovereign"}]
    assert b["add_ship"] is None
    assert b["add_bridge"] == "GalaxyBridge"        # first available preselected
    assert b["can_add"] is False
    assert b["default_bridge_label"] == "Galaxy"


def test_select_ship_then_add_pins_and_drops_it_from_the_list(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:ship:BirdOfPrey") is True
    assert _body(p)["bridges"]["can_add"] is True
    assert p.dispatch_event("bridge:bridge:SovereignBridge") is True
    assert p.dispatch_event("bridge:add") is True
    b = _body(p)["bridges"]
    assert pins.pins()["BirdOfPrey"] == "SovereignBridge"
    assert [s["id"] for s in b["ships"]] == ["KessokLight"]
    assert b["add_ship"] is None                    # selection cleared
    assert b["can_add"] is False


def test_add_without_a_ship_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:add") is False
    assert len(pins.pins()) == 3


def test_selecting_a_pinned_ship_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:ship:Galaxy") is False


def test_selecting_an_unknown_bridge_is_rejected(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:bridge:VoyagerBridge") is False


def test_remove_deletes_the_pin(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.dispatch_event("bridge:remove:Akira") is True
    assert "Akira" not in pins.pins()
    assert "Akira" in [s["id"] for s in _body(p)["bridges"]["ships"]]


def test_missing_rows_are_flagged_not_hidden(fake_install, tmp_path):
    f = tmp_path / "bridges.json"
    f.write_text('{"version": 1, "pins": {"LCIntrepid": "VoyagerBridge"}}')
    p = _make(bs.load_bridge_pins(f)); p.open(); p.dispatch_event("tab:bridges")
    row = _body(p)["bridges"]["pins"][0]
    assert row["ship_missing"] is True and row["bridge_missing"] is True
    assert row["bridge_label"] == "Voyager"


def test_reset_bridges_deletes_the_file_and_touches_nothing_else(pins, tmp_path):
    on_reset = Mock(return_value={})
    p = _make(pins); p._on_reset = on_reset
    p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:remove:Akira")
    assert (tmp_path / "bridges.json").exists()
    assert p.dispatch_event("reset:bridges") is True
    assert not (tmp_path / "bridges.json").exists()
    assert pins.pins() == bs.DEFAULT_PINS
    on_reset.assert_not_called()                     # settings.json untouched


def test_reset_bridges_without_pins_is_rejected():
    p = _make(None)
    assert p.dispatch_event("reset:bridges") is False


def test_focusables_mirror_the_rendered_rows(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p._focusables() == [
        ("tab", "graphics"), ("tab", "bridges"),
        ("bridge_remove", "Galaxy"), ("bridge_remove", "Sovereign"),
        ("bridge_remove", "Akira"),
        ("bridge_ship", "BirdOfPrey"), ("bridge_ship", "KessokLight"),
        ("bridge_pick", "GalaxyBridge"), ("bridge_pick", "SovereignBridge"),
        ("ctrl", "bridge_add"), ("ctrl", "reset_bridges"),
    ]


def test_leaving_the_tab_clears_the_add_selection(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    p.dispatch_event("bridge:ship:BirdOfPrey")
    p.dispatch_event("tab:graphics"); p.dispatch_event("tab:bridges")
    assert _body(p)["bridges"]["add_ship"] is None


def test_payload_is_not_repushed_when_nothing_changed(pins):
    p = _make(pins); p.open(); p.dispatch_event("tab:bridges")
    assert p.render_payload() is not None
    assert p.render_payload() is None
    p.dispatch_event("bridge:ship:BirdOfPrey")
    assert p.render_payload() is not None
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_configuration_panel_bridges.py -v`
Expected: FAIL with `TypeError: __init__() got an unexpected keyword argument 'bridge_pins'`.

- [ ] **Step 3: Implement the panel side**

In `engine/ui/configuration_panel.py`:

(a) Constructor: add the parameter after `input_map=None`:

```python
                 # Bridges tab: the ship->bridge matrix (engine.bridge_selection.
                 # BridgePins). Optional so existing construction/tests without
                 # a bridges tab still work; the tab is inert without it.
                 bridge_pins=None,
```

and in the body after `self._input_map = input_map`:

```python
        self._bridge_pins = bridge_pins
        self._bridge_add_ship: Optional[str] = None
        self._bridge_add_bridge: Optional[str] = None
```

(b) `close()`: add `self._bridge_add_ship = None`.

(c) Add a helper method after `_controls_rows`:

```python
    def _bridges_block(self) -> Optional[dict]:
        """The Bridges tab payload, or None when the panel has no pins."""
        if self._bridge_pins is None:
            return None
        from engine import bridge_selection as bs
        available = bs.available_bridges()
        if self._bridge_add_bridge is None and available:
            self._bridge_add_bridge = available[0].script_name
        unpinned = self._bridge_pins.unpinned_ships()
        return {
            "pins": [r._asdict() for r in self._bridge_pins.rows()],
            "ships": [{"id": s, "label": bs.ship_label(s)} for s in unpinned],
            "bridges_available": [{"id": b.script_name, "label": b.label}
                                  for b in available],
            "add_ship": self._bridge_add_ship,
            "add_bridge": self._bridge_add_bridge,
            "can_add": (self._bridge_add_ship is not None
                        and self._bridge_add_bridge is not None),
            "default_bridge_label": bs.bridge_label(bs.DEFAULT_BRIDGE),
        }
```

(d) `render_payload`: compute `bridges = self._bridges_block()` first; add `json.dumps(bridges, sort_keys=True) if bridges is not None else None` to the `snapshot` tuple; add `"bridges": bridges` to `payload` only when not None (`if bridges is not None: payload["bridges"] = bridges`).

(e) `dispatch_event`: insert BEFORE the `if action.startswith("reset:"):` branch:

```python
        # ── Bridges tab: the ship->bridge matrix ─────────────────────────────
        if action.startswith("bridge:"):
            if self._bridge_pins is None:
                return False
            from engine import bridge_selection as bs
            rest = action[len("bridge:"):]
            if rest.startswith("ship:"):
                ship = rest[len("ship:"):]
                if ship not in self._bridge_pins.unpinned_ships():
                    return False
                self._bridge_add_ship = ship
                return True
            if rest.startswith("bridge:"):
                bridge = rest[len("bridge:"):]
                if not bs.is_available(bridge):
                    return False
                self._bridge_add_bridge = bridge
                return True
            if rest == "add":
                if self._bridge_add_ship is None or self._bridge_add_bridge is None:
                    return False
                try:
                    self._bridge_pins.add(self._bridge_add_ship, self._bridge_add_bridge)
                except (bs.DuplicateShip, bs.UnknownBridge):
                    # Only reachable by a race with a hand-edit; the re-push
                    # shows the truth.
                    self._bridge_add_ship = None
                    return False
                self._bridge_add_ship = None
                return True
            if rest.startswith("remove:"):
                self._bridge_pins.remove(rest[len("remove:"):])
                return True
            return False
```

and change the reset branch to:

```python
        if action.startswith("reset:"):
            section = action[len("reset:"):]
            if section == "bridges":
                if self._bridge_pins is None:
                    return False
                self._bridge_pins.reset()      # deletes bridges.json; settings.json untouched
                self._bridge_add_ship = None
                return True
            if section not in ("graphics", "gameplay"):
                return False
            for field, value in self._on_reset(section).items():
                setattr(self._settings, field, value)
            return True
```

and in the `tab:` branch add `self._bridge_add_ship = None` next to the existing resets.

(f) `_focusables`: add a branch:

```python
        elif self._selected_tab == "bridges" and self._bridge_pins is not None:
            from engine import bridge_selection as bs
            out += [("bridge_remove", r.ship) for r in self._bridge_pins.rows()]
            out += [("bridge_ship", s) for s in self._bridge_pins.unpinned_ships()]
            out += [("bridge_pick", b.script_name) for b in bs.available_bridges()]
            out += [("ctrl", "bridge_add"), ("ctrl", "reset_bridges")]
```

(g) `handle_input`: add activate branches next to the existing ones:

```python
        elif activate and kind == "bridge_remove":
            self.dispatch_event("bridge:remove:" + target)
        elif activate and kind == "bridge_ship":
            self.dispatch_event("bridge:ship:" + target)
        elif activate and kind == "bridge_pick":
            self.dispatch_event("bridge:bridge:" + target)
        elif activate and kind == "ctrl" and target == "bridge_add":
            self.dispatch_event("bridge:add")
        elif activate and kind == "ctrl" and target == "reset_bridges":
            self.dispatch_event("reset:bridges")
```

(h) `engine/host_loop.py` construction: `tabs=[("graphics", "Graphics"), ("gameplay", "Gameplay"), ("controls", "Controls"), ("bridges", "Bridges")]` and `bridge_pins=controller.bridge_pins,` after `input_map=input_map,`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/unit/test_configuration_panel_bridges.py tests/unit/test_configuration_panel.py -v`
Expected: all PASS. (`test_js_graphics_focusables_match_python` and the gameplay twin must still pass — no graphics/gameplay list changed.)

- [ ] **Step 5: Commit**

```bash
git add engine/ui/configuration_panel.py engine/host_loop.py tests/unit/test_configuration_panel_bridges.py
git commit -m "feat(ui): Bridges tab model in ConfigurationPanel

Optional bridge_pins collaborator; payload block, bridge:* actions,
per-tab reset that deletes bridges.json only, focus order.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Bridges tab — JS + CSS

**Files:**
- Modify: `native/assets/ui-cef/js/configuration_panel.js` — `_cpFocusableList` (~`:74`), add `_cpRenderBridgesBody`, `setConfigurationPanel` body switch (~`:291`)
- Modify: `native/assets/ui-cef/css/configuration_panel.css`
- Test: `tests/unit/test_configuration_panel_bridges.py` (structural pins against the JS source, same technique as `test_js_graphics_focusables_match_python`)

**Interfaces:**
- Consumes: the `bridges` payload block from Task 6 and its action names.

- [ ] **Step 1: Write the failing structural tests**

Append to `tests/unit/test_configuration_panel_bridges.py`:

```python
# ---- JS mirrors -----------------------------------------------------------------

def _js_source():
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    return (root / "native/assets/ui-cef/js/configuration_panel.js").read_text()


def test_js_focusable_list_has_a_bridges_branch_in_python_order():
    """_cpFocusableList's bridges branch must push, in order: one
    bridge_remove per pin, one bridge_ship per unpinned ship, one bridge_pick
    per available bridge, then bridge_add and reset_bridges — the order
    ConfigurationPanel._focusables uses. Space on a focused row otherwise
    fires the wrong control."""
    import re
    src = _js_source()
    branch = re.search(r"selected_tab === 'bridges'\)\s*\{(.*?)\n    \}", src, re.S)
    assert branch, "no bridges branch in _cpFocusableList"
    body = branch.group(1)
    order = [m for m in re.findall(r"kind: '(\w+)'", body)]
    assert order == ["bridge_remove", "bridge_ship", "bridge_pick", "ctrl", "ctrl"]
    assert re.search(r"target: 'bridge_add'", body)
    assert re.search(r"target: 'reset_bridges'", body)


def test_js_renders_the_bridges_tab_and_dispatches_every_action():
    src = _js_source()
    assert "_cpRenderBridgesBody" in src
    assert "selected_tab === 'bridges'" in src
    for action in ("configuration/bridge:ship:", "configuration/bridge:bridge:",
                   "configuration/bridge:add", "configuration/bridge:remove:",
                   "configuration/reset:bridges"):
        assert action in src, action


def test_js_shows_missing_markers_and_never_uses_a_native_select():
    src = _js_source()
    assert "(missing)" in src
    assert "(ship not installed)" in src
    assert "<select" not in src.lower()
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_configuration_panel_bridges.py -k js -v`
Expected: FAIL (no bridges branch / no `_cpRenderBridgesBody`).

- [ ] **Step 3: Implement the JS**

In `native/assets/ui-cef/js/configuration_panel.js`:

(a) In `_cpFocusableList`, add after the `controls` branch:

```javascript
    } else if (state.selected_tab === 'bridges') {
        const b = state.bridges || {pins: [], ships: [], bridges_available: []};
        b.pins.forEach(p => out.push({kind: 'bridge_remove', target: p.ship}));
        b.ships.forEach(s => out.push({kind: 'bridge_ship', target: s.id}));
        b.bridges_available.forEach(x => out.push({kind: 'bridge_pick', target: x.id}));
        out.push({kind: 'ctrl', target: 'bridge_add'});
        out.push({kind: 'ctrl', target: 'reset_bridges'});
    }
```

(b) Add before `_cpUpdateCaptureOverlay`:

```javascript
// Bridges tab — the ship->bridge matrix. Pinned rows with Remove, then an
// add row: a scrollable ship list (unpinned ships only — Python enforces
// "each ship once" by never offering a pinned one) and a bridge picker.
// No native <select>: CEF OSR has no popup surface for one.
function _cpRenderBridgesBody(state, focusables) {
    const focused = focusables[state.focused] || {};
    const isFoc = (kind, target) => focused.kind === kind && focused.target === target;
    const b = state.bridges || {pins: [], ships: [], bridges_available: [],
                                add_ship: null, add_bridge: null, can_add: false,
                                default_bridge_label: ''};
    let html = '';

    html += '<div class="cp-group-header">Pinned</div>';
    if (b.pins.length === 0) {
        html += '<div class="sc-note">No ships pinned.</div>';
    }
    b.pins.forEach(function (p) {
        const shipTxt = escapeHtmlCP(p.ship_label)
                      + (p.ship_missing ? ' <span class="cp-bridges__missing">(ship not installed)</span>' : '');
        const bridgeTxt = escapeHtmlCP(p.bridge_label)
                        + (p.bridge_missing ? ' <span class="cp-bridges__missing">(missing)</span>' : '');
        html += '<div class="cp-row cp-bridges__pin' + (isFoc('bridge_remove', p.ship) ? ' cp-focused' : '') + '">'
              +     '<span class="cp-label cp-bridges__ship">' + shipTxt + '</span>'
              +     '<span class="cp-label cp-bridges__bridge">' + bridgeTxt + '</span>'
              +     '<button class="cp-toggle"'
              +        ' onclick="dauntlessEvent(\'configuration/bridge:remove:' + escapeHtmlCP(p.ship) + '\')">Remove</button>'
              + '</div>';
    });

    html += '<hr class="cp-divider">';
    html += '<div class="cp-group-header">Add a ship</div>';
    html += '<div class="cp-bridges__add">';
    html +=   '<div class="cp-bridges__ships">';
    if (b.ships.length === 0) {
        html += '<div class="sc-note">Every ship is pinned.</div>';
    }
    b.ships.forEach(function (s) {
        const sel = s.id === b.add_ship;
        html += '<div class="sc-row' + (sel ? ' sc-row--selected' : '')
              +   (isFoc('bridge_ship', s.id) ? ' cp-focused' : '') + '"'
              +   ' onclick="dauntlessEvent(\'configuration/bridge:ship:' + escapeHtmlCP(s.id) + '\')">'
              +   escapeHtmlCP(s.label)
              + '</div>';
    });
    html +=   '</div>';
    html +=   '<div class="cp-bridges__picker">';
    b.bridges_available.forEach(function (x) {
        const on = x.id === b.add_bridge;
        html += '<button class="cp-toggle cp-bridges__pick' + (on ? ' cp-toggle--on' : '')
              +   (isFoc('bridge_pick', x.id) ? ' cp-focused' : '') + '"'
              +   ' onclick="dauntlessEvent(\'configuration/bridge:bridge:' + escapeHtmlCP(x.id) + '\')">'
              +   escapeHtmlCP(x.label)
              + '</button>';
    });
    html +=     '<button class="cp-toggle cp-bridges__addbtn' + (b.can_add ? ' cp-toggle--on' : ' cp-toggle--disabled')
          +       (isFoc('ctrl', 'bridge_add') ? ' cp-focused' : '') + '"'
          +       (b.can_add ? ' onclick="dauntlessEvent(\'configuration/bridge:add\')"' : ' disabled')
          +     '>Add</button>';
    html +=   '</div>';
    html += '</div>';

    html += '<div class="sc-note">Ships without a pin use the '
          + escapeHtmlCP(b.default_bridge_label) + ' bridge. '
          + 'Changes apply the next time your ship is created.</div>';

    html += _cpResetRow('bridges', isFoc('ctrl', 'reset_bridges'));
    return html;
}
```

(c) In `setConfigurationPanel`, add the branch:

```javascript
        } else if (state.selected_tab === 'bridges') {
            body.innerHTML = _cpRenderBridgesBody(state, focusables);
```

(d) `CP_RESET_TARGETS` (`:33`) becomes `{graphics: 'reset_graphics', gameplay: 'reset_gameplay', bridges: 'reset_bridges'}`. The graphics/gameplay `.concat([CP_RESET_TARGETS.x])` lines are untouched; the bridges branch in `_cpFocusableList` pushes `'reset_bridges'` literally (a) so the structural test can read it.

- [ ] **Step 4: CSS**

Append to `native/assets/ui-cef/css/configuration_panel.css`:

```css
/* Bridges tab — ship->bridge matrix. Reuses cp-row/cp-toggle/sc-row; only
   the two-column add area and the missing marker are new. */
.cp-bridges__pin .cp-bridges__ship   { flex: 1 1 40%; }
.cp-bridges__pin .cp-bridges__bridge { flex: 1 1 40%; }
.cp-bridges__missing { color: #d85e56; font-size: 12px; letter-spacing: 0.04em; }

.cp-bridges__add {
    display: flex;
    gap: 16px;
    min-height: 0;
}
.cp-bridges__ships {
    flex: 1 1 55%;
    max-height: 180px;
    overflow-y: auto;
    border: 1px solid rgba(255, 255, 255, 0.12);
}
.cp-bridges__picker {
    flex: 1 1 45%;
    display: flex;
    flex-direction: column;
    gap: 6px;
}
.cp-bridges__pick { text-align: left; }
.cp-bridges__addbtn { margin-top: auto; }
.cp-toggle--disabled { opacity: 0.4; cursor: default; }
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/unit/test_configuration_panel_bridges.py tests/unit/test_configuration_panel.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the gate**

Run: `scripts/check_tests.sh`
Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add native/assets/ui-cef/js/configuration_panel.js native/assets/ui-cef/css/configuration_panel.css tests/unit/test_configuration_panel_bridges.py
git commit -m "feat(ui): render the Bridges tab (pinned rows, ship list, bridge picker)

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: Docs — CLAUDE.md row, spec status, live-verification checklist

**Files:**
- Modify: `CLAUDE.md` (key reference table)
- Modify: `docs/superpowers/specs/2026-09-16-ship-bridge-matrix-design.md` (Status line)

- [ ] **Step 1: CLAUDE.md row**

Add to the key-reference table in `CLAUDE.md`, after the Manual Aim row:

```markdown
| Ship → bridge matrix (auto player bridge) | `engine/bridge_selection.py`, `bridges.json` (beside `settings.json`), `docs/superpowers/specs/2026-09-16-ship-bridge-matrix-design.md` | The DEFAULT bridge-for-ship mechanism for any mode that doesn't dictate one. `BridgePins.resolve(ship)` → bridge config script; absent file ⇒ Galaxy/Sovereign/Akira defaults, present ⇒ authoritative. QuickBattle consumes it via a once-per-load wrap of `RecreatePlayer` (`install_quickbattle_hook`) so all four SDK callers resolve at use. Campaign/tutorial `LoadBridge.Load("<literal>")` override by construction — do NOT hook `LoadBridge.Load`. A runtime bridge swap is re-realised per tick by `_reconcile_bridge_config` (host_loop) on a `BridgeSet.GetConfig()` change. Labels are BC's (*Galaxy*/*Sovereign*, `Ships.tgl`), never DBridge/EBridge. `_scan_mod_bridges` is a STUB with an `xfail(strict)` contract test. |
```

- [ ] **Step 2: Spec status**

Change the spec's Status line to:

```markdown
**Status:** implemented by docs/superpowers/plans/2026-09-16-ship-bridge-matrix.md; awaiting live verification (§4 Live verification, items 1–5).
```

- [ ] **Step 3: Gate and commit**

Run: `scripts/check_tests.sh` — exit 0.

```bash
git add CLAUDE.md docs/superpowers/specs/2026-09-16-ship-bridge-matrix-design.md
git commit -m "docs: ship->bridge matrix reference row and spec status

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Live verification (Mark — NOT done by the executor)

After Task 8, the branch is code-complete but the spec's §4 live list (1–5) is
the real gate: (1) Galaxy→Sovereign pin, boot QuickBattle → EBridge after the
boot double-load, officers seated, viewscreen live; (2) Set As Player Ship →
Akira mid-session, bridge follows; (3) End Combat reverts ship and bridge;
(4) remove the Akira pin, relaunch, Akira gets DBridge; (5) hand-edit
`bridges.json` to a bogus bridge → *(missing)* in the panel, DBridge loads,
one `[bridge_selection]` line at boot.
