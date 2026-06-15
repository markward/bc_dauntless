# SDK-driven bridge viewscreen mesh (step 5b) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Realize the SDK-created viewscreen object (`DBridgeViewScreen.nif`) into a rendered bridge instance, mirroring step 3's `_realize_bridge_model`, and drop `ViewScreenObject_Create` + the whole `BridgeSet.*` block off the `[BRIDGE-STUB] SUMMARY`.

**Architecture:** Two changes. (1) `engine/appc/bridge_set.py`: promote `ViewScreenObject` from pure loud-stub to a real data object (keeping `_LoudStub` as the base for the unbuilt menu/handler method surface) and drop the `stub_call`s from `ViewScreenObject_Create` + the six `BridgeSet.*` methods. (2) `engine/host_loop.py`: new module-level `_realize_viewscreen(controller, r)`, a near-clone of `_realize_bridge_model`, wired into `_after_mission_loaded` right after the bridge mesh is realized; the screen renders faithfully-as-authored (blank panel) until 5c/RTT.

**Tech Stack:** Python (headless `engine/appc` shim + host loop), pytest. **Pure Python — no C++/shader/CMake/rebuild.**

**Spec:** `docs/superpowers/specs/2026-06-15-sdk-driven-bridge-viewscreen-step5b-design.md`

> ⚠️ **NEVER run the full pytest suite** (`uv run pytest` with no path) — the full bc_dauntless suite uses >100 GB RAM and freezes macOS. Always pass explicit test file/node paths, as every `Run:` command below does. Warn any subagent of this.

---

## File Structure

- **Modify** `engine/appc/bridge_set.py` — `ViewScreenObject` becomes a real data object; `ViewScreenObject_Create` and `BridgeSet.{GetViewScreen,SetViewScreen,GetConfig,SetConfig,IsSameConfig,DeleteCameraFromSet}` drop their `stub_call`s. (headless — no renderer import)
- **Modify** `engine/host_loop.py` — add `controller.viewscreen_instance` slot; add module-level `_realize_viewscreen`; wire it into `_after_mission_loaded`.
- **Modify** `tests/unit/test_bridge_set_stubs.py` — assert the promoted symbols no longer fire `stub_call`; `ViewScreenObject` data round-trips; catch-all still no-ops.
- **Create** `tests/unit/test_realize_viewscreen.py` — fake-renderer idempotency matrix mirroring `test_realize_bridge_model.py`.
- **Modify** `tests/integration/test_sdk_bridge_load.py` — flip the `ViewScreenObject_Create` assertions from "still stubbed" to "off the summary".

---

## Task 1: Promote `ViewScreenObject` + drop `BridgeSet.*` / `ViewScreenObject_Create` stub_calls

**Files:**
- Modify: `engine/appc/bridge_set.py:66-83` (`ViewScreenObject` class), `:110-152` (`BridgeSet.*` methods + `ViewScreenObject_Create`)
- Test: `tests/unit/test_bridge_set_stubs.py`

- [ ] **Step 1: Update the unit test to pin the new behavior (write failing test)**

In `tests/unit/test_bridge_set_stubs.py`, **replace** the existing `test_viewscreen_round_trips` (lines 39-44) with the expanded version below, and **replace** `test_config_round_trips_and_is_same_config` (lines 30-36) so it also asserts the config methods are no longer loud:

```python
def test_config_round_trips_and_is_not_loud():
    bs = BridgeSet_Create()
    assert bs.IsSameConfig("GalaxyBridge") == 0     # nothing set yet
    bs.SetConfig("GalaxyBridge")
    assert bs.GetConfig() == "GalaxyBridge"
    assert bs.IsSameConfig("GalaxyBridge")          # truthy
    assert bs.IsSameConfig("SovereignBridge") == 0
    # Step 5b: faithful plumbing the host/SDK consume — off the summary.
    assert "BridgeSet.GetConfig" not in st.fired()
    assert "BridgeSet.SetConfig" not in st.fired()
    assert "BridgeSet.IsSameConfig" not in st.fired()


def test_viewscreen_is_real_data_object_and_round_trips():
    bs = BridgeSet_Create()
    assert bs.GetViewScreen() is None
    vs = ViewScreenObject_Create("data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    # Step 5b: now a real object — must drop off the bridge-stub summary.
    assert "ViewScreenObject_Create" not in st.fired()
    # Carries the NIF path so the host can realize the screen mesh.
    assert vs.nif == "data/Models/Sets/DBridge/DBridgeViewScreen.nif"
    # Host fills this in; defaults to None.
    assert vs.render_instance is None
    # Feed state round-trips (consumed later by 5c/RTT). Off by default.
    assert vs.GetRemoteCam() is None
    vs.SetRemoteCam("cam-sentinel")
    assert vs.GetRemoteCam() == "cam-sentinel"
    vs.SetIsOn(1)
    assert vs._is_on == 1
    # SetViewScreen stores it and is no longer loud.
    bs.SetViewScreen(vs, "viewscreen")
    assert bs.GetViewScreen() is vs
    assert "BridgeSet.SetViewScreen" not in st.fired()
    assert "BridgeSet.GetViewScreen" not in st.fired()
    # The unbuilt menu/handler surface still no-ops via the _LoudStub catch-all
    # (does not raise, does not fire a stub_call).
    assert vs.SetMenu("whatever") is None
    assert vs.ToggleRemoteCam() is None
    assert vs.IsStaticOn() is None


def test_delete_camera_from_set_is_not_loud():
    bs = BridgeSet_Create()
    cam = ZoomCameraObjectClass_Create(0, 0, 0, 0, 0, 0, 1, "maincamera")
    bs.AddCameraToSet(cam, "maincamera")
    bs.DeleteCameraFromSet("maincamera")
    assert bs.GetCamera("maincamera") is None
    assert "BridgeSet.DeleteCameraFromSet" not in st.fired()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -q`
