# Comm-set Viewscreen Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Render BC comm scenes (a remote set's room + hailing character) on the bridge viewscreen, driven entirely by the SDK's `ViewscreenOn`/`Off`, by converging bridge + comm set rendering onto one generic `realize_set` path and adding a `Pass::Comm` render branch into the viewscreen RTT.

**Architecture:** A generic Python `realize_set(controller, r, set)` realizes any named `SetClass` (background geometry + ambient + characters), replacing the bridge-specific realize functions. Native gains `Pass::Comm` and a per-instance set tag; the bridge pass is parameterized to render any pass from any camera into any target, so comm sets render from their `"maincamera"` into the viewscreen HDR target. Each frame, Python resolves which comm set the viewscreen's remote cam belongs to and feeds it to the host.

**Tech Stack:** Python 3 (engine shim + host loop), pytest; C++17 renderer (OpenGL, pybind11 bindings `_dauntless_host`), gtest (`renderer_tests`); CMake build.

## Global Constraints

- **Build:** `cmake -B build -S . && cmake --build build -j`; binary `build/dauntless`, module `build/python/_dauntless_host.cpython-*.so`. Never build from inside `native/`.
- **Shader/asset rebuild:** `.vert`/`.frag` changes need a `cmake -B build -S .` reconfigure before `--build` (shaders are embedded via generated headers).
- **`host_bindings.cc` is compiled into both `dauntless` and `_dauntless_host`** — edits require a full `dauntless` rebuild, not just the module.
- **SDK drives everything:** no hardcoded mission/asset names (`"StarbaseSet"`/`"Liu"`) in engine code. The SDK's `SetBackgroundModel`/`CreateAmbientLight`/`CreateCharacter`/`AddCameraToSet` calls declare content; the engine realizes whatever they reference.
- **Rotation convention:** column-vector, right-handed (det +1); world-forward = `R.GetCol(1)`. Game units throughout (1 GU = 175 m); convert only at display.
- **Python tests:** run via `uv run pytest`. Full suite is memory-safe (~290 MB) via `scripts/run_tests.sh`.
- **Naming:** spatial vars are `*_gu` / `*_gups`, never `*_m` / `*_mps`.

---

## File Structure

**Python (engine):**
- `engine/appc/sets.py` — `SetClass`: un-stub `SetBackgroundModel` + `CreateAmbientLight` to record `_background_model` / `_ambient`.
- `engine/host_loop.py` — replace `_realize_bridge_model` / `_realize_viewscreen` / `_place_bridge_officers` with generic `realize_set` + `realize_all_sets`; add `_active_comm_feed` selection; retire `CommRenderFlag` usage.
- `engine/renderer.py` — wrapper for new bindings: `create_comm_instance`, `set_comm_set_id`, `set_viewscreen_comm_source`, `clear_viewscreen_comm_source`.
- `engine/appc/comm_render_flag.py` — deleted (tripwire retired).

**Native (C++):**
- `native/src/scenegraph/include/scenegraph/instance.h` — `Pass::Comm`; `Instance::comm_set_id`.
- `native/src/host/host_bindings.cc` — `create_comm_instance`, `set_comm_set_id`, `set_viewscreen_comm_source`/`clear_viewscreen_comm_source` bindings; comm render branch in `frame()`.
- `native/src/renderer/include/renderer/bridge_pass.h` + `native/src/renderer/bridge_pass.cc` — parameterize `render` + `walk_bridge_meshes` + skinned sub-pass by `Pass` and an optional `comm_set_id` filter.

**Tests:**
- `tests/unit/test_set_background_model.py` (new)
- `tests/host/test_realize_set.py` (new; absorbs/extends `test_realize_bridge_model.py`, `test_realize_viewscreen.py`, `test_place_bridge_officers.py`)
- `tests/host/test_comm_viewscreen_feed.py` (new)
- `native/tests/renderer/comm_pass_test.cc` (new; registered in the renderer_tests CMake target)

---

## Task 1: SetClass records background model + ambient

**Files:**
- Modify: `engine/appc/sets.py`
- Test: `tests/unit/test_set_background_model.py` (create)

**Interfaces:**
- Produces: `SetClass.SetBackgroundModel(self, nif: str, x=0.0, y=0.0, z=0.0) -> None` sets `self._background_model = (nif, (x, y, z))`. `SetClass.GetBackgroundModelNIF(self) -> str | None`. `SetClass.CreateAmbientLight` continues returning its existing value but also stores `self._ambient = (r, g, b, clamped_dimmer)`; add `GetAmbient(self) -> tuple | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_set_background_model.py
from engine.appc.sets import SetClass


def test_set_background_model_records_nif_and_offset():
    s = SetClass()
    s.SetBackgroundModel("data/Models/Sets/StarbaseControl/starbasecontrolRM.nif", 1.0, 2.0, 3.0)
    assert s.GetBackgroundModelNIF() == "data/Models/Sets/StarbaseControl/starbasecontrolRM.nif"
    assert s._background_model[1] == (1.0, 2.0, 3.0)


def test_set_background_model_default_offset_is_origin():
    s = SetClass()
    s.SetBackgroundModel("x.nif")
    assert s._background_model[1] == (0.0, 0.0, 0.0)


def test_get_background_model_nif_none_when_unset():
    assert SetClass().GetBackgroundModelNIF() is None


def test_create_ambient_light_records_clamped_dimmer():
    s = SetClass()
    s.CreateAmbientLight(1.0, 1.0, 1.0, 19.0, "ambientlight1")   # MissionLib outlier
    assert s.GetAmbient() == (1.0, 1.0, 1.0, 1.0)                # clamped to 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_set_background_model.py -v`
