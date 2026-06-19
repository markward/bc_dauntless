# Bridge Breathing Idle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bridge officers continuously loop their authentic per-station breathe idle, layered over the placement pose, as their default state — so they breathe at load and return to breathing (not a frozen frame) after each gesture.

**Architecture:** Officers are positioned by the placement clip's root translation (the layering anchor in `inst.rest_pose`). The SDK-registered `<location>Breathe` clip is a root-less full-body idle; played with `loop=true` + `layer_over_rest=true` it supplies the body pose while the placement supplies the root. The renderer already supports loop+layer; this adds one binding, an SDK-lookup capture, and rewires the controller's default-return from a static frame to the breathe loop.

**Tech Stack:** C++ (renderer/scenegraph, GoogleTest/ctest), pybind11, Python (`engine/`, pytest), GLM.

## Global Constraints

- One build tree at `<root>/build/`; `cmake --build build -j` after `native/` edits; host_bindings.cc edits rebuild both `build/dauntless` and the `_dauntless_host` module. Never cmake inside `native/`.
- Host module imports as `_dauntless_host`, wrapped by `engine/renderer.py` as `_h`. New `r.<binding>` calls from host_loop/controller are `hasattr`-guarded so the FakeRenderer / engineless paths no-op.
- SDK-driven: the breathe clip choice comes ENTIRELY from the officer's registered `<location>Breathe` animation. We never pick or invent a pose.
- The placement rest pose (`inst.rest_pose`, set by `set_instance_rest_pose`) stays the layering anchor (frame 0). Breathing layers over it; it does not replace it.
- Breathing is best-effort at placement: a breathing failure must NOT unplace a correctly-stationed officer.
- TDD: failing test first. Python: `uv run pytest`. C++: `cmake --build build -j && ctest --test-dir build --output-on-failure -R <name>`.
- Do NOT launch the GUI (the user verifies the visual).

---

### Task 1: Native `play_instance_idle` (looping layered idle) + binding

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`play_instance_idle` binding)
- Modify: `engine/renderer.py` (wrapper)
- Test: `native/tests/renderer/animation_update_test.cc` (loop+layer keeps root anchored, never settles)

**Interfaces:**
- Produces (Python): `renderer.play_instance_idle(iid, clip_index)` — sets the instance animation to `{clip_index, loop=true, layer_over_rest=true}`.
- Consumes: existing `World::set_animation`, `sample_pose_over_base`, `AnimationState.{loop,layer_over_rest}` (all present), and the `two_clip_layered_model()` test helper in `animation_update_test.cc`.

- [ ] **Step 1: Write the failing C++ test**

Add to `native/tests/renderer/animation_update_test.cc` (mirrors `LayerOverRestKeepsRootAtStation` at line 190, which uses `two_clip_layered_model()` — clip[0] = placement positioning the root at `(33,-104,23)`, clip[1] = a root-less body clip):

```cpp
TEST(AnimationUpdate, LoopingLayeredIdleStaysAnchoredAndNeverSettles) {
    // Breathing: clip[1] played with loop=true + layer_over_rest=true must keep
    // the root at the placement station across cycling t, and never settle (it
    // loops forever until replaced).
    assets::Model model = two_clip_layered_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);

    scenegraph::Instance::AnimationState rest_st;
    rest_st.clip_index = 0;
    rest_st.sample_at_end = true;        // placement holds last frame = station
    world.set_rest_pose(id, rest_st);

    scenegraph::Instance::AnimationState idle_st;
    idle_st.clip_index = 1;
    idle_st.loop = true;
    idle_st.layer_over_rest = true;
    idle_st.start_wall_time = 0.0;
    world.set_animation(id, idle_st);

    auto root_world_at = [&](double now) {
        renderer::update_animations(world, lookup, now);
        return glm::vec3(world.get(id)->bone_palette[0] * glm::vec4(0,0,0,1));
    };

    // Sample within the first cycle and well past the clip duration (looped).
    glm::vec3 r1 = root_world_at(0.3);
    EXPECT_FALSE(world.get(id)->animation.settled);   // looping never settles
    glm::vec3 r2 = root_world_at(50.0);
    EXPECT_FALSE(world.get(id)->animation.settled);

    // Root stays at the station at BOTH times (the idle clip has no root track).
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r1, glm::vec3(33,-104,23), 1e-3f)));
    EXPECT_TRUE(glm::all(glm::epsilonEqual(r2, glm::vec3(33,-104,23), 1e-3f)));
}
```

