# Audio Subsystem Design

**Status:** Approved, ready for implementation plan
**Date:** 2026-05-13
**Scope:** Phase 2 audio engine — OpenAL-backed C++ subsystem exposed to Python through `_open_stbc_host`, sufficient to make `LoadTacticalSounds.py` / `LoadBridge.py` register sounds and produce engine rumble on ships and one-shot alert SFX on alert-level transitions.

## Goals

- Audible **engine rumble** on every loaded ship — 3D, looping, attached to ship scene node, picked from the race-specific sound name set on each ship's `ImpulseEngineProperty`.
- Audible **alert one-shots** (`redalert.wav`, `yellowalert.wav`, `greenalert.wav`) on transitions of the Python-side alert state introduced in commit `4589635`.
- Real `TGSound` / `TGSoundManager` / `TGSoundAction` surface in the Python shim, so SDK code in `LoadTacticalSounds.py`, `LoadBridge.py`, hardpoint files, and `MissionLib.RedAlert` runs without modification and routes through the new audio module.
- Headless pytest stays green: tests use a null backend that records a command log without opening an audio device.

## Non-goals (for this slice)

- Weapons/explosion playback. The TGSound surface will be wide enough that the existing SDK calls succeed, but we don't audition those callsites in this slice.
- Streamed audio (`LS_STREAMED`). Music + voice streams are deferred.
- 3D cone data, occlusion, doppler tuning, environmental reverb.
- Save/load round-trip for sound state (`__getstate__`/`__setstate__`).
- End-event notifications (`PlayAndNotify`). Stub it; nothing in the immediate scope calls it.
- UI for mixer volumes. Read existing `Options.cfg` values at init; no settings panel.

## Architecture

```
native/src/audio/                              (new)
  audio_system.h/.cc           AudioSystem facade; owns backend; per-frame update
  audio_backend.h              IAudioBackend interface (load/play/stop/...)
  openal_backend.h/.cc         OpenAL Soft implementation
  null_backend.h/.cc           Command-log backend for headless tests
  sound_buffer.h/.cc           PCM WAV decoder; produces backend-agnostic buffer id
  sound_source.h/.cc           Live source state: buffer, looping, 3D, attach node ptr
  python_binding.cc            pybind11 surface exposed via _open_stbc_host.audio

engine/audio/                                  (new)
  tg_sound.py                  TGSound / TGSoundManager / TGSoundAction Python wrappers
                               that hold opaque handles into _open_stbc_host.audio
  alert_audio.py               Listener: subscribes to alert-state changes,
                               calls g_kSoundManager.PlaySound("RedAlertSound") etc.

App.py (root SDK shim)         Fill in TGSound, TGSoundPtr, TGSoundManager,
                               TGSoundAction, TGSoundAction_Create.
                               Patch ImpulseEngineProperty.SetEngineSound to
                               remember the sound name on the property instance.

engine/host_loop.py            Construct AudioSystem at boot; per-tick call
                               AudioSystem.update(listener_pose, dt).
                               Mount engine/audio/alert_audio.py listener.
```

### Module boundary

The C++ audio module owns all OpenAL state, buffer memory, and 3D math. Python receives opaque integer handles for sounds and for "logical sources" (a sound currently playing or paused). All position math and listener updates happen on the C++ side; Python only sends `attach_to_node(source_id, node_id)` and the C++ update loop reads node world transforms each frame.

This mirrors the renderer module's pattern (Python owns logic + handles; C++ owns resources).

### Per-frame update

The host loop already drives the renderer; we add one call per tick:

```python
audio.update(listener_position=camera.world_pos,
             listener_orientation=camera.world_forward_up,
             listener_velocity=camera.velocity,
             dt=tick_dt)
```

Inside `audio.update`:
1. For every live 3D source attached to a scene node, pull the node's world position and push it to OpenAL.
2. Update listener pose.
3. Service end-of-buffer cleanup for one-shots (release source slot).

## Component detail

### `AudioSystem` (C++)

Public surface (called from Python binding):

- `init(backend_kind)` — `backend_kind ∈ {OPENAL, NULL}`. Selected by host based on `OPEN_STBC_AUDIO` env var and device availability.
- `load_sound(path, name, load_spec)` → buffer handle. `load_spec` mirrors `App.TGSound.LS_*`. For this slice: `LS_3D` and the default 2D path are supported; `LS_STREAMED` falls through to a stubbed full-load.
- `get_sound(name)` → buffer handle or `None`.
- `play(sound_handle, looping, gain, attach_node_id_or_zero, position_or_none, category)` → source handle.
- `stop(source_handle)`, `pause`, `unpause`, `set_volume`, `set_position`, `set_min_max_distance`, `set_looping`, `set_category`.
- `update(listener_pose, dt)`.

