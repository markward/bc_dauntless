# SDK-Driven Bridge Initialization — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hardcoded bridge-crew/placement shortcut with the real SDK `LoadBridge.Load(name)` sequence, running it end-to-end against **loud, control-flow-correct stubs**, proven by a headless test.

**Architecture:** Stop shadowing the SDK's `LoadBridge.py` with our root shim; let the real `sdk/Build/scripts/LoadBridge.py` run. Add explicit loud stubs in `engine/appc/` for the missing Appc surface (`BridgeSet` + factories, `BridgeObjectClass`/`ViewScreenObject`/`ZoomCameraObjectClass`, `g_kModelManager`) — explicit module attributes that **shadow** App.py's permissive `_NamedStub` catch-all and are control-flow-correct (e.g. `BridgeSet_Cast` returns `None` when there is no bridge set). Each stub announces loudly to the terminal on call; an end-of-load summary lists which stubs still need fleshing out. Delete the shortcut. Keep the SP1/SP2 skinned renderer + `compose_officer_model` untouched.

**Scope of THIS plan:** spec steps 1–2 — cleanup + "runs end-to-end on loud stubs," with a passing headless test. Faithful replacement of the bridge model, officer placement, viewscreen, and camera (spec steps 3–6) are **follow-on plans**. During this plan's intermediate state the live bridge will render *without* the SDK-driven model/officers — that is the expected, loud, stub-summary-tracked state.

**Tech Stack:** Python 3 (engine shim), pytest (focused subsets only — the full suite OOMs the host), C++/CMake (placement_map deletion + `dauntless` rebuild).

**Reference spec:** `docs/superpowers/specs/2026-06-15-sdk-driven-bridge-init-design.md`

---

## Key facts the implementer must know

- **App.py resolves every missing symbol via a module-level `__getattr__` → `_NamedStub`** (App.py:1426-1427). `_NamedStub` is truthy, chainable, and silently swallows calls. An **explicit module attribute** (e.g. `BridgeSet_Create = ...` via an import) takes precedence over `__getattr__`, so registering our stubs in App.py shadows the catch-all. This is why the stubs must be registered explicitly.
- **`SetClass.__getattr__`** (engine/appc/sets.py:83-88) likewise returns a chainable truthy `_RendererStub` for unknown methods. So `BridgeSet` must **override** the methods we want to be loud (`IsSameConfig`, `GetConfig`/`SetConfig`, `GetViewScreen`/`SetViewScreen`, `DeleteCameraFromSet`) — otherwise they no-op silently.
- **There is already a silent `_StubTracker`** in App.py (line 1213) used for color/analysis, mission-gated. Our loud layer is **separate** (`engine/appc/_stub_trace.py`) and unconditional — do not conflate them.
- **The real SDK `LoadBridge.Load(sBridgeConfigScript)` assumes a live Game** (`App.Game_GetCurrentGame()` is non-None — it calls `pGame.AddPythonFuncHandlerForInstance`). It must only be called during mission load, never the host's eager pre-game preview.
- **Never run the full pytest suite** (it uses >100 GB RAM and freezes macOS). Run only the specific test files/functions named in each task.
- **C++ binding edits require a full `dauntless` rebuild** (`cmake --build build -j`); `host_bindings.cc` compiles into both the binary and the `_dauntless_host` module.

---

## File Structure

**New:**
- `engine/appc/_stub_trace.py` — loud stub announcer + end-of-load summary (one responsibility: terminal-visible "not yet implemented" tracking).
- `engine/appc/bridge_set.py` — `BridgeSet` (loud subclass of `SetClass`) + the bridge object/viewscreen/camera/model-manager loud stubs + factory functions.
- `tests/unit/test_stub_trace.py`, `tests/unit/test_bridge_set_stubs.py`, `tests/integration/test_sdk_bridge_load.py`.

**Modified:**
- `App.py` — register the new symbols (explicit imports + `g_kModelManager`); add `Light.UnilluminateEntireSet` no-op (in engine/appc/lights.py).
- `engine/host_loop.py` — route mission-load to the real `LoadBridge.Load`; remove `_place_bridge_officers`, `_BRIDGE_NIF_MAP`, the no-arg eager preload; source the camera's bridge name from the bridge set's config instead of `LoadBridge.LAST_REQUESTED`.
- `tests/conftest.py` — drop the `LoadBridge._reset_crew_populated` reset / stale references.