Expected: FAIL — `AttributeError` / `GetBackgroundModelNIF` returns a `_RendererStub`, `GetAmbient` missing.

- [ ] **Step 3: Implement**

In `engine/appc/sets.py`, add explicit methods to `SetClass` (above `__getattr__` so they take precedence). Find the current clamp logic already present in `CreateAmbientLight` (it currently falls through `__getattr__`; replace with a real method):

```python
    def SetBackgroundModel(self, nif, x=0.0, y=0.0, z=0.0):
        # SDK: comm/bridge sets declare their room geometry here. Recorded so
        # the host's realize_set can load + render it. (Was a _RendererStub no-op.)
        self._background_model = (str(nif), (float(x), float(y), float(z)))

    def GetBackgroundModelNIF(self):
        bm = getattr(self, "_background_model", None)
        return bm[0] if bm else None

    def CreateAmbientLight(self, r, g, b, dimmer, name):
        # 4th arg is range (MissionLib: 19.0) or dimmer (LoadBridge: 0.7); for
        # ambient, treat as dimmer clamped to [0, 1] (a 19x multiply would blow
        # the set to white). Recorded for realize_set's per-set lighting.
        d = max(0.0, min(1.0, float(dimmer)))
        self._ambient = (float(r), float(g), float(b), d)
        from engine.appc.lights import Light
        light = Light(name)
        self._lights[name] = light
        return light

    def GetAmbient(self):
        return getattr(self, "_ambient", None)
```

If `engine/appc/lights.py:Light` has a different constructor or `_lights` is keyed differently, match the existing `GetLight`/`_lights` usage already in `sets.py` (the prior `CreateAmbientLight` returned a light retrievable via `GetLight(name)`). Preserve that behavior.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/unit/test_set_background_model.py -v`
Expected: PASS.

- [ ] **Step 5: Verify no regression in light retrieval**

Run: `uv run pytest tests/unit/test_appc_lights.py tests/unit/test_set.py -q`
Expected: PASS (CreateAmbientLight still registers a retrievable light).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/sets.py tests/unit/test_set_background_model.py
git commit -m "feat(sets): SetBackgroundModel/CreateAmbientLight record on SetClass"
```

---

## Task 2: Generic `realize_set` — background geometry

**Files:**
- Modify: `engine/host_loop.py` (add `realize_set`; keep old functions for now, delete in Task 5)
- Test: `tests/host/test_realize_set.py` (create)

**Interfaces:**
- Consumes: `SetClass.GetBackgroundModelNIF()` (Task 1); the renderer wrapper `r.load_model`, `r.create_bridge_instance`, `r.create_comm_instance` (Task 7 — until then comm path is unreachable in tests, so Task 2 tests use the bridge carrier only), `r.set_world_transform`, `r.destroy_instance`.
- Produces: `realize_set(controller, r, set, *, is_bridge: bool) -> None`. Tags the set's geometry instance; records `set._geometry_instance` (new attr) for idempotency/leak-free reuse, and appends to `controller.comm_instances_by_set[set_name]` for comm sets.

- [ ] **Step 1: Write the failing test**

```python
# tests/host/test_realize_set.py
import engine.host_loop as hl


class _FakeRenderer:
    def __init__(self):
        self.loaded = []
        self.created = []
        self.destroyed = []
        self.transforms = {}
        self._next = 1

    def load_model(self, nif_abs, tex_abs):
        self.loaded.append((nif_abs, tex_abs))
        return 100 + len(self.loaded)

    def create_bridge_instance(self, handle):
        iid = ("bridge", self._next); self._next += 1
        self.created.append(("bridge", handle, iid)); return iid

    def create_comm_instance(self, handle):
        iid = ("comm", self._next); self._next += 1
        self.created.append(("comm", handle, iid)); return iid

    def set_world_transform(self, iid, mat): self.transforms[iid] = mat
    def destroy_instance(self, iid): self.destroyed.append(iid)


class _FakeBridgeObj:
    def __init__(self, nif): self.nif = nif; self.render_instance = None


def _bridge_set_with_geometry(nif="data/Models/Sets/DBridge/DBridge.nif"):
    from engine.appc.bridge_set import BridgeObjectClass
    from engine.appc.sets import SetClass
    s = SetClass(); s.SetName("bridge")
    obj = BridgeObjectClass(nif)
    s.AddObjectToSet(obj, "bridge")
    return s, obj


def test_realize_set_loads_bridge_geometry_and_tags_instance():
    s, obj = _bridge_set_with_geometry()

    class _C:
        bridge_instance = None
        nif_to_handle = {}
        comm_instances_by_set = {}
    c = _C(); r = _FakeRenderer()

    hl.realize_set(c, r, s, is_bridge=True)

    assert len(r.created) == 1
    kind, _handle, iid = r.created[0]
    assert kind == "bridge"
    assert obj.render_instance == iid
    assert c.bridge_instance == iid


def test_realize_set_bridge_geometry_is_idempotent():
    s, obj = _bridge_set_with_geometry()

    class _C:
        bridge_instance = None
        nif_to_handle = {}
        comm_instances_by_set = {}
    c = _C(); r = _FakeRenderer()

    hl.realize_set(c, r, s, is_bridge=True)
    hl.realize_set(c, r, s, is_bridge=True)   # same carrier -> no second instance
    assert len(r.created) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/host/test_realize_set.py -v`
Expected: FAIL — `AttributeError: module 'engine.host_loop' has no attribute 'realize_set'`.

- [ ] **Step 3: Implement `realize_set` geometry half**

In `engine/host_loop.py`, add (near the existing `_realize_bridge_model`):