Categories are an enum: `SFX`, `VOICE`, `INTERFACE`. Each has a master gain read at init from `Options.cfg` (keys observed in existing SDK: `SoundVolume`, `VoiceVolume`, `InterfaceVolume` — exact keys confirmed against the running game's config during implementation).

### `IAudioBackend` (C++)

Minimal interface. Methods correspond 1:1 to the `AudioSystem` surface but receive primitive types only (raw buffer bytes, pose floats). This is the seam between OpenAL and the null backend.

### `OpenALBackend` (C++)

- Initializes with `alcOpenDevice(nullptr)` (system default).
- Maintains a pool of AL sources (e.g. 64) and recycles them. If the pool is full, oldest non-looping source is preempted; looping sources are never preempted.
- For 3D sources: enables AL_SOURCE_RELATIVE = false, sets reference distance and rolloff defaults from BC tuning, applies `AL_MIN_GAIN` / `AL_MAX_GAIN`.

### `NullBackend` (C++)

- Records every call as `(timestamp, op, args)` in a vector reachable from Python via `audio.debug_command_log()`.
- Returns successful handle ids without doing any work.
- Used in pytest (driven by `OPEN_STBC_AUDIO=0` set in `tests/conftest.py`) and when OpenAL device open fails on a real run.

### `SoundBuffer` / WAV decoder

In-tree PCM WAV parser (no external lib). Handles 16-bit PCM mono/stereo, 8-bit PCM mono/stereo, 44.1k / 22.05k / 11.025k. Anything outside that → error logged, sound treated as missing (silent), engine continues.

### `SoundSource`

State held in `AudioSystem`:
- backend source handle
- buffer handle (refcounted)
- looping flag, gain, category
- optional `attach_node_id` (looked up in scenegraph each `update`)
- one-shot completion watcher (so finished one-shots return their backend slot to the pool)

### Python binding (`python_binding.cc`)

Single submodule `_open_stbc_host.audio` with free functions matching `AudioSystem`. Handles are plain ints. No PyObject ownership of C++ resources beyond the system singleton.

### `engine/audio/tg_sound.py`

Implements:

```python
class TGSound:
    LS_3D, LS_STREAMED, LS_DELAY_LOADING = 0, 1, 2
    SS_PLAYING, SS_STOPPED, SS_UNLOADED, SS_UNKNOWN = 0, 1, 2, 3
    # Load, Play, Stop, SetLooping, SetVolume, SetMinMaxDistance,
    # SetPosition, AttachToNode, IsLoaded, GetStatus,
    # SetSFX, SetVoice, SetInterface
    # Other methods present as no-op stubs for now.

class TGSoundManager:
    def LoadSound(self, path, name, load_spec): ...
    def GetSound(self, name): ...
    def PlaySound(self, name): ...
    # Per-category master volume getters/setters.

class TGSoundAction:
    def Play(self): self._mgr.PlaySound(self._name)

def TGSoundAction_Create(name): return TGSoundAction(name)

g_kSoundManager = TGSoundManager()  # exposed as App.g_kSoundManager
```

`TGSound` instances hold an opaque buffer handle from the C++ side. `Play()` returns a source handle wrapped in a lightweight `_PlayingSound` for `Stop()`/`Pause()`.

### `engine/audio/alert_audio.py`

Subscribes to the alert-state signal added in commit `4589635`. On transition to `RED` → `g_kSoundManager.PlaySound("RedAlertSound")`. Same for yellow/green. No-op for `OFF`. Module-level singleton mounted by `engine/host_loop.py`.

### Root `App.py` shim updates

- Replace the `TGSoundAction` placeholder with a real `TGSoundAction` and `TGSoundAction_Create` that delegate to `engine/audio/tg_sound.py`.
- Re-export `TGSound`, `TGSoundPtr` (alias), `TGSoundManager`.
- `App.g_kSoundManager` resolves to the engine singleton.
- `ImpulseEngineProperty.SetEngineSound(name)` and `GetEngineSound()` store/return the sound name on the property instance. Hardpoint loading already calls `SetEngineSound`; we just need to record what it set.

### Ship-construction wiring (engine rumble playback)

In Appc, engine rumble starts automatically when an impulse engine property is bound to a ship. We don't have Appc; we approximate it in our `loadspacehelper` shim path. The hook lives in `loadspacehelper.LoadShip` (or our Python-side ship-spawn equivalent), right after the existing physics-integration step at the end of construction, before the function returns:

```python
engine_sound_name = ship.impulse_engines.GetEngineSound()  # e.g. "Federation Engines"
sound = g_kSoundManager.GetSound(engine_sound_name)
if sound is not None:
    src = sound.Play(looping=True, attach_node=ship.scene_node, category=SFX)
    ship._engine_sound_src = src  # stash for cleanup on ship destruction
```

Cleanup on ship removal: `src.Stop()` then drop the reference. Tied into the existing ship-teardown path.

### Categories and master volume

Three master gains: `SFX`, `VOICE`, `INTERFACE`. Read at init from `Options.cfg` via the existing `g_kConfigMapping`. Defaults (1.0, 1.0, 1.0) if missing. Engine rumble is `SFX`. Alert sounds are `SFX` (consistent with the SDK — they're tagged as SFX by `LoadBridge.py`, not voice).

## Data flow — engine rumble end-to-end

```
1. Boot:    LoadTacticalSounds.py runs
            -> pGame.LoadSound("sfx/engine1.wav", "Federation Engines", LS_3D)
            -> TGSoundManager.LoadSound -> audio.load_sound
            -> OpenALBackend decodes WAV, creates AL buffer, records name -> buffer

2. Boot:    Hardpoint file runs
            -> ImpulseEngineProperty.SetEngineSound("Federation Engines")
            -> recorded on the property instance

3. Spawn:   loadspacehelper.LoadShip(...)
            -> ship is constructed, ImpulseEngineProperty attached
            -> post-construct hook reads engine_sound_name, calls Play(looping, attach_node)
            -> audio.play(buf, looping=True, attach=scenegraph_node_id, category=SFX)
            -> OpenALBackend allocates AL source, queues buffer, starts playback
            -> source recorded in AudioSystem with attach_node_id

4. Tick:    host_loop.tick() -> audio.update(listener_pose, dt)
            -> for each attached source: read node world pos from scenegraph,
               alSource3f(AL_POSITION). Listener follows camera.

5. Despawn: ship teardown -> ship._engine_sound_src.Stop() -> source released
```

## Data flow — alert sound end-to-end

```
1. Boot:    LoadBridge.py registers "RedAlertSound" -> sfx/redalert.wav
            (same path as above, ends up as a 2D buffer since alerts are non-3D).

2. Boot:    host_loop mounts engine/audio/alert_audio.py listener,
            subscribing to the alert-state signal.

3. Runtime: Player presses key bound to red alert -> alert state -> RED
            -> alert_audio listener fires
            -> g_kSoundManager.PlaySound("RedAlertSound")
            -> audio.play(buf, looping=False, attach=0, position=None, category=SFX)
            -> OpenALBackend plays one-shot on a recycled source

3'. SDK:    MissionLib.RedAlert is called by some mission script
            -> builds sequence with TGSoundAction_Create("RedAlertSound")
            -> sequence runs, pSoundAction.Play() -> same g_kSoundManager.PlaySound path
            (No double-fire in QB because nothing in QB calls MissionLib.RedAlert;
            player drives alerts via key binds. If a mission *does* call it, we get
            the sound plus whatever dialogue actions the sequence schedules.)
```

## Headless / test strategy

Tests must not open an audio device. Strategy:

- `tests/conftest.py` sets `OPEN_STBC_AUDIO=0` before any engine import.
- `AudioSystem.init` reads the env var and constructs `NullBackend`.
- `audio.debug_command_log()` returns the recorded `(op, args)` list.

Test pattern:

```python
def test_engine_rumble_starts_on_ship_spawn():
    log = audio.debug_command_log()
    log.clear()
    spawn_federation_ship(...)
    ops = [entry.op for entry in log]
    assert "load_sound" in ops or "get_sound" in ops
    assert any(e.op == "play" and e.args.looping is True
               and e.args.category == "SFX" for e in log)
```

The macOS-headless-pixel memory applies here: don't trust hardware presence in CI, assert on the command log instead.

## Performance / lifetime

- Source pool sized at 64 (BC's original is similar order of magnitude; tune later).
- WAV buffers stay resident once loaded (alert SFX < 1 MB each).
- Per-frame audio work is bounded by live source count, not by total loaded buffers.
- `audio.update` runs after physics and before render in the host loop tick — same place an attached listener already expects current scene node transforms.

## Error handling

- Missing WAV: warn once, store a `None` buffer entry, `GetSound` returns `None`, `PlaySound` becomes a no-op. Game continues.
- OpenAL init failure: fall back to NullBackend, log a single warning at boot. Game continues silent.
- Source pool exhaustion: preempt oldest non-looping source. Looping sources (engines) are never preempted.
- Unsupported WAV format (e.g. ADPCM, 24-bit): treat as missing.

## Out-of-scope but flagged

- **Streamed audio (music, voice lines):** later slice; will likely need a streaming thread inside the backend.
- **Cone data, doppler tuning, environmental reverb:** later, when we have a working baseline to compare against.
- **TGSound pickle round-trip:** later, when save/load lands.
- **PlayAndNotify end-event:** later; stub now.
- **UI for mixer volumes:** later; read `Options.cfg` and no settings panel yet.

## Open implementation questions

1. **Options.cfg volume keys** — exact key names for SFX / Voice / Interface volumes need confirmation by inspecting the running game's `Options.cfg`. Defaults to 1.0 if absent.
2. **Reference distance / rolloff factor defaults** — start with `AL_REFERENCE_DISTANCE = 100` (BC world units) and `AL_ROLLOFF_FACTOR = 1.0`, tune by ear once we hear ships at distance.
3. **OpenAL Soft version pin** — fetched via CMake `FetchContent_Declare` pinned to a specific release tag (chosen at implementation time based on macOS/Linux compatibility). Single mechanism, no vcpkg fallback.

## Acceptance criteria

- Launching `./build/open_stbc` and spawning a federation ship: I can hear engine rumble, attenuated by distance, panned by relative position to the camera.
- Pressing the red-alert keybind: I hear `redalert.wav` play once. Yellow/green equivalents work.
- `pytest` passes with no audio device open, and at least two new tests assert the command log for engine-rumble-on-spawn and alert-on-transition.
