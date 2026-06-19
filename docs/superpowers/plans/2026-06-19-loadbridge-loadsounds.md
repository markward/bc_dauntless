# LoadBridge.LoadSounds() Wiring — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make BC's SDK-registered bridge sounds (`ViewOn`/`ViewOff`/`ConsoleExplosion1-8`/`InSystemWarp`/alerts/`AmbBridge`) audible by running the genuine `LoadBridge.LoadSounds()` against a real Appc sound surface, replacing the `register_default_sounds()` stand-in.

**Architecture:** Implement the missing Appc sound surface (`TGSoundRegion` + region registry, `Game.LoadSoundInGroup`, sound groups, stateful `TGSound.Play/Stop`) as headless Python shims over the existing `_dauntless_host.audio` backend. Move the audio-backend init ahead of mission load so the SDK's natural `LoadBridge.Load → LoadSounds()` call site loads into a live backend. Suppress the SDK's load-time `AmbBridge` play in the space scene via a now-functional `TGSound.Stop()`.

**Tech Stack:** Python 3.13 shims (`engine/audio/tg_sound.py`, `engine/core/game.py`, `App.py`, `engine/host_loop.py`, `engine/audio/bridge_ambient.py`); `_dauntless_host.audio` C++ backend (unchanged); pytest with the null audio backend.

## Global Constraints