```python
def realize_set(controller, r, set_obj, *, is_bridge: bool) -> None:
    """Realize any SDK set's renderable content into the renderer.

    Generic replacement for the bridge-specific _realize_bridge_model /
    _realize_viewscreen / _place_bridge_officers. Honors the SDK calls that
    declared the content:
      - bridge: BridgeObjectClass carrier (set.GetObject("bridge").nif)
      - comm:   set.GetBackgroundModelNIF()  (SetBackgroundModel)
    Idempotent + leak-free: a carrier that already has a render instance is
    reused; a fresh carrier (set rebuild) destroys the prior instance first.
    """
    import App as _App
    set_name = set_obj.GetName()

    # ── Background geometry ────────────────────────────────────────────────
    if is_bridge:
        carrier = set_obj.GetObject("bridge")
        nif = getattr(carrier, "nif", None) if carrier is not None else None
    else:
        carrier = set_obj
        nif = set_obj.GetBackgroundModelNIF()

    if nif and getattr(carrier, "render_instance", None) is None:
        if is_bridge and controller.bridge_instance is not None:
            try:
                r.destroy_instance(controller.bridge_instance)
            except Exception as _e:
                dev_mode.log_swallowed("destroy bridge instance", _e)
            controller.bridge_instance = None

        nif_abs = str(PROJECT_ROOT / "game" / nif)
        env = _App.g_kModelManager.env_for(nif)
        tex_abs = (str(PROJECT_ROOT / "game" / env) if env
                   else str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL))
        handle = r.load_model(nif_abs, tex_abs)
        if is_bridge:
            iid = r.create_bridge_instance(handle)
        else:
            iid = r.create_comm_instance(handle)
        r.set_world_transform(iid, IDENTITY_MAT4)
        if hasattr(carrier, "render_instance"):
            carrier.render_instance = iid
        controller.nif_to_handle[nif_abs] = handle
        if is_bridge:
            controller.bridge_instance = iid
            controller.current_bridge_nif_abs = nif_abs
        else:
            controller.comm_instances_by_set.setdefault(set_name, []).append(iid)
```

Add `self.comm_instances_by_set: dict = {}` to the controller `__init__` (alongside `self.bridge_instance`, ~line 1975).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/host/test_realize_set.py -v`
Expected: PASS (the comm path isn't exercised yet; `create_comm_instance` on `_FakeRenderer` exists for later tasks).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_realize_set.py
git commit -m "feat(host): generic realize_set — background geometry (bridge + comm)"
```

---

## Task 3: `realize_set` — viewscreen sub-step (bridge only)

**Files:**
- Modify: `engine/host_loop.py` (`realize_set`)
- Test: `tests/host/test_realize_set.py` (extend)

**Interfaces:**
- Consumes: `set.GetViewScreen()` (returns the `ViewScreenObject` or None); `r.set_viewscreen_model(handle)`.
- Produces: `realize_set` also realizes `set.GetViewScreen()` when `is_bridge` — same idempotency contract; sets `controller.viewscreen_instance` + `controller.viewscreen_obj`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/host/test_realize_set.py
def test_realize_set_realizes_bridge_viewscreen():
    from engine.appc.bridge_set import ViewScreenObject
    s, _obj = _bridge_set_with_geometry()
    vs = ViewScreenObject("data/Models/Sets/DBridge/DBridgeViewscreen.nif")
    s.SetViewScreen(vs)

    class _C:
        bridge_instance = None
        viewscreen_instance = None
        viewscreen_obj = None
        nif_to_handle = {}
        comm_instances_by_set = {}
    c = _C()

    class _R(_FakeRenderer):
        def __init__(s2): super().__init__(); s2.vs_model = None
        def set_viewscreen_model(s2, h): s2.vs_model = h
    r = _R()

    hl.realize_set(c, r, s, is_bridge=True)

    assert vs.render_instance is not None
    assert c.viewscreen_instance == vs.render_instance
    assert c.viewscreen_obj is vs
    assert r.vs_model is not None      # registered for the RTT feed
    assert vs.IsOn()                   # defaults on (SDK doesn't SetIsOn on load)
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/host/test_realize_set.py::test_realize_set_realizes_bridge_viewscreen -v`
Expected: FAIL — viewscreen not realized (`vs.render_instance is None`).

- [ ] **Step 3: Implement the viewscreen sub-step**

Append to `realize_set`, after the geometry block:

```python
    # ── Viewscreen (bridge only) ───────────────────────────────────────────
    if is_bridge:
        vs = set_obj.GetViewScreen()
        if vs is not None and hasattr(vs, "nif") and vs.render_instance is None:
            if controller.viewscreen_instance is not None:
                try:
                    r.destroy_instance(controller.viewscreen_instance)
                except Exception as _e:
                    dev_mode.log_swallowed("destroy viewscreen instance", _e)
                controller.viewscreen_instance = None
            vs_nif_abs = str(PROJECT_ROOT / "game" / vs.nif)
            vs_env = _App.g_kModelManager.env_for(vs.nif)
            vs_tex = (str(PROJECT_ROOT / "game" / vs_env) if vs_env
                      else str(PROJECT_ROOT / "game" / DBRIDGE_TEX_REL))
            vs_handle = r.load_model(vs_nif_abs, vs_tex)
            vs_iid = r.create_bridge_instance(vs_handle)
            r.set_world_transform(vs_iid, IDENTITY_MAT4)
            vs.render_instance = vs_iid
            controller.viewscreen_instance = vs_iid
            controller.nif_to_handle[vs_nif_abs] = vs_handle
            r.set_viewscreen_model(vs_handle)
            vs.SetIsOn(1)
            controller.viewscreen_obj = vs
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/host/test_realize_set.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_realize_set.py
git commit -m "feat(host): realize_set — bridge viewscreen sub-step"
```

---

## Task 4: `realize_set` — characters (generic placement)

**Files:**
- Modify: `engine/host_loop.py` (`realize_set` + extract the officer-placement body from `_place_bridge_officers` into a generic per-set loop)
- Test: `tests/host/test_realize_set.py` (extend)

**Interfaces:**
- Consumes: the existing officer pipeline used by `_place_bridge_officers` — `engine.appc.bridge_placement.capture_placement`, `assemble_officer`, `r.create_bridge_instance` / `r.create_comm_instance`, `r.set_world_transform`, `r.set_instance_animation`; the set's `CharacterClass` objects (enumerate via the same mechanism `_place_bridge_officers` uses today).
- Produces: `realize_set` places every `CharacterClass` in the set; comm characters use `create_comm_instance` and are tracked in `controller.comm_instances_by_set[set_name]`; each character carries a `_render_instance` tag to prevent double-placement.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/host/test_realize_set.py
def test_realize_set_places_characters_with_pass_matching_set_kind(monkeypatch):
    # A comm set with one character must place it via create_comm_instance and
    # track it under the set name.
    from engine.appc.sets import SetClass
    from engine.appc.characters import CharacterClass

    s = SetClass(); s.SetName("StarbaseSet")
    s.SetBackgroundModel("data/Models/Sets/StarbaseControl/starbasecontrolRM.nif")
    liu = CharacterClass("body.nif", "head.nif"); liu.SetCharacterName("Liu")
    s.AddObjectToSet(liu, "Liu")

    placed = []
    # Stub the heavy skinned-assembly path: realize_set must call a single
    # helper per character; assert it receives create_comm_instance for comm.
    monkeypatch.setattr(hl, "_place_one_character",
                        lambda c, r, ch, set_name, is_bridge: placed.append((ch.GetCharacterName(), is_bridge)))

    class _C:
        bridge_instance = None
        viewscreen_instance = None
        viewscreen_obj = None
        nif_to_handle = {}
        comm_instances_by_set = {}
    hl.realize_set(_C(), _FakeRenderer(), s, is_bridge=False)
    assert placed == [("Liu", False)]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/host/test_realize_set.py::test_realize_set_places_characters_with_pass_matching_set_kind -v`
