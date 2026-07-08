# E1M1 Character Walk-On Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make E1M1's Picard and Saffi render — walking onto the bridge from the turbolift while the opening briefing plays — by implementing the `CharacterAction AT_MOVE` movement primitive that reveals, walks, and re-stations bridge characters.

**Architecture:** `AT_MOVE` stops being a no-op: it resolves the SDK's registered `<location>To<detail>` animation builder (the same registry turn-to-captain uses), extracts the walk clip + end-location, and queues a request on a new `BridgeCharacterWalkController`. The controller (which has the renderer) realizes the hidden character's skinned instance on demand, un-hides it, and plays the walk clip with **root motion applied** via a new `play_instance_walk` binding — the walk clip's baked Bip01 translation carries the character across the bridge (BC officers are positioned entirely by that root translation). On settle it re-stations the character (rest pose = walk's last frame + breathe idle) and fires the action's completion so the mission sequence advances. Standing and seated end-states use the identical path.

**Tech Stack:** Python 3 (engine), C++/pybind11 + GLM (native renderer), pytest + GoogleTest/ctest.

## Global Constraints

- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). A failure is "pre-existing" only if the ledger says so. Never call a failure pre-existing by eyeball.
- **Native rebuild:** any `native/src/host/host_bindings.cc` change requires rebuilding the `dauntless` binary (`cmake --build build -j`), not just the module — a module-only rebuild leaves `./build/dauntless` stale. Build tree is the single `build/` at project root; never spawn alternate output paths.
- **Renderer wrapper discipline:** all renderer calls go through `engine/renderer.py` wrappers over `_h` (the host module) — never call `_dauntless_host` directly. A new binding needs both the C++ `m.def` and the Python wrapper, or hasattr-guarded `r.<binding>` calls silently no-op.
- **Units:** everything spatial is game units (GU); no conversions here (bridge-local space throughout).
- **Rotation convention:** column-vector, right-handed (`GetCol(1)` = forward). Not exercised directly by this plan (root translation only), but do not introduce row reads.
- **Production path untouched:** all behavior is bridge-character-scoped and best-effort (collapses to no-op on any resolution failure); the dialogue/audio path is never modified.

---

## File Structure

- **Create** `engine/bridge_character_walk.py` — `BridgeCharacterWalkController` (realize → reveal → root-motion walk → settle → re-station → complete) + module singleton. One responsibility: the walk lifecycle.
- **Create** `tests/unit/test_bridge_character_walk.py` — controller unit tests (FakeRenderer).
- **Create** `tests/unit/test_character_action_move.py` — `AT_MOVE`/`AT_SET_LOCATION_NAME`/`AT_WATCH_ME` dispatch tests.
- **Create** `tests/unit/test_capture_move.py` — `capture_move` builder-resolution tests.
- **Modify** `engine/appc/bridge_placement.py` — add `capture_move(character, detail)`.
- **Modify** `engine/appc/ai.py` — `CharacterAction`: `AT_MOVE` queues a walk; `AT_SET_LOCATION_NAME`/`AT_WATCH_ME`/`AT_STOP_WATCHING_ME` become real (state + completion).
- **Modify** `engine/host_loop.py` — extract `_realize_character_instance`; construct/reset/pump the walk controller; add `_sync_bridge_character_visibility`.
- **Modify** `engine/renderer.py` — `play_instance_walk` wrapper.
- **Modify** `native/src/host/host_bindings.cc` — `play_instance_walk` binding.
- **Modify** `native/tests/renderer/animation_update_test.cc` — root-motion play-through test.

---

## Task 1: `play_instance_walk` — root-motion playback binding

**Files:**
- Modify: `native/src/host/host_bindings.cc` (after `play_instance_gesture`, ~line 1259)
- Modify: `native/tests/renderer/animation_update_test.cc`
- Modify: `engine/renderer.py` (after `play_instance_gesture`, ~line 627)

**Interfaces:**
- Produces (native binding + Python wrapper): `play_instance_walk(iid: InstanceId, clip_index: int) -> None` — starts the instance animation with `layer_over_rest=false, loop=false, sample_at_start=false, sample_at_end=false`, routing to `update_animations`' non-layered `sample_pose` branch (root translation applied, plays through, settles at last frame).

- [ ] **Step 1: Write the failing native test**

Add to `native/tests/renderer/animation_update_test.cc`. First add a model builder with a moving-root clip (place it in the anonymous namespace, after `two_bone_model_with_clip`):

```cpp
// Model whose clip TRANSLATES the root (Bip01) over time: (0,0,0) at t=0 to
// (100,0,0) at t=1. Used to verify walk playback applies root motion (unlike
// layer_over_rest gestures, which anchor the root).
assets::Model root_motion_model() {
    assets::Model m;
    assets::Bone b0; b0.name = "Bip01"; b0.parent_index = -1;
    b0.local_transform = glm::mat4(1.0f);
    m.skeleton.bones = {b0};
    m.skeleton.root_bone_index = 0;
    m.skeleton.bones[0].inverse_bind_pose = glm::mat4(1.0f);

    assets::AnimationClip clip; clip.name = "walk"; clip.duration_seconds = 1.0f;
    assets::AnimationClip::NodeTrack tr; tr.target_node_name = "Bip01";
    tr.translation = {{0.0f, glm::vec3(0, 0, 0)}, {1.0f, glm::vec3(100, 0, 0)}};
    clip.tracks = {tr};
    m.animations = {clip};
    return m;
}
```

Then the test:

```cpp
TEST(AnimationUpdate, WalkFlagsApplyRootMotionAndPlayThrough) {
    // The flag combo play_instance_walk sets (layer_over_rest=false, loop=false,
    // sample_at_start=false, sample_at_end=false) must APPLY the clip's root
    // translation and play through over time — the opposite of a layered gesture.
    assets::Model model = root_motion_model();
    auto lookup = [&](scenegraph::ModelHandle){ return &model; };

    scenegraph::World world;
    auto id = world.create_instance(/*model=*/1);
    scenegraph::Instance::AnimationState st;   // exactly what play_instance_walk sets
    st.clip_index = 0;
    st.loop = false;
    st.layer_over_rest = false;
    st.sample_at_start = false;
    st.sample_at_end = false;
    st.start_wall_time = 100.0;
    world.set_animation(id, st);

    auto root_x_at = [&](double now) {
        renderer::update_animations(world, lookup, now);
        return (world.get(id)->bone_palette[0] * glm::vec4(0, 0, 0, 1)).x;
    };

    EXPECT_NEAR(root_x_at(100.0), 0.0f, 1e-3f);        // t=0: at lift
    EXPECT_FALSE(world.get(id)->animation.settled);
    EXPECT_NEAR(root_x_at(100.5), 50.0f, 1e-3f);       // t=0.5: mid-walk (root moved)
    EXPECT_FALSE(world.get(id)->animation.settled);
    EXPECT_NEAR(root_x_at(200.0), 100.0f, 1e-3f);      // t>=dur: arrived, settled
    EXPECT_TRUE(world.get(id)->animation.settled);
}
```

