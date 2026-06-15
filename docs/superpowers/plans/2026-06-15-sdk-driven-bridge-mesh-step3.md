# SDK-Driven Bridge Mesh (Step 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the SDK-created `"bridge"` set object produce the actual bridge render instance, and delete the host's eager fallback load, so the SDK is the single source of the bridge mesh.

**Architecture:** `engine/appc/bridge_set.py` stays headless: `ModelManager.LoadModel` becomes a real env-path recorder and `BridgeObjectClass` becomes a real pure data object (NIF path + transform + an empty `render_instance` slot) — both stop calling `stub_call`, so they drop off the loud stub summary. The host's `engine/host_loop.py` gains `_realize_bridge_model(controller, r)`, which reads the SDK-created bridge object after `LoadBridge.Load`, loads its NIF, calls `create_bridge_instance`, and harvests the iid onto the controller. The eager startup load is deleted. Mesh selection is config-driven (read from `obj.nif`), so EBridge/Sovereign work with no bridge-name branching.

**Tech Stack:** Python 3 (engine shim + host), pytest (focused subsets only — the full suite OOMs the host). No C++/CMake/shader changes in step 3, so no `dauntless` rebuild is needed.

**Reference spec:** `docs/superpowers/specs/2026-06-15-sdk-driven-bridge-mesh-step3-design.md`

---

## Key facts the implementer must know

- **`engine/appc/` is the headless Appc shim and must not import the renderer.** `engine/renderer.py` imports `_dauntless_host` at module top; the renderer call lives host-side only. The bridge object is pure data; the host realizes it.
- **`controller.bridge_instance` is never read for drawing** — `create_bridge_instance` (host_bindings.cc) = `create_instance` + `set_pass(Bridge)`, which registers the mesh into the C++ bridge pass internally. The Python iid is retained only for ownership / `destroy_instance` / future transform updates. `destroy_instance` works on a bridge-tagged instance like any other.
- **`LoadBridge.Load` runs per mission load.** Same config → returns early (reuses the existing bridge object, which keeps its `render_instance`). Different config → `DeleteObjectFromSet("bridge")` then recreates (a fresh object with `render_instance = None`). Realization must be idempotent: create iff `obj.render_instance is None`, destroying any prior `controller.bridge_instance` first.
- **The texture env/detail path is passed to `LoadModel`, not to `BridgeObjectClass_Create`** (see `sdk/Build/scripts/Bridge/GalaxyBridge.py:37,45`). So `LoadModel` records `nif → envpath`, and the host reads it back via `env_for(nif)`.
- **`tests/conftest.py` puts the real built `_dauntless_host.so` on `sys.path`**, so `host_loop` imports cleanly headless and unit tests already import it. The host-realization test passes a *fake* renderer object into `_realize_bridge_model` so it never touches GL.
- **Never run the full pytest suite** (>100 GB RAM, freezes macOS). Run only the specific test files named in each task.
- **`PROJECT_ROOT`** is defined at `engine/host_loop.py:729`; **`DBRIDGE_TEX_REL`** at `:741`; the controller fields at `:1740-1743`; the eager block at `:2091-2105`; `_after_mission_loaded` (nested in `run()`) at `:2138-2154`.

---

## File Structure

**Modified:**
- `engine/appc/bridge_set.py` — `ModelManager` (real `LoadModel` + `env_for`); `BridgeObjectClass` (real pure object) + `BridgeObjectClass_Create` (no `stub_call`).
- `engine/host_loop.py` — add module-level `IDENTITY_MAT4`; add `_realize_bridge_model(controller, r)`; call it from `_after_mission_loaded`; delete the eager block (`:2091-2105`); refresh the now-stale controller-field comments.
- `tests/unit/test_bridge_set_stubs.py` — invert the two "is loud" assertions; add env-path + transform-recording assertions.
- `tests/integration/test_sdk_bridge_load.py` — assert the two symbols are **absent** from `fired()`; assert the bridge object carries the DBridge NIF; summary asserts a still-stubbed symbol.