Expected: FAIL — `realize_set` doesn't enumerate characters / `_place_one_character` missing.

- [ ] **Step 3: Extract `_place_one_character` and call it from `realize_set`**

Refactor the per-character body of `_place_bridge_officers` into:

```python
def _place_one_character(controller, r, character, set_name, is_bridge) -> None:
    """Pose one SDK CharacterClass at its station and create its skinned
    instance. Body extracted verbatim from the prior _place_bridge_officers
    loop; the only change is create_bridge_instance vs create_comm_instance
    and the comm_instances_by_set bookkeeping."""
    if getattr(character, "_render_instance", None) is not None:
        return
    # ... existing assemble_officer / capture_placement / set_world_transform /
    #     set_instance_animation body from _place_bridge_officers, using:
    create = r.create_bridge_instance if is_bridge else r.create_comm_instance
    # iid = create(handle); ...; character._render_instance = iid
    # if not is_bridge: controller.comm_instances_by_set.setdefault(set_name, []).append(iid)
```

(Move the real assembly code from `_place_bridge_officers` here unchanged except for the `create` selection and the comm tracking. The implementer reads the current `_place_bridge_officers` body, lines 2347+, and relocates it.)

Then in `realize_set`, after the viewscreen block:

```python
    # ── Characters ─────────────────────────────────────────────────────────
    for character in _iter_set_characters(set_obj):     # same enumeration the
        _place_one_character(controller, r, character,  # old officer loop used
                             set_name, is_bridge)
```

Add `_iter_set_characters(set_obj)` extracting the character-enumeration the old loop used (the `CharacterClass` walk of the set).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/host/test_realize_set.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/test_realize_set.py
git commit -m "feat(host): realize_set — generic character placement (bridge + comm)"
```

---

## Task 5: Mission-load wiring — realize all sets; retire bridge-specific functions

**Files:**
- Modify: `engine/host_loop.py` (replace the call sequence at ~line 2661; delete `_realize_bridge_model`, `_realize_viewscreen`, `_place_bridge_officers`)
- Test: adapt `tests/host/test_realize_bridge_model.py`, `test_realize_viewscreen.py`, `test_place_bridge_officers.py` to call `realize_set` (or delete if fully covered by `test_realize_set.py`)

**Interfaces:**
- Consumes: `realize_set` (Tasks 2-4); `_App.g_kSetManager` set enumeration.
- Produces: `realize_all_sets(controller, r) -> None` — realizes the `"bridge"` set as `is_bridge=True` and every other set with a background model or characters as `is_bridge=False`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/host/test_realize_set.py
def test_realize_all_sets_realizes_bridge_and_comm_sets(monkeypatch):
    import App as _App
    from engine.appc.sets import SetClass
    from engine.appc.bridge_set import BridgeObjectClass

    # Reset + register a bridge set and a comm set in the SetManager.
    seen = []
    monkeypatch.setattr(hl, "realize_set",
                        lambda c, r, s, *, is_bridge: seen.append((s.GetName(), is_bridge)))
    bridge = SetClass(); bridge.SetName("bridge")
    bridge.AddObjectToSet(BridgeObjectClass("b.nif"), "bridge")
    comm = SetClass(); comm.SetName("StarbaseSet"); comm.SetBackgroundModel("c.nif")
    _App.g_kSetManager.AddSet(bridge, "bridge")
    _App.g_kSetManager.AddSet(comm, "StarbaseSet")

    hl.realize_all_sets(object(), object())
    assert ("bridge", True) in seen
    assert ("StarbaseSet", False) in seen
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/host/test_realize_set.py::test_realize_all_sets_realizes_bridge_and_comm_sets -v`
Expected: FAIL — `realize_all_sets` missing.