- [ ] **Step 2: Build and run the test to verify it passes against existing `update_animations`**

The non-layered branch already exists, so this test should PASS immediately — it locks in the contract `play_instance_walk` depends on. Run:

```bash
cmake --build build -j --target renderer_tests 2>&1 | tail -5
cd build && ctest -R AnimationUpdate.WalkFlagsApplyRootMotionAndPlayThrough --output-on-failure; cd ..
```
Expected: PASS. (If it fails, the play-through/root-motion assumption is wrong — STOP and re-investigate before adding the binding.)

- [ ] **Step 3: Add the native binding**

In `native/src/host/host_bindings.cc`, immediately after the `play_instance_gesture` `m.def` block (ends ~line 1259):

```cpp
    m.def("play_instance_walk",
          [](scenegraph::InstanceId id, int clip_index) {
              scenegraph::Instance::AnimationState st;
              st.clip_index = clip_index;
              st.loop = false;
              st.layer_over_rest = false;   // FULL clip: root translation applied
              st.sample_at_start = false;
              st.sample_at_end = false;
              st.start_wall_time = glfwGetTime();
              g_world.set_animation(id, st);
          },
          py::arg("iid"), py::arg("clip_index"),
          "Play a full clip with ROOT MOTION applied (non-layered): the clip's "
          "baked Bip01 root translation moves the character across the set (e.g. "
          "a turbolift walk-on). Plays once and settles at the last frame.");
```

- [ ] **Step 4: Add the Python wrapper**

In `engine/renderer.py`, after `play_instance_gesture` (~line 627):

```python
def play_instance_walk(iid: InstanceId, clip_index: int) -> None:
    """Play a full clip with root motion applied (non-layered): the clip's baked
    Bip01 root translation moves the character across the set (turbolift walk-on).
    Plays once and settles at the last frame — unlike play_instance_gesture, which
    anchors the root at the placement pose."""
    _h.play_instance_walk(iid, clip_index)
```

- [ ] **Step 5: Rebuild the dauntless binary and run the gate**

```bash
cmake --build build -j 2>&1 | tail -5
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: build clean, gate green (no new failures vs `tests/known_failures.txt`).

- [ ] **Step 6: Commit**

```bash
git add native/src/host/host_bindings.cc native/tests/renderer/animation_update_test.cc engine/renderer.py
git commit -m "feat(walk-on): play_instance_walk root-motion playback binding"
```

---

## Task 2: `capture_move` — resolve the SDK walk builder

**Files:**
- Modify: `engine/appc/bridge_placement.py` (add after `capture_registered_clip`, ~line 146)
- Test: `tests/unit/test_capture_move.py`

**Interfaces:**
- Consumes: `_resolve_builder_sequence(character, suffix)`, `_nif_path_for_clip(clip_name)` (existing module-level helpers in `bridge_placement.py`).
- Produces: `capture_move(character, detail) -> dict | None`. Returns `{"clip_nif": <data-root-relative path>, "end_location": <str|None>}` or `None` when there is no location, no `<location>To<detail>` registration, or the clip is unresolvable. `end_location` is the detail of the trailing `AT_SET_LOCATION_NAME` action in the builder sequence (the station the character occupies after the move), or `None`.

- [ ] **Step 1: Write the failing test**

`tests/unit/test_capture_move.py`:

```python
from engine.appc import bridge_placement


class _AnimNode:
    def __init__(self, kind):
        self.kind = kind


class _AnimAction:
    """Stands in for a TGAnimAction: has an anim node + clip name."""
    def __init__(self, kind, clip):
        self._anim_node = _AnimNode(kind)
        self._clip = clip


class _CharAction:
    """Stands in for a CharacterAction inside the builder sequence."""
    def __init__(self, action_type, detail):
        self._action_type = action_type
        self._detail = detail


class _Seq:
    def __init__(self, actions):
        self._actions = actions
    def GetNumActions(self):
        return len(self._actions)
    def GetAction(self, i):
        return self._actions[i]


AT_SET_LOCATION_NAME = 1   # CharacterAction.AT_SET_LOCATION_NAME


def test_capture_move_extracts_walk_clip_and_end_location(monkeypatch):
    # Builder returns: [walk TGAnimAction on the character, trailing set-location].
    seq = _Seq([
        _AnimAction("character", "db_L1toP_P"),
        _CharAction(AT_SET_LOCATION_NAME, "DBGuest1"),
    ])
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda ch, suffix: seq if suffix == "ToP1" else None)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip",
                        lambda name: "data/animations/db_L1toP_P.nif"
                        if name == "db_L1toP_P" else None)

    got = bridge_placement.capture_move(character=object(), detail="P1")
    assert got == {"clip_nif": "data/animations/db_L1toP_P.nif",
                   "end_location": "DBGuest1"}


def test_capture_move_none_when_no_builder(monkeypatch):
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda ch, suffix: None)
    assert bridge_placement.capture_move(character=object(), detail="P1") is None


def test_capture_move_none_when_clip_unresolvable(monkeypatch):
    seq = _Seq([_AnimAction("character", "missing_clip")])
    monkeypatch.setattr(bridge_placement, "_resolve_builder_sequence",
                        lambda ch, suffix: seq)
    monkeypatch.setattr(bridge_placement, "_nif_path_for_clip", lambda name: None)
    assert bridge_placement.capture_move(character=object(), detail="P1") is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_capture_move.py -v
