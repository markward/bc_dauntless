# LoadBridge.LoadSounds() — faithful bridge-sound wiring

**Date:** 2026-06-19
**Status:** Approved — ready for implementation plan
**Related memory:** `project_sdk_driven_bridge_init`, `project_comm_viewscreen_static_fade`, `reference_audio_mp3_decode`

## Problem

The SDK registers a set of bridge sounds in
`sdk/Build/scripts/LoadBridge.py:349` (`LoadSounds()`): `AmbBridge`,
`RedAlertSound`/`YellowAlertSound`/`GreenAlertSound`, `CollisionAlertSound`,
`ViewOn`→`sfx/hail.wav`, `ViewOff`→`sfx/ViewscreenOff.WAV`,
`ConsoleExplosion1-8` (`sfx/Bridge/console_explo_0N.wav`, vol 0.5), and
`InSystemWarp` (`sfx/Bridge/bridge_loop_warp.wav`). These are played all over
the bridge/comm code — e.g. `MissionLib.py:1290,1355` create
`TGSoundAction("ViewOn")`/`("ViewOff")` on every viewscreen switch.

`LoadSounds()` **is already reached** in our engine: the mission load at
`engine/host_loop.py:2898` runs the real SDK `LoadBridge.Load(name)` →
`CreateAndPopulateBridgeSet()` → `LoadSounds()` (LoadBridge.py:210). But it
loads **nothing** because the Appc surface it needs is unimplemented and falls
through to stubs:

- `App.TGSoundRegion_GetRegion("bridge")` → App module-level `__getattr__`
  returns a `_NamedStub` (no-op).
- `pGame.LoadSoundInGroup(file, name, "BridgeGeneric")` → `Game` has no such
  method, so `TGObject.__getattr__` returns a `_Stub` (no-op).
- `pBridgeRegion.SetFilter/AddSound`, `pSound.SetVolume` → no-op on stubs.

So the bridge SFX never reach the `_dauntless_host.audio` backend and are
silent. `AmbBridge` + alerts only work today because
`engine/audio/tg_sound.py:register_default_sounds()` hardcodes them, and engine
rumble sounds come from `LoadTacticalSounds.LoadSounds()`
(`engine/host_loop.py:180`). `register_default_sounds()` is the shortcut this
project removes.

### Secondary finding — backend init ordering

`_dauntless_host.audio` is initialized only by `init_audio()` at
`engine/host_loop.py:3149` — which runs **after** the mission load at
2898. So at the natural `LoadSounds()` call site the audio backend is not yet
live. For the in-SDK `LoadSounds()` to load real audio, the backend init must
move ahead of the mission load.

## Goal

Run the genuine SDK `LoadBridge.LoadSounds()` against a real Appc sound surface
so all bridge SFX become audible, and delete the `register_default_sounds()`
stand-in. Stay faithful to what the original STBC build clearly indicates
(real API shapes: `Game.LoadSoundInGroup`, `TGSoundRegion`, sound groups,
`TGSoundManager.StopSound`/`DeleteAllSoundsInGroup`).

## Design

### 1. New Appc sound surface

All in `engine/audio/tg_sound.py`, re-exported through `App.py`.

**`TGSoundRegion` + module registry.**
- `TGSoundRegion_GetRegion(name)` returns a per-name singleton region, creating
  it on first request; `TGSoundRegion_Create(name)` likewise. The SDK only uses
  `"bridge"`.
- Class constants `FT_NONE = 0`, `FT_MUTE = 1`, `FT_MUFFLE = 2` (values match
  whatever the SDK reads via `App.TGSoundRegion.FT_*`; only `FT_NONE` is set on
  the bridge region in practice).
- `SetFilter(ft)` stores the filter **and actively re-applies** it to the
  currently-playing handles of member sounds (the "active gating" decision):
  - `FT_MUTE` → set those handles' gain to 0.
  - `FT_MUFFLE` → attenuate (~0.3× amplitude). This approximates BC's lowpass
    muffle with a simple gain cut; documented as an approximation in code.
  - `FT_NONE` → restore each member sound's nominal gain.
  Implemented via the existing `_audio.set_gain(pid, gain)`.
- `AddSound(snd)` / `RemoveSound(snd)` manage membership and set/clear the
  sound→region back-link so `TGSound.Play()` applies the region's current
  filter factor at playback start. `AddSound(None)` is tolerated (a failed
  `LoadSoundInGroup` returns `None`).

**`Game.LoadSoundInGroup(path, name, group)`** (`engine/core/game.py`).
- Loads through `TGSoundManager` (same backend path as `Game.LoadSound`),
  records `name` under `group`, and returns the `TGSound` so the SDK's
  `.SetVolume(fVolume)` and `pBridgeRegion.AddSound(pSound)` chain works.
- Returns `None` if the load fails (missing file / backend down) without
  raising — matching the SDK's null-tolerant call site.