- [ ] **Step 3: Implement `realize_all_sets` + swap the call site**

```python
def realize_all_sets(controller, r) -> None:
    """Realize every SDK-created set into the renderer after mission load.
    The 'bridge' set is the player bridge; any other set that declared a
    background model or characters is a comm/remote set."""
    import App as _App
    mgr = _App.g_kSetManager
    for name, s in list(mgr.iter_sets()):          # use the manager's set map
        if name == "bridge":
            realize_set(controller, r, s, is_bridge=True)
        elif s.GetBackgroundModelNIF() is not None or _iter_set_characters(s):
            realize_set(controller, r, s, is_bridge=False)
```

If `g_kSetManager` has no `iter_sets()`, add a minimal accessor returning `self._sets.items()` to the set manager (check `engine/appc/sets.py` for the manager class) — match its existing private storage.

Replace the call site (~line 2661):

```python
            realize_all_sets(controller, r)
```

Delete `_realize_bridge_model`, `_realize_viewscreen`, `_place_bridge_officers`.

- [ ] **Step 4: Run the adapted + full host suite**

Run: `uv run pytest tests/host/ tests/unit/test_set.py -q`
Expected: PASS. Update/delete the three old tests so none import the deleted functions.

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/host/
git commit -m "refactor(host): realize_all_sets replaces bridge-specific realize functions"
```

---

## Task 6: Native — `Pass::Comm` + per-instance set tag

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h`
- Test: `native/tests/renderer/comm_pass_test.cc` (create; add to the renderer_tests target in the renderer tests `CMakeLists.txt`)

**Interfaces:**
- Produces: `enum class Pass { Space=0, Bridge=1, Comm=2 }`; `Instance::comm_set_id` (`std::uint32_t`, default 0 = "no comm set").

- [ ] **Step 1: Write the failing test**

```cpp
// native/tests/renderer/comm_pass_test.cc
#include <gtest/gtest.h>
#include "scenegraph/world.h"
#include "scenegraph/instance.h"

TEST(CommPass, InstanceCarriesCommSetIdAndPass) {
    scenegraph::World w;
    auto id = w.create_instance(0);
    w.set_pass(id, scenegraph::Pass::Comm);
    int count = 0;
    w.for_each_visible_in_pass(scenegraph::Pass::Comm,
        [&](const scenegraph::Instance&) { ++count; });
    EXPECT_EQ(count, 1);
}
```

Register the file in the renderer tests CMake target (find the `add_executable(renderer_tests ...)` / `target_sources` list in `native/tests/renderer/CMakeLists.txt` and append `comm_pass_test.cc`).

- [ ] **Step 2: Build + run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j --target renderer_tests && build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.*'`
Expected: FAIL to compile — `Pass::Comm` does not exist.

- [ ] **Step 3: Implement**

In `instance.h`:

```cpp
enum class Pass : std::uint8_t { Space = 0, Bridge = 1, Comm = 2 };
```

Add to `struct Instance` (near `Pass pass = Pass::Space;`):

```cpp
    /// Which comm/remote set this instance belongs to (0 = none). Lets the
    /// comm render branch draw only the viewscreen's active set when several
    /// comm sets are realized at once.
    std::uint32_t comm_set_id = 0;
```

- [ ] **Step 4: Build + run**

Run: `cmake --build build -j --target renderer_tests && build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.*'`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/scenegraph/include/scenegraph/instance.h native/tests/renderer/comm_pass_test.cc native/tests/renderer/CMakeLists.txt
git commit -m "feat(scenegraph): add Pass::Comm and Instance::comm_set_id"
```

---

## Task 7: Native — `create_comm_instance` + `set_comm_set_id` bindings

**Files:**
- Modify: `native/src/host/host_bindings.cc`
- Modify: `engine/renderer.py` (wrappers)
- Test: `native/tests/renderer/comm_pass_test.cc` (extend) + `tests/host/test_realize_set.py` already exercises the wrapper via fakes

**Interfaces:**
- Produces (native): `m.def("create_comm_instance", ...)` tags `Pass::Comm`; `m.def("set_comm_set_id", [](InstanceId, unsigned) ...)`.
- Produces (Python wrapper): `engine.renderer.create_comm_instance(model) -> InstanceId`; `engine.renderer.set_comm_set_id(iid, set_id) -> None`.

- [ ] **Step 1: Write the failing test (native)**

```cpp
// append to comm_pass_test.cc
TEST(CommPass, SetCommSetIdFiltersInstances) {
    scenegraph::World w;
    auto a = w.create_instance(0); w.set_pass(a, scenegraph::Pass::Comm);
    auto b = w.create_instance(0); w.set_pass(b, scenegraph::Pass::Comm);
    w.set_comm_set_id(a, 7);
    w.set_comm_set_id(b, 9);
    int only7 = 0;
    w.for_each_visible_in_pass(scenegraph::Pass::Comm,
        [&](const scenegraph::Instance& i){ if (i.comm_set_id == 7) ++only7; });
    EXPECT_EQ(only7, 1);
}
```

- [ ] **Step 2: Build + run to verify it fails**

Run: `cmake --build build -j --target renderer_tests && build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.*'`
Expected: FAIL — `World::set_comm_set_id` missing.

- [ ] **Step 3: Implement**

`native/src/scenegraph/include/scenegraph/world.h` — add next to `set_pass`:

```cpp
    void set_comm_set_id(InstanceId id, std::uint32_t set_id);
```