```
Expected: FAIL with `AttributeError: module 'engine.appc.bridge_placement' has no attribute 'capture_move'`.

- [ ] **Step 3: Implement `capture_move`**

In `engine/appc/bridge_placement.py`, after `capture_registered_clip` (~line 146):

```python
def capture_move(character, detail):
    """Resolve the SDK-registered movement builder for AT_MOVE to `detail`.

    AT_MOVE composes the animation key <current-location>To<detail> (e.g. location
    "DBL1M" + "To" + "P1" = "DBL1MToP1") and runs the registered builder
    (Picard.py:143 -> PicardAnimations.MoveFromL1ToP1). That builder returns a
    TGSequence carrying the walk clip (a TGAnimAction on the character's anim
    node) and a trailing AT_SET_LOCATION_NAME giving the station the character
    occupies after the move.

    Returns {"clip_nif": <data-root-relative path>, "end_location": <str|None>}
    or None (no location / no <location>To<detail> registration / unresolvable
    clip). Best-effort — mirrors the capture_* helpers.
    """
    # Import here so the module stays headless-importable; only needed for the
    # AT_SET_LOCATION_NAME action-type constant.
    from engine.appc.ai import CharacterAction

    seq = _resolve_builder_sequence(character, "To" + str(detail))
    if seq is None:
        return None

    # Walk clip: the last action targeting the CHARACTER anim node (same rule as
    # capture_registered_clip — a move builder may also carry set/door actions).
    clip_name = ""
    for i in range(seq.GetNumActions() - 1, -1, -1):
        a = seq.GetAction(i)
        if getattr(getattr(a, "_anim_node", None), "kind", None) == "character":
            clip_name = getattr(a, "_clip", "") or getattr(a, "name", "")
            break
    if not clip_name:
        return None
    clip_nif = _nif_path_for_clip(clip_name)
    if not clip_nif:
        _logger.warning("capture_move: no path for %r", clip_name)
        return None

    # End location: the trailing AT_SET_LOCATION_NAME detail, if the builder
    # appends one (the station the character stands/sits at after the move).
    end_location = None
    for i in range(seq.GetNumActions()):
        a = seq.GetAction(i)
        if getattr(a, "_action_type", None) == CharacterAction.AT_SET_LOCATION_NAME:
            end_location = getattr(a, "_detail", None)

    return {"clip_nif": clip_nif, "end_location": end_location}
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/unit/test_capture_move.py -v
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/appc/bridge_placement.py tests/unit/test_capture_move.py
git commit -m "feat(walk-on): capture_move resolves AT_MOVE walk builder + end-location"
```

---

## Task 3: `BridgeCharacterWalkController`

**Files:**
- Create: `engine/bridge_character_walk.py`
- Test: `tests/unit/test_bridge_character_walk.py`

**Interfaces:**
- Consumes: a `realize_fn(character) -> iid|None` injected at construction (created by Task 6 host wiring; closes over the renderer + mission controller). Renderer methods used via the `renderer` passed to `update`: `load_instance_clip`, `play_instance_walk` (Task 1), `set_instance_rest_pose`, `play_instance_idle`, `load_animation_clips`. `capture_breathing` (existing).
- Produces:
  - `BridgeCharacterWalkController(realize_fn=None, asset_resolver=None)`
  - `.request_move(character, clip_nif, end_location, on_complete) -> None`
  - `.update(dt, *, renderer) -> None`
  - `.reset() -> None`
  - `.is_moving(character) -> bool`
  - module singletons: `get_controller()`, `set_controller(ctrl)`, `clear_controller()`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_bridge_character_walk.py`:

```python
from engine.bridge_character_walk import BridgeCharacterWalkController


class _FakeRenderer:
    def __init__(self):
        self._next = 100
        self.loaded = {}          # (iid, path) -> clip_index
        self.walked = []          # (iid, clip_index)
        self.rest_poses = []      # (iid, clip_index, at_start)
        self.idled = []           # (iid, clip_index)
    def load_instance_clip(self, iid, path):
        key = (iid, path)
        if key not in self.loaded:
            self._next += 1
            self.loaded[key] = self._next
        return self.loaded[key]
    def play_instance_walk(self, iid, clip_index):
        self.walked.append((iid, clip_index))
    def set_instance_rest_pose(self, iid, clip_index, at_start):
        self.rest_poses.append((iid, clip_index, at_start))
    def play_instance_idle(self, iid, clip_index):
        self.idled.append((iid, clip_index))
    def load_animation_clips(self, path):
        return [{"duration": 2.0}]     # every walk clip is 2s in tests


class _Char:
    def __init__(self, name="Picard"):
        self._character_name = name
        self._render_instance = None
        self._location = "DBL1M"
        self._hidden = 1
    def GetCharacterName(self):
        return self._character_name
    def SetHidden(self, h):
        self._hidden = 1 if h else 0
    def IsHidden(self):
        return self._hidden
    def SetLocation(self, loc):
        self._location = loc
    def GetLocation(self):
        return self._location


def _controller_with_realize():
    realized = {"next": 500}
    def realize_fn(character):
        realized["next"] += 1
        character._render_instance = realized["next"]
        return character._render_instance
    return BridgeCharacterWalkController(realize_fn=realize_fn), realize_fn


def test_move_realizes_reveals_and_walks(monkeypatch):
    import engine.bridge_character_walk as bcw
    monkeypatch.setattr(bcw, "capture_breathing", lambda ch: None)
    ctrl, _ = _controller_with_realize()
    r = _FakeRenderer()
    ch = _Char()
    done = []
    ctrl.request_move(ch, "db_L1toP_P.nif", "DBGuest1",
                      on_complete=lambda: done.append(True))

    ctrl.update(0.0, renderer=r)                 # drain: realize + reveal + walk
    assert ch._render_instance is not None
    assert ch.IsHidden() == 0                    # revealed
    iid = ch._render_instance
    assert r.walked == [(iid, r.loaded[(iid, "db_L1toP_P.nif")])]
    assert ctrl.is_moving(ch) is True
    assert done == []                            # not complete until settle


def test_move_settles_restations_and_completes(monkeypatch):
    import engine.bridge_character_walk as bcw
    monkeypatch.setattr(bcw, "capture_breathing",
                        lambda ch: {"clip_nif": "DBGuest1Breathe.nif"})
    ctrl, _ = _controller_with_realize()
    r = _FakeRenderer()
    ch = _Char()
    done = []
    ctrl.request_move(ch, "db_L1toP_P.nif", "DBGuest1",
                      on_complete=lambda: done.append(True))
    ctrl.update(0.0, renderer=r)                 # start (duration 2.0)
    iid = ch._render_instance
    walk_clip = r.loaded[(iid, "db_L1toP_P.nif")]

    ctrl.update(1.0, renderer=r)                 # mid-walk: still moving
    assert ctrl.is_moving(ch) is True
    assert done == []

    ctrl.update(1.5, renderer=r)                 # elapsed 2.5 >= 2.0: settle
    assert ch.GetLocation() == "DBGuest1"        # re-stationed
    # rest pose frozen at the walk clip's LAST frame (at_start=False)
    assert (iid, walk_clip, False) in r.rest_poses
    assert r.idled == [(iid, r.loaded[(iid, "DBGuest1Breathe.nif")])]
    assert done == [True]                        # completion fired
    assert ctrl.is_moving(ch) is False


def test_move_completes_inline_when_realize_fails():
    ctrl = BridgeCharacterWalkController(realize_fn=lambda ch: None)  # realize fails
    r = _FakeRenderer()
    ch = _Char()
    done = []
    ctrl.request_move(ch, "db_L1toP_P.nif", "DBGuest1",
                      on_complete=lambda: done.append(True))
    ctrl.update(0.0, renderer=r)
    assert done == [True]                        # never stalls the sequence
    assert r.walked == []


def test_reset_clears_active(monkeypatch):
    import engine.bridge_character_walk as bcw
    monkeypatch.setattr(bcw, "capture_breathing", lambda ch: None)
    ctrl, _ = _controller_with_realize()
    r = _FakeRenderer()
    ch = _Char()
    ctrl.request_move(ch, "w.nif", "DBGuest1", on_complete=lambda: None)
    ctrl.update(0.0, renderer=r)
    ctrl.reset()
    assert ctrl.is_moving(ch) is False
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_bridge_character_walk.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'engine.bridge_character_walk'`).

