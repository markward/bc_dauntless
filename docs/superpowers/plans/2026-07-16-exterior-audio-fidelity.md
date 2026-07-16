# Exterior Audio Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the exterior (space) 3D audio path in line with `docs/architecture/sound-system-openal-guide.md` — BC's real attenuation constants, working node attachment, doppler, the nearest-≤4 engine-hum allocator, voice priority, and the space side of the one-active-scene rule.

**Architecture:** The guide assumes BC's scene graph, where `AttachToNode` copies a node's world transform into the emitter each frame. **We have no scene graph** — the deferred renderer means Python owns object transforms, and `ObjectClass.GetNode()` already returns an `_ObjectNodeRef` (a weak handle to the owning object) for exactly this purpose. So node attachment lands as a Python-side per-frame pump (`engine/audio/attached_sources.py`), and the C++ `NodeId`/`node_pos_fn_` machinery — which assumed a scene graph, was never wired outside a unit test, and is the reason the breakage stayed invisible — gets removed rather than connected.

**Tech Stack:** C++17 + OpenAL Soft (`native/src/audio/`), pybind11 binding (`python_binding.cc`), Python shim layer (`engine/audio/`), gtest/ctest + pytest.

## Global Constraints

- **Scope is the exterior/space 3D path only.** Streaming (guide §12), music, category-bus slider wiring, and EFX/region reverb (§11) are explicitly **out of scope**. Do not implement them.
- **Units: feed raw game units, never convert.** BC's `unitsPerMeter = 1.0` means the engine treats 1 GU as 1 m for doppler regardless of visual scale. Our GU is 175 m (`engine/units.py`), but being *faithful* means adopting BC's convention verbatim: `alSpeedOfSound(343.3)` with positions and velocities in raw GU. **Do not "correct" this to 60025.** Do not port BC's velocity ÷1000 (that is a Miles m/ms API convention; OpenAL wants units/sec).
- **BC's shipped constants (guide §5), recovered from `TGSound::SetupFromFile` @ `0x0070B360`:** everything = reference `50.0` / max `700.0`; ship engine hum = reference `4.375` / max `35.0`. Rolloff is always `1.0` (BC never overrides it). Pitch `1.0`, volume `1.0`, priority `0.5`, cone `360/360/1.0` (disabled).
- **Priority is a voice-stealing rank, NOT gain.** `0.9` local / `0.6` remote phaser / `0.5` remote pulse+tractor go to the eviction comparator, never to `AL_GAIN`.
- **Distance model must be `AL_INVERSE_DISTANCE_CLAMPED`.** `maxDistance` clamps (floors gain), it does not cut off.
- **3D sources must be mono.** OpenAL silently plays stereo buffers unspatialised.
- **Shared checkout — NEVER run destructive git.** No `git checkout -- <path>`, `git restore`, `git stash`, `git clean`, `git reset --hard`, `git add -A`, or `git add .`. Always stage with an explicit pathspec. To mutate a file temporarily, `cp` it to `/tmp`, mutate, restore by `cp`, and `diff` to prove the restore.
- **Test gate:** `scripts/check_tests.sh` (builds C++, runs pytest + ctest, diffs against `tests/known_failures.txt`). `scripts/run_tests.sh` is pytest-only and cannot see C++ regressions. The only legitimate baseline failures are the 7 headless-GL scorch/heat-glow `FrameTest`s.
- **Build:** `cmake -B build -S . && cmake --build build -j` from the project root. Never run `cmake` inside `native/`. Binary is `build/dauntless`; extension is `build/python/_dauntless_host.cpython-*.so`. An `AttributeError: module '_dauntless_host' has no attribute X` means a stale binary — rebuild, don't change Python.
- **Green tests cannot see the live game.** Every task ends green, but the plan is not done until the live verify (Task 10) has been run and observed.

---

## File Structure

**Created:**
- `engine/audio/attached_sources.py` — the per-frame position/velocity pump for node-attached 3D sounds. Owns the `_ObjectNodeRef` → world-transform copy and the numeric guard. Replaces `engine_rumble.update_positions`.
- `engine/audio/hum_allocator.py` — the nearest-≤4 engine-hum allocator (guide §10). Replaces `engine_rumble`'s unbounded play-for-every-ship listener.
- `tests/audio/test_attached_sources.py`, `tests/audio/test_hum_allocator.py`, `tests/audio/test_voice_priority.py`, `tests/audio/test_scene_scope.py`

**Modified:**
- `native/src/audio/src/openal_backend.cc` — distance model pin, BC ref/max defaults, velocity, doppler globals, batching, mono guard, source pool.
- `native/src/audio/include/audio/audio_backend.h` + `null_backend.{h,cc}` — `set_velocity`, `set_listener` velocity args, priority arg on `play`.
- `native/src/audio/include/audio/audio_system.h` + `src/audio_system.cc` — remove the dead `NodeId`/`node_pos_fn_` path; add velocity + priority.
- `native/src/audio/src/python_binding.cc` — drop `attach_node`, add `set_velocity` + `priority`.
- `engine/audio/tg_sound.py` — BC defaults, real `AttachToNode`, priority default `0.5`.
- `engine/audio/engine_rumble.py` — hand hum lifetime to the allocator; delete `update_positions`.
- `engine/appc/weapon_subsystems.py` — retire the `GetSceneNodeId` phantom; pass `GetNode()`.
- `engine/host_loop.py` — pump attached sources + hum allocator in `tick_audio`.
- `tests/audio/test_engine_rumble.py`, `tests/unit/test_phaser_fire_sfx_attach.py`, `tests/unit/test_phaser_fire_sfx_edge_trigger.py` — remove the `GetSceneNodeId` fakes that masked the phantom.
- `native/tests/audio/audio_system_test.cc` — track the C++ surface changes.

---

### Task 1: BC's attenuation constants + pin the distance model

The guide's §5 numbers are the single highest-value fix: our defaults are `100 / 100000`, BC's are `50 / 700`. The `100000` is the serious half — it means `maxDistance` never clamps, so we lose the audible floor (`50/700 ≈ 0.071`) that keeps distant capital ships faintly present. `alDistanceModel` is also never called; we inherit `AL_INVERSE_DISTANCE_CLAMPED` from OpenAL's default, which is correct but unpinned and is the guide's #1 footgun.

**Files:**
- Modify: `engine/audio/tg_sound.py:79-80` (defaults), `:104-105` (setter)
- Modify: `native/src/audio/src/openal_backend.cc:21-36` (init), `:76-89` (play)
- Test: `tests/audio/test_tg_sound.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces: `TGSound.BC_DEFAULT_MIN_DISTANCE = 50.0`, `TGSound.BC_DEFAULT_MAX_DISTANCE = 700.0` — module constants later tasks import rather than re-typing the literals.

- [ ] **Step 1: Write the failing test**

Append to `tests/audio/test_tg_sound.py`:

```python
def test_bc_default_min_max_distance(audio, tmp_path):
    """Guide §5: BC's TGSound::SetupFromFile defaults are 50/700, not 100/100000.

    The max matters most: AL_INVERSE_DISTANCE_CLAMPED floors gain at
    ref/(ref+(max-ref)) past max and holds it there. At max=100000 the floor
    never engages and distant ships fade to nothing, which is the one thing
    guide §5 says makes BC sound like BC.
    """
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "Ranged", TGSound.LS_3D)
    snd = audio.GetSound("Ranged")

    assert snd._min_dist == 50.0
    assert snd._max_dist == 700.0
    assert TGSound.BC_DEFAULT_MIN_DISTANCE == 50.0
    assert TGSound.BC_DEFAULT_MAX_DISTANCE == 700.0

    _dauntless_host.audio.clear_command_log()
    snd.Play()
    log = _dauntless_host.audio.debug_command_log()
    mm = [c for c in log if c["op"] == "set_min_max_distance"]
    assert len(mm) == 1, f"expected one set_min_max_distance, got {log}"
    assert mm[0]["f"][0] == 50.0
    assert mm[0]["f"][1] == 700.0


def test_bc_default_priority_is_half(audio, tmp_path):
    """Guide §8: TGSound+0x68 default priority is 0.5, not 0.0."""
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSound(str(wav), "Prio", TGSound.LS_3D)
    assert audio.GetSound("Prio").GetPriority() == 0.5
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/audio/test_tg_sound.py::test_bc_default_min_max_distance \
              tests/audio/test_tg_sound.py::test_bc_default_priority_is_half -v
```

Expected: FAIL — `AttributeError: type object 'TGSound' has no attribute 'BC_DEFAULT_MIN_DISTANCE'`, and `assert 100.0 == 50.0`.

> If `debug_command_log()` entries do not expose `["name"]` / `["f"]` keys in that shape, read `native/src/audio/src/python_binding.cc:debug_command_log_impl` and match the real shape — adapt the test, not the binding.

- [ ] **Step 3: Write minimal implementation**

In `engine/audio/tg_sound.py`, add the constants to the `TGSound` class body next to the existing `LS_*` constants:

```python
class TGSound:
    # Loadspec constants (match App.py).
    LS_3D = 0
    LS_STREAMED = 1
    LS_DELAY_LOADING = 2
    # Status (return values for GetStatus).
    SS_PLAYING = 0
    SS_STOPPED = 1
    SS_UNLOADED = 2
    SS_UNKNOWN = 3

    # BC's TGSound::SetupFromFile shipped defaults (0x0070B360), recovered in
    # docs/architecture/sound-system-openal-guide.md §5. SetMinMaxDistance has
    # exactly three xrefs in the original binary and no weapon code touches it,
    # so this one pair sets the loudness balance of essentially all BC combat
    # audio. The ship engine hum is the sole exception (see hum_allocator).
    BC_DEFAULT_MIN_DISTANCE = 50.0
    BC_DEFAULT_MAX_DISTANCE = 700.0
    BC_DEFAULT_PRIORITY = 0.5
```

Then change `__init__` (currently lines 78-80):

```python
        self._priority = TGSound.BC_DEFAULT_PRIORITY
        self._min_dist = TGSound.BC_DEFAULT_MIN_DISTANCE
        self._max_dist = TGSound.BC_DEFAULT_MAX_DISTANCE