**Created:**
- `tests/unit/test_realize_bridge_model.py` — host realization with a fake renderer.

**Not touched:** `_stub_trace.py`, the SP1/SP2 skinned renderer, `compose_officer_model`, `assemble_officer`, viewscreen/camera stubs, any C++/CMake.

---

## Task 1: `ModelManager.LoadModel` records the env path (drops off summary)

**Files:**
- Modify: `engine/appc/bridge_set.py` (the `ModelManager` class, lines 67-70)
- Test: `tests/unit/test_bridge_set_stubs.py` (replace `test_model_manager_load_model_is_loud_but_noop`)

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_bridge_set_stubs.py`, **replace** `test_model_manager_load_model_is_loud_but_noop` (lines 74-77) with:

```python
def test_model_manager_load_model_records_env_and_is_not_loud():
    mm = ModelManager()
    # Real now: records the texture/env path, returns None, and is NOT a
    # loud stub (it must drop off the bridge-stub summary in step 3).
    assert mm.LoadModel("data/Models/Sets/DBridge/DBridge.nif", None,
                        "data/Models/Sets/DBridge/High/") is None
    assert "g_kModelManager.LoadModel" not in st.fired()
    assert mm.env_for("data/Models/Sets/DBridge/DBridge.nif") == \
        "data/Models/Sets/DBridge/High/"
    assert mm.env_for("missing.nif") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py::test_model_manager_load_model_records_env_and_is_not_loud -v`
Expected: FAIL — `AttributeError: 'ModelManager' object has no attribute 'env_for'` (and the old `stub_call` still fires).

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/bridge_set.py`, **replace** the `ModelManager` class (lines 67-70) with:

```python
class ModelManager:
    """Real (no longer a loud stub): our renderer loads NIFs lazily at instance
    creation, host-side. LoadModel's faithful equivalent is to remember the
    texture/env path the SDK pre-loads each NIF with, so the host can search the
    right detail directory (Low/Medium/High) when it realizes the mesh. It loads
    nothing into the renderer itself."""
    def __init__(self):
        self._env = {}                       # nif path -> texture/env path

    def LoadModel(self, path, a=None, env=None):
        self._env[path] = env
        return None

    def env_for(self, path):
        return self._env.get(path)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -v`
Expected: PASS (all tests in the file, including the new one).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set_stubs.py
git commit -m "feat(bridge): ModelManager.LoadModel records env path (off stub summary)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 2: `BridgeObjectClass` becomes a real pure object (drops off summary)

**Files:**
- Modify: `engine/appc/bridge_set.py` (the `BridgeObjectClass` class, lines 35-46; and `BridgeObjectClass_Create`, lines 118-120)
- Test: `tests/unit/test_bridge_set_stubs.py` (replace `test_bridge_object_stub_supports_sdk_calls`)

**Context:** The SDK only calls `SetTranslateXYZ`, `SetAngleAxisRotation`, and `GetPropertySet` on the bridge object (`GalaxyBridge.py:47-51`). `BridgeObjectClass` stops being a `_LoudStub` subclass and becomes a plain data object that records its transform and exposes an empty `render_instance` slot for the host to fill. `GetPropertySet()` keeps returning a `_LoudStub` so `DBridgeProperties.LoadPropertySet(pPropertySet)` still runs (hardpoints are a later step).

- [ ] **Step 1: Write the failing test**

In `tests/unit/test_bridge_set_stubs.py`, **replace** `test_bridge_object_stub_supports_sdk_calls` (lines 47-53) with:

```python
def test_bridge_object_is_real_pure_object():
    obj = BridgeObjectClass_Create("data/Models/Sets/DBridge/DBridge.nif")
    # No longer a loud stub — must drop off the bridge-stub summary.
    assert "BridgeObjectClass_Create" not in st.fired()
    # Carries the NIF path so the host can realize the mesh.
    assert obj.nif == "data/Models/Sets/DBridge/DBridge.nif"
    # Host fills this in; defaults to None.
    assert obj.render_instance is None
    # GalaxyBridge.CreateBridgeModel calls these — they record, don't raise.
    obj.SetTranslateXYZ(1.0, 2.0, 3.0)
    obj.SetAngleAxisRotation(0.0, 1.0, 0.0, 0.0)
    assert obj.translate == (1.0, 2.0, 3.0)
    assert obj.rotation == (0.0, 1.0, 0.0, 0.0)
    # Property set stays truthy so DBridgeProperties.LoadPropertySet runs.
    assert obj.GetPropertySet() is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py::test_bridge_object_is_real_pure_object -v`
Expected: FAIL — `AttributeError: 'BridgeObjectClass' object has no attribute 'nif'` (current class stores `_nif`), and `"BridgeObjectClass_Create"` still in `fired()`.

- [ ] **Step 3: Write minimal implementation**

In `engine/appc/bridge_set.py`, **replace** the `BridgeObjectClass` class (lines 35-46) with:

```python
class BridgeObjectClass:
    """The bridge model object the SDK config script creates and adds to the
    bridge set as "bridge". A pure, headless data object: it carries the NIF
    path and transform the SDK sets; the HOST reads it after LoadBridge.Load and
    fills in `render_instance` (see host_loop._realize_bridge_model). Not a
    `_LoudStub` — it is real, so it drops off the bridge-stub summary."""
    def __init__(self, nif):
        self.nif = nif
        self.translate = (0.0, 0.0, 0.0)
        self.rotation = (0.0, 1.0, 0.0, 0.0)   # angle, x, y, z
        self.render_instance = None            # host fills this in
        # DBridgeProperties.LoadPropertySet(pPropertySet) still runs against a
        # chainable stub; faithful hardpoint loading is a later step.
        self._property_set = _LoudStub()

    def GetPropertySet(self):
        return self._property_set

    def SetTranslateXYZ(self, x, y, z):
        self.translate = (x, y, z)

    def SetAngleAxisRotation(self, a, x, y, z):
        self.rotation = (a, x, y, z)
```

Then **replace** `BridgeObjectClass_Create` (lines 118-120) with:

```python
def BridgeObjectClass_Create(nif):
    return BridgeObjectClass(nif)              # real, no stub_call -> off summary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_set_stubs.py -v`
Expected: PASS (all tests in the file).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_set.py tests/unit/test_bridge_set_stubs.py
git commit -m "feat(bridge): BridgeObjectClass is a real pure data object (off stub summary)

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 3: Integration test — SDK path still runs, two symbols gone

**Files:**
- Modify: `tests/integration/test_sdk_bridge_load.py` (lines 111-115 and 118-125)

**Context:** This proves the real SDK `LoadBridge.Load("GalaxyBridge")` still runs end-to-end after Tasks 1-2, that the bridge object now carries the DBridge NIF, and that the two now-real symbols have left the loud summary (while the still-stubbed viewscreen/camera remain).

- [ ] **Step 1: Update the assertions**

In `tests/integration/test_sdk_bridge_load.py`, in `test_sdk_load_runs_end_to_end_and_populates_crew`, **replace** the final `fired` block (lines 111-115) with:

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

Then **replace** `test_summary_prints_outstanding_stubs` (lines 118-125) with:

```python
def test_summary_prints_outstanding_stubs(sdk_loadbridge, capsys):
    sdk_loadbridge.Load("GalaxyBridge")
    capsys.readouterr()
    st.dump_stub_summary()
    err = capsys.readouterr().err
    assert "still need fleshing out" in err
    # The viewscreen is still a stub (step 5); the bridge object is not.
    assert "ViewScreenObject_Create" in err
    assert "BridgeObjectClass_Create" not in err
```

