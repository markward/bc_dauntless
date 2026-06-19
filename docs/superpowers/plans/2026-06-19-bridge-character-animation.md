# Bridge Character Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make bridge officers appear in a static rest pose at load (fixing the "stand up" bug), then gesture ambiently and react to hits — all driven by the SDK's own `CommonAnimations` sequences.

**Architecture:** One per-character runner. The placement clip becomes a *static rest pose*; idle gestures and hit reactions are transient SDK `TGSequence`s played over it that return to rest via `AT_DEFAULT`. Python (`engine/`) owns the controller + scheduling policy; native (`native/src/`) owns palette math and gains rest-pose store/restore plus runtime clip loading. Mirrors the existing `BridgeCutsceneController`.

**Tech Stack:** C++ (scenegraph/renderer, GoogleTest via ctest), pybind11 host bindings, Python 3 (`engine/`, pytest), GLM.

## Global Constraints

- One build tree at `<root>/build/`; binary `build/dauntless`, module `build/python/_open_stbc_host.cpython-*.so`. Build: `cmake -B build -S . && cmake --build build -j`. Never build from inside `native/`.
- Edits to `native/src/host/host_bindings.cc` require a **`dauntless` rebuild** (compiled into both the binary and the `_dauntless_host` module); rebuilding only the module leaves `build/dauntless` stale.
- Rotation convention is column-vector, right-handed (det +1): world-right = `GetWorldRotation().GetCol(0)`, world-forward = `GetCol(1)`, world-up = `GetCol(2)`.
- `_dauntless_host` is exposed to Python via `engine/renderer.py` wrappers; `hasattr`-guard new `r.<binding>` calls so the `FakeRenderer` and engineless paths silently no-op.
- Faithfulness rule (the point of this project): clip CHOICES come only from SDK `Bridge/Characters/CommonAnimations.py`; we never author motion. We own only scheduling policy (timers, hit→direction mapping).
- Tests: `uv run pytest <path>` for Python; `cmake --build build -j && ctest --test-dir build/native/tests/renderer` (and `.../scenegraph`) for C++. Use `scripts/run_tests.sh` for the full Python suite (watchdog-capped).

**Gate:** Tasks 1–2 (placement fix) are independent and ship the user's bug fix. **Task 3 is a spike that gates Tasks 4–7.** If the spike shows gesture clips do not retarget onto the officer skeleton, stop after Task 2 (placement-fix-only) and split idle/hit into a follow-up project.

---

### Task 1: Native — static rest-pose sampling (`sample_at_end`) + store/restore

**Files:**
- Modify: `native/src/scenegraph/include/scenegraph/instance.h` (AnimationState + rest storage)
- Modify: `native/src/scenegraph/include/scenegraph/world.h` (declarations)
- Modify: `native/src/scenegraph/src/world.cc` (set_rest_pose / restore_rest_pose)
- Modify: `native/src/renderer/animation_update.cc` (sample_at_end branch)
- Test: `native/tests/renderer/animation_update_test.cc` (new cases)
- Test: `native/tests/scenegraph/world_test.cc` (rest store/restore)

**Interfaces:**
- Produces (C++): `Instance::AnimationState.sample_at_end` (bool); `Instance::rest_pose` (AnimationState) + `Instance::has_rest_pose` (bool); `World::set_rest_pose(InstanceId, AnimationState)`; `World::restore_rest_pose(InstanceId)`.
- Consumes: existing `update_animations`, `World::set_animation`, `World::get`.

- [ ] **Step 1: Write the failing C++ test for `sample_at_end`**

Add to `native/tests/renderer/animation_update_test.cc` (reuses `two_bone_model_with_clip()` already in the file):

```cpp
TEST(AnimationUpdate, SampleAtEndHoldsEndFrameAndSettlesImmediately) {
    assets::Model model = two_bone_model_with_clip();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);
    scenegraph::Instance::AnimationState st;
    st.clip_index = 0; st.start_wall_time = 100.0; st.loop = false;
    st.sample_at_end = true;
    world.set_animation(id, st);

    // Settles on the FIRST update, no play-through, even at t just past start.
    renderer::update_animations(world, lookup, /*now=*/100.01);
    ASSERT_TRUE(world.get(id));
    EXPECT_TRUE(world.get(id)->animation.settled);
    auto end_palette = world.get(id)->bone_palette;
    ASSERT_EQ(end_palette.size(), 2u);

    // Held palette equals the t=dur pose (clip's 90deg-Z key is constant).
    glm::mat4 j1_local = glm::translate(glm::mat4(1.0f), glm::vec3(0, 10, 0));
    glm::quat q90 = glm::angleAxis(glm::radians(90.0f), glm::vec3(0, 0, 1));
    glm::mat4 expect_skin = (j1_local * glm::mat4_cast(q90)) * glm::inverse(j1_local);
    glm::vec4 probe(3.0f, 4.0f, 0.0f, 1.0f);
    EXPECT_TRUE(glm::all(glm::epsilonEqual(end_palette[1] * probe,
                                           expect_skin * probe, 1e-4f)));

    // Freezes: a later call leaves the palette bit-identical.
    renderer::update_animations(world, lookup, /*now=*/500.0);
    for (std::size_t b = 0; b < end_palette.size(); ++b)
        EXPECT_EQ(world.get(id)->bone_palette[b], end_palette[b]);
}
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cmake -B build -S . && cmake --build build -j && ctest --test-dir build --output-on-failure -R AnimationUpdate`
Expected: FAIL — `sample_at_end` is not a member of `AnimationState` (compile error).

- [ ] **Step 3: Add the `sample_at_end` field**

In `native/src/scenegraph/include/scenegraph/instance.h`, in the `AnimationState` struct (next to `sample_at_start`):

```cpp
        bool   sample_at_end  = false;   // rest "stand"/"seated" clips hold t=dur
```

Also add rest storage to `Instance` (after the `AnimationState animation;` member):

```cpp
    AnimationState rest_pose;            // the static placement pose (AT_DEFAULT)
    bool           has_rest_pose = false;
```

- [ ] **Step 4: Add the `sample_at_end` branch**

In `native/src/renderer/animation_update.cc`, insert immediately after the `if (a.sample_at_start) { ... }` block and before `else if (a.loop)`:

```cpp
        } else if (a.sample_at_end) {
            // Rest "stand"/"seated" clips place the officer AT the station on
            // the LAST frame. A stationed officer holds it: evaluate at t=dur
            // and freeze immediately — no play-through (the load-time bug fix).
            t = dur;
            a.settled = true;
```

(The line becomes `if (a.sample_at_start) {` … `} else if (a.sample_at_end) {` … `} else if (a.loop) {` …)

- [ ] **Step 5: Run the renderer test to verify it passes**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R AnimationUpdate`
Expected: PASS (all `AnimationUpdate.*` cases, including the two pre-existing ones).

- [ ] **Step 6: Write the failing world rest-pose test**

Add to `native/tests/scenegraph/world_test.cc`:

```cpp
TEST(World, RestPoseStoreAndRestore) {
    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);

    scenegraph::Instance::AnimationState rest;
    rest.clip_index = 0; rest.sample_at_end = true;
    world.set_rest_pose(id, rest);
    EXPECT_TRUE(world.get(id)->has_rest_pose);
    EXPECT_EQ(world.get(id)->animation.clip_index, 0);
    EXPECT_TRUE(world.get(id)->animation.sample_at_end);

    // Overwrite current with a transient gesture clip.
    scenegraph::Instance::AnimationState gesture;
    gesture.clip_index = 5; gesture.loop = false;
    world.set_animation(id, gesture);
    EXPECT_EQ(world.get(id)->animation.clip_index, 5);

    // Restore returns current to the stored rest pose, un-settled so it
    // re-samples once on the next update.
    world.restore_rest_pose(id);
    EXPECT_EQ(world.get(id)->animation.clip_index, 0);
    EXPECT_TRUE(world.get(id)->animation.sample_at_end);
    EXPECT_FALSE(world.get(id)->animation.settled);
}
```

- [ ] **Step 7: Run it to verify it fails**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R "World.RestPose"`
Expected: FAIL — `set_rest_pose` / `restore_rest_pose` not declared.

- [ ] **Step 8: Declare and implement rest store/restore**

In `native/src/scenegraph/include/scenegraph/world.h`, next to `set_animation`:

```cpp
    void set_rest_pose(InstanceId id, Instance::AnimationState rest);
    void restore_rest_pose(InstanceId id);
```

In `native/src/scenegraph/src/world.cc`, next to `set_animation`:

```cpp
void World::set_rest_pose(InstanceId id, Instance::AnimationState rest) {
    Instance* in = get(id);
    if (!in) return;
    rest.settled = false;
    in->rest_pose = rest;
    in->has_rest_pose = true;
    in->animation = rest;                  // adopt the rest pose now
}

void World::restore_rest_pose(InstanceId id) {
    Instance* in = get(id);
    if (!in || !in->has_rest_pose) return;
    Instance::AnimationState rest = in->rest_pose;
    rest.settled = false;                  // force one re-sample
    in->animation = rest;
}
```

- [ ] **Step 9: Run both test suites to verify pass**

Run: `cmake --build build -j && ctest --test-dir build --output-on-failure -R "AnimationUpdate|World.RestPose"`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add native/src/scenegraph native/src/renderer/animation_update.cc native/tests/renderer/animation_update_test.cc native/tests/scenegraph/world_test.cc
git commit -m "feat(native): static rest-pose sampling + store/restore for bridge placement"
```

---

### Task 2: Wire placement to the static rest pose (the bug fix)

**Files:**
- Modify: `native/src/host/host_bindings.cc` (new `set_instance_rest_pose`, `restore_rest_pose` bindings)
- Modify: `engine/renderer.py` (wrappers)
- Modify: `engine/host_loop.py:2521` (placement call)
- Test: `tests/unit/test_bridge_placement_rest_pose.py` (new)

**Interfaces:**
- Consumes (Task 1): `World::set_rest_pose`, `World::restore_rest_pose`.
- Produces (Python): `renderer.set_instance_rest_pose(iid, clip_index, at_start)`, `renderer.restore_rest_pose(iid)`.

- [ ] **Step 1: Add the host bindings**

In `native/src/host/host_bindings.cc`, after the `set_instance_animation` binding:

```cpp
    m.def("set_instance_rest_pose",
          [](scenegraph::InstanceId id, int clip_index, bool at_start) {
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = false;
              st.sample_at_start = at_start;
              st.sample_at_end = !at_start;
              st.start_wall_time = glfwGetTime();
              g_world.set_rest_pose(id, st);
          },
          py::arg("iid"), py::arg("clip_index"), py::arg("at_start") = false,
          "Freeze an officer at the static placement pose: at_start=true holds "
          "the clip's first frame (move-from-station clips), false holds the "
          "last frame (stand/seated clips). No play-through.");
    m.def("restore_rest_pose",
          [](scenegraph::InstanceId id) { g_world.restore_rest_pose(id); },
          py::arg("iid"),
          "Snap the instance back to its stored rest pose (AT_DEFAULT).");