- [ ] **Step 3: Implement the controller**

`engine/bridge_character_walk.py`:

```python
# engine/bridge_character_walk.py
"""BridgeCharacterWalkController — the CharacterAction AT_MOVE walk lifecycle.

A walk-on (E1M1 Picard/Saffi entering from the turbolift) is a hidden bridge
character being realized, revealed, and moved to a station via a root-motion
clip. This controller owns that one-shot lifecycle; it is kept separate from the
transient gesture/turn runner (bridge_character_anim) because its completion
signalling and root-motion playback differ.

Seam (mirrors bridge_character_anim / bridge_cutscene): CharacterAction.Play
QUEUES a request headlessly; update() — which has the renderer — drains it.
Completion is DEFERRED: on_complete (the action's Completed()) fires when the
walk clip settles, so the mission TGSequence advances exactly when the walk ends.
"""

from engine.appc.bridge_placement import capture_breathing

# Floor duration for a walk clip whose length the renderer can't report (headless
# FakeRenderer without load_animation_clips): completes on the next update.
_MIN_WALK_S = 0.0


class _Move:
    __slots__ = ("character", "iid", "clip_index", "end_location",
                 "on_complete", "elapsed", "duration")

    def __init__(self, character, clip_nif, end_location, on_complete):
        self.character = character
        self.clip_nif = clip_nif                # resolved lazily on drain
        self.end_location = end_location
        self.on_complete = on_complete
        self.iid = None
        self.clip_index = -1
        self.elapsed = 0.0
        self.duration = 0.0


# _Move needs clip_nif before drain; add it to __slots__.
_Move.__slots__ = ("character", "clip_nif", "iid", "clip_index", "end_location",
                   "on_complete", "elapsed", "duration")


class BridgeCharacterWalkController:
    def __init__(self, realize_fn=None, asset_resolver=None):
        self._pending = []          # [_Move] not yet started
        self._active = {}           # iid -> _Move
        self._realize = realize_fn or (lambda character: None)
        self._resolve = asset_resolver or (lambda p: p)

    def is_moving(self, character) -> bool:
        iid = getattr(character, "_render_instance", None)
        return iid is not None and iid in self._active

    def request_move(self, character, clip_nif, end_location, on_complete) -> None:
        self._pending.append(
            _Move(character, clip_nif, end_location, on_complete))

    def reset(self) -> None:
        self._pending = []
        self._active = {}

    def update(self, dt, *, renderer) -> None:
        if self._pending:
            pending, self._pending = self._pending, []
            for mv in pending:
                self._start(renderer, mv)
        if not self._active:
            return
        done = []
        for iid, mv in self._active.items():
            mv.elapsed += dt
            if mv.elapsed >= mv.duration:
                self._settle(renderer, mv)
                done.append(iid)
        for iid in done:
            self._active.pop(iid, None)

    def _complete(self, mv) -> None:
        cb = mv.on_complete
        if cb is not None:
            try:
                cb()
            except Exception:
                pass

    def _start(self, renderer, mv) -> None:
        character = mv.character
        iid = getattr(character, "_render_instance", None)
        if iid is None:
            iid = self._realize(character)      # lazy build for hidden walk target
        if iid is None:
            self._complete(mv)                  # can't render → don't stall sequence
            return
        try:
            character.SetHidden(0)              # reveal
            path = self._resolve(mv.clip_nif)
            clip_index = renderer.load_instance_clip(iid, path)
            if clip_index is None or clip_index < 0:
                self._complete(mv)
                return
            renderer.play_instance_walk(iid, clip_index)
        except Exception:
            self._complete(mv)
            return
        mv.iid = iid
        mv.clip_index = clip_index
        mv.elapsed = 0.0
        mv.duration = self._real_duration(renderer, path)
        self._active[iid] = mv

    def _settle(self, renderer, mv) -> None:
        """Walk finished: re-station the character (rest pose = walk's last frame),
        set its end location, resume breathing, and fire completion."""
        character = mv.character
        iid = mv.iid
        try:
            if mv.end_location:
                character.SetLocation(mv.end_location)
            # Freeze the rest pose at the walk clip's LAST frame — the character is
            # now standing/seated at the destination — so breathing layers over it.
            renderer.set_instance_rest_pose(iid, mv.clip_index, False)
            breathing = capture_breathing(character)
            if breathing:
                bidx = renderer.load_instance_clip(
                    iid, self._resolve(breathing["clip_nif"]))
                if bidx is not None and bidx >= 0:
                    renderer.play_instance_idle(iid, bidx)
                    from engine.bridge_character_anim import get_controller
                    ca = get_controller()
                    if ca is not None:
                        ca.set_idle(iid, bidx)
        except Exception:
            pass
        self._complete(mv)

    def _real_duration(self, renderer, path) -> float:
        fn = getattr(renderer, "load_animation_clips", None)
        if fn is None:
            return _MIN_WALK_S
        try:
            clips = fn(path)
            if clips:
                return float(clips[0].get("duration", 0.0) or 0.0)
        except Exception:
            pass
        return _MIN_WALK_S


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

Note: the duplicate `_Move.__slots__` assignment in Step 3 is a copy error — remove the first `__slots__` line inside the class and keep ONLY the corrected tuple that includes `clip_nif`. Final `_Move` has exactly one `__slots__` line:

```python
class _Move:
    __slots__ = ("character", "clip_nif", "iid", "clip_index", "end_location",
                 "on_complete", "elapsed", "duration")

    def __init__(self, character, clip_nif, end_location, on_complete):
        self.character = character
        self.clip_nif = clip_nif
        self.end_location = end_location
        self.on_complete = on_complete
        self.iid = None
        self.clip_index = -1
        self.elapsed = 0.0
        self.duration = 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_bridge_character_walk.py -v