- [ ] **Step 2: Run the test**

Run: `uv run pytest tests/integration/test_sdk_bridge_load.py -v`
Expected: PASS (2 passed). If `bridge.GetObject("bridge")` is `None`, the SDK `CreateBridgeModel` did not add the object — check that Task 2's `BridgeObjectClass_Create` returns the object (it must, unchanged signature).

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_sdk_bridge_load.py
git commit -m "test(bridge): SDK load leaves BridgeObjectClass_Create + LoadModel off summary

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 4: Host realization + delete the eager fallback

**Files:**
- Create: `tests/unit/test_realize_bridge_model.py`
- Modify: `engine/host_loop.py` (add `IDENTITY_MAT4` module const; add `_realize_bridge_model`; call it from `_after_mission_loaded`; delete the eager block at `:2091-2105`; refresh controller-field comments at `:1740-1743`)

**Context:** `_realize_bridge_model(controller, r)` is module-level so it is unit-testable with a fake `r`. `_after_mission_loaded` (nested in `run()`) calls it with the module-global renderer `r`. The fake renderer records calls and returns sentinel ids, so the test never touches GL.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_realize_bridge_model.py`:

```python
"""Host-side realization of the SDK-created bridge object into a render
instance. Uses a fake renderer so it runs headless (never touches GL)."""
import App
from engine.appc.bridge_set import BridgeSet, BridgeObjectClass
from engine.host_loop import _realize_bridge_model


class _FakeRenderer:
    def __init__(self):
        self.loaded = []          # (nif_abs, tex_abs)
        self.created = []         # handles passed to create_bridge_instance
        self.transformed = []     # (iid, mat4)
        self.destroyed = []       # iids
        self._next_handle = 100
        self._next_iid = 900

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
        self.bridge_instance = None
        self.nif_to_handle = {}
        self.current_bridge_nif_abs = None


def _make_bridge_with_object(nif="data/Models/Sets/DBridge/DBridge.nif",
                             record_env=True):
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")
    obj = BridgeObjectClass(nif)
    bridge.AddObjectToSet(obj, "bridge")
    if record_env:
        App.g_kModelManager.LoadModel(nif, None, "data/Models/Sets/DBridge/High/")
    return bridge, obj


def teardown_function(_):
    App.g_kSetManager._sets.clear()
    App.g_kModelManager._env.clear()


def test_realizes_instance_and_harvests_iid():
    _bridge, obj = _make_bridge_with_object()
    r = _FakeRenderer()
    ctl = _FakeController()

    _realize_bridge_model(ctl, r)

    assert len(r.loaded) == 1
    nif_abs, tex_abs = r.loaded[0]
    assert nif_abs.endswith("game/data/Models/Sets/DBridge/DBridge.nif")
    # Texture search uses the env path recorded by LoadModel.
    assert tex_abs.endswith("game/data/Models/Sets/DBridge/High")
    assert len(r.created) == 1
    assert obj.render_instance == ctl.bridge_instance
    assert ctl.bridge_instance is not None
    assert ctl.current_bridge_nif_abs == nif_abs
    assert ctl.nif_to_handle[nif_abs] == r.created[0]
    # World transform applied once.
    assert len(r.transformed) == 1


def test_same_config_reuse_is_noop():
    _bridge, obj = _make_bridge_with_object()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_bridge_model(ctl, r)
    first_iid = ctl.bridge_instance

    # Second pass with the SAME object (render_instance already set): no-op.
    _realize_bridge_model(ctl, r)
    assert ctl.bridge_instance == first_iid
    assert len(r.loaded) == 1
    assert len(r.created) == 1
    assert r.destroyed == []