**`TGSoundManager` group surface.**
- `_groups: dict[str, set[str]]` maps group → member sound names.
- `DeleteAllSoundsInGroup(group)` and `StopAllSoundsInGroup(group)` —
  faithful to Appc; used by `LoadBridge.Terminate()`
  (`DeleteAllSoundsInGroup("BridgeGeneric")`).

**`TGSound.Play()/Stop()` made stateful.**
- `Play()` records its returned playing-handle(s) on the `TGSound` instance and
  applies the member region's current filter factor to the launch gain.
- `Stop()` (today a no-op) stops the recorded handle(s). Needed for region
  gating and the AmbBridge fix below. Faithful: real Appc `TGSound.Stop()`.

### 2. Backend-init reorder (surgical)

Extract just the backend init (`_audio.init(backend=…)`) from `init_audio()`
into an idempotent helper and call it **before** the mission load at
`engine/host_loop.py:2898`. The natural in-SDK `LoadBridge.Load → LoadSounds()`
then loads bridge SFX into a live backend; no explicit duplicate `LoadSounds()`
call is added. The rumble/alert listener installs stay at 3149 — relocating
them would change ship-spawn-event capture ordering and is out of scope.

`register_default_sounds()` and its `_DEFAULT_3D_SOUNDS` / `_DEFAULT_2D_SOUNDS`
tables are deleted. Post-removal coverage:
- engine rumble sounds: `LoadTacticalSounds.LoadSounds()` (host_loop:180,
  unchanged) — identical file→name mapping.
- alerts / `AmbBridge` / `ViewOn` / `ViewOff` / console / warp: the real
  `LoadBridge.LoadSounds()` at mission load (now against a live backend).

No regression in load timing: all sounds are registered before the game loop
starts (3150+); alerts in fact load earlier than before.

### 3. AmbBridge-in-space wrinkle + mitigation

`CreateAndPopulateBridgeSet` plays `AmbBridge` looping at LoadBridge.py:213-217
on the same first-load pass. Today that is silently swallowed (stub / dead
backend). With a live backend it would start the bridge hum during the **space
scene**, regressing the deliberate decoupling in
`engine/audio/bridge_ambient.py` (hum gated to bridge view via
`set_active()` on view-mode toggle).

Mitigation:
- `TGSound.Stop()` becomes functional (§1).
- `bridge_ambient.set_active(False)` calls `GetSound("AmbBridge").Stop()` so it
  stops whatever started the hum — including the SDK's load-time play.
- An explicit AmbBridge stop runs right after `loader.load()` returns so the
  initial space view is silent with no audible blip before the first view-mode
  sync.
- `bridge_ambient` remains the single authority on when the hum plays.

### Risk

Bringing the backend up before mission load can un-silence any *other*
load-time `Play()` the SDK issues during `loader.load()` that was previously
muted by the dead backend. Only `AmbBridge` was found on that path; implementation
watches for others and gates them the same way if any appear.

## Testing (TDD, null backend)

- `TGSoundRegion_GetRegion(name)` returns the same instance per name;
  `TGSoundRegion_Create` registers it.
- `SetFilter` gating: a playing member sound's gain goes to 0 on `FT_MUTE`,
  attenuates on `FT_MUFFLE`, and restores on `FT_NONE`.
- `Game.LoadSoundInGroup` loads + registers the name, returns the `TGSound`,
  and records group membership; `DeleteAllSoundsInGroup` removes them.
- Running the real `LoadBridge.LoadSounds()` registers all 16 SDK names
  (including `ViewOn`/`ViewOff`/`ConsoleExplosion1-8`/`InSystemWarp`) in
  `TGSoundManager`, with per-sound volumes applied.
- `TGSound.Stop()` stops an active looping handle; AmbBridge is silent in the
  space view and audible on the bridge view.

In-game (Mark verifies): `ViewOn` (`sfx/hail.wav`) on hail open, `ViewOff`
(`sfx/ViewscreenOff.WAV`) on hang-up in E1M1/E1M2; console-explosion +
`InSystemWarp` audible where the SDK triggers them.

## Files touched

- `engine/audio/tg_sound.py` — `TGSoundRegion`, region registry, group
  tracking, stateful `TGSound.Play/Stop`, remove `register_default_sounds` +
  `_DEFAULT_*`.
- `engine/core/game.py` — `Game.LoadSoundInGroup`.
- `App.py` — export `TGSoundRegion`, `TGSoundRegion_GetRegion`,
  `TGSoundRegion_Create`; ensure `g_kSoundManager.DeleteAllSoundsInGroup`/
  `StopAllSoundsInGroup` resolve.
- `engine/host_loop.py` — surgical backend-init reorder; drop
  `register_default_sounds` import/call; post-load AmbBridge stop.
- `engine/audio/bridge_ambient.py` — `set_active(False)` uses `TGSound.Stop()`.
- Tests under `tests/` for the surface + LoadBridge.LoadSounds integration.

## Out of scope

- Relocating the rumble/alert listener installs or `LoadTacticalSounds`.
- Native (C++) audio changes — the whole feature is Python-shim over the
  existing backend.
- A true lowpass `FT_MUFFLE`; gain attenuation is the Phase-2 approximation.