Expected: FAIL — `test_viewscreen_is_real_data_object_and_round_trips` fails because `ViewScreenObject_Create` still fires `stub_call` (and `vs.nif`/`render_instance`/`GetRemoteCam` don't exist as real attrs); the config/delete tests fail on the `not in st.fired()` asserts.

- [ ] **Step 3: Rewrite `ViewScreenObject` as a real data object**

In `engine/appc/bridge_set.py`, **replace** the current class (lines 66-68):

```python
class ViewScreenObject(_LoudStub):
    def __init__(self, nif):
        self._nif = nif
```

with:

```python
class ViewScreenObject(_LoudStub):
    """SDK viewscreen object. Core data is real (nif, render_instance, the
    RemoteCam/IsOn feed state consumed later by 5c RTT); the unbuilt
    station-menu/handler surface (SetMenu, ToggleRemoteCam,
    AddPythonFuncHandlerForInstance, IsStaticOn, MenuDown, ...) falls through
    _LoudStub.__getattr__ as a silent no-op so missions that touch it don't
    crash. The HOST reads this object after LoadBridge.Load and fills in
    render_instance (see host_loop._realize_viewscreen), mirroring
    BridgeObjectClass. Kept a _LoudStub (unlike BridgeObjectClass) precisely
    because that menu/handler surface is large and not yet built."""
    def __init__(self, nif):
        self.nif = nif
        self.render_instance = None    # host fills this in
        self._remote_cam = None
        self._is_on = 0

    def GetRemoteCam(self):
        return self._remote_cam

    def SetRemoteCam(self, cam):
        self._remote_cam = cam

    def SetIsOn(self, on):
        self._is_on = on
```

- [ ] **Step 4: Drop the `stub_call` from `ViewScreenObject_Create`**

In `engine/appc/bridge_set.py`, **replace** (lines 150-152):

```python
def ViewScreenObject_Create(nif):
    _stub_trace.stub_call("ViewScreenObject_Create", "nif=%s" % nif)
    return ViewScreenObject(nif)
```

with:

```python
def ViewScreenObject_Create(nif):
    return ViewScreenObject(nif)               # real, no stub_call -> off summary
```

- [ ] **Step 5: Drop the `stub_call`s from the six `BridgeSet.*` methods**

In `engine/appc/bridge_set.py`, **replace** the method bodies (lines 110-133) so each drops its `_stub_trace.stub_call(...)` line while keeping the logic:

```python
    def IsSameConfig(self, name):
        return 1 if self._config == name else 0

    def GetConfig(self):
        return self._config

    def SetConfig(self, name):
        self._config = name

    def GetViewScreen(self):
        return self._viewscreen

    def SetViewScreen(self, viewscreen, name="viewscreen"):
        self._viewscreen = viewscreen
        self.AddObjectToSet(viewscreen, name)

    def DeleteCameraFromSet(self, name):
        self.RemoveCameraFromSet(name)
```

(The class docstring at lines 101-104 says "only the bridge-config/viewscreen/camera-delete surface is overridden so it is loud + stateful"; update "loud + stateful" to "stateful — faithful plumbing the host/SDK consume" so the comment stays accurate.)

- [ ] **Step 6: Run the unit tests to verify they pass**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -q`
Expected: PASS (all tests, including the unchanged `test_camera_*` and `test_model_manager_*`).

- [ ] **Step 7: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set_stubs.py
git commit -m "feat(bridge): make ViewScreenObject + BridgeSet.* real (step 5b)

Promote ViewScreenObject to a real data object (nif, render_instance,
RemoteCam/IsOn feed state) over a _LoudStub base that keeps the unbuilt
menu/handler surface a silent no-op. Drop stub_calls from
ViewScreenObject_Create and the six BridgeSet.* plumbing methods so they
leave the [BRIDGE-STUB] SUMMARY.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `_realize_viewscreen` host function + controller slot + wiring

**Files:**
- Modify: `engine/host_loop.py` — add `self.viewscreen_instance` next to `self.bridge_instance` (~line 1772); add module-level `_realize_viewscreen` after `_realize_bridge_model` (~line 2070); call it in `_after_mission_loaded` after `_realize_bridge_model` (~line 2299).
- Test: `tests/unit/test_realize_viewscreen.py` (new)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_realize_viewscreen.py`:

```python
"""Host-side realization of the SDK-created viewscreen object into a render
instance. Uses a fake renderer so it runs headless (never touches GL).
Mirrors tests/unit/test_realize_bridge_model.py."""
import App
from engine.appc.bridge_set import BridgeSet, ViewScreenObject
from engine.host_loop import _realize_viewscreen

VS_NIF = "data/Models/Sets/DBridge/DBridgeViewScreen.nif"


class _FakeRenderer:
    def __init__(self):
        self.loaded = []          # (nif_abs, tex_abs)
        self.created = []         # handles passed to create_bridge_instance
        self.transformed = []     # (iid, mat4)
        self.destroyed = []       # iids
        self._next_handle = 200
        self._next_iid = 800

    def load_model(self, nif_abs, tex_abs):
        self.loaded.append((nif_abs, tex_abs))
        self._next_handle += 1
        return self._next_handle

    def create_bridge_instance(self, handle):
        self.created.append(handle)
        self._next_iid += 1
        return self._next_iid

    def set_world_transform(self, iid, mat4):
        self.transformed.append((iid, mat4))

    def destroy_instance(self, iid):
        self.destroyed.append(iid)


class _FakeController:
    def __init__(self):
        self.viewscreen_instance = None
        self.nif_to_handle = {}


def _make_bridge_with_viewscreen(nif=VS_NIF, record_env=True):
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")
    vs = ViewScreenObject(nif)
    bridge.SetViewScreen(vs, "viewscreen")
    if record_env:
        App.g_kModelManager.LoadModel(nif, None, "data/Models/Sets/DBridge/High/")
    return bridge, vs


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kModelManager._env.clear()


def test_realizes_instance_and_harvests_iid():
    _bridge, vs = _make_bridge_with_viewscreen()
    r = _FakeRenderer()
    ctl = _FakeController()

    _realize_viewscreen(ctl, r)

    assert len(r.loaded) == 1
    nif_abs, tex_abs = r.loaded[0]
    assert nif_abs.endswith("game/data/Models/Sets/DBridge/DBridgeViewScreen.nif")
    assert tex_abs.endswith("game/data/Models/Sets/DBridge/High")
    assert len(r.created) == 1
    assert vs.render_instance == ctl.viewscreen_instance
    assert ctl.viewscreen_instance is not None
    assert ctl.nif_to_handle[nif_abs] == r.created[0]
    # World transform applied once (identity — bridge-local space).
    assert len(r.transformed) == 1


def test_same_config_reuse_is_noop():
    _bridge, _vs = _make_bridge_with_viewscreen()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    first_iid = ctl.viewscreen_instance

    _realize_viewscreen(ctl, r)        # same object, render_instance set
    assert ctl.viewscreen_instance == first_iid
    assert len(r.loaded) == 1
    assert len(r.created) == 1
    assert r.destroyed == []


def test_fresh_object_destroys_prior_instance():
    _bridge, _vs = _make_bridge_with_viewscreen()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    prior_iid = ctl.viewscreen_instance

    # Config change / set rebuild: a fresh viewscreen object replaces the old.
    _bridge2, _vs2 = _make_bridge_with_viewscreen(
        nif="data/Models/Sets/EBridge/EBridgeViewScreen.nif", record_env=False)
    _realize_viewscreen(ctl, r)

    assert prior_iid in r.destroyed
    assert ctl.viewscreen_instance != prior_iid
    assert len(r.created) == 2
    # No env recorded -> falls back to the default High tex dir.
    assert r.loaded[1][1].endswith("game/data/Models/Sets/DBridge/High")
    assert r.loaded[1][0].endswith("game/data/Models/Sets/EBridge/EBridgeViewScreen.nif")


def test_no_viewscreen_is_noop():
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")   # set exists, no viewscreen
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    assert r.loaded == []
    assert ctl.viewscreen_instance is None


def test_no_bridge_set_is_noop():
    App.g_kSetManager._sets.clear()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_viewscreen(ctl, r)
    assert r.loaded == []
    assert ctl.viewscreen_instance is None
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/unit/test_realize_viewscreen.py -q`
Expected: FAIL with `ImportError: cannot import name '_realize_viewscreen' from 'engine.host_loop'`.

- [ ] **Step 3: Add the `viewscreen_instance` controller slot**

In `engine/host_loop.py`, find (~line 1772):

```python
        self.bridge_instance: Optional[Any] = None  # InstanceId; set by _realize_bridge_model
```

and add immediately after it:

```python
        self.viewscreen_instance: Optional[Any] = None  # InstanceId; set by _realize_viewscreen
```

- [ ] **Step 4: Add the `_realize_viewscreen` function**

In `engine/host_loop.py`, immediately after the end of `_realize_bridge_model` (after its last line `controller.current_bridge_nif_abs = nif_abs`, ~line 2069, before `def _place_bridge_officers`), insert:

```python
def _realize_viewscreen(controller, r) -> None:
    """Turn the SDK-created viewscreen object into a rendered bridge instance.

    Mirrors _realize_bridge_model: reads bridge.GetViewScreen() (set by the SDK's
    CreateBridgeModel -> ViewScreenObject_Create + SetViewScreen), resolves the
    NIF + the env path LoadModel recorded, and creates a bridge-pass instance at
    identity. The screen renders faithfully-as-authored (a blank panel) until
    5c/RTT feeds u_base_color from the tactical camera.

    Idempotent/leak-free (identical to _realize_bridge_model): same-config reuse
    (object already has render_instance) is a no-op; a fresh object (set rebuild
    via reset_sdk_globals) destroys the prior instance first. Config-driven —
    reads vs.nif, so Sovereign/EBridge viewscreens work with no name branching.
    """
    import App as _App
    bridge = _App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return
    vs = bridge.GetViewScreen()
    if vs is None or not hasattr(vs, "nif"):
        return                                     # no SDK viewscreen yet
    if vs.render_instance is not None:
        return                                     # same-config reuse

    if controller.viewscreen_instance is not None:
        try:
            r.destroy_instance(controller.viewscreen_instance)
        except Exception:
            pass
        controller.viewscreen_instance = None

    nif_abs = str(PROJECT_ROOT / "game" / vs.nif)
    env = _App.g_kModelManager.env_for(vs.nif)
    tex_abs = (str(PROJECT_ROOT / "game" / env) if env
               else str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL))

    handle = r.load_model(nif_abs, tex_abs)
    iid = r.create_bridge_instance(handle)
    r.set_world_transform(iid, IDENTITY_MAT4)

    vs.render_instance = iid
    controller.viewscreen_instance = iid
    controller.nif_to_handle[nif_abs] = handle
```

- [ ] **Step 5: Run the unit test to verify it passes**

Run: `uv run pytest tests/unit/test_realize_viewscreen.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Wire `_realize_viewscreen` into `_after_mission_loaded`**

In `engine/host_loop.py`, find (~line 2299):

```python
            _realize_bridge_model(controller, r)
            _place_bridge_officers(controller, r)
```

and insert the viewscreen call between them:

```python
            _realize_bridge_model(controller, r)
            _realize_viewscreen(controller, r)
            _place_bridge_officers(controller, r)
```

- [ ] **Step 7: Re-run the unit test (wiring is a pure addition; confirm still green)**

Run: `uv run pytest tests/unit/test_realize_viewscreen.py tests/unit/test_realize_bridge_model.py -q`
Expected: PASS (both files — the bridge-model test must remain green, proving no regression to step 3).

- [ ] **Step 8: Commit**

```bash
git add engine/host_loop.py tests/unit/test_realize_viewscreen.py
git commit -m "feat(bridge): realize SDK viewscreen mesh into a render instance (step 5b)

Add _realize_viewscreen (near-clone of _realize_bridge_model) + the
controller.viewscreen_instance slot, wired into _after_mission_loaded
after the bridge mesh. Reads bridge.GetViewScreen(), resolves the NIF +
env path, and creates a bridge-pass instance at identity. Screen renders
faithfully-as-authored until 5c/RTT. Idempotent + leak-free.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Integration test — viewscreen is off the summary after a real `Load`

**Files:**
- Modify: `tests/integration/test_sdk_bridge_load.py:111-136`

- [ ] **Step 1: Flip the `ViewScreenObject_Create` assertions (write failing test)**

In `tests/integration/test_sdk_bridge_load.py`, in `test_sdk_load_runs_end_to_end_and_populates_crew`, **replace** the block (lines 111-125):

```python
    fired = st.fired()
    # Step 3: these two are now REAL and must have left the summary.
    assert "BridgeObjectClass_Create" not in fired
    assert "g_kModelManager.LoadModel" not in fired
    # Still-stubbed control-flow symbols prove the SDK path actually ran.
    assert "BridgeSet_Create" in fired
    assert "ViewScreenObject_Create" in fired
    assert "ZoomCameraObjectClass_Create" in fired

    # The SDK-created bridge object now carries the bridge NIF for the host
    # to realize (mesh selection is config-driven, not hardcoded).
    bridge_obj = bridge.GetObject("bridge")
    assert bridge_obj is not None
    assert bridge_obj.nif.endswith("DBridge.nif")
    assert bridge_obj.render_instance is None      # host fills this in live
```

with:

```python
    fired = st.fired()
    # Steps 3 + 5b: these are now REAL and must have left the summary.
    assert "BridgeObjectClass_Create" not in fired
    assert "g_kModelManager.LoadModel" not in fired
    assert "ViewScreenObject_Create" not in fired
    assert "BridgeSet.GetViewScreen" not in fired
    assert "BridgeSet.SetViewScreen" not in fired
    assert "BridgeSet.GetConfig" not in fired
    assert "BridgeSet.SetConfig" not in fired
    assert "BridgeSet.IsSameConfig" not in fired
    assert "BridgeSet.DeleteCameraFromSet" not in fired
    # Still-stubbed control-flow symbols prove the SDK path actually ran.
    assert "BridgeSet_Create" in fired
    assert "ZoomCameraObjectClass_Create" in fired

    # The SDK-created bridge object carries the bridge NIF for the host to
    # realize (mesh selection is config-driven, not hardcoded).
    bridge_obj = bridge.GetObject("bridge")
    assert bridge_obj is not None
    assert bridge_obj.nif.endswith("DBridge.nif")
    assert bridge_obj.render_instance is None      # host fills this in live

    # Step 5b: the SDK-created viewscreen carries DBridgeViewScreen.nif for
    # the host to realize; render_instance stays None until the host runs.
    viewscreen = bridge.GetViewScreen()
    assert viewscreen is not None
    assert viewscreen.nif.endswith("DBridgeViewScreen.nif")
    assert viewscreen.render_instance is None
```

Then in `test_summary_prints_outstanding_stubs`, **replace** (lines 134-136):

```python
    # The viewscreen is still a stub (step 5); the bridge object is not.
    assert "ViewScreenObject_Create" in err
    assert "BridgeObjectClass_Create" not in err
```

with:

```python
    # Step 5b: the viewscreen + BridgeSet.* are real now; only the zoom
    # camera remains stubbed for step 5a.
    assert "ZoomCameraObjectClass_Create" in err
    assert "ViewScreenObject_Create" not in err
    assert "BridgeObjectClass_Create" not in err
```

- [ ] **Step 2: Run the integration test**

Run: `uv run pytest tests/integration/test_sdk_bridge_load.py -q`
Expected: PASS (2 tests) — the real SDK `Load("GalaxyBridge")` now produces a real viewscreen object and an empty `BridgeSet.*` stub footprint; only `ZoomCameraObjectClass_*` remain.

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_sdk_bridge_load.py
git commit -m "test(bridge): viewscreen + BridgeSet.* off the stub summary (step 5b)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Full focused-suite check + live-verify handoff

**Files:** none (verification only)

- [ ] **Step 1: Run the three touched test files together**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py tests/unit/test_realize_viewscreen.py tests/unit/test_realize_bridge_model.py tests/integration/test_sdk_bridge_load.py -q`
Expected: PASS (all). **Do NOT run the bare `uv run pytest` — it OOMs the host.**

- [ ] **Step 2: Sanity-check the officer-placement integration still passes (no step-4 regression)**

Run: `uv run pytest tests/integration/test_officer_placement_sdk.py -q`
Expected: PASS — proves the added `_realize_viewscreen` call in `_after_mission_loaded` did not disturb officer placement.

- [ ] **Step 3: Hand off to Mark for live verification**

Mark drives all visual verification (no synthetic desktop input / full-screen capture). Ask him to:
1. Build is unnecessary (pure Python) — just run `./build/dauntless`.
2. Enter a mission, switch to bridge view.
3. Confirm: the front viewscreen surface now renders as a (blank/bright) panel where there was previously nothing; mesh + officers unchanged; no crash.
4. Confirm the on-exit `[BRIDGE-STUB] SUMMARY` lists only `ZoomCameraObjectClass_Create` / `ZoomCameraObjectClass_GetObject`.

Note for Mark: per spec decision (A), a blank/bright panel is expected (the NIF has no authored screen texture — it's the RTT target); 5c replaces it with the live tactical feed. If the screen geometry looks mis-aligned, that's a NIF-coordinate finding to record, not a transform to invent.

---

## Self-Review

**Spec coverage:**
- ViewScreenObject promoted to real data object (keeps `_LoudStub` catch-all) → Task 1, Steps 3-4. ✓
- `ViewScreenObject_Create` + six `BridgeSet.*` methods drop `stub_call` → Task 1, Steps 4-5. ✓
- `_realize_viewscreen` mirroring `_realize_bridge_model`, identity transform, config-driven, idempotent/leak-free → Task 2, Step 4. ✓
- `controller.viewscreen_instance` slot + wiring after `_realize_bridge_model` → Task 2, Steps 3, 6. ✓
- Decision A (faithful-as-authored, no shader change) → no forced-color code anywhere; render path unchanged. ✓
- Tests: new `test_realize_viewscreen.py` (idempotency matrix), updated `test_bridge_set_stubs.py`, updated `test_sdk_bridge_load.py` → Tasks 1-3. ✓
- Pure Python / no rebuild → no CMake/shader steps anywhere. ✓
- Live-verify handoff to Mark → Task 4, Step 3. ✓

**Placeholder scan:** No TBD/TODO; every code step shows full code; every `Run:` has an explicit path + expected result. ✓

**Type consistency:** `viewscreen_instance` (controller attr), `vs.nif` / `vs.render_instance` / `vs.GetRemoteCam` / `vs.SetRemoteCam` / `vs.SetIsOn` / `vs._is_on`, `bridge.GetViewScreen()`, `r.{load_model,create_bridge_instance,set_world_transform,destroy_instance}`, `_App.g_kModelManager.env_for`, `DBRIDGE_TEX_REL`, `IDENTITY_MAT4`, `PROJECT_ROOT` — all names match between the function, the wiring, and the tests. ✓