```

In `native/src/audio/src/openal_backend.cc`, pin the distance model in `init()` — add immediately after the successful `alcMakeContextCurrent` and before `return true;`:

```cpp
        // Guide §2/§14.1: THE faithful model — the same law DS3D uses. This is
        // already OpenAL's default, but pin it explicitly: AL_LINEAR_DISTANCE
        // cuts off at max where BC/DS3D clamps, and that is the one change
        // that makes BC's audio sound wrong.
        alDistanceModel(AL_INVERSE_DISTANCE_CLAMPED);
        return true;
```

And in `play()`, replace the hardcoded reference distance (currently line 79) so the backend default matches BC even if nothing pushes min/max afterwards:

```cpp
        if (positional) {
            alSourcei(al, AL_SOURCE_RELATIVE, AL_FALSE);
            alSource3f(al, AL_POSITION, x, y, z);
            // BC TGSound::SetupFromFile defaults (guide §5). TGSound.Play
            // overwrites these via set_min_max_distance; they are the floor
            // for any caller that does not.
            alSourcef(al, AL_REFERENCE_DISTANCE, 50.0f);
            alSourcef(al, AL_MAX_DISTANCE,       700.0f);
            alSourcef(al, AL_ROLLOFF_FACTOR,     1.0f);
        } else {
```

- [ ] **Step 4: Run test to verify it passes**

```bash
cmake --build build -j
uv run pytest tests/audio/test_tg_sound.py -v
```

Expected: PASS (all tests in the file).

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0. Any failure not in `tests/known_failures.txt` is a regression this task introduced.

- [ ] **Step 6: Commit**

```bash
git add engine/audio/tg_sound.py native/src/audio/src/openal_backend.cc tests/audio/test_tg_sound.py
git commit -m "fix(audio): BC's real 50/700 attenuation defaults; pin AL_INVERSE_DISTANCE_CLAMPED

TGSound defaulted to 100/100000. BC's SetupFromFile ships 50/700 (guide §5).
The 100000 max meant the clamped-inverse floor never engaged, so distant ships
faded to silence instead of holding at ref/(ref+(max-ref)).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Retire the `GetSceneNodeId` phantom; make `AttachToNode` real

`GetSceneNodeId` appears **nowhere in the SDK or `App.py`** — it is our own invention. Two production sites probe for it (`engine/audio/engine_rumble.py:43`, `engine/appc/weapon_subsystems.py:530`), get a truthy `_Stub` back, and collapse `int(_Stub())` to `0`. The stub heatmap ranks `engine_rumble.py:44` **#8 in the truthiness table at 233 hits, 46/47 coverage** — this is live-observed, not inferred. All three covering tests define `GetSceneNodeId` on their fake ships, which is why the suite is green.

Meanwhile `TGSound.AttachToNode` is an explicit `pass`, so MissionLib's two torpedo-sound attach sites (`MissionLib.py:3289`, `:3389`) are inert.

The real anchor already exists: `ObjectClass.GetNode()` returns an `_ObjectNodeRef` (weak handle → `GetWorldLocation()`), and `TGSoundAction.SetNode` already consumes exactly that.

**Files:**
- Create: `engine/audio/attached_sources.py`
- Create: `tests/audio/test_attached_sources.py`
- Modify: `engine/audio/tg_sound.py` (`AttachToNode`, `DetachFromNode`, `Play`, `_PlayingSound.Stop`)
- Modify: `engine/appc/weapon_subsystems.py:520-531` (`_firing_ship_node_id`)
- Modify: `engine/appc/actions.py:560-575` (`_node_position` → shared helper)
- Modify: `engine/host_loop.py:135-145` (`tick_audio`)
- Modify: `tests/unit/test_phaser_fire_sfx_attach.py:44`, `tests/unit/test_phaser_fire_sfx_edge_trigger.py:45`

**Interfaces:**
- Consumes: `TGSound.BC_DEFAULT_*` (Task 1).
- Produces:
  - `engine.audio.attached_sources.node_world_position(node) -> tuple[float,float,float] | None`
  - `engine.audio.attached_sources.attach(handle: _PlayingSound, node) -> None`
  - `engine.audio.attached_sources.detach(handle) -> None`
  - `engine.audio.attached_sources.pump(dt: float) -> None`
  - `engine.audio.attached_sources.reset_for_tests() -> None`
  - `TGSound.AttachToNode(node)` / `TGSound.DetachFromNode()` now real.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_attached_sources.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import attached_sources
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _Loc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _FakeNode:
    """Stands in for _ObjectNodeRef: the only contract is GetWorldLocation()."""
    def __init__(self, loc): self._loc = loc
    def GetWorldLocation(self): return self._loc


class _ChainableStub:
    """Mimics TGObject.__getattr__ -> _Stub: truthy, and coerces to 0.0.

    This is the trap the whole task exists to close — a stub node must fall
    back to non-positional, never silently pin the sound to the world origin.
    """
    def __call__(self, *a, **k): return self
    def __getattr__(self, _n): return self
    def __float__(self): return 0.0


@pytest.fixture
def audio(tmp_path):
    attached_sources.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Torp", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()
    attached_sources.reset_for_tests()


def test_node_world_position_reads_the_node():
    assert attached_sources.node_world_position(_FakeNode(_Loc(1.0, 2.0, 3.0))) == (1.0, 2.0, 3.0)


def test_node_world_position_rejects_stub_node():
    """A chainable stub must yield None, not (0.0, 0.0, 0.0)."""
    assert attached_sources.node_world_position(_ChainableStub()) is None
    assert attached_sources.node_world_position(None) is None
    assert attached_sources.node_world_position(_FakeNode(None)) is None


def test_attach_to_node_tracks_the_object_each_pump(audio):
    snd = audio.GetSound("Torp")
    loc = _Loc(10.0, 0.0, 0.0)
    snd.AttachToNode(_FakeNode(loc))
    handle = snd.Play()
    assert handle is not None

    _dauntless_host.audio.clear_command_log()
    loc.x = 25.0
    attached_sources.pump(dt=0.016)

    moves = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "set_position"]
    assert moves, "AttachToNode must move the source when the object moves"
    assert moves[-1]["f"][0] == 25.0


def test_stopped_handle_is_dropped_from_the_pump(audio):
    snd = audio.GetSound("Torp")
    snd.AttachToNode(_FakeNode(_Loc(1.0, 1.0, 1.0)))
    handle = snd.Play()
    handle.Stop()

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "set_position"]


def test_dead_object_is_dropped_from_the_pump(audio):
    """_ObjectNodeRef is weak — a GC'd ship must not keep the source pumping."""
    import weakref

    class _Owner:
        def GetWorldLocation(self): return _Loc(5.0, 5.0, 5.0)

    owner = _Owner()
    ref = weakref.ref(owner)

    class _WeakNode:
        def GetWorldLocation(self):
            o = ref()
            return None if o is None else o.GetWorldLocation()

    snd = audio.GetSound("Torp")
    snd.AttachToNode(_WeakNode())
    snd.Play()
    del owner

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.016)
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "set_position"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/audio/test_attached_sources.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.audio.attached_sources'`.

- [ ] **Step 3: Write the implementation**

Create `engine/audio/attached_sources.py`:

```python
"""Per-frame world-transform copy for node-attached 3D sounds.

Guide §7: `AttachToNode` is the only positioning mechanism BC scripts use —
they never set a position per frame. BC stores the scene node and copies its
world transform into the emitter every frame.

We have no scene graph. In the deferred-renderer model Python owns object
transforms and `ObjectClass.GetNode()` hands back an `_ObjectNodeRef` — a weak
handle to the owning object exposing `GetWorldLocation()`. So the "node" here
is that ref, and this module is BC's per-frame copy.

Weakness matters: a queued torpedo sound must never keep a dead ship alive, and
a GC'd owner must drop out of the pump rather than freeze its emitter in place.
"""
from __future__ import annotations

from typing import Optional


def node_world_position(node) -> Optional[tuple[float, float, float]]:
    """World (x, y, z) for a node ref, or None when it cannot be resolved.

    Coordinates MUST be real numbers. `TGObject.__getattr__` hands back a
    chainable `_Stub` for any unimplemented attribute; a stub coerces to 0.0
    and would silently pin the sound to the world origin, which is strictly
    worse than falling back to non-positional playback. This guard is the same
    one `TGSoundAction._node_position` documents — both call here now.
    """
    if node is None:
        return None
    getter = getattr(node, "GetWorldLocation", None)
    if getter is None:
        return None
    try:
        loc = getter()
    except Exception:
        return None
    if loc is None:
        return None
    x = getattr(loc, "x", None)
    y = getattr(loc, "y", None)
    z = getattr(loc, "z", None)
    if not all(type(c) in (int, float) for c in (x, y, z)):
        return None
    return (float(x), float(y), float(z))


class _Entry:
    __slots__ = ("handle", "node", "prev_pos")

    def __init__(self, handle, node) -> None:
        self.handle = handle
        self.node = node
        self.prev_pos: Optional[tuple[float, float, float]] = None


# Keyed by the playing-source id so a re-attached handle replaces cleanly.
_attached: dict[int, _Entry] = {}


def attach(handle, node) -> None:
    """Track `handle` against `node` until the handle stops or the node dies."""
    if handle is None or node is None or not handle._pid:
        return
    _attached[handle._pid] = _Entry(handle, node)


def detach(handle) -> None:
    if handle is not None and handle._pid:
        _attached.pop(handle._pid, None)


def pump(dt: float) -> None:
    """Copy every attached node's world position into its source.

    Called once per tick from host_loop.tick_audio, before the listener update
    so the positional math sees current source positions.
    """
    for pid, entry in list(_attached.items()):
        if not entry.handle._pid:          # explicitly stopped
            del _attached[pid]
            continue
        pos = node_world_position(entry.node)
        if pos is None:                    # owner GC'd or unresolvable
            del _attached[pid]
            continue
        entry.handle.SetPosition(*pos)
        entry.prev_pos = pos


def reset_for_tests() -> None:
    _attached.clear()
```

In `engine/audio/tg_sound.py`, replace the `AttachToNode` / `DetachFromNode` no-ops (currently lines 172-173):

```python
    def AttachToNode(self, node=None) -> None:
        """Anchor playback to `node` (an ObjectClass.GetNode() ref).

        Guide §7 — BC's only positioning mechanism. Applies to sources this
        sound starts from now on; already-playing handles keep their anchor.
        """
        self._node = node

    def DetachFromNode(self, *_a) -> None:
        self._node = None
```

Add `self._node = None` to `TGSound.__init__` alongside `self._region`:

```python
        self._region = None  # set by TGSoundRegion.AddSound; gates launch gain
        self._node = None    # AttachToNode anchor; see engine.audio.attached_sources
```

Register the handle in `TGSound.Play`. Replace the tail of `Play` (currently lines 132-138):

```python
        if pid == 0:
            return None
        handle = _PlayingSound(pid)
        self._active.append(handle)
        if self._positional or self._node is not None or position is not None:
            _audio.set_min_max_distance(pid, self._min_dist, self._max_dist)
        if self._node is not None:
            from engine.audio import attached_sources
            attached_sources.attach(handle, self._node)
        return handle
```

Change `Play`'s signature and the launch position so an attached sound starts at its node rather than at the origin (replace lines 120-131):

```python
    def Play(self, attach_node=None, position=None) -> Optional[_PlayingSound]:
        if not _audio or not self._loaded:
            return None
        # Drop handles we explicitly stopped earlier so the list can't grow
        # without bound across repeated one-shot plays.
        self._active = [h for h in self._active if h._pid]
        if attach_node is not None:
            self.AttachToNode(attach_node)
        if position is None and self._node is not None:
            from engine.audio import attached_sources
            # Launch at the anchor: a one-shot may finish before the first pump.
            position = attached_sources.node_world_position(self._node)
        factor = self._region.filter_factor() if self._region is not None else 1.0
        pid = _audio.play(
            name=self._name, looping=self._looping, gain=self._gain * factor,
            category=self._category_tag, position=position,
            # C++ node tracking is dead (node_pos_fn_ is never wired); Task 3
            # removes this parameter. Pass 0 until then — play_impl declares
            # attach_node with NO default, so omitting it raises TypeError.
            attach_node=0,
        )
```

> Two things to keep straight about `attach_node`:
> 1. **`TGSound.Play`'s `attach_node` keyword** is kept — callers pass it — but it now takes a **node ref**, not an int id, and it no longer reaches the C++ layer.
> 2. **`_audio.play`'s `attach_node`** is the C++ binding's parameter. It has no default (`python_binding.cc:play_impl`), so this task must keep passing `0`. **Task 3 removes it**, and only then does the argument come out of this call.

Make `_PlayingSound.Stop` detach (replace lines 47-50):

```python
    def Stop(self) -> None:
        if _audio and self._pid:
            _audio.stop(self._pid)
        if self._pid:
            from engine.audio import attached_sources
            attached_sources.detach(self)
        self._pid = 0
```

In `engine/appc/actions.py`, make `_node_position` delegate so the guard lives in one place (replace the body at lines 560-575, keeping the method name and its callers untouched):

```python
    def _node_position(self):
        """World position (x, y, z) from the SetNode anchor, or None.

        Resolved at Play time — the object may move between SetNode and the
        sequence firing this action. The numeric guard lives in
        engine.audio.attached_sources.node_world_position: a chainable stub
        node coerces to 0.0 and would silently pin the sound to the origin,
        which is worse than the non-positional fallback.
        """
        from engine.audio.attached_sources import node_world_position
        return node_world_position(self._node)
```

In `engine/appc/weapon_subsystems.py`, retire the phantom. Replace `_firing_ship_node_id` (lines 520-531) with:

```python
    def _firing_ship_node(self):
        """Walk parent_subsystem → parent_ship → GetNode() for the sound anchor.

        Returns None (non-positional) when any link is missing. NOTE: this used
        to probe a `GetSceneNodeId` that exists nowhere in the SDK or App.py —
        our own invention. It resolved to a truthy `_Stub`, `int()` collapsed it
        to 0, and every weapon sound played unattached. The tests only passed
        because their fake ships defined the phantom.
        """
        parent_sys = self.GetParentSubsystem() if hasattr(self, "GetParentSubsystem") else None
        if parent_sys is None:
            return None
        parent_ship = parent_sys.GetParentShip() if hasattr(parent_sys, "GetParentShip") else None
        if parent_ship is None:
            return None
        getter = getattr(parent_ship, "GetNode", None)
        return getter() if getter is not None else None
```

And update its call site (line 506):

```python
        attach_node = self._firing_ship_node()
```

- [ ] **Step 4: Fix the three tests that mocked the phantom**

These tests define `GetSceneNodeId` on their fakes, which is the only reason the broken code looked correct. Replace the phantom with the real `GetNode()` contract.

In `tests/audio/test_engine_rumble.py`, replace `_FakeShip` (lines 32-38):

```python
class _FakeLoc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _FakeShip:
    def __init__(self, sound_name, loc=(0.0, 0.0, 0.0)):
        self._impulse = _FakeSubsystem(_FakeProperty(sound_name))
        self._loc = _FakeLoc(*loc)
    def GetImpulseEngineSubsystem(self):
        return self._impulse
    def GetWorldLocation(self):
        return self._loc
    def GetNode(self):
        # Mirrors ObjectClass.GetNode(): a handle resolving GetWorldLocation.
        return self
```

In `tests/unit/test_phaser_fire_sfx_attach.py:44` and `tests/unit/test_phaser_fire_sfx_edge_trigger.py:45`, delete the `GetSceneNodeId` methods and give each fake ship the same `GetWorldLocation` + `GetNode` pair shown above. Update any assertion that expects the integer node id (`42`, `7`) to instead assert the sound was attached — e.g. that `attached_sources` tracks a handle after the fire call:

```python
    from engine.audio import attached_sources
    assert attached_sources._attached, "fire SFX must be anchored to the firing ship"
```

- [ ] **Step 5: Pump from the host loop**

In `engine/host_loop.py`, replace `tick_audio`'s body (lines 135-145):

```python
def tick_audio(*, camera_position, camera_forward, camera_up, dt, player) -> None:
    if _audio_mod is None:
        return
    # Copy attached nodes' world transforms into their sources before
    # set_listener, so the positional math sees up-to-date source positions.
    from engine.audio import attached_sources
    attached_sources.pump(dt)
    px, py, pz = camera_position
    fx, fy, fz = camera_forward
    ux, uy, uz = camera_up
    _audio_mod.update(px, py, pz, fx, fy, fz, ux, uy, uz, dt)
    _alert_listener.tick(player)
```

Remove the now-dead `update_positions` import at the top of `engine/host_loop.py` (grep for `from engine.audio.engine_rumble import` and drop `update_positions` from it), and delete `update_positions` from `engine/audio/engine_rumble.py` (lines 86-107) — `attached_sources.pump` supersedes it. Update `engine_rumble._scene_node_for` (lines 42-44) to hand back the node ref:

```python
def _node_for(ship):
    getter = getattr(ship, "GetNode", None)
    return getter() if getter is not None else None
```

and its call site (line 57):

```python
        playing = snd.Play(attach_node=_node_for(ship))
```

- [ ] **Step 6: Run the tests**

```bash
uv run pytest tests/audio/ tests/unit/test_phaser_fire_sfx_attach.py \
              tests/unit/test_phaser_fire_sfx_edge_trigger.py -v
```

Expected: PASS.

- [ ] **Step 7: Prove the phantom is gone**

```bash
grep -rn "GetSceneNodeId" engine/ tests/ native/ --include="*.py" --include="*.cc" | grep -v worktrees
```

Expected: **no output.** Any hit means a call site or a fake still references the invention.

- [ ] **Step 8: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0.

- [ ] **Step 9: Commit**

```bash
git add engine/audio/attached_sources.py engine/audio/tg_sound.py \
        engine/audio/engine_rumble.py engine/appc/weapon_subsystems.py \
        engine/appc/actions.py engine/host_loop.py \
        tests/audio/test_attached_sources.py tests/audio/test_engine_rumble.py \
        tests/unit/test_phaser_fire_sfx_attach.py \
        tests/unit/test_phaser_fire_sfx_edge_trigger.py
git commit -m "fix(audio): real AttachToNode; retire the GetSceneNodeId phantom

GetSceneNodeId exists nowhere in the SDK or App.py — our own invention. Both
production sites probed for it, got a truthy _Stub, and int() collapsed it to 0,
so every weapon sound and engine hum played unattached. All three covering tests
defined the phantom on their fakes, which is why this was green.

TGSound.AttachToNode was an explicit no-op, so MissionLib's two torpedo attach
sites were inert. Anchor on the existing _ObjectNodeRef contract instead, pumped
per-frame from tick_audio (guide §7).

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Remove the dead C++ `NodeId` / `node_pos_fn_` path

`set_node_position_fn` is called **only** from `native/tests/audio/audio_system_test.cc:68` — never in production. So `node_pos_fn_` is always null and `AudioSystem::update`'s node loop (`if (src.node == 0 || !node_pos_fn_) continue;`) has never moved a source. It assumed a scene graph we do not have. Task 2 replaced it; leaving two competing mechanisms is exactly how the breakage stayed invisible for so long.

**Files:**
- Modify: `native/src/audio/include/audio/audio_system.h:12-15, 25, 35-40, 64-68, 76`
- Modify: `native/src/audio/src/audio_system.cc:59-79, 114-139`
- Modify: `native/src/audio/src/python_binding.cc` (`play_impl`, `m.def("play", ...)`)
- Modify: `native/tests/audio/audio_system_test.cc`
- Modify: `engine/audio/tg_sound.py` — drop the `attach_node=0` argument Task 2 left in the `_audio.play` call

**Interfaces:**
- Consumes: `attached_sources.pump` (Task 2) is now the only node-tracking mechanism.
- Produces: `AudioSystem::play(SoundId, bool looping, float gain, Category, bool position_provided, float x, float y, float z)` and `play_sound(...)` with the same tail — **`NodeId attach_node` removed**. `_dauntless_host.audio.play(name=, looping=, gain=, category=, position=)` — **no `attach_node` kwarg**.

- [ ] **Step 1: Write the failing test**

In `native/tests/audio/audio_system_test.cc`, delete the `set_node_position_fn` test block (around line 68) and add:

```cpp
TEST(AudioSystem, PlayHasNoNodeParameter) {
    // Node tracking lives in Python (engine/audio/attached_sources.py) because
    // the deferred renderer has no scene graph. The C++ NodeId path assumed one,
    // was never wired outside this test file, and never moved a source.
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_wav();
    ASSERT_TRUE(sys.load_sound("sfx/test.wav", "S", wav.data(), wav.size(), true));

    PlayingId pid = sys.play_sound("S", /*looping*/ false, /*gain*/ 1.0f,
                                   Category::SFX,
                                   /*pos_provided*/ true, 4.f, 5.f, 6.f);
    ASSERT_NE(pid, 0u);

    sys.update(0,0,0, 0,1,0, 0,0,1, 0.016f);

    // update() must not emit set_position for anything: the C++ layer no longer
    // owns tracking.
    for (const auto& c : raw->command_log())
        EXPECT_NE(c.op, "set_position");
}
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cmake -B build -S . && cmake --build build -j 2>&1 | tail -20
```

Expected: FAIL to compile — `no matching function for call to 'play_sound'` (the current signature still requires `NodeId`).

- [ ] **Step 3: Write the implementation**

In `native/src/audio/include/audio/audio_system.h`:
- Delete the `using NodeId = uint32_t;` line and the `NodePositionFn` alias + its `#include <functional>`.
- Delete `void set_node_position_fn(NodePositionFn fn)`.
- Delete the `NodePositionFn node_pos_fn_;` member.
- Delete `NodeId node;` from `struct Source`.
- Change the two declarations:

```cpp
    PlayingId play_sound(const std::string& name, bool looping, float gain,
                         Category, bool position_provided, float x, float y, float z);

    PlayingId play(SoundId, bool looping, float gain, Category,
                   bool position_provided, float x, float y, float z);
```

In `native/src/audio/src/audio_system.cc`, update `play` (lines 59-71):

```cpp
PlayingId AudioSystem::play(SoundId id, bool looping, float gain, Category cat,
                            bool pos_provided, float x, float y, float z) {
    auto it = sounds_.find(id);
    if (it == sounds_.end()) return 0;
    bool positional = it->second.positional || pos_provided;
    SourceHandle bh = backend_->play(it->second.buf, looping, gain, cat,
                                     positional, x, y, z);
    if (bh == 0) return 0;
    PlayingId pid = next_playing_id_++;
    sources_[pid] = {bh, looping};
    return pid;
}

PlayingId AudioSystem::play_sound(const std::string& name, bool looping, float gain,
                                  Category cat, bool pos_provided,
                                  float x, float y, float z) {
    SoundId id = get_sound(name);
    return id == 0 ? 0 : play(id, looping, gain, cat, pos_provided, x, y, z);
}
```

And `update` (lines 114-139) — drop the node loop entirely, keep the reap:

```cpp
void AudioSystem::update(float lx, float ly, float lz,
                         float fx, float fy, float fz,
                         float ux, float uy, float uz, float /*dt*/) {
    backend_->set_listener(lx,ly,lz, fx,fy,fz, ux,uy,uz);

    // Reap finished one-shots. Must call backend_->stop() so the underlying
    // ALuint is released — otherwise finished sources accumulate until OpenAL
    // Soft trips its 256-source-per-context limit.
    //
    // Source POSITIONS are pumped from Python (engine/audio/attached_sources.py):
    // the deferred renderer has no scene graph, so Python owns object transforms.
    for (auto it = sources_.begin(); it != sources_.end(); ) {
        if (!it->second.looping && backend_->source_finished(it->second.backend)) {
            backend_->stop(it->second.backend);
            it = sources_.erase(it);
        } else {
            ++it;
        }
    }
}
```

In `native/src/audio/src/python_binding.cc`, drop `attach_node` from `play_impl`'s parameter list, its forwarding call, and the `py::arg("attach_node")` entry in `m.def("play", ...)`:

```cpp
static uint32_t play_impl(const std::string& name, bool looping, float gain,
                          const std::string& category, py::object position) {
    if (!g_system) return 0;
    float x=0,y=0,z=0; bool provided=false;
    if (!position.is_none()) {
        auto t = position.cast<std::tuple<float,float,float>>();
        x = std::get<0>(t); y = std::get<1>(t); z = std::get<2>(t);
        provided = true;
    }
    return g_system->play_sound(name, looping, gain, parse_category(category),
                                provided, x, y, z);
}
```

Finally, in `engine/audio/tg_sound.py`, remove the `attach_node=0` argument Task 2 left behind — the parameter no longer exists:

```python
        pid = _audio.play(
            name=self._name, looping=self._looping, gain=self._gain * factor,
            category=self._category_tag, position=position,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j
ctest --test-dir build -R Audio --output-on-failure
uv run pytest tests/audio/ -v
```

Expected: PASS.

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/include/audio/audio_system.h \
        native/src/audio/src/audio_system.cc \
        native/src/audio/src/python_binding.cc \
        native/tests/audio/audio_system_test.cc \
        engine/audio/tg_sound.py
git commit -m "refactor(audio): remove the dead C++ NodeId tracking path

set_node_position_fn was called only from a unit test, so node_pos_fn_ was
always null and update()'s node loop never moved a source. It assumed a scene
graph the deferred renderer does not have. Python owns transforms; attached_sources
is now the single mechanism.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: The engine hum's `4.375 / 35.0`

Guide §5: the ship engine hum is the **sole** exception to 50/700 — it is the one C++ tuning call site in the original binary. Its max of `35.0` is what makes it a tight near-field sound versus the 700-unit reach of weapons. Ours currently inherits the shared default.

> **Caveat to carry (guide §5):** `4.375` is computed as `35.0 × 0.125` by a routine reachable only through a function pointer, so it could not be statically proven to run. If it doesn't, the hum's min is `0.0`. The **max of 35.0 is certain** and is what matters.

**Files:**
- Modify: `engine/audio/engine_rumble.py`
- Test: `tests/audio/test_engine_rumble.py`

**Interfaces:**
- Consumes: `TGSound.SetMinMaxDistance` (Task 1), `_node_for` (Task 2).
- Produces: `engine_rumble.HUM_MIN_DISTANCE = 4.375`, `engine_rumble.HUM_MAX_DISTANCE = 35.0` — Task 6's allocator imports these.

- [ ] **Step 1: Write the failing test**

Append to `tests/audio/test_engine_rumble.py`:

```python
def test_hum_uses_bc_near_field_distances(boot):
    """Guide §5: the hum is the sole exception to 50/700 — 4.375/35.0.

    The max of 35.0 is the certain half and the one that matters: it makes the
    hum a tight near-field sound instead of reaching 700 units like weapons do.
    """
    from engine.appc import ship_lifecycle
    from engine.audio import engine_rumble
    ship_lifecycle.reset()
    install_engine_rumble_listener()

    _dauntless_host.audio.clear_command_log()
    ship_lifecycle.publish_added(_FakeShip("Federation Engines"))

    mm = [c for c in _dauntless_host.audio.debug_command_log()
          if c["op"] == "set_min_max_distance"]
    assert mm, "hum must push its own min/max, not inherit the 50/700 default"
    assert mm[-1]["f"][0] == 4.375
    assert mm[-1]["f"][1] == 35.0
    assert engine_rumble.HUM_MIN_DISTANCE == 4.375
    assert engine_rumble.HUM_MAX_DISTANCE == 35.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/audio/test_engine_rumble.py::test_hum_uses_bc_near_field_distances -v
```

Expected: FAIL — `AttributeError: module 'engine.audio.engine_rumble' has no attribute 'HUM_MIN_DISTANCE'`.

- [ ] **Step 3: Write minimal implementation**

In `engine/audio/engine_rumble.py`, add module constants below the imports:

```python
# Guide §5: the ship engine hum is the SOLE exception to BC's 50/700 default —
# the one C++ tuning call site in the original binary. The max of 35.0 is what
# makes the hum tight and near-field versus the 700-unit reach of weapons.
#
# Caveat: 4.375 is computed as 35.0 * 0.125 by a routine reachable only through
# a function pointer, so it could not be statically proven to run; if it does
# not, BC's real min is 0.0. The max is certain either way.
HUM_MIN_DISTANCE = 4.375
HUM_MAX_DISTANCE = 35.0
```

And in `_on_ship_event`'s `"added"` branch, set them before `Play` (so the values are live when `Play` pushes min/max):

```python
        snd.SetLooping(1)
        snd.SetSFX()
        snd.SetMinMaxDistance(HUM_MIN_DISTANCE, HUM_MAX_DISTANCE)
        playing = snd.Play(attach_node=_node_for(ship))
```

- [ ] **Step 4: Run test to verify it passes**

```bash
uv run pytest tests/audio/test_engine_rumble.py -v
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add engine/audio/engine_rumble.py tests/audio/test_engine_rumble.py
git commit -m "fix(audio): engine hum gets BC's 4.375/35 near-field distances

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Doppler — velocity, `alDopplerFactor`, `alSpeedOfSound`

Guide §6: doppler is entirely absent. No `AL_VELOCITY` is ever set on listener or source; neither `alDopplerFactor` nor `alSpeedOfSound` is called. `AudioSystem::update` takes `dt` and discards it (`float /*dt*/`).

> **The units trap (Global Constraints, guide §3).** Feed **raw game units**. BC's `unitsPerMeter = 1.0` applies to velocity only and means the engine treats 1 GU as 1 m for doppler. Do **not** convert GU→m. Do **not** port BC's ÷1000 (a Miles m/ms convention). Doppler depends only on `v/c`; replicating the ÷1000 against a 343.3 speed of sound would make doppler ~1000× too weak.

**Files:**
- Modify: `native/src/audio/include/audio/audio_backend.h` (`set_velocity`, `set_listener` signature)
- Modify: `native/src/audio/src/openal_backend.cc`, `null_backend.{h,cc}`
- Modify: `native/src/audio/include/audio/audio_system.h`, `src/audio_system.cc`
- Modify: `native/src/audio/src/python_binding.cc`
- Modify: `engine/audio/tg_sound.py` (`_PlayingSound.SetVelocity`)
- Modify: `engine/audio/attached_sources.py` (`pump` computes velocity)
- Test: `native/tests/audio/audio_system_test.cc`, `tests/audio/test_attached_sources.py`

**Interfaces:**
- Consumes: `attached_sources.pump`, `_Entry.prev_pos` (Task 2).
- Produces:
  - `IAudioBackend::set_velocity(SourceHandle, float, float, float)`
  - `IAudioBackend::set_listener(px,py,pz, fx,fy,fz, ux,uy,uz, vx,vy,vz)` — three velocity args appended.
  - `AudioSystem::update(lx,ly,lz, fx,fy,fz, ux,uy,uz, dt)` — unchanged signature; velocity derived internally from listener position delta.
  - `_dauntless_host.audio.set_velocity(pid, x, y, z)`
  - `_PlayingSound.SetVelocity(x, y, z)`
  - `engine.audio.attached_sources.SPEED_OF_SOUND_GU = 343.3`

- [ ] **Step 1: Write the failing test**

Append to `tests/audio/test_attached_sources.py`:

```python
def test_pump_feeds_source_velocity_from_position_delta(audio):
    """Guide §6: a moving emitter needs AL_VELOCITY or doppler is dead."""
    snd = audio.GetSound("Torp")
    loc = _Loc(0.0, 0.0, 0.0)
    snd.AttachToNode(_FakeNode(loc))
    snd.Play()

    attached_sources.pump(dt=0.5)   # first pump seeds prev_pos
    _dauntless_host.audio.clear_command_log()
    loc.x = 10.0
    attached_sources.pump(dt=0.5)   # 10 GU in 0.5 s -> 20 GU/s

    vels = [c for c in _dauntless_host.audio.debug_command_log()
            if c["op"] == "set_velocity"]
    assert vels, "attached sources must report velocity for doppler"
    assert vels[-1]["f"][0] == pytest.approx(20.0)