**Deleted:**
- Root `LoadBridge.py` (un-shadow → SDK `LoadBridge.py` runs).
- `engine/bridge_officers.py::place_officers`/`_place_one`/`resolve_placement`/`_BRIDGE_IDENTITY_MAT4` (delete the file if nothing else remains).
- `native/src/renderer/placement_map.{h,cc}` + `native/tests/renderer/placement_map_test.cc` + their CMake lines + the `resolve_placement` binding in `native/src/host/host_bindings.cc`.
- Shortcut-specific tests: `tests/unit/test_bridge_officers.py`, `tests/unit/test_bridge_crew_population.py` (replaced by the new end-to-end test).

---

## Task 1: Loud stub-trace infrastructure

**Files:**
- Create: `engine/appc/_stub_trace.py`
- Test: `tests/unit/test_stub_trace.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_stub_trace.py
import engine.appc._stub_trace as st


def setup_function(_):
    st.reset()


def test_stub_call_records_and_is_loud(capsys):
    st.stub_call("BridgeObjectClass_Create", "nif=DBridge.nif")
    captured = capsys.readouterr()
    assert "BRIDGE-STUB" in captured.err
    assert "BridgeObjectClass_Create" in captured.err
    assert "NOT YET IMPLEMENTED" in captured.err
    assert "BridgeObjectClass_Create" in st.fired()


def test_summary_lists_each_fired_symbol_once(capsys):
    st.stub_call("BridgeSet_Create")
    st.stub_call("BridgeSet_Create")          # same symbol twice
    st.stub_call("ViewScreenObject_Create")
    capsys.readouterr()                         # clear per-call banners
    st.dump_stub_summary()
    err = capsys.readouterr().err
    assert "2 stub(s)" in err
    assert "BridgeSet_Create" in err
    assert "ViewScreenObject_Create" in err


def test_summary_when_none_fired_says_faithful(capsys):
    st.dump_stub_summary()
    assert "faithful" in capsys.readouterr().err


def test_reset_clears_fired():
    st.stub_call("BridgeSet_Create")
    st.reset()
    assert st.fired() == set()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_stub_trace.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc._stub_trace'`.

- [ ] **Step 3: Write minimal implementation**