def test_fresh_object_destroys_prior_instance():
    _bridge, _obj = _make_bridge_with_object()
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_bridge_model(ctl, r)
    prior_iid = ctl.bridge_instance

    # Simulate a config change / set rebuild: a fresh bridge object with no
    # render_instance replaces the old one in the set.
    _bridge2, _obj2 = _make_bridge_with_object(
        nif="data/Models/Sets/EBridge/EBridge.nif", record_env=False)
    _realize_bridge_model(ctl, r)

    assert prior_iid in r.destroyed
    assert ctl.bridge_instance != prior_iid
    assert len(r.created) == 2
    # No env recorded for EBridge -> falls back to the default High tex dir.
    assert r.loaded[1][1].endswith("game/data/Models/Sets/DBridge/High")
    assert r.loaded[1][0].endswith("game/data/Models/Sets/EBridge/EBridge.nif")


def test_no_bridge_object_is_noop():
    App.g_kSetManager._sets.clear()
    bridge = BridgeSet()
    App.g_kSetManager.AddSet(bridge, "bridge")   # set exists, no "bridge" object
    r = _FakeRenderer()
    ctl = _FakeController()
    _realize_bridge_model(ctl, r)
    assert r.loaded == []
    assert ctl.bridge_instance is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_realize_bridge_model.py -v`
Expected: FAIL — `ImportError: cannot import name '_realize_bridge_model' from 'engine.host_loop'`.

- [ ] **Step 3a: Add the module-level `IDENTITY_MAT4` and `_realize_bridge_model`**

In `engine/host_loop.py`, immediately after the `DBRIDGE_*`/`EBRIDGE_*` constants block (after line 743), add:

```python
# Bridge geometry renders at world identity: the bridge pass camera works in
# bridge-local frame, so the bridge's world position is irrelevant.
IDENTITY_MAT4 = [
    1.0, 0.0, 0.0, 0.0,
    0.0, 1.0, 0.0, 0.0,
    0.0, 0.0, 1.0, 0.0,
    0.0, 0.0, 0.0, 1.0,
]
```

Then add the helper just above `def _wire_target_menu_to_player_set` (before line 1993):

```python
def _realize_bridge_model(controller, r) -> None:
    """Turn the SDK-created "bridge" set object into the rendered instance.

    Called from _after_mission_loaded after the mission's StartMission has run
    the real LoadBridge.Load (which calls GalaxyBridge.CreateBridgeModel ->
    BridgeObjectClass_Create + g_kModelManager.LoadModel). Reads the bridge
    object's NIF path + the env path LoadModel recorded, loads the mesh, and
    creates the bridge render instance.

    Idempotent: same-config reuse (object already has render_instance) is a
    no-op; a config change / set rebuild (a fresh object with render_instance
    None) destroys the prior instance first. Mesh selection is config-driven —
    obj.nif is whatever the active Bridge.<name> config script set, so
    EBridge/Sovereign work with no bridge-name branching.
    """
    import App as _App
    bridge = _App.g_kSetManager.GetSet("bridge")
    if bridge is None:
        return
    obj = bridge.GetObject("bridge")
    if obj is None or not hasattr(obj, "nif"):
        return                                     # no SDK bridge object yet
    if obj.render_instance is not None:
        return                                     # same-config reuse

    if controller.bridge_instance is not None:
        try:
            r.destroy_instance(controller.bridge_instance)
        except Exception:
            pass
        controller.bridge_instance = None

    nif_abs = str(PROJECT_ROOT / "game" / obj.nif)
    env = _App.g_kModelManager.env_for(obj.nif)
    tex_abs = (str(PROJECT_ROOT / "game" / env) if env
               else str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL))

    handle = r.load_model(nif_abs, tex_abs)
    iid = r.create_bridge_instance(handle)
    r.set_world_transform(iid, IDENTITY_MAT4)

    obj.render_instance = iid
    controller.bridge_instance = iid
    controller.nif_to_handle[nif_abs] = handle
    controller.current_bridge_nif_abs = nif_abs
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_realize_bridge_model.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Delete the eager fallback and wire the call**