`native/src/scenegraph/world.cc` (mirror `set_pass`'s body):

```cpp
void World::set_comm_set_id(InstanceId id, std::uint32_t set_id) {
    if (Instance* inst = get(id)) inst->comm_set_id = set_id;
}
```

`host_bindings.cc` — after the `create_bridge_instance` binding (~line 762):

```cpp
    m.def("create_comm_instance",
          [](scenegraph::ModelHandle h) {
              auto id = g_world.create_instance(h);
              g_world.set_pass(id, scenegraph::Pass::Comm);
              return id;
          },
          py::arg("model"),
          "Like create_instance but tags the new instance for the comm pass.");
    m.def("set_comm_set_id",
          [](scenegraph::InstanceId id, unsigned int set_id) {
              g_world.set_comm_set_id(id, set_id);
          },
          py::arg("id"), py::arg("set_id"));
```

`engine/renderer.py` — add wrappers mirroring `create_bridge_instance` (~line 287):

```python
def create_comm_instance(model: int) -> "InstanceId":
    return _host.create_comm_instance(model)


def set_comm_set_id(iid: "InstanceId", set_id: int) -> None:
    _host.set_comm_set_id(iid, set_id)
```

(Match the module's actual handle name — `_host` / `_open_stbc_host` / `_dauntless_host` — used by the neighboring wrappers.)

- [ ] **Step 4: Build + run**

Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.*'`
Expected: PASS. (Full `dauntless` rebuild because `host_bindings.cc` changed.)

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc native/src/scenegraph/include/scenegraph/world.h native/src/scenegraph/world.cc engine/renderer.py native/tests/renderer/comm_pass_test.cc
git commit -m "feat(host): create_comm_instance + set_comm_set_id bindings"
```

---

## Task 8: Native — parameterize the bridge pass by `Pass` + set filter + camera

**Files:**
- Modify: `native/src/renderer/include/renderer/bridge_pass.h`, `native/src/renderer/bridge_pass.cc`
- Test: `native/tests/renderer/comm_pass_test.cc` (extend) — render a Comm instance into an offscreen target and assert non-empty (mirror the existing `SkinnedBridgeTest` readback pattern)

**Interfaces:**
- Produces: `BridgePass::render(world, camera, pipeline, lookup, lighting, Pass pass = Pass::Bridge, std::uint32_t comm_set_id = 0)`. `walk_bridge_meshes` and the skinned sub-pass take the same `pass` + `comm_set_id` and filter on them (`comm_set_id == 0` means "no set filter").

- [ ] **Step 1: Write the failing test**

Mirror `SkinnedBridgeTest.SkinnedCharacterRendersLitByBridgeAmbient` (read it for the offscreen-render + readback harness), but tag the instance `Pass::Comm` with a `comm_set_id`, call `render(..., Pass::Comm, set_id)`, and assert the target is non-empty. Name it `CommPass.RendersTaggedSetFromCamera`. (Use the same fixture/util the skinned test uses.)

- [ ] **Step 2: Build + run to verify it fails**

Run: `cmake --build build -j --target renderer_tests && build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.RendersTaggedSetFromCamera'`
Expected: FAIL — `render` has no `Pass`/`comm_set_id` params.

- [ ] **Step 3: Implement parameterization**

`bridge_pass.h` — update the signature:

```cpp
    void render(const scenegraph::World& world,
                const scenegraph::Camera& camera,
                Pipeline& pipeline,
                const ModelLookup& lookup,
                const Lighting& lighting,
                scenegraph::Pass pass = scenegraph::Pass::Bridge,
                std::uint32_t comm_set_id = 0);
```

`bridge_pass.cc`:
- `walk_bridge_meshes` — add `scenegraph::Pass pass` + `std::uint32_t comm_set_id` params; change `for_each_visible_in_pass(scenegraph::Pass::Bridge, ...)` to use `pass`, and inside the callback `if (comm_set_id != 0 && inst.comm_set_id != comm_set_id) return;`.
- The skinned sub-pass loop (`for_each_visible_in_pass(scenegraph::Pass::Bridge, ...)`, ~line 236) — same `pass` + `comm_set_id` filter.
- `render` — thread `pass` + `comm_set_id` into both `walk_bridge_meshes` calls and the skinned loop. Keep the existing `Pass::Bridge` callers working via the defaults.

- [ ] **Step 4: Build + run (comm + bridge tests)**

Run: `cmake --build build -j && build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.*:SkinnedBridgeTest.*:BridgePassPartitioning.*'`
Expected: PASS (bridge unaffected by defaults; comm renders).

- [ ] **Step 5: Commit**

```bash
git add native/src/renderer/include/renderer/bridge_pass.h native/src/renderer/bridge_pass.cc native/tests/renderer/comm_pass_test.cc
git commit -m "feat(render): parameterize bridge pass by Pass + comm set filter + camera"
```

---

## Task 9: Native — comm render branch into the viewscreen target

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`frame()` + bindings)
- Test: exercised end-to-end by Task 10's Python feed test + manual in-game verification (no offscreen readback test for `frame()` — it isn't unit-harnessed)

**Interfaces:**
- Produces (native): `m.def("set_viewscreen_comm_source", [](unsigned set_id, eye, target, up, fov_y_rad, near, far) ...)` stores `g_comm_source` (active set id + a `scenegraph::Camera`); `m.def("clear_viewscreen_comm_source", ...)` zeroes it. `frame()`'s viewscreen-RTT block renders the comm source when set, else the forward feed.

- [ ] **Step 1: Add the bindings + state**

In `host_bindings.cc` near the other viewscreen globals (`g_viewscreen_enabled`, ~line 161):