- SDK is ground truth. The real `sdk/Build/scripts/LoadBridge.py:349 LoadSounds()` runs unmodified; we only supply the Appc surface it calls.
- No native (C++) changes — Python shim over the existing backend only.
- `TGSoundRegion` filter constants are defined by our shim: `FT_NONE = 0`, `FT_MUTE = 1`, `FT_MUFFLE = 2`. The SDK references them only symbolically (`App.TGSoundRegion.FT_NONE`), never as integer literals.
- `FT_MUFFLE` is approximated as a 0.3× gain cut (amplitude approximation of BC's lowpass), documented as such in code.
- Bridge sounds load non-positional (`TGSound.LS_STREAMED`).
- All units stay in game units / unchanged; this feature touches no spatial math.
- Tests use the null backend (`OPEN_STBC_AUDIO=0`) and the `init_audio_for_tests()` / `shutdown_audio_for_tests()` helpers.

---

## File Structure

- `engine/audio/tg_sound.py` — add `TGSoundRegion` + registry, stateful `TGSound.Play/Stop` + region gating, group tracking on `TGSoundManager`, `LoadSoundInGroup`; delete `register_default_sounds` + `_DEFAULT_*`; reset regions in test helpers.
- `engine/core/game.py` — add `Game.LoadSoundInGroup`.
- `App.py` — export `TGSoundRegion`, `TGSoundRegion_GetRegion`, `TGSoundRegion_Create`.
- `engine/audio/bridge_ambient.py` — `set_active(False)` also stops any orphan `AmbBridge`.
- `engine/host_loop.py` — split out `init_audio_backend()`, call it before mission load, drop `register_default_sounds`, silence `AmbBridge` post-load.
- Tests: `tests/audio/test_tg_sound_region.py`, `tests/audio/test_sound_groups.py`, `tests/audio/test_loadbridge_loadsounds.py`, additions to `tests/audio/test_tg_sound.py` and `tests/audio/test_bridge_ambient.py` (create if absent).

---

## Task 1: Stateful `TGSound.Play()` / `Stop()` (active-handle tracking)

**Files:**
- Modify: `engine/audio/tg_sound.py` (`TGSound.__init__`, `Play`, `Stop`)
- Test: `tests/audio/test_tg_sound.py` (add one test)

**Interfaces:**
- Consumes: existing `_PlayingSound` (has `.Stop()`, `.SetGain(gain)`), `_audio.play(...)`.
- Produces: `TGSound._active: list[_PlayingSound]` (the live handles started by this sound), `TGSound._region` (set later by `TGSoundRegion.AddSound`, default `None`), `TGSound.Stop()` stops and clears all `_active`. `TGSound._gain` remains the nominal volume.

- [ ] **Step 1: Write the failing test**

Add to `tests/audio/test_tg_sound.py`:

```python
def test_tgsound_stop_stops_active_loop(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    snd = audio.LoadSound(str(wav), "AmbLoop", TGSound.LS_STREAMED)
    snd.SetLooping(1)
    snd.Play()
    _dauntless_host.audio.clear_command_log()
    snd.Stop()  # TGSound.Stop (not the per-handle _PlayingSound.Stop)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_tg_sound.py::test_tgsound_stop_stops_active_loop -v`
Expected: FAIL — current `TGSound.Stop` is a no-op (`def Stop(self): pass`), so no `stop` op is logged.

- [ ] **Step 3: Write minimal implementation**

In `engine/audio/tg_sound.py`, in `TGSound.__init__` (after `self._loaded = ...`), add:

```python
        self._active: list[_PlayingSound] = []
        self._region = None  # set by TGSoundRegion.AddSound; gates launch gain
```

Replace the body of `TGSound.Play` so it records the handle and applies the region factor:

```python
    def Play(self, attach_node: int = 0, position=None) -> Optional[_PlayingSound]:
        if not _audio or not self._loaded:
            return None
        # Drop handles we explicitly stopped earlier so the list can't grow
        # without bound across repeated one-shot plays.
        self._active = [h for h in self._active if h._pid]
        factor = self._region.filter_factor() if self._region is not None else 1.0
        pid = _audio.play(
            name=self._name, looping=self._looping, gain=self._gain * factor,
            category=self._category_tag, attach_node=int(attach_node),
            position=position,
        )
        if pid == 0:
            return None
        handle = _PlayingSound(pid)
        self._active.append(handle)
        if self._positional or attach_node != 0 or position is not None:
            _audio.set_min_max_distance(pid, self._min_dist, self._max_dist)
        return handle
```

Replace the no-op `def Stop(self): pass` (in the "No-ops kept" block) with a real implementation, and remove `Stop` from that comment block:

```python
    def Stop(self):
        """Stop every handle this sound started (real Appc TGSound.Stop).

        Used by region muting and to silence the SDK's load-time AmbBridge
        play when the player isn't on the bridge.
        """
        for h in self._active:
            h.Stop()
        self._active = []
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_tg_sound.py -v`
Expected: PASS (all tests in file, including the new one).

- [ ] **Step 5: Commit**

```bash
git add engine/audio/tg_sound.py tests/audio/test_tg_sound.py
git commit -m "feat(audio): stateful TGSound.Play/Stop with active-handle tracking

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `TGSoundRegion` + registry + active filter gating + App.py exposure

**Files:**
- Modify: `engine/audio/tg_sound.py` (add `TGSoundRegion`, registry, `TGSoundRegion_GetRegion`, `TGSoundRegion_Create`; reset registry in test helpers)
- Modify: `App.py` (export the new symbols)
- Test: `tests/audio/test_tg_sound_region.py` (create)

**Interfaces:**
- Consumes: `TGSound._active` and `TGSound._gain` (Task 1), `_PlayingSound.SetGain(gain)`.
- Produces:
  - `class TGSoundRegion` with `FT_NONE=0`, `FT_MUTE=1`, `FT_MUFFLE=2`, methods `SetFilter(ft)`, `AddSound(snd)`, `RemoveSound(snd)`, `filter_factor() -> float`.
  - `TGSoundRegion_GetRegion(name) -> TGSoundRegion` (per-name singleton, created on demand).
  - `TGSoundRegion_Create(name) -> TGSoundRegion` (alias of the above).
  - `App.TGSoundRegion`, `App.TGSoundRegion_GetRegion`, `App.TGSoundRegion_Create` resolve to these.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_tg_sound_region.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager, TGSoundRegion,
    TGSoundRegion_GetRegion, TGSoundRegion_Create,
    init_audio_for_tests, shutdown_audio_for_tests,
)


def _wav(rate, samples):
    data = b"".join(struct.pack("<h", s) for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio():
    init_audio_for_tests()
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()


def test_get_region_is_singleton_per_name(audio):
    r1 = TGSoundRegion_GetRegion("bridge")
    r2 = TGSoundRegion_GetRegion("bridge")
    r3 = TGSoundRegion_GetRegion("other")
    assert r1 is r2
    assert r1 is not r3
    assert TGSoundRegion_Create("bridge") is r1


def test_set_filter_mutes_then_restores_playing_member(audio, tmp_path):
    wav = tmp_path / "x.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    snd = audio.LoadSound(str(wav), "Hum", TGSound.LS_STREAMED)
    snd.SetVolume(1.0)
    snd.SetLooping(1)
    region = TGSoundRegion_GetRegion("bridge")
    region.SetFilter(TGSoundRegion.FT_NONE)
    region.AddSound(snd)
    snd.Play()

    _dauntless_host.audio.clear_command_log()
    region.SetFilter(TGSoundRegion.FT_MUTE)
    muted = [e for e in _dauntless_host.audio.debug_command_log()
             if e["op"] == "set_gain"]
    assert muted and muted[-1]["f"][0] == 0.0

    _dauntless_host.audio.clear_command_log()
    region.SetFilter(TGSoundRegion.FT_NONE)
    restored = [e for e in _dauntless_host.audio.debug_command_log()
                if e["op"] == "set_gain"]
    assert restored and restored[-1]["f"][0] == 1.0


def test_add_sound_tolerates_none(audio):
    region = TGSoundRegion_GetRegion("bridge")
    region.AddSound(None)  # a failed LoadSoundInGroup returns None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_tg_sound_region.py -v`
Expected: FAIL at import — `cannot import name 'TGSoundRegion'`.

- [ ] **Step 3: Write minimal implementation**

In `engine/audio/tg_sound.py`, add after the `TGSound` class (before `class TGSoundManager`):

```python
class TGSoundRegion:
    """Headless shim for Appc's TGSoundRegion.

    A named bucket of sounds with a filter that can mute / muffle the whole
    region. The SDK only ever uses the "bridge" region with FT_NONE
    (LoadBridge.py:353-356), but we honour FT_MUTE/FT_MUFFLE actively so the
    surface behaves like the original.
    """

    # Filter types. Values are ours to define — the SDK references them only
    # symbolically (App.TGSoundRegion.FT_NONE), never as integer literals.
    FT_NONE = 0
    FT_MUTE = 1
    FT_MUFFLE = 2

    # FT_MUFFLE is BC's lowpass; we approximate it with a gain cut.
    _MUFFLE_FACTOR = 0.3

    def __init__(self, name: str) -> None:
        self._name = name
        self._filter = TGSoundRegion.FT_NONE
        self._sounds: list[TGSound] = []

    def filter_factor(self) -> float:
        if self._filter == TGSoundRegion.FT_MUTE:
            return 0.0
        if self._filter == TGSoundRegion.FT_MUFFLE:
            return TGSoundRegion._MUFFLE_FACTOR
        return 1.0

    def SetFilter(self, ft) -> None:
        self._filter = int(ft)
        factor = self.filter_factor()
        for snd in self._sounds:
            for h in snd._active:
                if h._pid:
                    h.SetGain(snd._gain * factor)

    def AddSound(self, snd) -> None:
        if snd is None:  # a failed LoadSoundInGroup returns None
            return
        if snd not in self._sounds:
            self._sounds.append(snd)
        snd._region = self

    def RemoveSound(self, snd) -> None:
        if snd in self._sounds:
            self._sounds.remove(snd)
        if snd is not None and getattr(snd, "_region", None) is self:
            snd._region = None


_regions: dict[str, TGSoundRegion] = {}


def TGSoundRegion_GetRegion(name: str) -> TGSoundRegion:
    r = _regions.get(name)
    if r is None:
        r = TGSoundRegion(name)
        _regions[name] = r
    return r


def TGSoundRegion_Create(name: str) -> TGSoundRegion:
    return TGSoundRegion_GetRegion(name)
```

In the same file, in `init_audio_for_tests()` (right after `TGSoundManager._instance = TGSoundManager()`), add region reset:

```python
    _regions.clear()
```

And in `shutdown_audio_for_tests()` (after `TGSoundManager._instance = None`), add:

```python
    _regions.clear()
```

In `App.py`, extend the existing tg_sound import (lines 126-128):

```python
from engine.audio.tg_sound import (
    TGSound, TGSoundManager, g_kSoundManager,
    TGSoundRegion, TGSoundRegion_GetRegion, TGSoundRegion_Create,
)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_tg_sound_region.py -v`
Expected: PASS (3 tests).

Then verify App exposure:

Run: `OPEN_STBC_AUDIO=0 uv run python -c "import App; print(App.TGSoundRegion.FT_NONE, App.TGSoundRegion_GetRegion('bridge'))"`
Expected: prints `0 <...TGSoundRegion object...>` (a real object, not a stub).

- [ ] **Step 5: Commit**

```bash
git add engine/audio/tg_sound.py App.py tests/audio/test_tg_sound_region.py
git commit -m "feat(audio): TGSoundRegion shim with active mute/muffle gating

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Sound groups + `Game.LoadSoundInGroup`

**Files:**
- Modify: `engine/audio/tg_sound.py` (`TGSoundManager.__init__`, add `LoadSoundInGroup`, `DeleteAllSoundsInGroup`, `StopAllSoundsInGroup`)
- Modify: `engine/core/game.py` (`Game.LoadSoundInGroup`)
- Test: `tests/audio/test_sound_groups.py` (create)

**Interfaces:**
- Consumes: `TGSoundManager.LoadSound`, `TGSound.Stop` (Task 1), `TGSound.LS_STREAMED`.
- Produces:
  - `TGSoundManager.LoadSoundInGroup(path, name, group) -> Optional[TGSound]` — loads non-positional, records `name` under `group`, returns the sound (or `None`).
  - `TGSoundManager.DeleteAllSoundsInGroup(group)` — stops + forgets every sound in the group.
  - `TGSoundManager.StopAllSoundsInGroup(group)` — stops (keeps loaded) every sound in the group.
  - `Game.LoadSoundInGroup(path, name, group)` — delegates to the manager, returns the `TGSound`.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_sound_groups.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager,
    init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.core.game import Game


def _wav(rate, samples):
    data = b"".join(struct.pack("<h", s) for s in samples)
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, rate, rate * 2, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio():
    init_audio_for_tests()
    yield TGSoundManager.instance()
    shutdown_audio_for_tests()


def test_game_load_sound_in_group_registers_and_groups(audio, tmp_path):
    wav = tmp_path / "v.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    g = Game()
    snd = g.LoadSoundInGroup(str(wav), "ViewOn", "BridgeGeneric")
    assert snd is not None
    snd.SetVolume(1.0)  # SDK chains .SetVolume on the return value
    assert audio.GetSound("ViewOn") is snd


def test_delete_all_sounds_in_group_removes_members(audio, tmp_path):
    wav = tmp_path / "v.wav"
    wav.write_bytes(_wav(22050, [0, 0]))
    audio.LoadSoundInGroup(str(wav), "A", "BridgeGeneric")
    audio.LoadSoundInGroup(str(wav), "B", "BridgeGeneric")
    assert audio.GetSound("A") is not None
    audio.DeleteAllSoundsInGroup("BridgeGeneric")
    assert audio.GetSound("A") is None
    assert audio.GetSound("B") is None


def test_load_sound_in_group_missing_file_returns_none(audio, tmp_path):
    snd = audio.LoadSoundInGroup(str(tmp_path / "nope.wav"), "X", "BridgeGeneric")
    assert snd is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_sound_groups.py -v`
Expected: FAIL — `Game` has no `LoadSoundInGroup` (falls through to a `_Stub`, so `snd is not None` but `GetSound("ViewOn")` is `None`), and `TGSoundManager` has no `LoadSoundInGroup`/`DeleteAllSoundsInGroup`.

- [ ] **Step 3: Write minimal implementation**

In `engine/audio/tg_sound.py`, in `TGSoundManager.__init__`, add a groups map:

```python
    def __init__(self) -> None:
        self._sounds: dict[str, TGSound] = {}
        self._groups: dict[str, set[str]] = {}
```

Add these methods to `TGSoundManager` (after `LoadSound`):

```python
    def LoadSoundInGroup(self, path: str, name: str, group: str) -> Optional[TGSound]:
        """Load a sound and tag it as a member of `group`.

        Mirrors Appc Game.LoadSoundInGroup. Bridge sounds are non-positional,
        so we load them streamed (2D). Returns the TGSound so the SDK can chain
        .SetVolume(); returns None on load failure.
        """
        snd = self.LoadSound(path, name, TGSound.LS_STREAMED)
        if snd is not None:
            self._groups.setdefault(group, set()).add(name)
        return snd

    def DeleteAllSoundsInGroup(self, group: str) -> None:
        for name in self._groups.pop(group, set()):
            snd = self._sounds.pop(name, None)
            if snd is not None:
                snd.Stop()

    def StopAllSoundsInGroup(self, group: str) -> None:
        for name in self._groups.get(group, set()):
            snd = self._sounds.get(name)
            if snd is not None:
                snd.Stop()
```

In `engine/core/game.py`, add to `class Game` (after `LoadSound`):

```python
    def LoadSoundInGroup(self, path: str, name: str, group: str):
        # Late import: engine.audio depends on the native extension which may
        # not be ready at game.py import time.
        from engine.audio.tg_sound import TGSoundManager
        return TGSoundManager.instance().LoadSoundInGroup(path, name, group)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_sound_groups.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/audio/tg_sound.py engine/core/game.py tests/audio/test_sound_groups.py
git commit -m "feat(audio): sound groups + Game.LoadSoundInGroup

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Integration — real `LoadBridge.LoadSounds()` loads all 16 sounds

**Files:**
- Test: `tests/audio/test_loadbridge_loadsounds.py` (create)

**Interfaces:**
- Consumes: everything from Tasks 1-3, plus `App.Game_GetCurrentGame`, `App._set_current_game`, the SDK module `LoadBridge` (resolved by `tests/conftest.py`'s `_SDKFinder`).
- Produces: no new production code — this task verifies the genuine SDK `LoadBridge.LoadSounds()` (sdk/Build/scripts/LoadBridge.py:349) runs end-to-end against our surface and registers every named sound. If it fails, fix the surface from Tasks 1-3.

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_loadbridge_loadsounds.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSoundManager, init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.core.game import Game, _set_current_game


# (file, sound-name, volume) — must match sdk/Build/scripts/LoadBridge.py:358-375
_EXPECTED = [
    ("sfx/bridge2.loop.wav", "AmbBridge", 1.0),
    ("sfx/redalert.wav", "RedAlertSound", 1.0),
    ("sfx/yellowalert.wav", "YellowAlertSound", 1.0),
    ("sfx/greenalert.wav", "GreenAlertSound", 1.0),
    ("sfx/critical.wav", "CollisionAlertSound", 1.0),
    ("sfx/hail.wav", "ViewOn", 1.0),
    ("sfx/ViewscreenOff.WAV", "ViewOff", 1.0),
    ("sfx/Bridge/console_explo_01.wav", "ConsoleExplosion1", 0.5),
    ("sfx/Bridge/console_explo_02.wav", "ConsoleExplosion2", 0.5),
    ("sfx/Bridge/console_explo_03.wav", "ConsoleExplosion3", 0.5),
    ("sfx/Bridge/console_explo_04.wav", "ConsoleExplosion4", 0.5),
    ("sfx/Bridge/console_explo_05.wav", "ConsoleExplosion5", 0.5),
    ("sfx/Bridge/console_explo_06.wav", "ConsoleExplosion6", 0.5),
    ("sfx/Bridge/console_explo_07.wav", "ConsoleExplosion7", 0.5),
    ("sfx/Bridge/console_explo_08.wav", "ConsoleExplosion8", 0.5),
    ("sfx/Bridge/bridge_loop_warp.wav", "InSystemWarp", 1.0),
]


def _wav():
    data = struct.pack("<h", 0) * 2
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def game_with_assets(tmp_path, monkeypatch):
    # Point the sfx resolver at a tmp game dir and stage every bridge WAV so the
    # real LoadBridge.LoadSounds() loads from disk without needing the game/ tree.
    monkeypatch.setenv("OPEN_STBC_GAME_DIR", str(tmp_path))
    for rel, _name, _vol in _EXPECTED:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(_wav())
    init_audio_for_tests()
    g = Game()
    _set_current_game(g)
    yield g
    _set_current_game(None)
    shutdown_audio_for_tests()


def test_real_loadbridge_loadsounds_registers_all(game_with_assets):
    import LoadBridge
    LoadBridge.LoadSounds()
    mgr = TGSoundManager.instance()
    for _rel, name, vol in _EXPECTED:
        snd = mgr.GetSound(name)
        assert snd is not None, f"{name} was not loaded by LoadBridge.LoadSounds()"
        assert abs(snd.GetVolume() - vol) < 1e-6, f"{name} volume {snd.GetVolume()} != {vol}"


def test_loadbridge_sounds_are_in_bridge_group(game_with_assets):
    import LoadBridge
    LoadBridge.LoadSounds()
    mgr = TGSoundManager.instance()
    # Terminate() relies on the BridgeGeneric group for unload.
    mgr.DeleteAllSoundsInGroup("BridgeGeneric")
    assert mgr.GetSound("ViewOn") is None
    assert mgr.GetSound("InSystemWarp") is None
```

- [ ] **Step 2: Run test to verify it fails (or passes) — diagnose**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_loadbridge_loadsounds.py -v`
Expected: With Tasks 1-3 done, this should PASS. If it FAILS, the failure pinpoints a surface gap (e.g. `App.TGSoundRegion_GetRegion` not resolving, or `pGame.LoadSoundInGroup` returning a stub). Fix the relevant Task 1-3 code until green — do not weaken the test.

- [ ] **Step 3: (only if Step 2 failed) fix the surface**

Apply the minimal fix to `engine/audio/tg_sound.py` / `engine/core/game.py` / `App.py` indicated by the failure, then re-run.

- [ ] **Step 4: Run test to verify it passes**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_loadbridge_loadsounds.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/audio/test_loadbridge_loadsounds.py engine/ App.py
git commit -m "test(audio): real LoadBridge.LoadSounds() loads all 16 bridge sounds

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: `bridge_ambient` stops orphan `AmbBridge`

**Files:**
- Modify: `engine/audio/bridge_ambient.py` (`set_active`)
- Test: `tests/audio/test_bridge_ambient.py` (create)

**Interfaces:**
- Consumes: `TGSoundManager.instance().GetSound("AmbBridge")`, `TGSound.Stop()` (Task 1), `_PlayingSound`.
- Produces: `set_active(False)` stops both `bridge_ambient`'s own handle **and** any orphan `AmbBridge` started elsewhere (the SDK's LoadBridge.py:213 load-time play), so the hum is silent off-bridge. `set_active(True)` unchanged in intent (start if not already playing).

- [ ] **Step 1: Write the failing test**

Create `tests/audio/test_bridge_ambient.py`:

```python
import os
import struct
import pytest

os.environ.setdefault("OPEN_STBC_AUDIO", "0")
_dauntless_host = pytest.importorskip("_dauntless_host")

from engine.audio.tg_sound import (
    TGSound, TGSoundManager,
    init_audio_for_tests, shutdown_audio_for_tests,
)
from engine.audio import bridge_ambient


def _wav():
    data = struct.pack("<h", 0) * 2
    return (b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
            + b"fmt " + struct.pack("<I", 16)
            + struct.pack("<HHIIHH", 1, 1, 22050, 44100, 2, 16)
            + b"data" + struct.pack("<I", len(data)) + data)


@pytest.fixture
def audio(tmp_path):
    init_audio_for_tests()
    bridge_ambient.reset_for_tests()
    wav = tmp_path / "amb.wav"
    wav.write_bytes(_wav())
    TGSoundManager.instance().LoadSound(str(wav), "AmbBridge", TGSound.LS_STREAMED)
    yield TGSoundManager.instance()
    bridge_ambient.reset_for_tests()
    shutdown_audio_for_tests()


def test_set_active_false_stops_orphan_ambbridge(audio):
    # Simulate the SDK's LoadBridge.py:213 load-time play that bridge_ambient
    # does NOT own a handle for.
    snd = audio.GetSound("AmbBridge")
    snd.SetLooping(1)
    snd.Play()
    _dauntless_host.audio.clear_command_log()
    bridge_ambient.set_active(False)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops


def test_set_active_true_starts_then_false_stops(audio):
    bridge_ambient.set_active(True)
    _dauntless_host.audio.clear_command_log()
    bridge_ambient.set_active(False)
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "stop" in ops
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_bridge_ambient.py -v`
Expected: FAIL on `test_set_active_false_stops_orphan_ambbridge` — current `set_active(False)` only stops its own `_playing` handle (which is `None` here), so no `stop` op is emitted for the orphan.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `set_active` in `engine/audio/bridge_ambient.py`:

```python
def set_active(active: bool) -> None:
    """Start the bridge ambient loop if `active` and not yet playing;
    stop it if not `active`. Idempotent.

    On deactivate we also stop the AmbBridge sound directly (not just our own
    handle), so the SDK's load-time play at LoadBridge.py:213 — which runs in
    the space scene during mission load — goes silent off-bridge.
    """
    global _playing
    if active:
        if _playing is None:
            snd = TGSoundManager.instance().GetSound("AmbBridge")
            if snd is None:
                return
            snd.SetLooping(1)
            snd.SetSFX()
            _playing = snd.Play()  # non-positional (no attach_node)
    else:
        if _playing is not None:
            _playing.Stop()
            _playing = None
        snd = TGSoundManager.instance().GetSound("AmbBridge")
        if snd is not None:
            snd.Stop()  # kill any orphan handle (e.g. SDK load-time play)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_bridge_ambient.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add engine/audio/bridge_ambient.py tests/audio/test_bridge_ambient.py
git commit -m "feat(audio): bridge_ambient.set_active(False) stops orphan AmbBridge

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: host_loop — backend-init reorder, drop `register_default_sounds`, post-load AmbBridge silence

**Files:**
- Modify: `engine/audio/tg_sound.py` (delete `register_default_sounds`, `_DEFAULT_3D_SOUNDS`, `_DEFAULT_2D_SOUNDS`)
- Modify: `engine/host_loop.py` (import line, `init_audio`, add `init_audio_backend`, `shutdown_audio`, pre-mission-load backend init, post-load AmbBridge silence)
- Test: `tests/audio/test_host_loop_audio_init.py` (add one test)

**Interfaces:**
- Consumes: `_audio_mod.init`, `_bridge_ambient_set` (the `set_active` import at host_loop.py:52, updated in Task 5), `controller.loader.load`.
- Produces: `host_loop.init_audio_backend()` — idempotent backend init, safe to call before mission load and again from `init_audio()`. `init_audio()` no longer loads default sounds. `register_default_sounds` no longer exists.

- [ ] **Step 1: Write the failing test**

Add to `tests/audio/test_host_loop_audio_init.py`:

```python
def test_register_default_sounds_is_gone():
    # The hardcoded stand-in is replaced by the real LoadBridge.LoadSounds()
    # + LoadTacticalSounds.LoadSounds() paths.
    import engine.audio.tg_sound as tg
    assert not hasattr(tg, "register_default_sounds")


def test_init_audio_backend_is_idempotent(monkeypatch):
    monkeypatch.setenv("OPEN_STBC_AUDIO", "0")
    _dauntless_host = pytest.importorskip("_dauntless_host")
    from engine import host_loop
    host_loop.init_audio_backend()
    _dauntless_host.audio.clear_command_log()
    host_loop.init_audio_backend()  # second call must not re-init
    ops = [e["op"] for e in _dauntless_host.audio.debug_command_log()]
    assert "init" not in ops
    host_loop.shutdown_audio()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_host_loop_audio_init.py -v`
Expected: FAIL — `register_default_sounds` still exists, and `host_loop.init_audio_backend` is undefined.

- [ ] **Step 3: Write minimal implementation**

In `engine/audio/tg_sound.py`, delete the `_DEFAULT_3D_SOUNDS`, `_DEFAULT_2D_SOUNDS` tuples and the entire `register_default_sounds()` function (the block spanning the "Subset of ... LoadSounds()" comment through the end of `register_default_sounds`). Leave the `g_kSoundManager` singleton and the test helpers below it intact.

In `engine/host_loop.py`, update the import (around line 38-40). Replace:

```python
# well-defined from frame 0. register_default_sounds is called from
# init_audio so engine rumble + alert names resolve before first spawn.
from engine.audio.tg_sound import TGSoundManager, register_default_sounds  # noqa: F401
```

with:

```python
# Engine-rumble names come from LoadTacticalSounds.LoadSounds(); bridge/alert
# names from the real LoadBridge.LoadSounds() at mission load (against a live
# backend, since init_audio_backend() runs before the mission loads).
from engine.audio.tg_sound import TGSoundManager  # noqa: F401
```

Add a module-level flag near the other audio module state (just above `def init_audio()`):

```python
_audio_backend_ready = False
```

Replace `init_audio()` (lines 92-100) with a split version:

```python
def init_audio_backend() -> None:
    """Boot the audio backend (idempotent).

    Must run before the SDK's LoadBridge.Load -> LoadSounds() at mission load
    so bridge SFX load into a live backend. Null backend if OPEN_STBC_AUDIO=0.
    """
    global _audio_backend_ready
    if _audio_mod is None or _audio_backend_ready:
        return
    backend = "null" if _os_mod.environ.get("OPEN_STBC_AUDIO") == "0" else "openal"
    _audio_mod.init(backend=backend)
    _audio_backend_ready = True


def init_audio() -> None:
    """Finish audio setup: backend (if not already up) + event listeners."""
    if _audio_mod is None:
        return
    init_audio_backend()
    install_engine_rumble_listener()
    _alert_listener.reset()
```

Update `shutdown_audio()` to clear the flag:

```python
def shutdown_audio() -> None:
    global _audio_backend_ready
    if _audio_mod is None:
        return
    _audio_mod.shutdown()
    _audio_backend_ready = False
```

In `run()`, insert the backend init immediately before the mission load. Find (around line 2897-2898):

```python
        controller.session = controller.loader.load(mission_name)
```

Insert directly above it:

```python
        # Bring the audio backend up BEFORE the mission loads: the mission's
        # StartMission runs the real SDK LoadBridge.Load -> LoadSounds(), which
        # must load bridge SFX into a live backend. Listener installs stay in
        # init_audio() below (relocating them would change spawn-event capture).
        init_audio_backend()
        controller.session = controller.loader.load(mission_name)
        # The SDK's CreateAndPopulateBridgeSet plays AmbBridge at load
        # (LoadBridge.py:213); silence it now since the initial view is space.
        # bridge_ambient remains the sole authority on when the hum plays.
        _bridge_ambient_set(False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_host_loop_audio_init.py -v`
Expected: PASS (all tests, including the two new ones and the existing init/tick tests).

- [ ] **Step 5: Commit**

```bash
git add engine/audio/tg_sound.py engine/host_loop.py tests/audio/test_host_loop_audio_init.py
git commit -m "feat(audio): reorder backend init before mission load; drop register_default_sounds

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: Full-suite regression + cleanup verification

**Files:**
- No new code. Verification only.

- [ ] **Step 1: Run the audio test suite**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio -v`
Expected: PASS (all audio tests, old + new).

- [ ] **Step 2: Run the broader sound/engine-rumble/alert tests**

Run: `OPEN_STBC_AUDIO=0 uv run pytest tests/audio/test_engine_rumble.py tests/audio/test_alert_audio.py tests/unit/test_tg_sound_duration.py tests/unit/test_load_damage_hit_sounds.py -v`
Expected: PASS — removing `register_default_sounds` must not regress rumble/alert resolution (those names come from `LoadTacticalSounds` / `LoadBridge.LoadSounds`).

- [ ] **Step 3: Confirm no stale references to the removed symbol**

Run: `grep -rn "register_default_sounds\|_DEFAULT_3D_SOUNDS\|_DEFAULT_2D_SOUNDS" engine/ App.py tests/`
Expected: no matches (the `.claude/worktrees/` stale checkout is not in scope).

- [ ] **Step 4: Run the watchdog-capped full suite**

Run: `scripts/run_tests.sh`
Expected: PASS, peak memory well under the cap (see `docs/test-suite-memory.md`).

- [ ] **Step 5: Commit (if any fixes were needed)**

```bash
git add -A
git commit -m "test(audio): full-suite regression for LoadBridge.LoadSounds wiring

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Manual verification (Mark, in-game)

With `--developer` and a real `game/` install, load E1M1/E1M2 and confirm:
- Hailing opens the viewscreen with `ViewOn` (`sfx/hail.wav`).
- Hanging up plays `ViewOff` (`sfx/ViewscreenOff.WAV`).
- Console explosions (`ConsoleExplosion1-8`) and `InSystemWarp` are audible where the SDK triggers them.
- `AmbBridge` hum is silent in the space scene and plays only on the bridge view.

---

## Self-Review notes

- **Spec coverage:** TGSoundRegion + gating (Task 2), Game.LoadSoundInGroup + groups (Task 3), stateful Play/Stop (Task 1), real LoadBridge.LoadSounds integration (Task 4), AmbBridge wrinkle mitigation (Tasks 5-6), backend reorder + register_default_sounds removal (Task 6), risk regression sweep (Task 7). All spec sections mapped.
- **Type consistency:** `TGSound._active`, `TGSound._region`, `filter_factor()`, `LoadSoundInGroup(path, name, group)`, `DeleteAllSoundsInGroup(group)`, `init_audio_backend()`, `_bridge_ambient_set` used consistently across tasks.
- **Filter constants** fixed at `FT_NONE/FT_MUTE/FT_MUFFLE = 0/1/2` everywhere.