```python
# engine/appc/_stub_trace.py
"""Loud, terminal-visible tracking for bridge-init Appc stubs.

Distinct from App.py's silent, mission-gated `_StubTracker` (color/analysis).
Every bridge stub calls `stub_call(symbol, detail)` on entry, which prints a
LOUD banner to both stderr and stdout and records the symbol. After
LoadBridge.Load returns, `dump_stub_summary()` prints the set of stubs that
fired — the running "what still needs fleshing out" to-do list. When the
summary prints nothing, the bridge-init sequence is fully faithful.
"""
import sys

_FIRED: set[str] = set()


def stub_call(symbol: str, detail: str = "") -> None:
    banner = "\n*** [BRIDGE-STUB] %s — NOT YET IMPLEMENTED %s\n" % (symbol, detail)
    # Print to BOTH streams so the banner shows regardless of how the host
    # routes output; flush so it is not buffered behind later native logging.
    sys.stderr.write(banner)
    sys.stderr.flush()
    try:
        sys.stdout.write(banner)
        sys.stdout.flush()
    except Exception:
        # stdout may be unavailable in some host contexts; stderr is enough.
        pass
    _FIRED.add(symbol)


def fired() -> set[str]:
    return set(_FIRED)


def dump_stub_summary() -> None:
    if not _FIRED:
        sys.stderr.write(
            "\n*** [BRIDGE-STUB] none fired — bridge init is faithful\n")
        sys.stderr.flush()
        return
    sys.stderr.write(
        "\n*** [BRIDGE-STUB] SUMMARY — %d stub(s) still need fleshing out:\n"
        % len(_FIRED))
    for symbol in sorted(_FIRED):
        sys.stderr.write("***   - %s\n" % symbol)
    sys.stderr.flush()


def reset() -> None:
    _FIRED.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_stub_trace.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/_stub_trace.py tests/unit/test_stub_trace.py
git commit -m "feat(bridge): loud stub-trace infrastructure

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: BridgeSet + bridge-object/viewscreen/camera/model-manager loud stubs

**Files:**
- Create: `engine/appc/bridge_set.py`
- Test: `tests/unit/test_bridge_set_stubs.py`

**Context:** These stubs must be *control-flow-correct* (the real SDK `Load` branches on their return values), and *loud* (each call announces via `_stub_trace.stub_call`). `BridgeSet` subclasses the real `SetClass` so crew creation / `GetObject` / `CreateAmbientLight` all work for real; it only overrides the bridge-specific config/viewscreen/camera-delete methods so they are loud + stateful instead of silently no-oping through `SetClass.__getattr__`. The camera stub carries `PushCameraMode`/`GetNamedCameraMode` because the SDK calls them as **methods on the camera** (`pCamera.PushCameraMode(pCamera.GetNamedCameraMode(...))`, GalaxyBridge.py:66), not as module functions.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_bridge_set_stubs.py
import engine.appc._stub_trace as st
from engine.appc.bridge_set import (
    BridgeSet, BridgeSet_Create, BridgeSet_Cast,
    BridgeObjectClass_Create, ViewScreenObject_Create,
    ZoomCameraObjectClass_Create, ZoomCameraObjectClass_GetObject,
    ModelManager,
)
from engine.appc.sets import SetClass


def setup_function(_):
    st.reset()


def test_create_returns_bridgeset_and_is_a_setclass():
    pset = BridgeSet_Create()
    assert isinstance(pset, BridgeSet)
    assert isinstance(pset, SetClass)          # crew creation path works for real
    assert "BridgeSet_Create" in st.fired()


def test_cast_returns_none_for_non_bridgeset():
    # Critical: the real Load() branches `if BridgeSet_Cast(...) == None:`.
    assert BridgeSet_Cast(None) is None
    assert BridgeSet_Cast(SetClass()) is None
    bs = BridgeSet_Create()
    assert BridgeSet_Cast(bs) is bs


def test_config_round_trips_and_is_same_config():
    bs = BridgeSet_Create()
    assert bs.IsSameConfig("GalaxyBridge") == 0     # nothing set yet
    bs.SetConfig("GalaxyBridge")
    assert bs.GetConfig() == "GalaxyBridge"
    assert bs.IsSameConfig("GalaxyBridge")          # truthy
    assert bs.IsSameConfig("SovereignBridge") == 0


def test_viewscreen_round_trips():
    bs = BridgeSet_Create()
    assert bs.GetViewScreen() is None
    vs = ViewScreenObject_Create("vs.nif")
    bs.SetViewScreen(vs, "viewscreen")
    assert bs.GetViewScreen() is vs


def test_bridge_object_stub_supports_sdk_calls():
    obj = BridgeObjectClass_Create("DBridge.nif")
    # GalaxyBridge.CreateBridgeModel calls these — must not raise.
    obj.SetTranslateXYZ(0.0, 0.0, 0.0)
    obj.SetAngleAxisRotation(0.0, 1.0, 0.0, 0.0)
    assert obj.GetPropertySet() is not None
    assert "BridgeObjectClass_Create" in st.fired()


def test_camera_stub_supports_sdk_calls():
    cam = ZoomCameraObjectClass_Create(0.0, 1.0, 2.0, 1.57, 0.0, 0.0, 1.0, "maincamera")
    cam.SetMinZoom(0.64)
    cam.SetMaxZoom(1.0)
    cam.SetZoomTime(0.375)
    cam.PushCameraMode(cam.GetNamedCameraMode("GalaxyBridgeCaptain"))
    cam.Update(0.0)
    cam.SetTranslateXYZ(0.0, 1.0, 2.0)
    assert "ZoomCameraObjectClass_Create" in st.fired()


def test_camera_get_object_returns_added_camera():
    bs = BridgeSet_Create()
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    bs.AddCameraToSet(cam, "maincamera")
    assert ZoomCameraObjectClass_GetObject(bs, "maincamera") is cam


def test_model_manager_load_model_is_loud_but_noop():
    mm = ModelManager()
    assert mm.LoadModel("DBridge.nif", None, "env/") is None
    assert "g_kModelManager.LoadModel" in st.fired()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.appc.bridge_set'`.

- [ ] **Step 3: Write minimal implementation**