In `engine/host_loop.py`, **delete** the eager block (current lines 2088-2105):

```python
        # Bridge interior — eagerly loaded once and reused across mission
        # swaps. Instance lives on the controller, not the per-mission
        # session, so MissionSession.teardown doesn't destroy it.
        bridge_nif_abs = str(PROJECT_ROOT / "game" / DBRIDGE_NIF_REL)
        bridge_tex_abs = str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL)
        bridge_handle  = r.load_model(bridge_nif_abs, bridge_tex_abs)
        controller.nif_to_handle[bridge_nif_abs] = bridge_handle
        controller.bridge_instance = r.create_bridge_instance(bridge_handle)
        controller.current_bridge_nif_abs = bridge_nif_abs
        # Identity transform — the bridge pass camera works in
        # bridge-local frame, so the bridge's world position is irrelevant.
        IDENTITY_MAT4 = [
            1.0, 0.0, 0.0, 0.0,
            0.0, 1.0, 0.0, 0.0,
            0.0, 0.0, 1.0, 0.0,
            0.0, 0.0, 0.0, 1.0,
        ]
        r.set_world_transform(controller.bridge_instance, IDENTITY_MAT4)
```

Replace it with a single comment marking the SDK ownership:

```python
        # Bridge interior is created by the SDK path (LoadBridge.Load ->
        # Bridge.<name>.CreateBridgeModel) during the mission load below, then
        # realized into a render instance by _realize_bridge_model in
        # _after_mission_loaded. No eager pre-game load — the SDK is the single
        # source of the bridge mesh.
```

Then in `_after_mission_loaded` (nested in `run()`), add the realization call right after the bridge-config caching block and before `dump_stub_summary()`. The current body ends:

```python
            if _bridge is not None and hasattr(_bridge, "GetConfig"):
                _name = _bridge.GetConfig() or ""
                if _name:
                    _CURRENT_BRIDGE_NAME = _name
            import engine.appc._stub_trace as _stub_trace
            _stub_trace.dump_stub_summary()
            _wire_target_menu_to_player_set(controller)
```

Insert `_realize_bridge_model(controller, r)` immediately before the `import engine.appc._stub_trace` line:

```python
            if _bridge is not None and hasattr(_bridge, "GetConfig"):
                _name = _bridge.GetConfig() or ""
                if _name:
                    _CURRENT_BRIDGE_NAME = _name
            # Realize the SDK-created bridge object into a render instance
            # (replaces the deleted eager startup load).
            _realize_bridge_model(controller, r)
            import engine.appc._stub_trace as _stub_trace
            _stub_trace.dump_stub_summary()
            _wire_target_menu_to_player_set(controller)
```

Finally, refresh the now-stale controller-field comment at lines 1741-1743 — **replace**:

```python
        self.bridge_instance: Optional[Any] = None  # InstanceId from create_bridge_instance
        # NIF path currently bound to bridge_instance. Set when the eager
        # bridge mesh is loaded at run() startup.
        self.current_bridge_nif_abs: Optional[str] = None
```

with:

```python
        self.bridge_instance: Optional[Any] = None  # InstanceId; set by _realize_bridge_model
        # NIF path currently bound to bridge_instance. Set by
        # _realize_bridge_model when the SDK-created bridge object is realized.
        self.current_bridge_nif_abs: Optional[str] = None
```

- [ ] **Step 6: Verify the eager const is no longer referenced and host_loop imports**