```
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/bridge_character_walk.py tests/unit/test_bridge_character_walk.py
git commit -m "feat(walk-on): BridgeCharacterWalkController (realize/reveal/walk/settle)"
```

---

## Task 4: Extract `_realize_character_instance` in host_loop

**Files:**
- Modify: `engine/host_loop.py` (`_place_one_character`, lines ~4129-4240)

**Interfaces:**
- Produces: `_realize_character_instance(controller, r, character, set_name, is_bridge, *, comm_set_id=None, start_hidden=False) -> int | None` — builds the skinned instance from the character's current placement, tags `character._render_instance`, wires breathing, appends to the right instance registry, and returns the iid (or None on failure). `start_hidden=True` sets the instance invisible after creation (comm path). This is the instance-building tail of `_place_one_character`, made callable so the walk controller can realize a hidden bridge character on demand.
- Consumes: existing `capture_placement`, `capture_breathing`, `assemble_officer`, `OFFICER_TRANSFORM`, `_tag_comm_instance`.

- [ ] **Step 1: Characterization test — capture current placement behavior**

Before refactoring, add a test that locks in the existing behavior so the extraction is provably behavior-preserving. `tests/unit/test_realize_character_instance.py`:

```python
"""Locks the placement/realization behavior that Task 4 extracts. If these pass
before AND after the refactor, the extraction preserved behavior."""
import engine.host_loop as HL


def test_realize_helper_exists_and_is_used_by_place_one_character():
    # The extracted helper must exist...
    assert hasattr(HL, "_realize_character_instance")
    # ...and _place_one_character must delegate to it (no duplicated build body).
    import inspect
    src = inspect.getsource(HL._place_one_character)
    assert "_realize_character_instance" in src
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_realize_character_instance.py -v
```
Expected: FAIL (`_realize_character_instance` does not exist yet).

- [ ] **Step 3: Extract the helper**

In `engine/host_loop.py`, refactor `_place_one_character`. Replace the instance-building tail (everything from `ap = character.appearance()` at ~line 4165 through the `comm_instances_by_set` bookkeeping at ~line 4230) with a call to a new function. The new function contains that exact body verbatim; `_place_one_character` keeps the early-returns (idempotency + `capture_placement` + the `placement["hidden"] and is_bridge` skip) and then delegates:

```python
def _place_one_character(controller, r, character, set_name, is_bridge,
                         *, comm_set_id: int = None) -> None:
    from engine.appc.bridge_placement import capture_placement

    if getattr(character, "_render_instance", None) is not None:
        return                                       # already placed this load
    try:
        placement = capture_placement(character)
        if not placement:
            return
        # Hidden bridge characters (e.g. E1M1 Picard in the turbolift) are NOT
        # placed at load — they are realized on demand by the walk controller
        # when AT_MOVE reveals them. Comm-set characters ARE built up front
        # (invisible) and revealed per-frame by _sync_comm_character_visibility.
        if placement["hidden"] and is_bridge:
            return
        _realize_character_instance(
            controller, r, character, set_name, is_bridge,
            comm_set_id=comm_set_id, start_hidden=placement["hidden"])
    except Exception:
        name = ""
        try:
            name = character.GetCharacterName()
        except Exception as _e:
            dev_mode.log_swallowed("character.GetCharacterName in error path", _e)
        import traceback
        print(f"[host_loop] WARNING: failed to place character {name!r}",
              flush=True)
        traceback.print_exc()


def _realize_character_instance(controller, r, character, set_name, is_bridge,
                                *, comm_set_id: int = None,
                                start_hidden: bool = False):
    """Build the skinned instance for a character at its CURRENT placement, tag
    _render_instance, wire breathing, and register it. Returns the iid or None.

    Extracted from _place_one_character so the walk controller can realize a
    hidden bridge character on demand (AT_MOVE reveal). start_hidden hides the
    fresh instance (comm path); the walk controller passes start_hidden=False and
    reveals via SetHidden(0)."""
    from engine.appc.bridge_placement import capture_placement, capture_breathing

    placement = capture_placement(character)
    if not placement:
        return None

    def _abs(p):
        return str(PROJECT_ROOT / "game" / p) if p else None

    create = r.create_bridge_instance if is_bridge else r.create_comm_instance

    ap = character.appearance()
    if not ap.get("body_nif"):
        return None

    _facial = getattr(character, "_facial_images", {}) or {}
    _slot_of = {"SpeakA": "a", "SpeakE": "e", "SpeakU": "u",
                "Blink0": "blink1", "Blink1": "blink2", "Blink2": "eyesclosed"}
    face_images = {slot: _abs(_facial[k])
                   for k, slot in _slot_of.items() if _facial.get(k)}

    model = r.assemble_officer(
        _abs(ap.get("body_nif")), _abs(ap.get("head_nif")),
        _abs(ap.get("body_tex")), _abs(ap.get("head_tex")),
        _abs(placement["clip_nif"]),
        placement["sample_at_start"],
        face_images=face_images,
    )
    iid = create(model)
    try:
        r.set_world_transform(iid, OFFICER_TRANSFORM)
        r.set_instance_rest_pose(iid, 0, placement["sample_at_start"])
    except Exception:
        try:
            r.destroy_instance(iid)
        except Exception as _e:
            dev_mode.log_swallowed("destroy officer instance (rollback)", _e)
        raise
    character._render_instance = iid
    if start_hidden:
        try:
            r.set_visible(iid, False)
        except Exception as _e:
            dev_mode.log_swallowed("char initial hide", _e)
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
    if is_bridge:
        controller.officer_instances.append(iid)
    else:
        controller.comm_instances_by_set.setdefault(set_name, []).append(iid)
        _tag_comm_instance(r, iid, comm_set_id)
    return iid
```