```python
# engine/appc/bridge_set.py
"""Loud, control-flow-correct stubs for the SDK bridge-load sequence.

The real sdk/Build/scripts/LoadBridge.py + Bridge/<name>.py call a swath of
Appc surface that does not yet exist in our shim. Rather than let App.py's
permissive `_NamedStub` swallow them silently (and break control flow —
`BridgeSet_Cast` returning a truthy stub makes Load skip crew creation), we
register explicit stubs here. Each announces via `_stub_trace.stub_call` and
returns control-flow-correct values, so the sequence runs end-to-end and the
end-of-load summary lists exactly what still needs faithful implementation.

These are registered into the `App` namespace by App.py (explicit module
attributes shadow App.py's `__getattr__` catch-all).
"""
from engine.appc import _stub_trace
from engine.appc.sets import SetClass


class _LoudStub:
    """A truthy, chainable object that announces the first time it is created.

    Used for engine objects (bridge object, viewscreen, camera) whose methods
    the SDK calls but whose behaviour is deferred. Method calls return self so
    chains like `pViewScreen.GetRemoteCam()` don't crash. Distinct from App.py's
    silent `_NamedStub` only in that creation is announced by the factory.
    """
    def __getattr__(self, name):
        return lambda *a, **k: None
    def __bool__(self):
        return True


class BridgeObjectClass(_LoudStub):
    def __init__(self, nif):
        self._nif = nif
        # A property-set object the SDK fetches via GetPropertySet(); return a
        # chainable stub so DBridgeProperties.LoadPropertySet(pPropertySet) runs.
        self._property_set = _LoudStub()
    def GetPropertySet(self):
        return self._property_set
    def SetTranslateXYZ(self, x, y, z):
        return None
    def SetAngleAxisRotation(self, a, x, y, z):
        return None


class ViewScreenObject(_LoudStub):
    def __init__(self, nif):
        self._nif = nif


class ZoomCameraObjectClass(_LoudStub):
    def __init__(self, x, y, z, qw, qx, qy, qz, name):
        self._name = name
    def SetMinZoom(self, v): return None
    def SetMaxZoom(self, v): return None
    def SetZoomTime(self, v): return None
    def GetNamedCameraMode(self, name):
        return _LoudStub()
    def PushCameraMode(self, mode): return None
    def Update(self, t): return None
    def SetTranslateXYZ(self, x, y, z): return None


class ModelManager:
    def LoadModel(self, path, a=None, env=None):
        _stub_trace.stub_call("g_kModelManager.LoadModel", "path=%s" % path)
        return None


class BridgeSet(SetClass):
    """The bridge SetClass. Crew/light/object registration is inherited REAL
    from SetClass; only the bridge-config/viewscreen/camera-delete surface is
    overridden so it is loud + stateful instead of silently stubbed."""
    def __init__(self):
        super().__init__()
        self._config = ""
        self._viewscreen = None

    def IsSameConfig(self, name):
        _stub_trace.stub_call("BridgeSet.IsSameConfig", "name=%s" % name)
        return 1 if self._config == name else 0

    def GetConfig(self):
        _stub_trace.stub_call("BridgeSet.GetConfig")
        return self._config

    def SetConfig(self, name):
        _stub_trace.stub_call("BridgeSet.SetConfig", "name=%s" % name)
        self._config = name

    def GetViewScreen(self):
        _stub_trace.stub_call("BridgeSet.GetViewScreen")
        return self._viewscreen

    def SetViewScreen(self, viewscreen, name="viewscreen"):
        _stub_trace.stub_call("BridgeSet.SetViewScreen", "name=%s" % name)
        self._viewscreen = viewscreen
        self.AddObjectToSet(viewscreen, name)

    def DeleteCameraFromSet(self, name):
        _stub_trace.stub_call("BridgeSet.DeleteCameraFromSet", "name=%s" % name)
        self.RemoveCameraFromSet(name)


def BridgeSet_Create():
    _stub_trace.stub_call("BridgeSet_Create")
    return BridgeSet()


def BridgeSet_Cast(obj):
    # Control-flow-correct: Load() does `if BridgeSet_Cast(GetSet("bridge")) == None`.
    return obj if isinstance(obj, BridgeSet) else None


def BridgeObjectClass_Create(nif):
    _stub_trace.stub_call("BridgeObjectClass_Create", "nif=%s" % nif)
    return BridgeObjectClass(nif)


def ViewScreenObject_Create(nif):
    _stub_trace.stub_call("ViewScreenObject_Create", "nif=%s" % nif)
    return ViewScreenObject(nif)


def ZoomCameraObjectClass_Create(x, y, z, qw, qx, qy, qz, name):
    _stub_trace.stub_call("ZoomCameraObjectClass_Create", "name=%s" % name)
    return ZoomCameraObjectClass(x, y, z, qw, qx, qy, qz, name)


def ZoomCameraObjectClass_GetObject(pSet, name):
    # The camera was added to the set via AddCameraToSet; return it (or a loud
    # stub if not present so ConfigureCharacters' SetTranslateXYZ doesn't crash).
    cam = pSet.GetCamera(name) if pSet is not None else None
    if cam is None:
        _stub_trace.stub_call("ZoomCameraObjectClass_GetObject", "name=%s" % name)
        return _LoudStub()
    return cam
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set_stubs.py
git commit -m "feat(bridge): loud control-flow-correct BridgeSet + bridge-object stubs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Register bridge stubs in App.py + Light.UnilluminateEntireSet

**Files:**
- Modify: `App.py` (add explicit imports near the other `from engine.appc...` imports, ~line 72; add `g_kModelManager` near the manager instantiations, ~line 562)
- Modify: `engine/appc/lights.py` (add `UnilluminateEntireSet` no-op to the `Light` class)
- Test: `tests/unit/test_app_bridge_symbols.py`

**Context:** The new symbols must be **explicit module attributes** of `App` so they beat App.py's `__getattr__` catch-all. The SDK's `CreateAndPopulateBridgeSet` calls `pBridgeSet.GetLight("ambientlight1").UnilluminateEntireSet()` — `GetLight` returns a real `Light`, which currently has no such method (it would raise, not stub), so add a no-op.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_app_bridge_symbols.py
import App
from engine.appc.bridge_set import BridgeSet


def test_app_exposes_bridge_factories():
    assert App.BridgeSet_Cast(None) is None              # not a _NamedStub
    bs = App.BridgeSet_Create()
    assert isinstance(bs, BridgeSet)
    assert App.BridgeSet_Cast(bs) is bs


def test_app_model_manager_present():
    # Real attribute, not the _NamedStub catch-all.
    assert App.g_kModelManager.LoadModel("x.nif", None, "env/") is None


def test_light_unilluminate_is_noop():
    bs = App.BridgeSet_Create()
    bs.CreateAmbientLight(1.0, 1.0, 1.0, 0.7, "ambientlight1")
    light = bs.GetLight("ambientlight1")
    assert light is not None
    light.UnilluminateEntireSet()        # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_app_bridge_symbols.py -v`