def test_first_pump_reports_zero_velocity(audio):
    """No prev_pos yet — must not invent a velocity from a null origin."""
    snd = audio.GetSound("Torp")
    snd.AttachToNode(_FakeNode(_Loc(500.0, 0.0, 0.0)))
    snd.Play()

    _dauntless_host.audio.clear_command_log()
    attached_sources.pump(dt=0.5)

    vels = [c for c in _dauntless_host.audio.debug_command_log()
            if c["op"] == "set_velocity"]
    assert vels, "first pump should still report a (zero) velocity"
    assert vels[-1]["f"][0] == pytest.approx(0.0)


def test_zero_dt_does_not_divide_by_zero(audio):
    snd = audio.GetSound("Torp")
    loc = _Loc(0.0, 0.0, 0.0)
    snd.AttachToNode(_FakeNode(loc))
    snd.Play()
    attached_sources.pump(dt=0.016)
    loc.x = 1.0
    attached_sources.pump(dt=0.0)   # paused frame — must not raise
```

Add to `native/tests/audio/audio_system_test.cc`:

```cpp
TEST(AudioSystem, ListenerVelocityFromPositionDelta) {
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    sys.update(0,0,0,  0,1,0,  0,0,1, 0.5f);    // seeds prev
    raw->clear_command_log();
    sys.update(5,0,0,  0,1,0,  0,0,1, 0.5f);    // 5 GU in 0.5 s -> 10 GU/s

    bool saw = false;
    for (const auto& c : raw->command_log()) {
        if (c.op == "set_listener") {
            EXPECT_FLOAT_EQ(c.f[9], 10.0f);     // vx
            saw = true;
        }
    }
    EXPECT_TRUE(saw);
}
```

> **`LoggedCall::f` is `float f[9]`** (`native/src/audio/include/audio/null_backend.h:12`) — too small for the listener's 3+3+3+3 = 12. Widen it to `float f[12] = {0,0,0,0,0,0,0,0,0,0,0,0};` and extend the binding's tuple in `debug_command_log_impl` (`python_binding.cc`) to match:
>
> ```cpp
>         d["f"] = py::make_tuple(c.f[0], c.f[1], c.f[2], c.f[3],
>                                  c.f[4], c.f[5], c.f[6], c.f[7], c.f[8],
>                                  c.f[9], c.f[10], c.f[11]);
> ```
>
> The accessors are already `command_log()` / `clear_command_log()` — no new ones needed.

- [ ] **Step 2: Run tests to verify they fail**

```bash
uv run pytest tests/audio/test_attached_sources.py -k velocity -v
cmake --build build -j 2>&1 | tail -20
```

Expected: pytest FAILs (`assert [] ` — no `set_velocity` entries); C++ FAILs to compile (`no member named 'clear_log'` / `f[9]` out of bounds).

- [ ] **Step 3: Write the implementation**

Backend interface — in `native/src/audio/include/audio/audio_backend.h`, add to `IAudioBackend`:

```cpp
    virtual void set_velocity(SourceHandle, float x, float y, float z) = 0;
```

and extend `set_listener`:

```cpp
    virtual void set_listener(float px, float py, float pz,
                              float fx, float fy, float fz,
                              float ux, float uy, float uz,
                              float vx, float vy, float vz) = 0;
```

In `native/src/audio/src/openal_backend.cc` — set the doppler globals in `init()`, right after `alDistanceModel` from Task 1:

```cpp
        alDistanceModel(AL_INVERSE_DISTANCE_CLAMPED);
        // Guide §3/§6: BC overrides no DS3D global — doppler and rolloff both
        // stay at 1.0 (the AIL_set_3D_*_factor symbols don't exist in the
        // image). unitsPerMeter defaults to 1.0 and applies to velocity only,
        // so BC treats one game unit as one metre for doppler regardless of
        // visual scale. Feed raw game units; do NOT convert GU->m and do NOT
        // port BC's velocity /1000 (a Miles m/ms API convention).
        alDopplerFactor(1.0f);
        alSpeedOfSound(343.3f);
        return true;
```

Add the source velocity setter alongside `set_position`:

```cpp
    void set_velocity(SourceHandle h, float x, float y, float z) override {
        if (auto it = sources_.find(h); it != sources_.end())
            alSource3f(it->second.al, AL_VELOCITY, x, y, z);
    }
```

And extend `set_listener`:

```cpp
    void set_listener(float px, float py, float pz,
                      float fx, float fy, float fz,
                      float ux, float uy, float uz,
                      float vx, float vy, float vz) override {
        alListener3f(AL_POSITION, px, py, pz);
        alListener3f(AL_VELOCITY, vx, vy, vz);
        float ori[6] = {fx, fy, fz, ux, uy, uz};
        alListenerfv(AL_ORIENTATION, ori);
    }
```

Mirror both in `null_backend.{h,cc}` with `LoggedCall` entries (`set_velocity` → `c.u[0]=h; c.f[0..2]=x,y,z`; `set_listener` → `c.f[0..11]`).

In `native/src/audio/include/audio/audio_system.h`, add the listener-velocity state:

```cpp
    bool  have_prev_listener_ = false;
    float prev_listener_[3] = {0.f, 0.f, 0.f};
```

In `native/src/audio/src/audio_system.cc`, use `dt` in `update` (it is currently discarded):

```cpp
void AudioSystem::update(float lx, float ly, float lz,
                         float fx, float fy, float fz,
                         float ux, float uy, float uz, float dt) {
    // Guide §4/§6: listener velocity for doppler, derived from the camera's
    // position delta. Raw game units per second — see the units note in init().
    float vx = 0.f, vy = 0.f, vz = 0.f;
    if (have_prev_listener_ && dt > 0.f) {
        vx = (lx - prev_listener_[0]) / dt;
        vy = (ly - prev_listener_[1]) / dt;
        vz = (lz - prev_listener_[2]) / dt;
    }
    prev_listener_[0] = lx; prev_listener_[1] = ly; prev_listener_[2] = lz;
    have_prev_listener_ = true;

    backend_->set_listener(lx,ly,lz, fx,fy,fz, ux,uy,uz, vx,vy,vz);
    // ... reap loop unchanged ...
}
```

In `python_binding.cc`, add:

```cpp
static void set_velocity_impl(PlayingId pid, float x, float y, float z) {
    if (g_system) g_system->set_velocity(pid, x, y, z);
}
// ...
    m.def("set_velocity", &set_velocity_impl);
```

with the matching `AudioSystem::set_velocity(PlayingId, float, float, float)` forwarding to the backend, exactly like `set_position`.

In `engine/audio/tg_sound.py`, add to `_PlayingSound`:

```python
    def SetVelocity(self, x: float, y: float, z: float) -> None:
        if _audio and self._pid:
            _audio.set_velocity(self._pid, x, y, z)
```

In `engine/audio/attached_sources.py`, add the constant and compute velocity in `pump`:

```python
# Guide §3: BC's unitsPerMeter = 1.0 means the engine treats one game unit as
# one metre for doppler, regardless of the visual scale of the models (our GU is
# actually 175 m — see engine/units.py). Reproducing BC faithfully means adopting
# its convention rather than "correcting" it: raw GU in, 343.3 GU/s for c.
# alDopplerFactor stays the tuning knob if we ever want to.
SPEED_OF_SOUND_GU = 343.3
```

```python
def pump(dt: float) -> None:
    """Copy every attached node's world position and velocity into its source.

    Velocity is the per-frame position delta (guide §4/§6), in raw game units
    per second. Called once per tick from host_loop.tick_audio, before the
    listener update so the positional math sees current source positions.
    """
    for pid, entry in list(_attached.items()):
        if not entry.handle._pid:          # explicitly stopped
            del _attached[pid]
            continue
        pos = node_world_position(entry.node)
        if pos is None:                    # owner GC'd or unresolvable
            del _attached[pid]
            continue
        entry.handle.SetPosition(*pos)
        if entry.prev_pos is not None and dt > 0.0:
            vx = (pos[0] - entry.prev_pos[0]) / dt
            vy = (pos[1] - entry.prev_pos[1]) / dt
            vz = (pos[2] - entry.prev_pos[2]) / dt
        else:
            vx = vy = vz = 0.0
        entry.handle.SetVelocity(vx, vy, vz)
        entry.prev_pos = pos
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j
ctest --test-dir build -R Audio --output-on-failure
uv run pytest tests/audio/ -v
```

Expected: PASS.

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/ engine/audio/tg_sound.py engine/audio/attached_sources.py \
        tests/audio/test_attached_sources.py native/tests/audio/audio_system_test.cc
git commit -m "feat(audio): doppler — listener + source velocity, DS3D defaults

No AL_VELOCITY was ever set and update() discarded dt, so doppler did not exist.
Feed raw game units against alSpeedOfSound(343.3): BC's unitsPerMeter=1.0 treats
1 GU as 1 m for doppler, and its /1000 is a Miles m/ms convention we must not port.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: The nearest-≤4 engine-hum allocator

Guide §10 — "BC's most distinctive positional behaviour". Ours plays a hum for **every** ship with an impulse engine, unbounded: no distance sort, no cap. The subsystem gate itself is already right (`GetImpulseEngineSubsystem` matches BC's `ship+0x2CC != 0`).

**Files:**
- Create: `engine/audio/hum_allocator.py`
- Create: `tests/audio/test_hum_allocator.py`
- Modify: `engine/audio/engine_rumble.py` (hand lifetime to the allocator)
- Modify: `engine/host_loop.py` (`tick_audio` calls the allocator)

**Interfaces:**
- Consumes: `engine_rumble.HUM_MIN_DISTANCE` / `HUM_MAX_DISTANCE` (Task 4), `_engine_sound_name_for`, `_node_for` (Task 2), `attached_sources.attach` (Task 2), `engine.appc.ship_iter.iter_active_ships`.
- Produces: `engine.audio.hum_allocator.MAX_HUMMING_SHIPS = 4`, `update(listener_pos: tuple[float,float,float]) -> None`, `reset_for_tests() -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_hum_allocator.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import hum_allocator
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