```

- [ ] **Step 2: Rebuild and confirm the binding exists**

Run: `cmake --build build -j && ./build/python/*/bin/python -c "import _open_stbc_host as h; print(hasattr(h,'set_instance_rest_pose'), hasattr(h,'restore_rest_pose'))"` — if that interpreter path differs, use the project's configured `uv run python -c "import _open_stbc_host as h; ..."`.
Expected: `True True`.

- [ ] **Step 3: Add the Python wrappers**

In `engine/renderer.py`, after `set_instance_animation`:

```python
def set_instance_rest_pose(iid: InstanceId, clip_index: int,
                           at_start: bool = False) -> None:
    """Freeze an officer at its static placement (rest) pose. at_start holds
    frame 0 (move-from-station clips); otherwise the last frame (stand/seated
    clips). Faithful to the SDK's TGAnimPosition — no play-through."""
    _h.set_instance_rest_pose(iid, clip_index, at_start)


def restore_rest_pose(iid: InstanceId) -> None:
    """Snap the instance back to its stored rest pose (AT_DEFAULT)."""
    _h.restore_rest_pose(iid)
```

- [ ] **Step 4: Write the failing wiring test**

Create `tests/unit/test_bridge_placement_rest_pose.py`. It checks that `_place_one_character` realises an officer via `set_instance_rest_pose` (static), NOT the play-through `set_instance_animation`:

```python
from engine import host_loop


class _FakeRenderer:
    def __init__(self):
        self.rest_calls = []
        self.anim_calls = []

    def assemble_officer(self, *a):
        return 1                      # ModelHandle
    def create_bridge_instance(self, model):
        return 42                     # InstanceId
    def set_world_transform(self, iid, mat):
        pass
    def set_instance_rest_pose(self, iid, clip_index, at_start=False):
        self.rest_calls.append((iid, clip_index, at_start))
    def set_instance_animation(self, iid, clip_index, loop=False, sample_at_start=False):
        self.anim_calls.append((iid, clip_index, loop, sample_at_start))


class _FakeCharacter:
    def __init__(self):
        self._render_instance = None
    def appearance(self):
        return {"body_nif": "b.nif", "head_nif": "h.nif",
                "body_tex": None, "head_tex": None}
    def GetCharacterName(self):
        return "Helm"


def test_placement_uses_rest_pose_not_playthrough(monkeypatch):
    monkeypatch.setattr(
        "engine.appc.bridge_placement.capture_placement",
        lambda c: {"clip_nif": "data/animations/db_stand_h_m.nif",
                   "hidden": False, "sample_at_start": False},
    )
    r = _FakeRenderer()
    controller = host_loop.BridgeController.__new__(host_loop.BridgeController)
    controller.officer_instances = []
    host_loop._place_one_character(controller, r, _FakeCharacter(),
                                   "bridge", is_bridge=True)

    assert r.rest_calls == [(42, 0, False)]      # static, last-frame
    assert r.anim_calls == []                    # never plays the clip through
```

(If `BridgeController` is named differently, use the actual controller class that defines `officer_instances`; confirm via `grep -n "officer_instances" engine/host_loop.py`.)

- [ ] **Step 5: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_placement_rest_pose.py -v`
Expected: FAIL — `_place_one_character` still calls `set_instance_animation` (rest_calls empty).

- [ ] **Step 6: Switch the placement call to the rest pose**

In `engine/host_loop.py`, replace the `set_instance_animation` call at ~line 2521 inside `_place_one_character`:

```python
            r.set_world_transform(iid, OFFICER_TRANSFORM)
            r.set_instance_rest_pose(iid, 0, placement["sample_at_start"])
```

- [ ] **Step 7: Run it to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_placement_rest_pose.py -v`
Expected: PASS.

- [ ] **Step 8: GUI smoke check (manual, the real acceptance gate for the bug)**

Run `./build/dauntless`, load a bridge. Confirm officers **appear standing at their stations with no stand-up motion**. Science/Engineer (sample_at_start) still pose correctly at their consoles.

- [ ] **Step 9: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py engine/host_loop.py tests/unit/test_bridge_placement_rest_pose.py
git commit -m "fix(bridge): place officers at static rest pose, not a played-through clip"
```

**STOP / GATE:** The user-reported bug is now fixed and shippable on its own. Proceed to Task 3 only to add gestures/reactions.

---

### Task 3: SPIKE — confirm gesture clips retarget onto the officer skeleton

**Goal:** Prove (or disprove) that a gesture NIF's keyframe tracks target the same bone-node names as a posed officer's skeleton, so transient clips can drive the skinned officer. This gates Tasks 4–7.

**Files:**
- Create: `tests/host/test_gesture_retarget_spike.py` (real-asset, skipif no `game/`)

**Interfaces:**
- Consumes: `renderer.load_animation_clips(path)` (existing) → `[{name, duration, tracks:[{node, translation, rotation}]}]`.

- [ ] **Step 1: Identify a gesture clip and the officer body skeleton's node names**

Run: `grep -rn "AddRandomAnimation\|LoadAnimation" sdk/Build/scripts/Bridge/Characters/MaleExtra1.py` to pick a real registered gesture (e.g. `react_console_left.NIF`, `LookAroundConsoleDown` → `Console_Look_Down_*.NIF`). Note one gesture NIF path under `game/data/animations/`.

- [ ] **Step 2: Write the spike test**

Create `tests/host/test_gesture_retarget_spike.py`:

```python
import os
import pathlib
import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
GAME = PROJECT_ROOT / "game"
GESTURE_NIF = GAME / "data/animations/react_console_left.NIF"
# A standard male officer body NIF (confirm the exact path from a Bridge/Characters file).
BODY_NIF = GAME / "data/Models/Characters/Body/male_command_body.nif"

pytestmark = pytest.mark.skipif(
    not (GESTURE_NIF.exists() and BODY_NIF.exists()),
    reason="needs game/ assets",
)


def test_gesture_tracks_target_body_bone_names():
    from engine import renderer
    gesture = renderer.load_animation_clips(str(GESTURE_NIF))
    assert gesture, "gesture NIF parsed to zero clips"
    track_nodes = {t["node"] for clip in gesture for t in clip["tracks"]}

    # The body NIF's skeleton bone names: parse via the same clip reader on the
    # body (its bind pose), or a skeleton-introspection helper if present.
    # Assert the gesture animates nodes that EXIST on the officer rig.
    body_clips = renderer.load_animation_clips(str(BODY_NIF))
    body_nodes = {t["node"] for clip in body_clips for t in clip["tracks"]}

    overlap = track_nodes & body_nodes
    assert overlap, (
        f"gesture targets {sorted(track_nodes)} but body rig exposes "
        f"{sorted(body_nodes)} — no shared bone names; retargeting will fail"
    )
```

- [ ] **Step 3: Run the spike**

Run: `uv run pytest tests/host/test_gesture_retarget_spike.py -v`
Expected (PASS): gesture node names overlap the rig → **proceed to Task 4.**
Expected (FAIL/empty): no overlap, or the body NIF exposes no nodes via the clip reader → the rig needs a skeleton-introspection binding, or names differ.

- [ ] **Step 4: Decide the gate**

- **Overlap found:** commit the spike test and continue to Task 4.
- **No overlap / reader insufficient:** STOP the gesture/reaction work. Update the spec's "Out of scope" with the finding, ship Tasks 1–2 as the deliverable, and open a follow-up project to design bone-name remapping. Do NOT proceed to Tasks 4–7.

- [ ] **Step 5: Commit (only if the gate passes)**

```bash
git add tests/host/test_gesture_retarget_spike.py
git commit -m "test(bridge): spike confirming gesture clips retarget onto officer rig"
```

---

### Task 4: Native — runtime clip loading + transient playback binding

**Files:**
- Modify: `native/src/host/host_bindings.cc` (`load_instance_clip` binding)
- Modify: `engine/renderer.py` (wrapper)
- Test: `tests/host/test_load_instance_clip.py` (real-asset, skipif no `game/`)

**Interfaces:**
- Produces (Python): `renderer.load_instance_clip(iid, nif_path) -> int` (clip index on the instance's model); `renderer.set_instance_animation(iid, clip_index, loop=False)` already plays a transient clip (Task-1 settle logic untouched for `loop=False, sample_at_start=False, sample_at_end=False`).
- Consumes: `assets::load_animation_clips`, the instance→model lookup used by `update_animations`.

- [ ] **Step 1: Write the failing test**

Create `tests/host/test_load_instance_clip.py`:

```python
import pathlib
import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
GAME = PROJECT_ROOT / "game"
GESTURE_NIF = GAME / "data/animations/react_console_left.NIF"

pytestmark = pytest.mark.skipif(not GESTURE_NIF.exists(), reason="needs game/")


def test_load_instance_clip_returns_new_index(host_renderer_officer):
    # host_renderer_officer: fixture that assembles a real officer and returns
    # (renderer, iid). Reuse the assembly helper from test_active_zoom_officer.
    r, iid = host_renderer_officer
    idx = r.load_instance_clip(iid, str(GESTURE_NIF))
    assert idx >= 1            # index 0 is the placement clip baked at assembly
```

(If no shared officer-assembly fixture exists, inline the `assemble_officer` + `create_bridge_instance` calls from `tests/unit/test_active_zoom_officer.py`.)

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/host/test_load_instance_clip.py -v`
Expected: FAIL — `load_instance_clip` not defined.

- [ ] **Step 3: Implement the binding**

In `native/src/host/host_bindings.cc`, add a binding that parses the NIF's clips and appends them to the instance's model, returning the first new index. Use the same model-lookup `update_animations` uses (the `ModelLookup` over `g_world` / the asset store). Pattern:

```cpp
    m.def("load_instance_clip",
          [](scenegraph::InstanceId id, const std::string& path) -> int {
              auto* in = g_world.get(id);
              if (!in) return -1;
              assets::Model* m = g_asset_store.mutable_model(in->model_handle);
              if (!m) return -1;
              int first = static_cast<int>(m->animations.size());
              for (auto& clip :
                   assets::load_animation_clips(renderer::resolve_asset_path(path)))
                  m->animations.push_back(std::move(clip));
              return (static_cast<int>(m->animations.size()) > first) ? first : -1;
          },
          py::arg("iid"), py::arg("path"),
          "Append a NIF's clips to this instance's model; returns the first new "
          "clip index, or -1. Officer models are per-instance, so this is safe.");
```

(Confirm the asset-store accessor name with `grep -n "mutable_model\|model_handle\|class .*Store\|lookup" native/src/host/host_bindings.cc native/src/assets/*.h`. If models are owned by the renderer's model cache rather than a global store, route through that owner instead — the requirement is "append clips to the model behind `iid`".)

- [ ] **Step 4: Add the Python wrapper**

In `engine/renderer.py`:

```python
def load_instance_clip(iid: InstanceId, nif_path: str) -> int:
    """Append a NIF's animation clips to this officer instance's model.
    Returns the first new clip index (>=1; index 0 is the placement clip), or
    -1 on failure. Officer models are per-instance, so this never bleeds across
    characters."""
    return _h.load_instance_clip(iid, nif_path)
```

- [ ] **Step 5: Rebuild and run the test**

Run: `cmake --build build -j && uv run pytest tests/host/test_load_instance_clip.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc engine/renderer.py tests/host/test_load_instance_clip.py
git commit -m "feat(native): load_instance_clip — attach gesture clips to an officer at runtime"
```

---

### Task 5: `BridgeCharacterAnimController` — action queue + AT_DEFAULT + preempt

**Files:**
- Create: `engine/bridge_character_anim.py`
- Modify: `engine/appc/actions.py` (route character `TGAnimAction` to the controller)
- Test: `tests/unit/test_bridge_character_anim.py`

**Interfaces:**
- Produces: `BridgeCharacterAnimController` with:
  - `submit(self, character, clips: list[tuple[str, float]], priority: int)` — `clips` is `[(nif_path, duration_seconds), ...]`; `priority` 0=idle, 1=reaction.
  - `update(self, dt, *, renderer, anim_mgr)` — per-tick pump.
  - `reset(self)` — clear all state (mission swap).
  - Module registry `get_controller()/set_controller(ctrl)/clear_controller()` (mirrors `bridge_cutscene`).
  - Each `character` must expose `_render_instance` (InstanceId) and `IsHidden()`.
- Consumes (Task 4): `renderer.load_instance_clip`, `renderer.set_instance_animation`, `renderer.restore_rest_pose`.

- [ ] **Step 1: Write the failing controller test**

Create `tests/unit/test_bridge_character_anim.py`:

```python
from engine.bridge_character_anim import BridgeCharacterAnimController


class _FakeRenderer:
    def __init__(self):
        self.loaded = {}        # (iid, path) -> clip_index
        self.played = []        # (iid, clip_index)
        self.restored = []      # iid
        self._next = 1
    def load_instance_clip(self, iid, path):
        key = (iid, path)
        if key not in self.loaded:
            self._next += 1
            self.loaded[key] = self._next
        return self.loaded[key]
    def set_instance_animation(self, iid, clip_index, loop=False):
        self.played.append((iid, clip_index))
    def restore_rest_pose(self, iid):
        self.restored.append(iid)


class _Char:
    def __init__(self, iid):
        self._render_instance = iid
    def IsHidden(self):
        return 0


def test_plays_clips_in_order_then_restores_rest():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(42)
    ctrl.submit(ch, [("a.nif", 1.0), ("b.nif", 0.5)], priority=0)

    ctrl.update(0.0, renderer=r, anim_mgr=None)     # start clip a
    assert r.played == [(42, r.loaded[(42, "a.nif")])]

    ctrl.update(1.0, renderer=r, anim_mgr=None)     # a done -> start b
    assert r.played[-1] == (42, r.loaded[(42, "b.nif")])

    ctrl.update(0.5, renderer=r, anim_mgr=None)     # b done -> AT_DEFAULT
    assert r.restored == [42]


def test_reaction_preempts_idle():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(7)
    ctrl.submit(ch, [("idle.nif", 5.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)     # idle playing
    ctrl.submit(ch, [("hit.nif", 0.4)], priority=1) # reaction preempts
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert r.played[-1] == (7, r.loaded[(7, "hit.nif")])

    # Lower-priority idle submitted during a reaction is dropped.
    ctrl.submit(ch, [("idle2.nif", 5.0)], priority=0)
    ctrl.update(0.1, renderer=r, anim_mgr=None)
    assert (7, r.loaded.get((7, "idle2.nif"))) not in r.played


def test_busy_returns_true_while_acting():
    ctrl = BridgeCharacterAnimController()
    r = _FakeRenderer()
    ch = _Char(9)
    assert ctrl.is_busy(ch) is False
    ctrl.submit(ch, [("g.nif", 2.0)], priority=0)
    ctrl.update(0.0, renderer=r, anim_mgr=None)
    assert ctrl.is_busy(ch) is True
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -v`
Expected: FAIL — module `engine.bridge_character_anim` does not exist.

- [ ] **Step 3: Implement the controller**

Create `engine/bridge_character_anim.py`:

```python
# engine/bridge_character_anim.py
"""BridgeCharacterAnimController — per-character transient animation runner.

The officer's placement is a STATIC rest pose (set_instance_rest_pose). Idle
gestures and hit reactions are transient SDK TGSequences played over it: each
is a list of (nif_path, duration) clips played in order; when the last clip
ends the controller issues restore_rest_pose (the SDK's AT_DEFAULT). Reactions
(priority 1) preempt idle (priority 0); a lower-or-equal priority submission for
a busy character is dropped. Mirrors engine/bridge_cutscene.py.
"""

_IDLE = 0
_REACTION = 1


class _Action:
    __slots__ = ("iid", "clips", "priority", "index", "elapsed", "started")

    def __init__(self, iid, clips, priority):
        self.iid = iid
        self.clips = clips          # [(nif_path, duration), ...]
        self.priority = priority
        self.index = -1             # current clip; -1 = not yet started
        self.elapsed = 0.0
        self.started = False


class BridgeCharacterAnimController:
    def __init__(self):
        self._active = {}           # iid -> _Action

    def is_busy(self, character) -> bool:
        iid = getattr(character, "_render_instance", None)
        return iid in self._active

    def submit(self, character, clips, priority) -> None:
        iid = getattr(character, "_render_instance", None)
        if iid is None or not clips:
            return
        if character.IsHidden():
            return
        cur = self._active.get(iid)
        if cur is not None and priority <= cur.priority:
            return                  # don't preempt equal/higher priority
        self._active[iid] = _Action(iid, list(clips), priority)

    def reset(self) -> None:
        self._active = {}

    def update(self, dt, *, renderer, anim_mgr=None) -> None:
        done = []
        for iid, act in self._active.items():
            if not act.started or act.index < 0:
                self._start_clip(renderer, act, 0)
                continue
            act.elapsed += dt
            _, dur = act.clips[act.index]
            if act.elapsed < dur:
                continue
            nxt = act.index + 1
            if nxt < len(act.clips):
                self._start_clip(renderer, act, nxt)
            else:
                if hasattr(renderer, "restore_rest_pose"):
                    renderer.restore_rest_pose(iid)
                done.append(iid)
        for iid in done:
            self._active.pop(iid, None)

    @staticmethod
    def _start_clip(renderer, act, index) -> None:
        path, _dur = act.clips[index]
        act.index = index
        act.elapsed = 0.0
        act.started = True
        if not hasattr(renderer, "load_instance_clip"):
            return
        clip_index = renderer.load_instance_clip(act.iid, path)
        if clip_index is not None and clip_index >= 0:
            renderer.set_instance_animation(act.iid, clip_index, False)


_controller = None


def get_controller():
    return _controller


def set_controller(ctrl) -> None:
    global _controller
    _controller = ctrl


def clear_controller() -> None:
    global _controller
    _controller = None
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_character_anim.py -v`
Expected: PASS (all four tests).

- [ ] **Step 5: Route character `TGAnimAction` to the controller**

In `engine/appc/actions.py`, the character-gesture branch of `TGAnimAction._do_play` currently returns early (instant-complete) for `kind not in ("camera", "object")`. A direct SDK `TGAnimAction` on a character anim node should not instant-complete silently anymore — but the idle/hit paths in Tasks 6–7 submit through the controller directly (not via `TGAnimAction`), so leave `_do_play` behavior unchanged here and add a docstring note pointing to `bridge_character_anim`. No functional edit; this step is a comment for the next reader:

```python
        kind = getattr(self._anim_node, "kind", None)
        # Character gesture clips are driven by BridgeCharacterAnimController via
        # the idle/hit schedulers (engine/bridge_character_anim.py), NOT by this
        # action path, which stays instant-complete for headless SDK sequences.
        if kind not in ("camera", "object"):
            return
```

- [ ] **Step 6: Commit**

```bash
git add engine/bridge_character_anim.py engine/appc/actions.py tests/unit/test_bridge_character_anim.py
git commit -m "feat(bridge): per-character animation controller (queue, AT_DEFAULT, preempt)"
```

---

### Task 6: Idle ambient gesture scheduler

**Files:**
- Create: `engine/bridge_idle_gestures.py`
- Modify: `engine/host_loop.py` (construct controller + scheduler, pump per tick, reset on swap)
- Test: `tests/unit/test_bridge_idle_gestures.py`

**Interfaces:**
- Produces: `IdleGestureScheduler(rng, *, interval=(8.0, 20.0))` with `update(self, dt, characters, *, renderer, anim_mgr, controller)`.
- Consumes: each character's `_random_animations` (list of arg-tuples; arg[0] = `"Bridge.Characters.CommonAnimations.<Func>"`, optional arg[1] = mode `SITTING_ONLY`/`STANDING_ONLY`); `character.IsStanding()`; the SDK builder resolved from the module path; `controller.submit(...)`; `controller.is_busy(...)`.

- [ ] **Step 1: Write the failing scheduler test**

Create `tests/unit/test_bridge_idle_gestures.py`:

```python
import random
from engine.bridge_idle_gestures import IdleGestureScheduler


class _Controller:
    def __init__(self):
        self.submitted = []
        self._busy = set()
    def is_busy(self, ch):
        return id(ch) in self._busy
    def submit(self, ch, clips, priority):
        self.submitted.append((ch, clips, priority))
        self._busy.add(id(ch))


class _Char:
    def __init__(self, registrations, standing=1):
        self._random_animations = registrations
        self._render_instance = 1
        self._standing = standing
    def IsStanding(self):
        return self._standing
    def IsHidden(self):
        return 0


def _builder_returns_one_clip(monkeypatch):
    # Stub the SDK builder resolution so no real SDK import is needed.
    import engine.bridge_idle_gestures as mod
    monkeypatch.setattr(
        mod, "build_sequence_clips",
        lambda module_path, ch, anim_mgr: [("clip.nif", 1.0)],
    )


def test_fires_after_interval_and_submits_idle(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(5.0, 5.0))
    ctrl = _Controller()
    ch = _Char([("Bridge.Characters.CommonAnimations.LookAroundConsole",)])

    sched.update(4.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []                    # not yet
    sched.update(2.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert len(ctrl.submitted) == 1
    assert ctrl.submitted[0][2] == 0               # idle priority


def test_respects_sitting_only_mode(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(0.0, 0.0))
    ctrl = _Controller()
    from engine.appc.characters import CharacterClass
    standing_char = _Char(
        [("Bridge.Characters.CommonAnimations.Foo", CharacterClass.SITTING_ONLY)],
        standing=1,
    )
    sched.update(0.0, [standing_char], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []                    # sitting-only skipped while standing


def test_skips_busy_character(monkeypatch):
    _builder_returns_one_clip(monkeypatch)
    sched = IdleGestureScheduler(random.Random(0), interval=(0.0, 0.0))
    ctrl = _Controller()
    ch = _Char([("Bridge.Characters.CommonAnimations.Foo",)])
    ctrl._busy.add(id(ch))
    sched.update(1.0, [ch], renderer=None, anim_mgr=None, controller=ctrl)
    assert ctrl.submitted == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_idle_gestures.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the scheduler**

Create `engine/bridge_idle_gestures.py`:

```python
# engine/bridge_idle_gestures.py
"""Per-character idle ambient gesture scheduler.

Each visible officer runs an independent random timer. On fire we pick one of
its registered AddRandomAnimation entries (respecting SITTING_ONLY/STANDING_ONLY
mode), call the SDK's CommonAnimations builder to get the gesture's clip list,
and submit it to BridgeCharacterAnimController at idle priority. The clip CHOICES
come entirely from the SDK; we own only the timing.
"""
import importlib

from engine.appc.characters import CharacterClass


def build_sequence_clips(module_path, character, anim_mgr):
    """Resolve "pkg.mod.Func", call Func(character) to get a TGSequence, and
    flatten it to [(nif_path, duration), ...] using anim_mgr.path_for + each
    action's clip name. Returns [] if anything is unavailable (headless-safe)."""
    try:
        mod_name, func_name = module_path.rsplit(".", 1)
        func = getattr(importlib.import_module(mod_name), func_name)
        seq = func(character)
    except Exception:
        return []
    clips = []
    n = seq.GetNumActions() if hasattr(seq, "GetNumActions") else 0
    for i in range(n):
        action = seq.GetAction(i)
        name = getattr(action, "_clip", "") or getattr(action, "name", "")
        if not name:
            continue
        path = anim_mgr.path_for(name) if anim_mgr is not None else None
        if not path:
            continue
        dur = getattr(action, "duration", None)
        clips.append((path, float(dur) if dur else 1.0))
    return clips


def _mode_ok(entry, character) -> bool:
    """entry = AddRandomAnimation arg-tuple; arg[1] (optional) is the posture
    mode. SITTING_ONLY skips standing officers; STANDING_ONLY skips seated."""
    if len(entry) < 2 or entry[1] is None:
        return True
    mode = entry[1]
    standing = bool(character.IsStanding())
    if mode == CharacterClass.SITTING_ONLY:
        return not standing
    if mode == CharacterClass.STANDING_ONLY:
        return standing
    return True


class IdleGestureScheduler:
    def __init__(self, rng, *, interval=(8.0, 20.0)):
        self._rng = rng
        self._lo, self._hi = interval
        self._timers = {}           # id(character) -> seconds until next gesture

    def _next_delay(self) -> float:
        return self._rng.uniform(self._lo, self._hi)

    def update(self, dt, characters, *, renderer, anim_mgr, controller) -> None:
        for ch in characters:
            if getattr(ch, "_render_instance", None) is None:
                continue
            if ch.IsHidden():
                continue
            key = id(ch)
            t = self._timers.get(key)
            if t is None:
                self._timers[key] = self._next_delay()
                continue
            if controller.is_busy(ch):
                continue
            t -= dt
            if t > 0.0:
                self._timers[key] = t
                continue
            self._timers[key] = self._next_delay()
            entries = [e for e in getattr(ch, "_random_animations", [])
                       if e and _mode_ok(e, ch)]
            if not entries:
                continue
            entry = entries[self._rng.randrange(len(entries))]
            clips = build_sequence_clips(entry[0], ch, anim_mgr)
            if clips:
                controller.submit(ch, clips, priority=0)
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_idle_gestures.py -v`
Expected: PASS.

- [ ] **Step 5: Wire into the host loop**

In `engine/host_loop.py`, where `BridgeCutsceneController` is created (~line 2902–2906), also construct and register the character controller + idle scheduler:

```python
        from engine.bridge_character_anim import (
            BridgeCharacterAnimController, set_controller as set_char_anim,
        )
        from engine.bridge_idle_gestures import IdleGestureScheduler
        import random as _random
        char_anim = BridgeCharacterAnimController()
        set_char_anim(char_anim)
        idle_gestures = IdleGestureScheduler(_random.Random(0xB1D6E))
```

In the per-tick block where `cutscene.update(...)` runs (~line 3611–3616), pump both — but only when the bridge is shown and not paused. Gather the live bridge characters from the rendered set (the same characters `_place_one_character` realised; each carries `_render_instance`):

```python
                if not pause.is_open:
                    bridge_chars = _live_bridge_characters()   # helper below
                    idle_gestures.update(dt, bridge_chars,
                                         renderer=r, anim_mgr=anim_mgr,
                                         controller=char_anim)
                    char_anim.update(dt, renderer=r, anim_mgr=anim_mgr)
```

Add a small helper near `_place_one_character` that returns the realised, visible bridge characters (iterate the bridge set's characters, filter `getattr(c, "_render_instance", None) is not None and not c.IsHidden()`). On mission swap (~line 3420–3426 where `cutscene.reset()` runs), also call `char_anim.reset()` and clear the idle timers by reconstructing the scheduler or adding `idle_gestures.reset()`.

- [ ] **Step 6: Add `reset()` to the scheduler**

In `engine/bridge_idle_gestures.py`, add:

```python
    def reset(self) -> None:
        self._timers = {}
```

- [ ] **Step 7: Run the focused suite + GUI check**

Run: `uv run pytest tests/unit/test_bridge_idle_gestures.py tests/unit/test_bridge_character_anim.py -v`
Expected: PASS. Then `./build/dauntless`: officers occasionally gesture (look around, shrug) and return to standing. No officer freezes mid-gesture; the bridge feels alive.

- [ ] **Step 8: Commit**

```bash
git add engine/bridge_idle_gestures.py engine/host_loop.py tests/unit/test_bridge_idle_gestures.py
git commit -m "feat(bridge): idle ambient gesture scheduler (per-character, SDK-driven)"
```

---

### Task 7: Hit reactions (direction + severity aware)

**Files:**
- Create: `engine/bridge_hit_reactions.py`
- Modify: `engine/host_loop.py` (subscribe at controller construction)
- Test: `tests/unit/test_bridge_hit_reactions.py`

**Interfaces:**
- Produces: `select_reaction(bearing_dot: float, damage: float) -> str` returning one of `"HitStanding" | "HitHardStanding" | "Blast" | "ReactLeft" | "ReactRight"`; `HitReactionHandler(controller, *, get_player, get_characters)` with `on_weapon_hit(self, event)`.
- Consumes: `WeaponHitEvent` (`GetTarget`, `GetDamage`, `GetHitPoint`), player ship `GetWorldRotation().GetCol(0)` (right axis) + `GetWorldLocation()`; each character's `_animations` (list of `(anim_key, module_path)`; key is location-prefixed, e.g. `"DBGuestReactLeft"`); `build_sequence_clips` from `engine.bridge_idle_gestures`.

- [ ] **Step 1: Write the failing mapping + handler test**

Create `tests/unit/test_bridge_hit_reactions.py`:

```python
from engine.bridge_hit_reactions import select_reaction, HitReactionHandler

# Severity thresholds (verify against combat damage magnitudes in tuning):
#   damage < 15  -> light lean (ReactLeft/ReactRight by bearing)
#   15..50       -> HitStanding
#   >= 50        -> HitHardStanding ; >= 120 -> Blast


def test_select_reaction_by_severity_and_direction():
    assert select_reaction(bearing_dot=+1.0, damage=5.0) == "ReactRight"
    assert select_reaction(bearing_dot=-1.0, damage=5.0) == "ReactLeft"
    assert select_reaction(bearing_dot=0.2, damage=30.0) == "HitStanding"
    assert select_reaction(bearing_dot=0.2, damage=80.0) == "HitHardStanding"
    assert select_reaction(bearing_dot=0.2, damage=200.0) == "Blast"


class _Controller:
    def __init__(self):
        self.submitted = []
    def submit(self, ch, clips, priority):
        self.submitted.append((ch, clips, priority))


class _Vec:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z
    def GetX(self): return self.x
    def GetY(self): return self.y
    def GetZ(self): return self.z


class _Col:
    def __init__(self, v): self._v = v
    def GetCol(self, i): return self._v        # always return the right axis


class _Ship:
    def __init__(self): pass
    def GetWorldLocation(self): return _Vec(0.0, 0.0, 0.0)
    def GetWorldRotation(self): return _Col(_Vec(1.0, 0.0, 0.0))   # right = +X


class _Char:
    def __init__(self):
        self._render_instance = 3
        self._animations = [("DBGuestReactRight",
                             "Bridge.Characters.CommonAnimations.ReactRight")]
    def IsHidden(self): return 0


class _Event:
    def __init__(self, target, damage, hit):
        self._t, self._d, self._h = target, damage, hit
    def GetTarget(self): return self._t
    def GetDamage(self): return self._d
    def GetHitPoint(self): return self._h


def test_handler_submits_directional_reaction(monkeypatch):
    import engine.bridge_hit_reactions as mod
    monkeypatch.setattr(mod, "build_sequence_clips",
                        lambda module_path, ch, anim_mgr: [("react.nif", 0.4)])
    ctrl = _Controller()
    ship = _Ship()
    ch = _Char()
    handler = HitReactionHandler(ctrl, get_player=lambda: ship,
                                 get_characters=lambda: [ch], anim_mgr=None)
    # Hit to starboard (+X): bearing_dot > 0 -> ReactRight, key DBGuestReactRight.
    handler.on_weapon_hit(_Event(ship, 5.0, _Vec(10.0, 0.0, 0.0)))
    assert len(ctrl.submitted) == 1
    assert ctrl.submitted[0][2] == 1               # reaction priority


def test_handler_ignores_non_player_hits():
    ctrl = _Controller()
    ship, other = _Ship(), _Ship()
    handler = HitReactionHandler(ctrl, get_player=lambda: ship,
                                 get_characters=lambda: [_Char()], anim_mgr=None)
    handler.on_weapon_hit(_Event(other, 99.0, _Vec(1, 0, 0)))
    assert ctrl.submitted == []
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/unit/test_bridge_hit_reactions.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement the handler**

Create `engine/bridge_hit_reactions.py`:

```python
# engine/bridge_hit_reactions.py
"""Direction + severity aware bridge-crew hit reactions.

On a player-ship WeaponHitEvent we compute the impact bearing relative to the
ship's starboard axis (GetCol(0)) and the damage severity, pick the SDK reaction
class (HitStanding/HitHardStanding/Blast/ReactLeft/ReactRight), resolve each
visible officer's registered key for it, and submit the SDK-built clip sequence
to the character controller at reaction priority (preempts idle).
"""
from engine.bridge_idle_gestures import build_sequence_clips

# Damage severity bands (tune against engine/appc/combat.py magnitudes).
_LIGHT_MAX = 15.0
_HARD_MIN = 50.0
_BLAST_MIN = 120.0


def select_reaction(bearing_dot, damage) -> str:
    if damage >= _BLAST_MIN:
        return "Blast"
    if damage >= _HARD_MIN:
        return "HitHardStanding"
    if damage >= _LIGHT_MAX:
        return "HitStanding"
    return "ReactRight" if bearing_dot >= 0.0 else "ReactLeft"


def _bearing_dot(ship, hit_point) -> float:
    """Sign>0 = starboard (right), <0 = port (left), via the ship's right axis."""
    try:
        loc = ship.GetWorldLocation()
        right = ship.GetWorldRotation().GetCol(0)
        dx = hit_point.GetX() - loc.GetX()
        dy = hit_point.GetY() - loc.GetY()
        dz = hit_point.GetZ() - loc.GetZ()
        return dx * right.GetX() + dy * right.GetY() + dz * right.GetZ()
    except Exception:
        return 0.0


class HitReactionHandler:
    def __init__(self, controller, *, get_player, get_characters, anim_mgr):
        self._controller = controller
        self._get_player = get_player
        self._get_characters = get_characters
        self._anim_mgr = anim_mgr

    def on_weapon_hit(self, event) -> None:
        player = self._get_player()
        if player is None or event.GetTarget() is not player:
            return
        hit_point = event.GetHitPoint()
        bearing = _bearing_dot(player, hit_point) if hit_point is not None else 0.0
        reaction = select_reaction(bearing, float(event.GetDamage()))
        for ch in self._get_characters():
            if getattr(ch, "_render_instance", None) is None or ch.IsHidden():
                continue
            module_path = self._resolve_key(ch, reaction)
            if not module_path:
                continue
            clips = build_sequence_clips(module_path, ch, self._anim_mgr)
            if clips:
                self._controller.submit(ch, clips, priority=1)

    @staticmethod
    def _resolve_key(character, reaction) -> str:
        """Find the character's registered animation whose key ENDS WITH the
        reaction name (keys are location-prefixed, e.g. 'DBGuestReactRight').
        Returns the module path, or '' if the character lacks that reaction."""
        for entry in getattr(character, "_animations", []):
            if entry and len(entry) >= 2 and str(entry[0]).endswith(reaction):
                return entry[1]
        return ""
```

- [ ] **Step 4: Run it to verify it passes**

Run: `uv run pytest tests/unit/test_bridge_hit_reactions.py -v`
Expected: PASS.

- [ ] **Step 5: Subscribe in the host loop**

In `engine/host_loop.py`, after constructing `char_anim` (Task 6 Step 5), build the handler and register it on the event manager for `ET_WEAPON_HIT`:

```python
        from engine.bridge_hit_reactions import HitReactionHandler
        hit_reactions = HitReactionHandler(
            char_anim,
            get_player=lambda: getattr(controller, "player_ship", None),
            get_characters=_live_bridge_characters,
            anim_mgr=anim_mgr,
        )
```

Subscribe `hit_reactions.on_weapon_hit` to the broadcast `ET_WEAPON_HIT` via the same registry combat uses (`App.g_kEventManager`). Confirm the exact registration call with `grep -n "AddBroadcastPython" engine/appc/events.py`; use the method-handler variant so `on_weapon_hit(event)` is invoked with the `WeaponHitEvent`. The `WeaponHitEvent` carries the firing ship via `GetSource()` and the hit ship via `GetTarget()`; the handler already filters to player-ship targets.

- [ ] **Step 6: Run the full bridge-anim suite + GUI check**

Run: `uv run pytest tests/unit/test_bridge_hit_reactions.py tests/unit/test_bridge_idle_gestures.py tests/unit/test_bridge_character_anim.py tests/unit/test_bridge_placement_rest_pose.py -v`
Expected: PASS. Then in `./build/dauntless`, take fire: crew flinch toward/away from impacts, harder hits give bigger reactions, then everyone returns to their rest pose.

- [ ] **Step 7: Commit**

```bash
git add engine/bridge_hit_reactions.py engine/host_loop.py tests/unit/test_bridge_hit_reactions.py
git commit -m "feat(bridge): direction+severity hit reactions for bridge crew"
```

---

## Self-Review

**Spec coverage:**
- Placement static rest-pose fix → Tasks 1–2 ✓
- Idle ambient gestures (per-character timers, SDK builders, mode-respecting) → Task 6 ✓
- Hit reactions (direction + severity) → Task 7 ✓
- Authored-transitions-only (play SDK sequence clips, AT_DEFAULT = restore_rest_pose) → Tasks 1, 5 ✓
- Priority/preempt (reaction > idle) → Task 5 ✓
- Phase 0 gesture-retarget spike (gates idle/hit) → Task 3 ✓
- Native rest store/restore + runtime clip loading → Tasks 1, 4 ✓
- `sample_at_start` heuristic kept as-is → Task 2 uses `placement["sample_at_start"]` unchanged ✓
- Lipsync + guest chair deferred → not in any task ✓
- Tests: placement regression (Task 2), controller queue (Task 5), idle scheduler (Task 6), hit mapping (Task 7) ✓

**Type consistency:** `set_instance_rest_pose(iid, clip_index, at_start)`, `restore_rest_pose(iid)`, `load_instance_clip(iid, nif_path)->int`, `controller.submit(character, clips, priority)`, `controller.is_busy(character)`, `controller.update(dt, *, renderer, anim_mgr)`, `build_sequence_clips(module_path, character, anim_mgr)`, `select_reaction(bearing_dot, damage)->str` — names/signatures match across producing and consuming tasks.

**Open confirmations flagged inline (resolve during implementation, not blockers):** the host-loop controller class name owning `officer_instances` (Task 2/5); the native asset-store accessor for mutating an instance's model (Task 4); the exact `AddBroadcastPython*` registration call (Task 7); a body-rig skeleton-introspection path if the spike's clip-reader comparison is insufficient (Task 3).