```cpp
struct CommSource { bool active = false; std::uint32_t set_id = 0; scenegraph::Camera cam; };
CommSource g_comm_source;
```

Bindings (near `set_viewscreen_enabled`, ~line 933):

```cpp
    m.def("set_viewscreen_comm_source",
          [](unsigned int set_id,
             std::tuple<float,float,float> eye,
             std::tuple<float,float,float> target,
             std::tuple<float,float,float> up,
             float fov_y_rad, float near, float far) {
              g_comm_source.active = true;
              g_comm_source.set_id = set_id;
              g_comm_source.cam.eye    = {std::get<0>(eye),    std::get<1>(eye),    std::get<2>(eye)};
              g_comm_source.cam.target = {std::get<0>(target), std::get<1>(target), std::get<2>(target)};
              g_comm_source.cam.up     = {std::get<0>(up),     std::get<1>(up),     std::get<2>(up)};
              g_comm_source.cam.fov_y_rad = fov_y_rad;
              g_comm_source.cam.near = near;
              g_comm_source.cam.far  = far;
          },
          py::arg("set_id"), py::arg("eye"), py::arg("target"),
          py::arg("up"), py::arg("fov_y_rad"), py::arg("near"), py::arg("far"));
    m.def("clear_viewscreen_comm_source",
          []() { g_comm_source.active = false; });
```

- [ ] **Step 2: Render the comm source in `frame()`**

In the RTT block (`if (viewscreen_on) { ... }`, ~line 429), after binding `g_viewscreen_hdr` and clearing, branch:

```cpp
    if (viewscreen_on) {
        g_viewscreen_hdr->resize(kViewscreenRttW, kViewscreenRttH);
        g_viewscreen_hdr->bind();
        glClearColor(0.0f, 0.0f, 0.0f, 1.0f);
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT);
        if (g_comm_source.active && g_bridge_pass) {
            scenegraph::Camera ccam = g_comm_source.cam;
            ccam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            g_bridge_pass->render(g_world, ccam, *g_pipeline, lookup,
                                  g_bridge_lighting, scenegraph::Pass::Comm,
                                  g_comm_source.set_id);
        } else {
            scenegraph::Camera vcam = g_camera;
            vcam.aspect = static_cast<float>(kViewscreenRttW)
                        / static_cast<float>(kViewscreenRttH);
            render_space(vcam, /*for_viewscreen=*/true);
        }
        g_bridge_pass->set_viewscreen_texture(g_viewscreen_hdr->color_texture());
    } else if (g_bridge_pass) {
        g_bridge_pass->set_viewscreen_texture(0);
    }
```

- [ ] **Step 3: Add Python wrappers**

`engine/renderer.py`:

```python
def set_viewscreen_comm_source(set_id, eye, target, up, fov_y_rad, near, far) -> None:
    _host.set_viewscreen_comm_source(set_id, eye, target, up, fov_y_rad, near, far)


def clear_viewscreen_comm_source() -> None:
    _host.clear_viewscreen_comm_source()
```

- [ ] **Step 4: Build**

Run: `cmake --build build -j` (full `dauntless` rebuild — `host_bindings.cc` changed).
Expected: builds clean; `build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.*:SkinnedBridgeTest.*'` still PASS.

- [ ] **Step 5: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py
git commit -m "feat(host): comm render branch into the viewscreen RTT target"
```

---

## Task 10: Python — viewscreen feed selection (comm vs forward); retire CommRenderFlag

**Files:**
- Modify: `engine/host_loop.py` (per-frame feed selection at ~line 3408-3412)
- Delete: `engine/appc/comm_render_flag.py` and its import/usage
- Test: `tests/host/test_comm_viewscreen_feed.py` (create)

**Interfaces:**
- Consumes: `controller.viewscreen_obj` (the bridge `ViewScreenObject`); its `GetRemoteCam()` returning a `CameraObjectClass`; `App.g_kSetManager` set enumeration; `controller.comm_set_ids` (a `dict[set_name -> int]` assigned in Task 4/5 when comm instances are tagged — add it); `engine.renderer.set_viewscreen_comm_source` / `clear_viewscreen_comm_source`.
- Produces: `_active_comm_feed(controller) -> tuple[int, CameraObjectClass] | None` — resolves the active comm set + camera, or None for the forward fallback.

- [ ] **Step 1: Assign stable comm set ids during realization**

In `realize_set` (Task 4 character path) and `realize_all_sets`, assign each comm set a small positive int id and tag its instances via `r.set_comm_set_id(iid, set_id)`. Store `controller.comm_set_ids[set_name] = set_id`. (Allocate ids sequentially from 1 in `realize_all_sets`.) Add `self.comm_set_ids: dict = {}` to the controller.

- [ ] **Step 2: Write the failing test**

```python
# tests/host/test_comm_viewscreen_feed.py
import engine.host_loop as hl


class _Cam:  # stand-in for CameraObjectClass
    pass


class _VS:
    def __init__(self, on, cam): self._on, self._cam = on, cam
    def IsOn(self): return self._on
    def GetRemoteCam(self): return self._cam


def test_active_comm_feed_resolves_set_from_remote_cam(monkeypatch):
    import App as _App
    from engine.appc.sets import SetClass
    cam = _Cam()
    s = SetClass(); s.SetName("StarbaseSet")
    s.AddCameraToSet(cam, "maincamera")
    _App.g_kSetManager.AddSet(s, "StarbaseSet")

    class _C:
        comm_set_ids = {"StarbaseSet": 3}
        viewscreen_obj = _VS(on=1, cam=cam)
    res = hl._active_comm_feed(_C())
    assert res is not None
    set_id, out_cam = res
    assert set_id == 3 and out_cam is cam