class _Loc:
    def __init__(self, x, y, z): self.x, self.y, self.z = x, y, z


class _Prop:
    def GetEngineSound(self): return "Federation Engines"


class _Sub:
    def GetProperty(self): return _Prop()


class _Ship:
    def __init__(self, name, x):
        self._name, self._loc = name, _Loc(float(x), 0.0, 0.0)
    def GetName(self): return self._name
    def GetImpulseEngineSubsystem(self): return _Sub()
    def GetWorldLocation(self): return self._loc
    def GetNode(self): return self


class _NoEngine(_Ship):
    def GetImpulseEngineSubsystem(self): return None


@pytest.fixture
def boot(tmp_path, monkeypatch):
    hum_allocator.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "e.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "Federation Engines", TGSound.LS_3D)
    yield
    shutdown_audio_for_tests()
    hum_allocator.reset_for_tests()


def _stub_roster(monkeypatch, ships):
    monkeypatch.setattr(hum_allocator, "_roster", lambda: list(ships))


def test_caps_at_four_nearest_ships(boot, monkeypatch):
    """Guide §10: cap of 4 is deliberate voice economy — keep it."""
    ships = [_Ship(f"s{i}", x=i * 10) for i in range(7)]
    _stub_roster(monkeypatch, ships)

    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    humming = hum_allocator.humming_ship_names()
    assert len(humming) == 4
    assert humming == {"s0", "s1", "s2", "s3"}   # the four nearest


def test_ship_falling_out_of_top4_stops_humming(boot, monkeypatch):
    near = [_Ship(f"s{i}", x=i * 10) for i in range(4)]
    far = _Ship("far", x=500)
    _stub_roster(monkeypatch, near + [far])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert "far" not in hum_allocator.humming_ship_names()

    # Listener travels out to the far ship; s3 (x=30) is now the odd one out.
    hum_allocator.update(listener_pos=(500.0, 0.0, 0.0))
    humming = hum_allocator.humming_ship_names()
    assert "far" in humming
    assert "s0" not in humming
    assert len(humming) == 4


def test_ships_without_an_impulse_engine_never_hum(boot, monkeypatch):
    """BC's gate: ShipClass with ship+0x2CC != 0 (the ImpulseEngine subsystem)."""
    _stub_roster(monkeypatch, [_NoEngine("rock", x=1), _Ship("ship", x=2)])
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    assert hum_allocator.humming_ship_names() == {"ship"}


def test_update_is_idempotent_for_a_stable_roster(boot, monkeypatch):
    """A ship already in the top-4 must not be restarted every frame."""
    ships = [_Ship(f"s{i}", x=i * 10) for i in range(3)]
    _stub_roster(monkeypatch, ships)
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))

    _dauntless_host.audio.clear_command_log()
    hum_allocator.update(listener_pos=(0.0, 0.0, 0.0))
    plays = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "play"]
    assert not plays, "a stable top-4 must not re-trigger play()"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/audio/test_hum_allocator.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.audio.hum_allocator'`.

- [ ] **Step 3: Write the implementation**

Create `engine/audio/hum_allocator.py`:

```python
"""Nearest-≤4 engine-hum allocator (guide §10).

BC's most distinctive positional behaviour. Each frame, in the active space set:
take the listener position, gather ships that have an impulse-engine subsystem
(BC's gate is `ship+0x2CC != 0` — that field IS the ImpulseEngine subsystem, and
the hum is its sound), sort by distance, keep the nearest 4, and reconcile:
stop the hum on any ship that fell out, start one for any ship that entered.

The cap of 4 is deliberate voice economy from the original — keeping it is what
makes our ambient density match BC's.

The hum's sound NAME comes from the engine subsystem's property; the name carries
no distances and no gain, so the caller supplies BC's 4.375/35.0 (see engine_rumble).
"""
from __future__ import annotations

import weakref

from engine.audio import attached_sources
from engine.audio.engine_rumble import (
    HUM_MAX_DISTANCE, HUM_MIN_DISTANCE, _engine_sound_name_for, _node_for,
)
from engine.audio.tg_sound import TGSoundManager

# Guide §10: BC's cap. Tunable, but default 4 so the mix density matches.
MAX_HUMMING_SHIPS = 4

# ship -> _PlayingSound. Weak so a ship GC'd without an explicit teardown
# drops out rather than humming until shutdown.
_humming: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def _roster():
    """Ships in the ACTIVE (rendered) set. Seam for tests."""
    from engine.appc.ship_iter import iter_active_ships
    return list(iter_active_ships())


def _distance_sq(ship, listener_pos) -> float:
    loc = attached_sources.node_world_position(ship)
    if loc is None:
        return float("inf")
    dx = loc[0] - listener_pos[0]
    dy = loc[1] - listener_pos[1]
    dz = loc[2] - listener_pos[2]
    return dx * dx + dy * dy + dz * dz


def _start_hum(ship) -> None:
    name = _engine_sound_name_for(ship)
    if not name:
        return
    snd = TGSoundManager.instance().GetSound(name)
    if snd is None:
        return
    snd.SetLooping(1)
    snd.SetSFX()
    snd.SetMinMaxDistance(HUM_MIN_DISTANCE, HUM_MAX_DISTANCE)
    playing = snd.Play(attach_node=_node_for(ship))
    if playing is not None:
        _humming[ship] = playing


def _stop_hum(ship) -> None:
    playing = _humming.pop(ship, None)
    if playing is not None:
        playing.Stop()


def update(listener_pos) -> None:
    """Reconcile the humming set against the nearest MAX_HUMMING_SHIPS."""
    candidates = [s for s in _roster() if _engine_sound_name_for(s)]
    candidates.sort(key=lambda s: _distance_sq(s, listener_pos))
    winners = candidates[:MAX_HUMMING_SHIPS]
    winner_ids = {id(s) for s in winners}

    for ship in [s for s in _humming.keys() if id(s) not in winner_ids]:
        _stop_hum(ship)
    for ship in winners:
        if ship not in _humming:
            _start_hum(ship)


def humming_ship_names() -> set:
    return {s.GetName() for s in _humming.keys()}


def reset_for_tests() -> None:
    for ship in list(_humming.keys()):
        _stop_hum(ship)
    _humming.clear()
```

In `engine/audio/engine_rumble.py`, the allocator now owns hum lifetime, so the lifecycle listener must stop starting hums itself. Replace `_on_ship_event` with a teardown-only handler:

```python
def _on_ship_event(event: str, ship) -> None:
    """Hum START/STOP is the allocator's job (guide §10 — nearest-≤4).

    This listener only handles teardown, so a destroyed ship's hum stops on the
    frame it dies rather than waiting for the next allocator reconcile.
    """
    if event == "destroyed":
        from engine.audio import hum_allocator
        hum_allocator._stop_hum(ship)
```

and drop the `snapshot()` replay from `install_engine_rumble_listener` (the allocator picks up live ships on its first `update`), leaving:

```python
def install_engine_rumble_listener() -> None:
    """Idempotent install — safe to call from host_loop boot."""
    global _installed, _unsubscribe
    if _installed:
        return
    _unsubscribe = ship_lifecycle.subscribe(_on_ship_event)
    _installed = True
```

Keep `set_muted` working against the allocator's dict — change its iteration source:

```python
def set_muted(muted: bool) -> None:
    """Mute (gain 0) or unmute (gain 1) every humming source.

    Used by the bridge-view mode: from inside the bridge, the player wouldn't
    hear their own engine humming directly.
    """
    global _muted
    if _muted == muted:
        return
    _muted = muted
    from engine.audio import hum_allocator
    gain = 0.0 if muted else 1.0
    for playing in list(hum_allocator._humming.values()):
        if playing is not None:
            playing.SetGain(gain)
```

In `engine/host_loop.py`, drive the allocator from `tick_audio`:

```python
def tick_audio(*, camera_position, camera_forward, camera_up, dt, player) -> None:
    if _audio_mod is None:
        return
    from engine.audio import attached_sources, hum_allocator
    # Guide §9, in order: (1) attached emitters from their nodes,
    # (2) the nearest-≤4 hum allocator, (3) the listener from the active camera.
    attached_sources.pump(dt)
    hum_allocator.update(listener_pos=camera_position)
    px, py, pz = camera_position
    fx, fy, fz = camera_forward
    ux, uy, uz = camera_up
    _audio_mod.update(px, py, pz, fx, fy, fz, ux, uy, uz, dt)
    _alert_listener.tick(player)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/audio/ -v
```

Expected: PASS. `tests/audio/test_engine_rumble.py`'s start-on-`publish_added` tests will now fail — the allocator owns starting. **Rewrite those tests against `hum_allocator.update`** rather than deleting them; keep the `destroyed`-stops-hum test against the listener.

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add engine/audio/hum_allocator.py engine/audio/engine_rumble.py \
        engine/host_loop.py tests/audio/test_hum_allocator.py \
        tests/audio/test_engine_rumble.py
git commit -m "feat(audio): nearest-<=4 engine-hum allocator (guide §10)

We hummed for every ship with an impulse engine, unbounded. BC caps at the
4 nearest to the listener and reconciles each frame — deliberate voice economy
and the thing that makes ambient density match the original.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Voice priority + eviction

Guide §8: `TGSound.SetPriority` stores `_priority` that **nothing reads**, so `LoadBridge.py:216`'s `SetPriority(1.0)` writes into a void. BC's shipped values are `0.9` local player, `0.6` remote phaser, `0.5` remote pulse+tractor, with co-fired voices (phaser Start + Loop) taking `priority − 0.01`.