Run:
```bash
grep -n "DBRIDGE_NIF_REL\|bridge_nif_abs\|bridge_handle" engine/host_loop.py
uv run python -c "import engine.host_loop; print('host_loop import OK')"
uv run pytest tests/unit/test_realize_bridge_model.py tests/unit/test_bridge_set_stubs.py tests/integration/test_sdk_bridge_load.py -v
```
Expected: `DBRIDGE_NIF_REL` now appears only at its definition (line ~740) and any unrelated use — **not** in a deleted-eager-load context; `bridge_nif_abs`/`bridge_handle` gone. `host_loop import OK`. All listed tests PASS. (`DBRIDGE_NIF_REL`/`EBRIDGE_*` may remain defined and used by other code — do not delete the constants; only the eager block is removed.)

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_realize_bridge_model.py
git commit -m "feat(bridge): SDK-driven bridge mesh — host realizes the SDK bridge object

Adds _realize_bridge_model to turn the SDK-created 'bridge' set object into a
render instance and deletes the eager startup load. The SDK path is now the
single source of the bridge mesh; mesh selection is config-driven.

Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
```

---

## Task 5: Live-verify checkpoint + memory update

**Files:** none (verification + memory). **Mark drives all visual verification — no synthetic input, no full-screen capture.**

**Context:** No C++/shader/CMake change in step 3, so no rebuild is required — the existing `./build/dauntless` runs the new Python. (If `_dauntless_host` is somehow stale from an unrelated change, rebuild with `cmake -B build -S . && cmake --build build -j`.)

- [ ] **Step 1: Launch for Mark**

Run `./build/dauntless`, load a mission, and confirm in the terminal that the `*** [BRIDGE-STUB] SUMMARY` no longer lists `BridgeObjectClass_Create` or `g_kModelManager.LoadModel` (it should still list `ViewScreenObject_Create`, `ZoomCameraObjectClass_Create`, and the `BridgeSet.*` config methods). Report the exact summary to Mark.

- [ ] **Step 2: Mark verifies**

Mark confirms: (a) no crash on mission load, (b) the GalaxyBridge interior renders (now via the SDK path, not the eager load), (c) the two symbols are gone from the summary, (d) crew/menus still function. Officer placement is still the existing `assemble_officer` path (step 4); viewscreen/camera are still stubbed (step 5) — both EXPECTED.

- [ ] **Step 3: Update memory**

Update `project_sdk_driven_bridge_init.md`: step 3 DONE — the SDK-created bridge object now produces the render instance via `host_loop._realize_bridge_model`; the eager fallback is deleted; `BridgeObjectClass_Create` + `g_kModelManager.LoadModel` are real and off the summary; mesh selection is config-driven (EBridge/Sovereign supported, not yet live-verified). Remaining summary / follow-on: step 4 SDK-driven officer placement, step 5 viewscreen + `ZoomCameraObjectClass` camera, step 6 verify extras/menus.

---

## Self-review notes

- **Spec coverage:** "Two stubs become real" (spec §Components) = Tasks 1-2. "Host harvest + delete eager fallback" (spec §host_loop) = Task 4. "Config-driven mesh selection" = Task 4 (`obj.nif` read, no branching) + Task 3's `endswith("DBridge.nif")` assertion. "Lifecycle/idempotency matrix" = Task 4 tests (`test_same_config_reuse_is_noop`, `test_fresh_object_destroys_prior_instance`, `test_no_bridge_object_is_noop`). "Testing" (spec §Testing) = Tasks 1-4 + Task 5 live. Caveat (non-Galaxy not live-verified) = Task 5 step 2 note.
- **Placeholder scan:** none — every code step shows full code; no TBD/TODO; the only `# ...`-style marker is the intentional replacement comment in Task 4 step 5.
- **Type consistency:** `env_for`, `_env`, `render_instance`, `nif`, `translate`, `rotation`, `BridgeObjectClass`, `_realize_bridge_model(controller, r)`, `IDENTITY_MAT4` are spelled identically across Tasks 1-4 and the design doc. `controller.bridge_instance` / `nif_to_handle` / `current_bridge_nif_abs` match the existing `HostController` fields (host_loop.py:1734,1740,1743).
- **No full-suite pytest** — every run targets named files. **No C++/CMake/shader change** → no `dauntless` rebuild needed (called out in Task 5).