def test_active_comm_feed_none_when_remote_cam_is_not_a_set_maincamera():
    class _C:
        comm_set_ids = {}
        viewscreen_obj = _VS(on=1, cam=_Cam())
    assert hl._active_comm_feed(_C()) is None
```

- [ ] **Step 3: Run to verify it fails**

Run: `uv run pytest tests/host/test_comm_viewscreen_feed.py -v`
Expected: FAIL — `_active_comm_feed` missing.

- [ ] **Step 4: Implement `_active_comm_feed` + frame wiring**

```python
def _active_comm_feed(controller):
    """If the bridge viewscreen's remote cam is a comm set's 'maincamera',
    return (comm_set_id, camera); else None (forward-view fallback)."""
    vs = getattr(controller, "viewscreen_obj", None)
    if vs is None or not vs.IsOn():
        return None
    cam = vs.GetRemoteCam()
    if cam is None:
        return None
    import App as _App
    for name, s in list(_App.g_kSetManager.iter_sets()):
        if s.GetCamera("maincamera") is cam:
            set_id = controller.comm_set_ids.get(name)
            if set_id is not None:
                return (set_id, cam)
    return None
```

Replace the per-frame block (~3408-3412) — drop `_comm_render_flag.notice(...)`:

```python
            _vs_obj = getattr(controller, "viewscreen_obj", None)
            r.set_viewscreen_enabled(_viewscreen_feed_on(_vs_obj))
            _feed = _active_comm_feed(controller)
            if _feed is not None:
                _set_id, _cam = _feed
                _eye, _tgt, _up, _fov, _near, _far = _comm_camera_params(_cam)
                r.set_viewscreen_comm_source(_set_id, _eye, _tgt, _up, _fov, _near, _far)
            else:
                r.clear_viewscreen_comm_source()
```

Add `_comm_camera_params(cam)` converting a `CameraObjectClass` (position + orientation `TGMatrix3` + frustum/near/far) into `(eye, target, up, fov_y_rad, near, far)`: `eye = cam.position`; `forward = cam.orientation.GetCol(1)`, `up = cam.orientation.GetCol(2)`; `target = eye + forward`; `fov_y_rad` derived from the `_NiFrustum` top/bottom + near (`2*atan((top-bottom)/2 / near)`), or a sensible default if the frustum is degenerate. (Reuse any existing frustum→fov helper if `engine/host_loop.py` already has one for the bridge camera.)

Remove the `from engine.appc.comm_render_flag import CommRenderFlag` import and the `_comm_render_flag = CommRenderFlag()` construction (~line 2670). Delete `engine/appc/comm_render_flag.py`.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/host/test_comm_viewscreen_feed.py tests/host/ -q`
Expected: PASS. Grep to confirm no remaining `comm_render_flag` references: `grep -rn comm_render_flag engine/ tests/` → empty.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py tests/host/test_comm_viewscreen_feed.py
git rm engine/appc/comm_render_flag.py
git commit -m "feat(host): drive viewscreen comm feed from remote cam; retire CommRenderFlag"
```

---

## Task 11: Full verification + in-game check

**Files:** none (verification only)

- [ ] **Step 1: Full Python suite under the watchdog**

Run: `scripts/run_tests.sh tests/unit tests/host`
Expected: all PASS, peak RSS well under ceiling.

- [ ] **Step 2: Renderer tests (note pre-existing batch flakiness)**

Run: `build/native/tests/renderer/renderer_tests --gtest_filter='CommPass.*:BridgePassPartitioning.*:SkinnedBridgeTest.*:PipelineTest.*'`
Expected: PASS. (The full-suite GL-readback failures are a pre-existing test-isolation artifact — confirm any failure also fails on `main` by running it standalone.)

- [ ] **Step 3: Clean build**

Run: `cmake -B build -S . && cmake --build build -j`
Expected: `dauntless` + `_dauntless_host` build clean.

- [ ] **Step 4: In-game verification (user-driven)**

Launch `./build/dauntless --developer`, run E1M1 to a Starbase 12 hail. Expected: the viewscreen shows Liu (lego-headed, per the accepted scope) in the StarbaseControl room, framed by the set's maincamera; `ViewscreenOff` returns the forward view. Confirm the player bridge, officers, walk-on, and crew menus still render. (Cannot be automated / screenshotted on the workstation — user confirms.)

- [ ] **Step 5: Final commit (if any verification fixups)**

```bash
git add -A
git commit -m "test: comm-set viewscreen rendering — full verification pass"
```

---

## Self-Review Notes

- **Spec coverage:** §4.1 realization → Tasks 1-5; §4.2 Pass::Comm + tag → Task 6; §4.3 camera → Task 10 (`_comm_camera_params`); §4.4 data flow → Tasks 5,9,10; §4.5 native branch → Tasks 8-9; §6 testing → tests in each task + Task 11; CommRenderFlag retirement → Task 10.
- **Deferred (out of scope, no tasks):** static overlay, hail-face variations, ViewOn/Off polish, viewscreen menus, lego-head fix — matches spec §1.
- **Type consistency:** `realize_set(controller, r, set, *, is_bridge)`, `_place_one_character(controller, r, character, set_name, is_bridge)`, `comm_set_ids: dict[str,int]`, `set_comm_set_id(iid, set_id)`, `set_viewscreen_comm_source(set_id, eye, target, up, fov_y_rad, near, far)`, `render(..., Pass, comm_set_id)` used consistently across tasks.
- **Known dependency on in-file reading:** Task 4 relocates the existing `_place_bridge_officers` body and Task 5 may add `iter_sets()` to the set manager — both grounded in current code the implementer has open.