> **Footgun #7 — these are a RANK, not a volume.** Wire them to the eviction comparator, never to `AL_GAIN`; mapping them to gain would make every remote phaser 33% quieter than the original and leave priority flat.
>
> **Honest caveat (guide §8):** BC's *consumer* of this field has not been identified, so "lowest priority is evicted first" is the natural reading but is **not verified**, and the purpose of the `−0.01` is unknown. OpenAL Soft mixes 256 sources in software, so eviction rarely fires and this is low-risk either way. Implement the obvious comparator and move on — do not over-invest here.

**Files:**
- Modify: `native/src/audio/include/audio/audio_backend.h`, `openal_backend.cc`, `null_backend.{h,cc}`
- Modify: `native/src/audio/include/audio/audio_system.h`, `src/audio_system.cc`
- Modify: `native/src/audio/src/python_binding.cc`
- Modify: `engine/audio/tg_sound.py`
- Modify: `engine/appc/weapon_subsystems.py` (the 0.9/0.6/0.5 + −0.01 call site)
- Create: `tests/audio/test_voice_priority.py`

**Interfaces:**
- Consumes: `TGSound.BC_DEFAULT_PRIORITY` (Task 1).
- Produces:
  - `IAudioBackend::play(..., float priority)` — appended parameter.
  - `AudioSystem` evicts the lowest-priority playing source when the pool is full.
  - `_dauntless_host.audio.play(..., priority=0.5)`.
  - `engine.appc.weapon_subsystems.LOCAL_FIRE_PRIORITY = 0.9`, `REMOTE_PHASER_PRIORITY = 0.6`, `REMOTE_PULSE_PRIORITY = 0.5`, `CO_FIRED_PRIORITY_STEP = 0.01`.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_voice_priority.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path):
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "P", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()


def test_priority_reaches_the_backend_and_not_the_gain(audio):
    """Guide §8/footgun #7: 0.9/0.6/0.5 are a voice-stealing RANK.

    Mapping them to AL_GAIN would make every remote phaser 33% quieter than the
    original and leave priority flat.
    """
    snd = audio.GetSound("P")
    snd.SetPriority(0.6)
    snd.SetVolume(1.0)

    _dauntless_host.audio.clear_command_log()
    snd.Play()

    plays = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "play"]
    assert len(plays) == 1
    assert plays[0]["f"][0] == 1.0, "gain must be untouched by priority"
    assert plays[0]["f"][4] == pytest.approx(0.6), "priority must reach the backend"


def test_weapon_fire_priorities_match_bc():
    from engine.appc import weapon_subsystems as ws
    assert ws.LOCAL_FIRE_PRIORITY == 0.9
    assert ws.REMOTE_PHASER_PRIORITY == 0.6
    assert ws.REMOTE_PULSE_PRIORITY == 0.5
    assert ws.CO_FIRED_PRIORITY_STEP == 0.01
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/audio/test_voice_priority.py -v
```

Expected: FAIL — `IndexError`/`KeyError` on `plays[0]["f"][4]` (no priority slot), and `AttributeError: ... has no attribute 'LOCAL_FIRE_PRIORITY'`.

- [ ] **Step 3: Write the implementation**

Append `float priority` to `IAudioBackend::play` and both implementations. In `openal_backend.cc`, store it on the `Source` struct (`struct Source { ALuint al; Category cat; float user_gain; float priority; };`) — **do not touch `AL_GAIN` with it**.

In `null_backend.cc`'s `play`, log it as `c.f[4] = priority;` (widen `LoggedCall::f` if Task 5 has not already).

In `AudioSystem::play`, forward the priority and evict when the pool is full:

```cpp
// Guide §8: lowest-priority playing source loses. BC's consumer of this field
// was never identified, so this is the natural reading, not a verified one —
// and OpenAL Soft mixes 256 sources in software, so it rarely fires.
static constexpr size_t kMaxSoundsAtOnce = 128;
```

```cpp
    if (sources_.size() >= kMaxSoundsAtOnce) {
        auto victim = sources_.end();
        for (auto it = sources_.begin(); it != sources_.end(); ++it)
            if (victim == sources_.end() || it->second.priority < victim->second.priority)
                victim = it;
        if (victim != sources_.end() && victim->second.priority < priority) {
            backend_->stop(victim->second.backend);
            sources_.erase(victim);
        } else {
            return 0;   // nothing lower-ranked to steal; drop this one
        }
    }
```

Add `float priority;` to `AudioSystem::Source` and store it. Thread `priority` through `python_binding.cc`'s `play_impl` with `py::arg("priority") = 0.5f`.

In `engine/audio/tg_sound.py`, pass it through in `Play`:

```python
        pid = _audio.play(
            name=self._name, looping=self._looping, gain=self._gain * factor,
            category=self._category_tag, position=position,
            priority=self._priority,
        )
```

In `engine/appc/weapon_subsystems.py`, add the constants near the top:

```python
# Guide §8: BC's shipped voice priorities (TGSound+0x68) — a voice-stealing
# RANK, never a gain. 0.9 when the firing ship is the local player's; remote is
# per-weapon. Co-fired voices (phaser Start + Loop) take the second at
# priority - 0.01; the purpose of that step is unknown, and BC's consumer of the
# field was never identified, so treat all of this as best-reading, not gospel.
LOCAL_FIRE_PRIORITY = 0.9
REMOTE_PHASER_PRIORITY = 0.6
REMOTE_PULSE_PRIORITY = 0.5
CO_FIRED_PRIORITY_STEP = 0.01
```

and apply them in the fire-sound path (the `start_snd` / `loop_snd` block at lines 505-518):

```python
        priority = (LOCAL_FIRE_PRIORITY if self._is_local_player_ship()
                    else self._remote_fire_priority())
        if start_snd is not None:
            start_snd.SetPriority(priority)
            start_snd.Play(attach_node=attach_node)

        loop_snd = mgr.GetSound(name + " Loop")
        if loop_snd is not None:
            loop_snd.SetLooping(True)
            loop_snd.SetPriority(priority - CO_FIRED_PRIORITY_STEP)
            self._loop_handle = loop_snd.Play(attach_node=attach_node)
```

The fire-sound path lives in `_EnergyWeaponFireMixin` (`engine/appc/weapon_subsystems.py:365`), which is mixed into `PhaserBank` (:1721) and `PulseWeapon` (:1773). The mixin is *defined before* both subclasses, so discriminate with a class attribute rather than an `isinstance` that would need a late import.

On `_EnergyWeaponFireMixin`, add the default (pulse + tractor) and the two helpers:

```python
class _EnergyWeaponFireMixin:
    # Remote-fire voice priority. Default covers pulse + tractor (0.5);
    # PhaserBank overrides to 0.6. See the guide §8 constants above.
    REMOTE_FIRE_PRIORITY = REMOTE_PULSE_PRIORITY

    def _remote_fire_priority(self) -> float:
        return self.REMOTE_FIRE_PRIORITY

    def _is_local_player_ship(self) -> bool:
        """True when the firing ship is the local player's (guide §8: 0.9).

        Same reach-for-the-player pattern as engine/appc/hit_feedback.py:246 —
        do not invent a second one.
        """
        parent_sys = self.GetParentSubsystem() if hasattr(self, "GetParentSubsystem") else None
        ship = parent_sys.GetParentShip() if parent_sys is not None and hasattr(parent_sys, "GetParentShip") else None
        if ship is None:
            return False
        try:
            import App
            game = App.Game_GetCurrentGame() if hasattr(App, "Game_GetCurrentGame") else None
            player = game.GetPlayer() if game is not None and hasattr(game, "GetPlayer") else None
        except Exception:
            return False
        return player is not None and ship is player
```

And on `PhaserBank` (:1721), override the one differing value:

```python
class PhaserBank(_EnergyWeaponFireMixin, WeaponSystem):
    REMOTE_FIRE_PRIORITY = REMOTE_PHASER_PRIORITY   # 0.6; pulse/tractor stay 0.5
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j
uv run pytest tests/audio/ tests/unit/test_phaser_fire_sfx_attach.py -v
ctest --test-dir build -R Audio --output-on-failure
```

Expected: PASS.

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/ engine/audio/tg_sound.py engine/appc/weapon_subsystems.py \
        tests/audio/test_voice_priority.py
git commit -m "feat(audio): wire voice priority to eviction (guide §8)

SetPriority stored a field nothing read. BC's 0.9/0.6/0.5 are a voice-stealing
rank, not a gain — routing them to AL_GAIN would make every remote phaser 33%
quieter. Lowest-rank-loses is the natural reading, not a verified one; BC's
consumer of the field was never identified.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 8: The one-active-scene rule (space side)

Guide §11: only the rendered set is audible. On a set/view change, stop every source belonging to the now-inactive set. This is what makes the bridge↔space switch silence the other world, and why the viewscreen (space rendered *visually* on the bridge) carries no audio — the space set isn't the active sound scene.

We have no set-ownership tracking at all. `engine_rumble.set_muted()` is a targeted hack covering only the hum.

**Files:**
- Modify: `engine/audio/tg_sound.py` (`_PlayingSound` gains an owning-set tag)
- Modify: `engine/audio/attached_sources.py` (or a new `scene_scope` seam — see below)
- Create: `tests/audio/test_scene_scope.py`
- Modify: `engine/host_loop.py`

**Interfaces:**
- Consumes: `attached_sources` (Task 2), `engine.appc.ship_iter.active_set`.
- Produces: `engine.audio.scene_scope.set_rendered_set(name: str | None) -> None`, `scene_scope.register(handle, set_name) -> None`, `scene_scope.reset_for_tests() -> None`.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_scene_scope.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio import scene_scope
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav():
    data = struct.pack("<h", 0) * 8
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path):
    scene_scope.reset_for_tests()
    init_audio_for_tests()
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "SpaceSfx", TGSound.LS_3D)
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()
    scene_scope.reset_for_tests()


def test_switching_rendered_set_stops_the_old_scene(audio):
    """Guide §11: only the rendered set is audible."""
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play()
    scene_scope.register(handle, "space")

    _dauntless_host.audio.clear_command_log()
    scene_scope.set_rendered_set("bridge")

    stops = [c for c in _dauntless_host.audio.debug_command_log()
             if c["op"] == "stop"]
    assert stops, "leaving the space set must stop its sources"
    assert not handle._pid


def test_sources_in_the_rendered_set_survive(audio):
    scene_scope.set_rendered_set("space")
    snd = audio.GetSound("SpaceSfx")
    snd.SetLooping(True)
    handle = snd.Play()
    scene_scope.register(handle, "space")

    scene_scope.set_rendered_set("space")   # no change
    assert handle._pid


def test_same_set_twice_is_a_noop(audio):
    scene_scope.set_rendered_set("space")
    _dauntless_host.audio.clear_command_log()
    scene_scope.set_rendered_set("space")
    assert not [c for c in _dauntless_host.audio.debug_command_log()
                if c["op"] == "stop"]
```