Expected: FAIL — `App.BridgeSet_Cast(None)` returns a truthy `_NamedStub` (not `None`), so the first assert fails; `UnilluminateEntireSet` raises `AttributeError`.

- [ ] **Step 3a: Add the imports + manager to App.py**

Near the existing `from engine.appc.sets import SetClass, SetManager, SetClass_Create, SetClass_GetNull` (App.py:72), add:

```python
from engine.appc.bridge_set import (
    BridgeSet,
    BridgeSet_Create,
    BridgeSet_Cast,
    BridgeObjectClass,
    BridgeObjectClass_Create,
    ViewScreenObject,
    ViewScreenObject_Create,
    ZoomCameraObjectClass,
    ZoomCameraObjectClass_Create,
    ZoomCameraObjectClass_GetObject,
    ModelManager,
)
```

Near the manager instantiations (App.py:562, where `g_kSetManager = SetManager()` is), add:

```python
g_kModelManager = ModelManager()
```

- [ ] **Step 3b: Add the no-op to Light**

In `engine/appc/lights.py`, find the `class Light` definition and add:

```python
    def UnilluminateEntireSet(self):
        """SDK LoadBridge.CreateAndPopulateBridgeSet calls this on the bridge
        ambient light. Renderer-internal in original BC; no-op in the shim."""
        return None
```