(The lip-sync `LIPSYNC_DEBUG` print block from the original tail is developer-only tracing — omit it from the extracted helper; it is not behavior.)

- [ ] **Step 4: Run the characterization test + the full gate**

```bash
uv run pytest tests/unit/test_realize_character_instance.py -v
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: new test PASS; gate green (existing bridge/comm placement tests still pass — behavior preserved).

- [ ] **Step 5: Commit**

```bash
git add engine/host_loop.py tests/unit/test_realize_character_instance.py
git commit -m "refactor(walk-on): extract _realize_character_instance from _place_one_character"
```

---

## Task 5: `CharacterAction` dispatch — `AT_MOVE` + companions

**Files:**
- Modify: `engine/appc/ai.py` (`CharacterAction`, lines ~1153-1235)
- Test: `tests/unit/test_character_action_move.py`

**Interfaces:**
- Consumes: `bridge_placement.capture_move` (Task 2), `bridge_character_walk.get_controller` (Task 3), `characters.CharacterClass_Cast`.
- Produces: `CharacterAction.Play()` behavior — `AT_MOVE` queues a walk (completion deferred to the controller); `AT_SET_LOCATION_NAME` sets the character location and completes; `AT_WATCH_ME`/`AT_STOP_WATCHING_ME` set/clear a watch flag and complete. All non-speak types other than these remain inline no-ops (unchanged).

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_character_action_move.py`:

```python
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
import engine.bridge_character_walk as bcw


class _Char:
    def __init__(self, name="Picard"):
        self._character_name = name
        self._location = "DBL1M"
    def GetCharacterName(self):
        return self._character_name
    def SetLocation(self, loc):
        self._location = loc
    def GetLocation(self):
        return self._location


class _RecordingWalkController:
    def __init__(self):
        self.requests = []
    def request_move(self, character, clip_nif, end_location, on_complete):
        self.requests.append((character, clip_nif, end_location, on_complete))


def test_at_move_queues_walk_and_defers_completion(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "capture_move",
                        lambda character, detail: {
                            "clip_nif": "db_L1toP_P.nif",
                            "end_location": "DBGuest1"} if detail == "P1" else None)
    # Cast is identity for our fake (it isn't a real CharacterClass).
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()

    assert act.IsPlaying() is True                    # deferred: not yet complete
    assert len(ctrl.requests) == 1
    character, clip_nif, end_location, on_complete = ctrl.requests[0]
    assert (clip_nif, end_location) == ("db_L1toP_P.nif", "DBGuest1")

    on_complete()                                     # controller signals settle
    assert act.IsPlaying() is False                   # now complete


def test_at_move_completes_inline_when_unresolvable(monkeypatch):
    ch = _Char()
    ctrl = _RecordingWalkController()
    monkeypatch.setattr(bcw, "get_controller", lambda: ctrl)
    monkeypatch.setattr(bridge_placement, "capture_move",
                        lambda character, detail: None)   # no builder
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)

    act = CharacterAction(ch, CharacterAction.AT_MOVE, "P1")
    act.Play()
    assert ctrl.requests == []
    assert act.IsPlaying() is False                   # never stalls the sequence


def test_at_set_location_name_updates_location():
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_SET_LOCATION_NAME, "DBGuest1")
    act.Play()
    assert ch.GetLocation() == "DBGuest1"
    assert act.IsPlaying() is False


def test_at_watch_me_completes_inline():
    ch = _Char()
    act = CharacterAction(ch, CharacterAction.AT_WATCH_ME)
    act.Play()
    assert act.IsPlaying() is False                   # sequencing advances
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/unit/test_character_action_move.py -v
```
Expected: FAIL — `test_at_move_queues_walk_and_defers_completion` fails because `Play()` currently completes AT_MOVE inline (no queue); `test_at_set_location_name_updates_location` fails because location is unchanged.

- [ ] **Step 3: Implement the dispatch**

In `engine/appc/ai.py`, modify `CharacterAction.Play` (currently ~line 1191) and add helpers. Replace `Play`:

```python
    def Play(self) -> None:
        self._playing = True
        at = self._action_type
        if at == self.AT_MOVE:
            # Movement (walk-on / sit-down) completes when the walk clip settles:
            # the walk controller calls our Completed(). If it can't be queued
            # (headless / unresolved builder), complete inline so the mission
            # TGSequence never stalls.
            self._queue_move()
            return
        if at == self.AT_SET_LOCATION_NAME:
            if self._character is not None and self._detail is not None:
                try:
                    self._character.SetLocation(self._detail)
                except Exception:
                    pass
            self.Completed()
            return
        # AT_WATCH_ME / AT_STOP_WATCHING_ME set the watch-captain flag (visual
        # head-track is a follow-up; sequencing must still advance). Other
        # non-speak types remain inline no-ops.
        if at in (self.AT_WATCH_ME, self.AT_STOP_WATCHING_ME):
            self._set_watch(at == self.AT_WATCH_ME)
            self.Completed()
            return
        # Speak types (and the remaining no-op types) keep the prior flow.
        dur = self._do_play()
        self._complete_after(dur or 0.0)

    def _queue_move(self) -> None:
        from engine.appc import bridge_placement
        from engine.appc.characters import CharacterClass_Cast
        from engine import bridge_character_walk
        cc = CharacterClass_Cast(self._character) if self._character is not None else None
        ctrl = bridge_character_walk.get_controller()
        move = bridge_placement.capture_move(cc, self._detail) if cc is not None else None
        if cc is None or ctrl is None or move is None:
            self.Completed()          # nothing to play → advance immediately
            return
        ctrl.request_move(cc, move["clip_nif"], move["end_location"],
                          on_complete=self.Completed)

    def _set_watch(self, watching: bool) -> None:
        cc = self._character
        if cc is None:
            return
        try:
            if watching:
                cc.SetStatus(cc.CS_TURNED)     # "watching the captain" state flag
            else:
                cc.ClearStatus(cc.CS_TURNED)
        except Exception:
            pass
```