- [ ] **Step 2: Run test to verify it fails**

```bash
uv run pytest tests/audio/test_scene_scope.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'engine.audio.scene_scope'`.

- [ ] **Step 3: Write the implementation**

Create `engine/audio/scene_scope.py`:

```python
"""The one-active-scene rule (guide §11).

Only the rendered set is audible. On a set/view change every source belonging
to the now-inactive set stops (BC flushes handles in UpdateSounds). This is what
makes the bridge↔space switch silence the other world, and why the viewscreen —
space rendered *visually* on the bridge — carries no audio: the space set is not
the active sound scene.

Scope note: this covers the space side. 2D bridge/UI/music sources are not
registered here and are unaffected.
"""
from __future__ import annotations

from typing import Optional

_rendered: Optional[str] = None
# set name -> list of _PlayingSound
_by_set: dict[str, list] = {}


def set_rendered_set(name: Optional[str]) -> None:
    """Make `name` the active sound scene, stopping every other set's sources."""
    global _rendered
    if name == _rendered:
        return
    _rendered = name
    for set_name, handles in list(_by_set.items()):
        if set_name == name:
            continue
        for h in handles:
            if h._pid:
                h.Stop()
        _by_set[set_name] = []


def register(handle, set_name: str) -> None:
    """Tag `handle` as belonging to `set_name`, so a scene change stops it."""
    if handle is None or not handle._pid or not set_name:
        return
    live = [h for h in _by_set.setdefault(set_name, []) if h._pid]
    live.append(handle)
    _by_set[set_name] = live


def rendered_set() -> Optional[str]:
    return _rendered


def reset_for_tests() -> None:
    global _rendered
    _rendered = None
    _by_set.clear()
```

Auto-register in `TGSound.Play` so callers do not have to remember. Add after the `attached_sources.attach` block:

```python
        from engine.audio import scene_scope
        if scene_scope.rendered_set() is not None and (
                self._positional or self._node is not None or position is not None):
            scene_scope.register(handle, scene_scope.rendered_set())
```

Drive it from `engine/host_loop.py`'s `tick_audio`, before the pump:

```python
    from engine.audio import attached_sources, hum_allocator, scene_scope
    from engine.appc.ship_iter import active_set
    act = active_set()
    scene_scope.set_rendered_set(act.GetName() if act is not None else None)
    attached_sources.pump(dt)
    hum_allocator.update(listener_pos=camera_position)
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
uv run pytest tests/audio/ -v
```

Expected: PASS.

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add engine/audio/scene_scope.py engine/audio/tg_sound.py engine/host_loop.py \
        tests/audio/test_scene_scope.py
git commit -m "feat(audio): one-active-scene rule for the space set (guide §11)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 9: Frame batching + the mono-for-3D guard

Guide §9: batch the per-frame update so OpenAL applies it atomically (the analog of DS3D's deferred commit). Guide §14.5: OpenAL only spatialises **mono** buffers — a stereo buffer plays 2D regardless of position, silently. Nothing in `pick_format` guards this today.

**Files:**
- Modify: `native/src/audio/include/audio/audio_backend.h` (`begin_frame`/`end_frame`)
- Modify: `native/src/audio/src/openal_backend.cc`, `null_backend.{h,cc}`
- Modify: `native/src/audio/src/audio_system.cc` (`update` wraps its body)
- Test: `native/tests/audio/audio_system_test.cc`

**Interfaces:**
- Consumes: `AudioSystem::update` (Task 5).
- Produces: `IAudioBackend::begin_frame()` / `end_frame()`.

- [ ] **Step 1: Write the failing test**

Add to `native/tests/audio/audio_system_test.cc`:

```cpp
TEST(AudioSystem, UpdateIsBatched) {
    // Guide §9/§14.12: batch with alcSuspendContext/alcProcessContext so a
    // frame's listener + emitter moves apply atomically.
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    NullBackend* raw = backend.get();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());
    raw->clear_command_log();

    sys.update(0,0,0, 0,1,0, 0,0,1, 0.016f);

    ASSERT_GE(raw->command_log().size(), 2u);
    EXPECT_EQ(raw->command_log().front().op, "begin_frame");
    EXPECT_EQ(raw->command_log().back().op,  "end_frame");
}

TEST(AudioSystem, StereoBufferCannotBePositional) {
    // Guide §14.5: OpenAL only spatialises mono. A stereo 3D sfx would play
    // unspatialised with no error — reject it loudly at load instead.
    using namespace dauntless::audio;
    auto backend = std::make_unique<NullBackend>();
    AudioSystem sys(std::move(backend));
    ASSERT_TRUE(sys.init());

    auto wav = tiny_stereo_wav();
    EXPECT_FALSE(sys.load_sound("sfx/s.wav", "Stereo3D",
                                wav.data(), wav.size(), /*positional*/ true));
    EXPECT_TRUE(sys.load_sound("sfx/s.wav", "Stereo2D",
                               wav.data(), wav.size(), /*positional*/ false));
}
```

Add a `tiny_stereo_wav()` helper next to `tiny_wav()`, identical but with `p16(2)` for channels and `p32(88200)` byte-rate / `p16(4)` block-align.

- [ ] **Step 2: Run tests to verify they fail**

```bash
cmake -B build -S . && cmake --build build -j 2>&1 | tail -20
```

Expected: FAIL to compile — `no member named 'begin_frame'`.

- [ ] **Step 3: Write the implementation**

Add to `IAudioBackend`:

```cpp
    virtual void begin_frame() = 0;
    virtual void end_frame() = 0;
```

In `openal_backend.cc`:

```cpp
    // Guide §9: the analog of DS3D's deferred commit — a frame's listener and
    // emitter moves apply atomically instead of tearing mid-frame.
    void begin_frame() override { if (context_) alcSuspendContext(context_); }
    void end_frame()   override { if (context_) alcProcessContext(context_); }
```

In `null_backend.cc`, log both. In `AudioSystem::update`, wrap the body:

```cpp
    backend_->begin_frame();
    // ... listener + reap ...
    backend_->end_frame();
```

Guard mono-for-3D in `AudioSystem::load_sound`, after the decode succeeds and before `create_buffer`:

```cpp
    // Guide §14.5: OpenAL only spatialises mono buffers — a stereo buffer plays
    // 2D regardless of position, with no error. All BC 3D sfx are mono; a stereo
    // one is an asset bug, so fail loudly rather than silently de-spatialising.
    if (positional && wav.channels != 1) {
        std::fprintf(stderr,
                     "[audio] '%s' is %u-channel but was loaded LS_3D; "
                     "OpenAL only spatialises mono. Refusing.\n",
                     name.c_str(), static_cast<unsigned>(wav.channels));
        return false;
    }
```

(add `#include <cstdio>` to `audio_system.cc`).

- [ ] **Step 4: Run tests to verify they pass**

```bash
cmake -B build -S . && cmake --build build -j
ctest --test-dir build -R Audio --output-on-failure
uv run pytest tests/audio/ -v
```

Expected: PASS.

> If a real BC asset now fails to load as `LS_3D` because it is stereo, **that is a live finding, not a test problem** — report it rather than loosening the guard.

- [ ] **Step 5: Run the full gate**

```bash
scripts/check_tests.sh
```

Expected: exit 0.

- [ ] **Step 6: Commit**

```bash
git add native/src/audio/ native/tests/audio/audio_system_test.cc
git commit -m "feat(audio): batch the frame; reject stereo 3D buffers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 10: Live verification

**Green tests cannot hear anything.** Every task above ends green, and the whole point of Task 2 is that a green suite hid a total failure for months because the tests mocked a method that did not exist. This task is not optional and cannot be satisfied by running pytest.

**Files:** none — this is an observation task.

- [ ] **Step 1: Build and launch**

```bash
cmake -B build -S . && cmake --build build -j
./build/dauntless --developer
```

- [ ] **Step 2: Observe each fix in the real game**

Load a Quick Battle with several ships and confirm, by ear:

1. **Attenuation floor (Task 1).** Fly away from a capital ship. Its hum/weapons should **fade to a faint floor and hold**, never to silence. Previously they faded to nothing.
2. **Node attachment (Task 2).** Fire a torpedo and follow it. The launch sound should **travel with the torpedo**, not stay at the firing point. Fire a phaser — the sound should sit on the firing ship and move with it.
3. **Hum near-field (Task 4).** The engine hum should be audible only close in (max 35 GU) and drop off far faster than weapons fire (700 GU).
4. **Doppler (Task 5).** Have a ship pass close at speed. Expect a **subtle** pitch shift — BC's own numbers make this small (~2% at 6 GU/s), so do not expect a dramatic sweep. Absence of *any* shift is the failure signal.
5. **Hum allocator (Task 6).** With 6+ ships nearby, at most 4 should hum. Fly between clusters and confirm hums hand off.
6. **Scene rule (Task 8).** Switch to the bridge. Space audio should **cut**. The viewscreen shows space but must carry no audio.

- [ ] **Step 3: Report findings to Mark before claiming completion**

Report what you actually heard, per item, including anything that did **not** behave as expected. Do not claim the plan is complete on green tests alone.

---

## Deferred (explicitly out of scope)

Recorded so they are not silently lost:

- **Streaming (guide §12)** — `LS_STREAMED` is accepted and ignored; the backend decodes whole files up front. Bridge dialogue and music.
- **Category buses → config sliders** — `set_category_gain` is plumbed from `python_binding.cc:138` all the way to the backend with **zero Python callers**. No volume sliders reach it.
- **Cones (guide §7)** — `TGSound.SetOrientation` is a no-op. BC's defaults are 360°/360° (disabled), so this only matters if an asset explicitly sets a cone.
- **EFX reverb + `TGSoundRegion` filters (guide §11)** — out of scope by the guide's own framing; `TGSoundRegion` already approximates FT_MUFFLE with a gain cut.
- **`engine/audio/tg_sound.py` imports `_dauntless_host` directly** (line 14), bypassing the `host_io` façade the project standardises on. Pre-existing; not churned here.