- [ ] **Step 2: Run to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure -R "AnimationUpdate.LoopingLayeredIdle"`
Expected: PASS or FAIL — the native loop+layer behavior already exists, so this test may PASS immediately (it documents/guards the combined behavior). If it PASSES, note that in the report and proceed; if it FAILS, the failure pinpoints a real loop+layer gap to fix before continuing. (Either way the binding in Step 3 is still required.)

- [ ] **Step 3: Add the `play_instance_idle` binding**

In `native/src/host/host_bindings.cc`, immediately after the `restore_rest_pose` binding:

```cpp
    m.def("play_instance_idle",
          [](scenegraph::InstanceId id, int clip_index) {
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = true;
              st.layer_over_rest = true;
              st.start_wall_time = glfwGetTime();
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Loop a layered idle (e.g. breathing) over the instance's rest pose: "
          "the idle clip drives the body, the placement supplies the root + any "
          "bones the idle doesn't track. Loops until a gesture or restore "
          "replaces it.");
```

- [ ] **Step 4: Add the Python wrapper**

In `engine/renderer.py`, after `restore_rest_pose`:

```python
def play_instance_idle(iid: InstanceId, clip_index: int) -> None:
    """Loop a layered idle (breathing) over the officer's rest pose: the idle
    clip drives the body, the placement supplies the root. Loops until a gesture
    or restore_rest_pose replaces it."""
    _h.play_instance_idle(iid, clip_index)
```

- [ ] **Step 5: Rebuild, run the test, confirm the binding is importable**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R "AnimationUpdate.LoopingLayeredIdle" && uv run python -c "import sys; sys.path.insert(0,'build/python'); import _dauntless_host as h; print(hasattr(h,'play_instance_idle'))"`
Expected: test PASS, prints `True`.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py native/tests/renderer/animation_update_test.cc
git commit -m "feat(native): play_instance_idle — looping layered breathe idle"
```

---

### Task 2: `capture_breathing` — resolve the officer's breathe clip from the SDK

**Files:**
- Modify: `engine/appc/bridge_placement.py` (add `capture_breathing`)
- Test: `tests/unit/test_bridge_breathing_capture.py` (new)

**Interfaces:**
- Produces: `capture_breathing(character) -> {"clip_nif": str} | None`.
- Consumes: `character.GetLocation()`, `character._animations` (list of `(key, module_path)`), the SDK `CommonAnimations` builders, `App.g_kAnimationManager.path_for`.

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_bridge_breathing_capture.py`:

```python
import App
from engine.appc.bridge_placement import capture_breathing


def _char(location, breathe_entry=None):
    c = App.CharacterClass_Create(
        "data/Models/Characters/Bodies/BodyMaleL/BodyMaleL.nif",
        "data/Models/Characters/Heads/HeadFelix/felix_head.nif",
    )
    c.SetCharacterName("Test")
    if location is not None:
        c.SetLocation(location)
    if breathe_entry is not None:
        c.AddAnimation(*breathe_entry)
    return c


def test_standing_station_resolves_standing_console():
    c = _char("DBEngineer",
              ("DBEngineerBreathe", "Bridge.Characters.CommonAnimations.StandingConsole"))
    p = capture_breathing(c)
    assert p == {"clip_nif": "data/animations/standing_console.NIF"}


def test_seated_station_resolves_seated_clip():
    c = _char("DBHelm",
              ("DBHelmBreathe", "Bridge.Characters.CommonAnimations.SeatedM"))
    p = capture_breathing(c)
    assert p == {"clip_nif": "data/animations/seated_M.nif"}


def test_no_breathe_registration_returns_none():
    c = _char("DBEngineer")          # location set, but no <loc>Breathe entry
    assert capture_breathing(c) is None


def test_no_location_returns_none():
    c = _char(None,
              ("DBEngineerBreathe", "Bridge.Characters.CommonAnimations.StandingConsole"))
    assert capture_breathing(c) is None
```

(If `path_for` returns a different exact case/path for these clips, adjust the two expected strings to match what `App.g_kAnimationManager.path_for` records after the builder's `LoadAnimation` — run the test once to read the actual value and pin it.)

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_breathing_capture.py -v`
Expected: FAIL — `capture_breathing` not defined (ImportError).

- [ ] **Step 3: Implement `capture_breathing`**

In `engine/appc/bridge_placement.py`, add (mirrors `capture_placement`'s clip-name → NIF resolution; resolves the SDK builder by the `<location>Breathe` registered key):

```python
def capture_breathing(character):
    """Return the officer's looping breathe idle clip, or None.

    The breathe clip is the SDK-registered "<location>Breathe" animation (e.g.
    DBEngineerBreathe -> CommonAnimations.StandingConsole). It is the
    authoritative idle BODY pose; the placement supplies the root (position) via
    layering. Returns {"clip_nif": <data-root-relative path>} or None when the
    officer has no location or no <location>Breathe registration.
    """
    import importlib
    import App

    location = character.GetLocation()
    if not location:
        return None
    key = str(location) + "Breathe"
    module_path = None
    for entry in getattr(character, "_animations", []):
        if entry and len(entry) >= 2 and str(entry[0]) == key:
            module_path = entry[1]
            break
    if not module_path:
        return None

    try:
        mod_name, func_name = module_path.rsplit(".", 1)
        func = getattr(importlib.import_module(mod_name), func_name)
        seq = func(character)
    except Exception:
        return None
    if seq is None or seq.GetNumActions() == 0:
        return None
    action = seq.GetAction(seq.GetNumActions() - 1)
    clip_name = getattr(action, "_clip", "") or getattr(action, "name", "")
    if not clip_name:
        return None

    clip_nif = App.g_kAnimationManager.path_for(clip_name)
    if not clip_nif:
        _logger.warning("capture_breathing: no path recorded for clip %r", clip_name)
        return None
    return {"clip_nif": clip_nif}
```

- [ ] **Step 4: Run to verify it passes (and pin the exact paths)**

Run: `uv run pytest tests/unit/test_bridge_breathing_capture.py -v`
Expected: PASS. If the two path assertions mismatch, read the actual `clip_nif` from the failure and update the expected strings (Step 1 note), then re-run to green.

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_placement.py tests/unit/test_bridge_breathing_capture.py
git commit -m "feat(bridge): capture_breathing — resolve the SDK <location>Breathe idle clip"
```

---

### Task 3: Controller returns to the breathe loop (not a static frame)

**Files:**
- Modify: `engine/bridge_character_anim.py` (`set_idle`, idle registry, completion resumes breathing, `reset` clears it)
- Test: `tests/unit/test_bridge_character_anim.py` (resume-breathing + fallback + reset)

**Interfaces:**
- Produces: `BridgeCharacterAnimController.set_idle(iid, clip_index)`; on action completion the controller calls `renderer.play_instance_idle(iid, idle_idx)` when an idle clip is registered for `iid`, else `renderer.restore_rest_pose(iid)`.
- Consumes: `renderer.play_instance_idle` (Task 1).

- [ ] **Step 1: Update the FakeRenderer + write failing tests**

In `tests/unit/test_bridge_character_anim.py`, add `play_instance_idle` to `_FakeRenderer` (after `restore_rest_pose`):

```python
    def play_instance_idle(self, iid, clip_index):
        self.idled.append((iid, clip_index))
```

and initialise `self.idled = []` in its `__init__`. Then append these tests:

```python
def test_completion_resumes_breathing_when_idle_registered():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(8)
    ctrl.set_idle(8, 99)                       # breathe clip index for iid 8
    ctrl.submit(ch, [("g.nif", 0.5)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)    # start gesture
    ctrl.update(0.5, renderer=r, anim_mgr=None)    # complete -> resume breathing
    assert r.idled == [(8, 99)]                # play_instance_idle called
    assert r.restored == []                    # NOT restore_rest_pose


def test_completion_falls_back_to_restore_when_no_idle():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(9)                              # no set_idle for 9
    ctrl.submit(ch, [("g.nif", 0.5)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    ctrl.update(0.5, renderer=r, anim_mgr=None)
    assert r.idled == []
    assert r.restored == [9]                   # static fallback


def test_reset_clears_idle_registry():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(10)
    ctrl.set_idle(10, 42)
    ctrl.reset()
    ctrl.submit(ch, [("g.nif", 0.5)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    ctrl.update(0.5, renderer=r, anim_mgr=None)
    assert r.idled == []                       # registry cleared -> fallback
    assert r.restored == [10]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -v`
Expected: FAIL — `set_idle` not defined / completion still calls `restore_rest_pose`.

- [ ] **Step 3: Implement the idle registry + resume-on-completion**

In `engine/bridge_character_anim.py`:

In `__init__`, add the registry:

```python
        self._idle_clips = {}       # iid -> looping breathe clip index
```

Add the `set_idle` method (next to `reset`):

```python
    def set_idle(self, iid, clip_index) -> None:
        """Register the officer's looping breathe clip — what the controller
        returns to when its transient queue empties (AT_DEFAULT)."""
        self._idle_clips[iid] = clip_index
```

In `reset`, also clear it:

```python
    def reset(self) -> None:
        self._active = {}
        self._idle_clips = {}
```

In `update`, replace the completion branch:

```python
            else:
                self._return_to_default(renderer, iid)
                done.append(iid)
```

Add the helper (next to `_start_clip`):

```python
    def _return_to_default(self, renderer, iid) -> None:
        """Resume the looping breathe idle if one is registered; otherwise snap
        to the static rest pose (officer with no breathe registration)."""
        idle = self._idle_clips.get(iid)
        if idle is not None and hasattr(renderer, "play_instance_idle"):
            renderer.play_instance_idle(iid, idle)
        elif hasattr(renderer, "restore_rest_pose"):
            renderer.restore_rest_pose(iid)
```

- [ ] **Step 4: Run to verify pass (and no regression in the existing controller tests)**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -v`
Expected: PASS — the new three tests plus all pre-existing controller tests (which register no idle, so they still hit the `restore_rest_pose` fallback and their `r.restored` assertions hold).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_character_anim.py tests/unit/test_bridge_character_anim.py
git commit -m "feat(bridge): controller returns to the breathe loop, not a static frame"
```

---

### Task 4: Establish breathing at placement (host_loop wiring)

**Files:**
- Modify: `engine/host_loop.py` (`_place_one_character` starts breathing + registers the idle clip)

**Interfaces:**
- Consumes: `capture_breathing` (Task 2), `renderer.play_instance_idle` + `renderer.load_instance_clip` (Task 1 / existing), `BridgeCharacterAnimController.set_idle` (Task 3) via `bridge_character_anim.get_controller()`.

- [ ] **Step 1: Add `capture_breathing` to the placement import**

In `engine/host_loop.py`, in `_place_one_character`, change the import line
`from engine.appc.bridge_placement import capture_placement`
to:

```python
    from engine.appc.bridge_placement import capture_placement, capture_breathing
```

- [ ] **Step 2: Start breathing after the officer is placed**

In `_place_one_character`, immediately AFTER `character._render_instance = iid` (the line that follows the placement `try/except`), add the best-effort breathing block. `_abs` and `dev_mode` are already in scope; the controller is fetched lazily:

```python
        # Looping breathe idle (SDK-driven), layered over the placement pose so
        # the body breathes while the root stays at the station. Best-effort: a
        # breathing failure must not unplace a correctly-stationed officer.
        if hasattr(r, "play_instance_idle"):
            try:
                breathing = capture_breathing(character)
                if breathing:
                    bidx = r.load_instance_clip(iid, _abs(breathing["clip_nif"]))
                    if bidx is not None and bidx >= 0:
                        r.play_instance_idle(iid, bidx)
                        from engine.bridge_character_anim import get_controller
                        _ca = get_controller()
                        if _ca is not None:
                            _ca.set_idle(iid, bidx)
            except Exception as _e:
                dev_mode.log_swallowed("establish breathing", _e)
```

- [ ] **Step 3: Confirm host_loop imports cleanly and the suite is green**

Run: `uv run pytest tests/unit/test_bridge_breathing_capture.py tests/unit/test_bridge_character_anim.py tests/host/test_host_loop_unit.py -q`
Expected: PASS. The breathing block is guarded (`hasattr(r, "play_instance_idle")`), so the FakeRenderer paths in existing host-loop tests skip it cleanly.

- [ ] **Step 4: Full-suite regression**

Run: `./scripts/run_tests.sh` (watchdog-capped)
Expected: all pass (no regression). The C++ `FrameTest.PhaserHeatGlow…` failure is a known pre-existing offscreen-GL artifact, NOT this work.

- [ ] **Step 5: GUI verification note (user)**

Report that the user should run `./build/dauntless`, load a bridge, and confirm: every officer breathes continuously in its authentic posture (seated stations seated, standing standing), positioned at the console; gestures play over breathing and return to breathing (no freeze). Do NOT launch the GUI yourself.

- [ ] **Step 6: Commit**

```bash
git add engine/host_loop.py
git commit -m "feat(bridge): establish the looping breathe idle at officer placement"
```

---

## Self-Review

**Spec coverage:**
- `capture_breathing` resolution by `<location>Breathe` → Task 2 ✓
- Native looping-layered idle (`play_instance_idle`) → Task 1 ✓
- Breathing as default state: established at placement (Task 4), controller returns to it (Task 3) ✓
- Placement stays the layering anchor (`set_instance_rest_pose` unchanged; breathing layers over it) → Task 4 ✓
- Best-effort (no-breathe officer keeps static behavior) → Task 2 returns None, Task 3 fallback, Task 4 guard ✓
- Mission-swap clears the idle registry → Task 3 `reset` ✓
- Tests: capture resolution (T2), native loop+layer anchor (T1), controller resume/fallback/reset (T3) ✓
- BreatheTurned + turn-to-captain explicitly out of scope → no task ✓

**Type consistency:** `capture_breathing(character) -> {"clip_nif": str}|None`, `play_instance_idle(iid, clip_index)`, `set_idle(iid, clip_index)`, `_return_to_default(renderer, iid)` — names/signatures match across tasks.

**Open confirmations (resolve during implementation, not blockers):** the exact `path_for` strings for `standing_console`/`seated_M` (Task 2 Step 1 note); whether the native loop+layer test passes immediately (Task 1 Step 2 — expected, since loop+layer already coexist).