Note: `_do_play` is unchanged — it still handles speak types and returns 0.0 for anything else (now only reached by the remaining no-op types, never AT_MOVE / AT_SET_LOCATION_NAME / AT_WATCH_ME, which `Play` intercepts above).

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/unit/test_character_action_move.py -v
```
Expected: PASS (4 tests).

- [ ] **Step 5: Run the speak-action regression tests (make sure dialogue still works)**

```bash
uv run pytest tests/unit/test_actions.py tests/unit/test_ai_primitives.py -v 2>&1 | tail -15
```
Expected: PASS (speak-line completion timing unchanged).

- [ ] **Step 6: Commit**

```bash
git add engine/appc/ai.py tests/unit/test_character_action_move.py
git commit -m "feat(walk-on): CharacterAction AT_MOVE/SET_LOCATION_NAME/WATCH_ME dispatch"
```

---

## Task 6: Host-loop wiring — construct, pump, reset, reveal

**Files:**
- Modify: `engine/host_loop.py` — construct + reset the walk controller; per-frame `update`; `_sync_bridge_character_visibility`.
- Test: `tests/unit/test_bridge_visibility_sync.py`

**Interfaces:**
- Consumes: `BridgeCharacterWalkController` (Task 3), `_realize_character_instance` (Task 4).
- Produces: `_sync_bridge_character_visibility(controller, r)` — per-frame `r.set_visible(iid, not ch.IsHidden())` for realized bridge characters (mirror of `_sync_comm_character_visibility`).

- [ ] **Step 1: Write the failing test for the visibility sync**

`tests/unit/test_bridge_visibility_sync.py`:

```python
import engine.host_loop as HL


class _FakeR:
    def __init__(self):
        self.vis = {}
    def set_visible(self, iid, v):
        self.vis[iid] = v


class _Char:
    def __init__(self, iid, hidden):
        self._render_instance = iid
        self._hidden = hidden
    def IsHidden(self):
        return self._hidden


class _Controller:
    def __init__(self, chars):
        self._chars = chars


def test_bridge_visibility_sync_drives_set_visible(monkeypatch):
    revealed = _Char(11, 0)
    hidden = _Char(12, 1)
    unrealized = _Char(None, 0)
    monkeypatch.setattr(HL, "_bridge_characters_for_sync",
                        lambda controller: [revealed, hidden, unrealized])
    r = _FakeR()
    HL._sync_bridge_character_visibility(_Controller([]), r)
    assert r.vis == {11: True, 12: False}    # unrealized (iid None) skipped
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/unit/test_bridge_visibility_sync.py -v
```
Expected: FAIL (`_sync_bridge_character_visibility` / `_bridge_characters_for_sync` do not exist).

- [ ] **Step 3: Implement the sync helper**

In `engine/host_loop.py`, near `_sync_comm_character_visibility` (~line 4092), add:

```python
def _bridge_characters_for_sync(controller):
    """Every realized-or-not bridge CharacterClass (the player bridge set). Split
    out so the visibility sync is unit-testable without a live set manager."""
    import App as _App
    s = _App.g_kSetManager.GetSet("bridge")
    if s is None:
        return []
    return list(_iter_set_characters(s))


def _sync_bridge_character_visibility(controller, r) -> None:
    """Drive each realized bridge character's instance visibility from its SDK
    IsHidden() flag — the bridge analogue of _sync_comm_character_visibility.

    Bridge walk-on characters (E1M1 Picard/Saffi) are realized on demand and
    revealed by the walk controller's SetHidden(0); this per-frame sync turns any
    IsHidden toggle into actual renderer visibility. Cheap: a handful of bridge
    characters."""
    for ch in _bridge_characters_for_sync(controller):
        iid = getattr(ch, "_render_instance", None)
        if iid is None:
            continue
        try:
            r.set_visible(iid, not ch.IsHidden())
        except Exception as _e:
            dev_mode.log_swallowed("bridge char visibility sync", _e)
```

- [ ] **Step 4: Run the sync test to verify it passes**

```bash
uv run pytest tests/unit/test_bridge_visibility_sync.py -v
```
Expected: PASS.

- [ ] **Step 5: Wire construction + node/reset + per-frame pump**

In `engine/host_loop.py`:

(a) Construct the walk controller alongside `char_anim` (~line 4808), after `set_char_anim(char_anim)`:

```python
        from engine.bridge_character_walk import (
            BridgeCharacterWalkController, set_controller as set_walk_ctrl,
        )
        walk_ctrl = BridgeCharacterWalkController(
            realize_fn=lambda ch: _realize_character_instance(
                controller, r, ch, "bridge", True, start_hidden=False),
            asset_resolver=_game_asset_path)
        set_walk_ctrl(walk_ctrl)
```

(b) Pump it per-frame in the bridge-view block, immediately after `char_anim.update(...)` (~line 5971):

```python
                        walk_ctrl.update(_player_dt, renderer=r)
```

(c) Reset it on mission swap, next to `char_anim.reset()` (~line 5585):

```python
                    walk_ctrl.reset()
```

(d) Call the bridge visibility sync each frame. Add it right after the existing `_sync_comm_character_visibility(controller, r)` call (~line 6125):

```python
            _sync_bridge_character_visibility(controller, r)
```

- [ ] **Step 6: Rebuild not required (Python only); run the full gate**

```bash
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: gate green.

- [ ] **Step 7: Commit**

```bash
git add engine/host_loop.py tests/unit/test_bridge_visibility_sync.py
git commit -m "feat(walk-on): wire walk controller + bridge IsHidden visibility sync"
```

---

## Task 7: Seated-variant coverage + full-path integration test

**Files:**
- Test: `tests/unit/test_walk_on_integration.py`

**Interfaces:**
- Consumes: everything from Tasks 2-6. No new production code expected — this task proves the seated transition (sit-down) rides the same primitive, and adds an end-to-end headless test of the dispatch → controller flow. If it reveals a gap, fix it here.

- [ ] **Step 1: Write the integration test (walk-on AND sit-down through one path)**

`tests/unit/test_walk_on_integration.py`:

```python
"""End-to-end (headless): CharacterAction AT_MOVE -> walk controller -> settle,
for BOTH a standing walk-on (P1) and a seated sit-down (P), proving they are one
primitive differing only by clip + end-location."""
from engine.appc.ai import CharacterAction
from engine.appc import bridge_placement
import engine.bridge_character_walk as bcw
from engine.bridge_character_walk import BridgeCharacterWalkController


class _FakeRenderer:
    def __init__(self):
        self._next = 100
        self.loaded = {}
        self.walked = []
        self.rest_poses = []
        self.idled = []
    def load_instance_clip(self, iid, path):
        self.loaded.setdefault((iid, path), len(self.loaded) + 200)
        return self.loaded[(iid, path)]
    def play_instance_walk(self, iid, ci):
        self.walked.append((iid, ci))
    def set_instance_rest_pose(self, iid, ci, at_start):
        self.rest_poses.append((iid, ci, at_start))
    def play_instance_idle(self, iid, ci):
        self.idled.append((iid, ci))
    def load_animation_clips(self, path):
        return [{"duration": 1.0}]


class _Char:
    def __init__(self):
        self._character_name = "Picard"
        self._render_instance = None
        self._location = "DBL1M"
        self._hidden = 1
    def GetCharacterName(self): return self._character_name
    def SetHidden(self, h): self._hidden = 1 if h else 0
    def IsHidden(self): return self._hidden
    def SetLocation(self, loc): self._location = loc
    def GetLocation(self): return self._location


def _run_move(monkeypatch, detail, clip, end_location):
    ch = _Char()
    walk = BridgeCharacterWalkController(
        realize_fn=lambda c: setattr(c, "_render_instance", 777)
        or c._render_instance)
    monkeypatch.setattr(bcw, "get_controller", lambda: walk)
    monkeypatch.setattr(bcw, "capture_breathing", lambda c: None)
    monkeypatch.setattr(bridge_placement, "capture_move",
                        lambda character, d: {"clip_nif": clip,
                                              "end_location": end_location}
                        if d == detail else None)
    monkeypatch.setattr("engine.appc.characters.CharacterClass_Cast",
                        lambda c: c)
    r = _FakeRenderer()

    act = CharacterAction(ch, CharacterAction.AT_MOVE, detail)
    act.Play()
    assert act.IsPlaying() is True
    walk.update(0.0, renderer=r)          # realize + reveal + walk
    assert ch.IsHidden() == 0
    assert r.walked and r.walked[0][0] == 777
    walk.update(2.0, renderer=r)          # settle (dur 1.0)
    assert ch.GetLocation() == end_location
    assert act.IsPlaying() is False       # completion propagated to the action
    return r


def test_standing_walk_on(monkeypatch):
    r = _run_move(monkeypatch, "P1", "db_L1toP_P.nif", "DBGuest1")
    assert any(rp[2] is False for rp in r.rest_poses)   # frozen at last frame


def test_seated_sit_down(monkeypatch):
    # Same primitive: only clip + end-location differ (MoveFromP1ToP -> db_sit_P).
    r = _run_move(monkeypatch, "P", "db_sit_P.nif", "DBGuest")
    assert any(rp[2] is False for rp in r.rest_poses)
```

- [ ] **Step 2: Run the test**

```bash
uv run pytest tests/unit/test_walk_on_integration.py -v
```
Expected: PASS (2 tests). If either fails, the primitive is not uniform across standing/seated — fix in the controller/dispatch, not the test.

- [ ] **Step 3: Run the full gate**

```bash
scripts/check_tests.sh 2>&1 | tail -20
```
Expected: gate green.

- [ ] **Step 4: Commit**

```bash
git add tests/unit/test_walk_on_integration.py
git commit -m "test(walk-on): standing walk-on + seated sit-down ride one AT_MOVE path"
```

---

## Task 8: GUI verification (manual, final sign-off)

**Files:** none (manual verification; the render path cannot be asserted headlessly, consistent with prior bridge-character sign-offs).

- [ ] **Step 1: Launch E1M1 and observe the opening**

```bash
./build/dauntless
```
Load E1M1 (dev mission picker if not the default boot). Watch the opening briefing.

- [ ] **Step 2: Verify the walk-on**

Confirm, and note any deviation:
- The turbolift door opens and **Picard walks onto the bridge** to his mark (P1), visible throughout the briefing.
- **Saffi walks on** to her mark (C2).
- Both are visible and correctly posed while their dialogue plays (no invisible speakers, no T-pose, no origin-snap).
- On arrival they settle to a standing pose and breathe (no frozen mid-stride).
- The later intro **sit-down** moves them to their seated stations.
- **Door timing** (out-of-scope component): note whether the camera-driven door open aligns with the characters emerging. If it visibly conflicts, log it for the deferred door follow-up — do not fix here.

- [ ] **Step 3: Record the result**

If all good: update the memory `project_e1m1_character_walkon.md` to "live-verified" and note the merge state. If issues: capture them as new observations (they are most likely one of the known layered-skinning gotchas — see `project_bc_character_rigid_skinning`) and return to systematic-debugging.

- [ ] **Step 4: Finish the branch**

Use `superpowers:finishing-a-development-branch` to decide merge/PR. The deferred follow-ups (lift-door ownership, full AT_TURN/AT_GLANCE family, other-mission walk-ons, watch-me visual head-track) are already recorded in the spec's follow-up section and the memory — carry them forward.

---

## Self-Review

**Spec coverage:**
- Root cause (AT_MOVE no-op, hidden bridge chars unplaced, no bridge reveal) → Tasks 5, 4, 6. ✓
- Component 1 (AT_MOVE dispatch, deferred completion) → Task 5. ✓
- Component 2 (movement controller) → Task 3. ✓
- Component 3 (realize + reveal + bridge visibility sync) → Tasks 4, 6. ✓
- Component 4 (root-motion playback binding) → Task 1. ✓
- Component 5 (AT_WATCH_ME/STOP_WATCHING_ME) → Task 5 (state + completion). **Scope refinement:** the *visual* body-yaw head-track is deferred to follow-ups (it fights the root-motion walk and is low-value until the walk itself is verified); dispatch/sequencing is implemented. Flagged to the user at handoff.
- Component 6 (AT_SET_LOCATION_NAME real) → Task 5. ✓
- Component 7 (end-state handoff to placement + breathe) → Task 3 `_settle`. ✓
- Standing + seated end-states → Task 7. ✓
- Testing (headless unit + native + GUI) → Tasks 1-8. ✓
- Deferred follow-ups → carried in spec + Task 8 Step 4. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code; the one copy-error in Task 3 Step 3 (`_Move.__slots__`) is explicitly called out and corrected inline.

**Type consistency:** `play_instance_walk(iid, clip_index)` consistent across Task 1 (binding + wrapper) and Task 3 (`_start`). `capture_move(...) -> {"clip_nif", "end_location"}` consistent across Tasks 2, 5, 7. `request_move(character, clip_nif, end_location, on_complete)` consistent across Tasks 3, 5. `_realize_character_instance(...)` signature consistent across Tasks 4, 6. `on_complete = self.Completed` (bound method) consistent with the controller calling `cb()`.