(If `Light` already has a permissive `__getattr__`, this explicit no-op is still preferred for clarity — add it regardless.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_app_bridge_symbols.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add App.py engine/appc/lights.py tests/unit/test_app_bridge_symbols.py
git commit -m "feat(bridge): register bridge stubs in App namespace + Light.UnilluminateEntireSet

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Headless end-to-end test — real SDK LoadBridge.Load against stubs

**Files:**
- Create: `tests/integration/test_sdk_bridge_load.py`

**Context:** This is the de-risking milestone and must pass BEFORE we delete the shortcut (so we prove the SDK path works in isolation). It imports the **SDK** `LoadBridge` directly (bypassing the root shadow that still exists at this point) and drives `Load("GalaxyBridge")` with a live Game, asserting the bridge set + crew + extras exist and the expected loud stubs fired. Follow the fixture pattern in `tests/integration/test_bridge_menu_activation.py` (Game context + bridge-set teardown).

- [ ] **Step 1: Write the test**

```python
# tests/integration/test_sdk_bridge_load.py
"""The real SDK LoadBridge.Load runs end-to-end against loud stubs.

Imports the SDK module directly (importlib from sdk/Build/scripts) so this
test is valid both before and after the root LoadBridge.py shadow is removed.
"""
import importlib.util
import sys
from pathlib import Path

import pytest

import App
import engine.appc._stub_trace as st

SDK_LOADBRIDGE = (
    Path(__file__).resolve().parents[2]
    / "sdk" / "Build" / "scripts" / "LoadBridge.py"
)


def _load_sdk_loadbridge():
    spec = importlib.util.spec_from_file_location("_sdk_LoadBridge", SDK_LOADBRIDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def sdk_loadbridge(current_game):          # current_game fixture: see conftest
    st.reset()
    App.g_kSetManager._sets.clear()
    mod = _load_sdk_loadbridge()
    yield mod
    App.g_kSetManager._sets.clear()
    st.reset()


def test_sdk_load_runs_end_to_end_and_populates_crew(sdk_loadbridge):
    sdk_loadbridge.Load("GalaxyBridge")

    bridge = App.g_kSetManager.GetSet("bridge")
    assert App.BridgeSet_Cast(bridge) is not None          # a real BridgeSet

    # 5 standard crew at their station names.
    for station in ("Tactical", "Helm", "XO", "Science", "Engineer"):
        assert App.CharacterClass_Cast(bridge.GetObject(station)) is not None

    # 3 random extras (Male/FemaleExtra1..3).
    extras = [n for n in ("MaleExtra1", "MaleExtra2", "MaleExtra3",
                          "FemaleExtra1", "FemaleExtra2", "FemaleExtra3")
              if bridge.GetObject(n) is not None]
    assert len(extras) == 3

    # The control-flow-critical stubs fired (proves the SDK path, not the shim).
    fired = st.fired()
    assert "BridgeSet_Create" in fired
    assert "BridgeObjectClass_Create" in fired
    assert "ViewScreenObject_Create" in fired
    assert "ZoomCameraObjectClass_Create" in fired


def test_summary_prints_outstanding_stubs(sdk_loadbridge, capsys):
    sdk_loadbridge.Load("GalaxyBridge")
    capsys.readouterr()
    st.dump_stub_summary()
    err = capsys.readouterr().err
    assert "still need fleshing out" in err
    assert "BridgeObjectClass_Create" in err
```

> **Implementer note:** Check `tests/conftest.py` for the existing Game-context fixture name (the menu-activation test uses one). If it is not a reusable fixture, replicate its `_set_current_game(Game())` setup/teardown inline as `current_game`. If `Load("GalaxyBridge")` raises on an unstubbed symbol, that is expected discovery work: add a loud stub for that exact symbol in `engine/appc/bridge_set.py` following the Task 2 pattern (announce via `_stub_trace.stub_call`, return a control-flow-correct value), re-run, repeat until green. Record each newly-needed symbol in the commit message.

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/integration/test_sdk_bridge_load.py -v`
Expected: iterate per the implementer note until PASS (2 passed). Likely additional loud stubs needed: `TGSoundRegion_GetRegion`, `pGame.AddPythonFuncHandlerForInstance` interplay — add only what the tracebacks demand.

- [ ] **Step 3: Commit**

```bash
git add engine/appc/bridge_set.py tests/integration/test_sdk_bridge_load.py
git commit -m "test(bridge): SDK LoadBridge.Load runs end-to-end on loud stubs

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Delete the Python shortcut + un-shadow the SDK loader

**Files:**
- Delete: root `LoadBridge.py`
- Modify/Delete: `engine/bridge_officers.py` (remove `place_officers`/`_place_one`/`resolve_placement`/`_BRIDGE_IDENTITY_MAT4`; delete the file if nothing remains)
- Modify: `engine/host_loop.py` (remove `_place_bridge_officers`, `_BRIDGE_NIF_MAP`, the no-arg eager preload; source the camera bridge-name from the bridge set's config; route mission-load to the real `LoadBridge.Load(name)` + `dump_stub_summary()`)
- Modify: `tests/conftest.py` (drop `LoadBridge._reset_crew_populated` / stale shim references)
- Delete: `tests/unit/test_bridge_officers.py`, `tests/unit/test_bridge_crew_population.py`

**Context:** After this task, `import LoadBridge` resolves to `sdk/Build/scripts/LoadBridge.py` (the root shadow is gone). The host's mission-load hook calls the real `Load(name)`; the eager pre-game preview is removed because the SDK `Load` requires a live Game. The bridge camera previously read `LoadBridge.LAST_REQUESTED` — replace that with the bridge set's `GetConfig()` (or default `"GalaxyBridge"` when no set yet).

- [ ] **Step 1: Delete the root shadow + shortcut placement**

```bash
git rm LoadBridge.py
git rm engine/bridge_officers.py
git rm tests/unit/test_bridge_officers.py tests/unit/test_bridge_crew_population.py
```

(If something outside placement still imports from `engine/bridge_officers.py`, keep the file and delete only the named functions — grep first: `grep -rn "bridge_officers" engine/ tests/`.)

- [ ] **Step 2: Update host_loop.py wiring**

In `engine/host_loop.py`:

- Remove `_BRIDGE_NIF_MAP` (lines ~745-750) and `_place_bridge_officers` (lines ~2052-2095) and its call site in `_after_mission_loaded` (line ~2260).
- Change the eager pre-game preload (lines ~2206-2207) from `LoadBridge.Load()` — **delete it** (the bridge now loads at mission start with a live Game).
- In `_after_mission_loaded` / the mission-load hook, after the SDK mission's own `StartMission` has called `LoadBridge.Load(name)`, call:

```python
import engine.appc._stub_trace as _stub_trace
_stub_trace.dump_stub_summary()
```

- In `_BridgeCamera._eye_offset` (lines ~1228-1235), replace the `LoadBridge.LAST_REQUESTED` read with the bridge set's config:

```python
import App
bridge = App.g_kSetManager.GetSet("bridge")
name = ""
if bridge is not None and hasattr(bridge, "GetConfig"):
    name = bridge.GetConfig() or ""
return _BRIDGE_CAMERA_OFFSETS.get(name, self.DEFAULT_BRIDGE_OFFSET)
```

> **Implementer note:** Grep `engine/host_loop.py` for every remaining `LoadBridge` / `bridge_officers` / `LAST_REQUESTED` / `_ensure_bridge_for_session` reference and reconcile. `_ensure_bridge_for_session` (lines ~2019-2050) loads the bridge NIF via the now-deleted `_BRIDGE_NIF_MAP`; for THIS plan its model-loading is superseded by the SDK's `CreateBridgeModel` (a loud stub), so remove its `_BRIDGE_NIF_MAP` lookup — the bridge model will be absent until the follow-on plan implements `BridgeObjectClass_Create` for real. Leave a `# TODO(sdk-bridge step 3): SDK CreateBridgeModel will create the render instance` marker.

- [ ] **Step 3: Update conftest.py**

Grep and remove stale references:

```bash
grep -n "_reset_crew_populated\|populate_bridge_crew\|bridge_officers" tests/conftest.py
```

Remove the `LoadBridge._reset_crew_populated()` line (~430) from the bridge fixture/teardown. Keep the `sys.modules.pop("LoadBridge", None)` line — it now ensures the SDK module is freshly imported.

- [ ] **Step 4: Run the affected tests**

Run:
```bash
uv run pytest tests/integration/test_sdk_bridge_load.py tests/integration/test_bridge_menu_activation.py -v
```
Expected: PASS. `test_bridge_menu_activation.py` now exercises the SDK `Load` (its `CreateCharacterMenus` runs); fix any assertion that depended on the shim's deferred behaviour. If it asserts shim-specific internals, update it to assert the SDK-driven outcome (5 menus built).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(bridge): delete hardcoded shortcut; un-shadow SDK LoadBridge

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 6: Delete placement_map (C++) + resolve_placement binding

**Files:**
- Delete: `native/src/renderer/placement_map.cc`, `native/src/renderer/include/renderer/placement_map.h`, `native/tests/renderer/placement_map_test.cc`
- Modify: `native/src/renderer/CMakeLists.txt` (remove `placement_map.cc`, line ~60), `native/tests/renderer/CMakeLists.txt` (remove `placement_map_test.cc`, line ~17)
- Modify: `native/src/host/host_bindings.cc` (remove `#include <renderer/placement_map.h>` line 1 and the `m.def("resolve_placement", ...)` binding, lines ~714-727)

**Context:** `resolve_placement`'s only Python caller was `place_officers`, deleted in Task 5. Confirm no remaining caller, then remove the binding and the C++ map. `assemble_officer`, `create_bridge_instance`, `set_instance_animation`, `set_world_transform`, `destroy_instance` are the KEEP renderer surface — do not touch them.

- [ ] **Step 1: Confirm no remaining caller**

Run:
```bash
grep -rn "resolve_placement\|placement_map\|placement_for_location" \
  /Users/mward/Documents/Projects/bc_dauntless/engine \
  /Users/mward/Documents/Projects/bc_dauntless/native \
  /Users/mward/Documents/Projects/bc_dauntless/tests
```
Expected: only the files listed above (definitions/CMake/test), no live Python caller.

- [ ] **Step 2: Delete files + CMake lines + binding**

```bash
git rm native/src/renderer/placement_map.cc \
       native/src/renderer/include/renderer/placement_map.h \
       native/tests/renderer/placement_map_test.cc
```
Then remove `placement_map.cc` from `native/src/renderer/CMakeLists.txt`, `placement_map_test.cc` from `native/tests/renderer/CMakeLists.txt`, and in `native/src/host/host_bindings.cc` remove the `#include <renderer/placement_map.h>` and the entire `m.def("resolve_placement", ...)` block.

- [ ] **Step 3: Reconfigure + rebuild dauntless**

Run:
```bash
cmake -B build -S . && cmake --build build -j
```
Expected: clean build; `build/dauntless` and `build/python/_open_stbc_host.cpython-*.so` rebuilt.

- [ ] **Step 4: Run the renderer C++ tests**

Run:
```bash
ctest --test-dir build --output-on-failure -R renderer
```
Expected: PASS (the deleted `placement_map_test` is gone; skinned-bridge tests stay green).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "refactor(bridge): remove placement_map + resolve_placement binding (no caller)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 7: Live-verify checkpoint + memory update

**Files:** none (verification + memory)

**Context:** This is a human-in-the-loop checkpoint (Mark drives all visual verification — no synthetic input). The intermediate state is intentional: the bridge set + crew exist as logical objects, the loud stub summary prints on every mission load, but the bridge model and posed officers are NOT yet rendered via the SDK path.

- [ ] **Step 1: Build + launch for Mark**

Confirm `./build/dauntless` launches, loads a mission, and the terminal shows the `*** [BRIDGE-STUB] SUMMARY` listing the outstanding symbols (`BridgeObjectClass_Create`, `ViewScreenObject_Create`, `ZoomCameraObjectClass_Create`, etc.). Report the exact summary to Mark.

- [ ] **Step 2: Mark verifies**

Mark confirms: (a) no crash on mission load, (b) the loud stub summary appears and lists the expected outstanding work, (c) crew/menus still function (CrewSpeechBus, bridge menus). Rendered bridge model + posed officers are EXPECTED ABSENT at this milestone.

- [ ] **Step 3: Update memory**

Update `project_sdk_driven_bridge_init.md`: this plan (spec steps 1–2) is DONE — the SDK path drives bridge init against loud stubs; the shortcut is deleted; the stub summary is the live to-do list for the follow-on plans (steps 3–6: faithful BridgeObjectClass_Create render instance, SDK-driven placement, viewscreen, camera).

---

## Self-review notes

- **Spec coverage:** Cleanup (spec step 1) = Task 5+6. Run-end-to-end-on-stubs (spec step 2) = Tasks 1–4. Loud stubs + summary (spec §2) = Tasks 1–2. Steps 3–6 are explicitly deferred to follow-on plans (stated in Goal + Task 7).
- **Type consistency:** `BridgeSet_Create`/`BridgeSet_Cast`/`BridgeObjectClass_Create`/`ViewScreenObject_Create`/`ZoomCameraObjectClass_Create`/`ZoomCameraObjectClass_GetObject`/`ModelManager` names are identical across Tasks 2, 3, 4 and match the SDK call sites in `GalaxyBridge.py`. `_stub_trace.stub_call`/`fired`/`dump_stub_summary`/`reset` consistent across Tasks 1, 4, 5.
- **Discovery latitude:** Tasks 4 & 5 include bounded "run, observe the loud banner / traceback, add a stub following the established pattern" notes — faithful to the agreed stub-then-replace methodology where the full transitive Appc set can't be statically enumerated without running.
- **No full-suite pytest; C++ binding change triggers full `dauntless` rebuild** — both called out in the relevant tasks.
