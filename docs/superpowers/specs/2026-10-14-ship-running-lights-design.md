# Ship running lights (`BlinkingLightProperty`) — design

**Status:** approved in conversation 2026-10-14; spec awaiting Mark's review.
**Branch:** `feat/running-lights` (worktree `.claude/worktrees/running-lights`).
**Scope:** sub-project A of the stub-heatmap emitter family. Sub-project B
(bridge-interior `Spark`/`Smoke`/`ExplodeEmitterProperty` damage effects driven
by `Bridge/bridgeeffects.py`) is a separate design and is **out of scope** here,
except that its three property classes are created as plain placement
properties so they stop being stubs.

## 1. Problem

A Quick Battle with the LC Intrepid Pack logged 98 hits on
`App.BlinkingLightProperty_Create` and its setters. They are unimplemented, and
the stub has a second effect: `TGModelPropertyManager.RegisterLocalTemplate`
keys templates by `prop.GetName()`, which on a `_NamedStub` is a fresh stub
hashed by identity (`engine/appc/properties.py:1027-1028`, `App.py:1978`). So
the hardpoint's later `FindByName("Bridge Blinker", ...)` returns `None`, and
**not one mod running light ever reaches the ship's property set.**

Who uses them (verified 2026-10-14):

| Source | Lights |
|---|---|
| LC Intrepid Pack — `LCintrepidHP.py`, `LCvoyagerHP.py` | 19 each |
| DCMPv2 — 12 hardpoints (Wolverine, Thunderer, Defiant, Greshna, Valiant, Avenger, Ironheart, Bannockburn, Lynx, Selat, SaoPaulo, Paccia) | 10 each |
| Stock — `kessoklight.py:672-690` "Strobe" | 1, registered but never added by `LoadPropertySet` |

All 158 mod lights use Period 3.0. Every `*Static` light has Duration 0.0
(76 lights) and every `*Blinker` has Duration 1.0 (82). Radius is 1.0 or 1.5.
Colours are white, red, green, amber, cyan and blue. Every one names
`scripts/Custom/NanoFXv2/SpecialFX/Gfx/Blinker/Blank.tga`, a NanoFX texture
that is not installed anywhere. DCMPv2's readme lists "NanoFX2b (For the
Running Lights)" as a requirement.

## 2. What BC itself does (RE, 2026-10-14)

Sources: `STBC-Reverse-Engineering-1/reference/decompiled_fresh/`, plus raw
disassembly of the retail `stbc.exe` where the decompiler drops arguments.

- `Ship_SetupProperties` (`0x005B3FB0`, `05_game_mission.c:74113`) dispatches
  tag `0x8145` to `FUN_005B5280`. That reads Position (orientation is never
  read) and colour RGB (alpha dropped), then builds the sprite with
  `FUN_004DB1D0` / `FUN_004DABA0` and attaches it to the ship's scene node
  (`ship+0x18`). No pointer is kept, and nothing ever touches the sprite again.
- The sprite is an **unlit additive billboard quad** (`NiBillboardNode`, a
  ±0.5 quad scaled by |Radius|, SRCALPHA/ONE blending, z-test on, z-write off).
  It is not a light and casts nothing on the hull.
- Timing (`03_game_objects.c:79464`, verified): alpha keys at
  (0,0), (0.1x,1), (0.9x,1), (x,0) with x = Duration/Period, LOOP cycle
  (`andw $0xfff9` at `0x4DB0C3`). The controller frequency is set to **Period**
  (`movl %eax,0xc(%esi)` at `0x4DB0C9`, where `%eax` = the Period argument).
  The loop therefore lasts Duration/Period² seconds: **0.11 s, a ~9 Hz
  near-steady flicker**, not a 1 s flash every 3 s. Every light shares one
  phase.
- Duration 0 pins alpha at 0, so a "Static" light is **invisible**.
- A NULL texture name crashes on load; a missing file leaves a NULL image.
- The sprite hangs off `ship+0x18`, outside the LOD root that cloak fades
  (`ship+0x1C`), so in BC the lights **stay visible on cloaked ships**.

**Conclusion:** BC never visibly drew these lights as the mod authors intended.
Its timing is almost certainly a bug, statics are invisible, and the texture is
absent. Mark's ruling (2026-10-14): reproduce what the authors meant, i.e. real
navigation running lights. Reference screenshot: mod Voyager in BC with
NanoFX — tiny red and green pinpoints with a faint glow, no light cast on the
hull.

## 3. Deliberate departures from BC

| BC behaviour | Dauntless | Why |
|---|---|---|
| Blink loop = D/P² s (~9 Hz) | On for D s out of every P s | Mark's ruling: the authors' intent |
| Duration 0 ⇒ invisible | Duration 0 ⇒ always on ("Static") | Same |
| Texture from `TextureName` | Procedural soft disc; `TextureName` stored, unused | The texture doesn't exist; a NULL name crashed BC |
| Sprite edge = Radius (ship units ≈ the hull's length) | `Radius × size_gu_per_radius`, floored at `min_px` | Literal size was never seen and would be absurd |
| One global phase | Phase per ship, from its name | A fleet shouldn't blink in lockstep |
| Visible while cloaked | Fades with the cloak | Mark's ruling |
| Never switched off | Off on death; tracks power plant state | Mark's ruling |

## 4. Design

### 4.1 Property classes (`engine/appc/properties.py`, `App.py`)

- `EffectEmitterProperty(PositionOrientationProperty)`, and under it
  `SmokeEmitterProperty`, `SparkEmitterProperty`, `ExplodeEmitterProperty`
  (no extra surface; SDK `App.py:9872-9935`) and `BlinkingLightProperty`.
- `BlinkingLightProperty` typed surface (SDK `App.py:9940-9968`):
  `Set/GetColor` (TGColorA), `Set/GetRadius`, `Set/GetPeriod`,
  `Set/GetDuration`, `Set/GetTextureName`. Constructor defaults match the
  binary (`FUN_0067B590`): Radius 0.1, Period 3.0, Duration 1.0, texture
  `None`, colour white.
- Module-level `<Name>_Create` / `<Name>_Cast` for all five, mirroring
  `ObjectEmitterProperty_Create` (`properties.py:986`).
- Register the tags `CT_EFFECT_EMITTER_PROPERTY`, `CT_SMOKE_EMITTER_PROPERTY`,
  `CT_SPARK_EMITTER_PROPERTY`, `CT_EXPLODE_EMITTER_PROPERTY` and
  `CT_BLINKING_LIGHT_PROPERTY` in `_CT_CLASS_FOR_TAG` (`App.py:416`), so
  `GetPropertiesByType` works. (`IsTypeOf` is not added: no SDK script calls
  it on a property.)
- `ShipClass.SetupProperties` stays as it is: running lights are render-only
  and are read straight from the property set by 4.2.

### 4.2 `engine/appc/running_lights.py` (pure; no host calls)

- `RunningLightSpec`: body-frame position (GU, unscaled, the same convention as
  the subsystem emitter lights), `rgb`, `size` (= Radius), `period`,
  `duration`.
- `lights_for(ship) -> list[RunningLightSpec]`: walks
  `GetPropertiesByType(CT_BLINKING_LIGHT_PROPERTY)` on the ship's property set.
  Colour alpha is dropped, as in BC. Order is stable (property-set order).
- `phase_for(ship) -> float`: seconds, `crc32(name) / 2**32 × 1000.0`, stable
  per ship name (`blink_alpha` takes it modulo each light's period). The ship's blinkers share this phase, so they flash together.
- `level_for(ship, cloak_frac, now) -> float` in [0, 1]:
  - 0 if `IsDying()` or `IsDead()`;
  - power term from `subsystem_glow.glow_state(ship.GetPowerSubsystem())`:
    HEALTHY 1, DISABLED `light_emitters.emitter_flicker(now, phase)`,
    DESTROYED 0; no power subsystem ⇒ 1. Through `glow_state`, the dev
    "forced glow state" preview (Developer Options → Lighting) previews the
    lights too;
  - × `(1 − clamp(cloak_frac, 0, 1))`.

### 4.3 Host loop (`engine/host_loop.py`, `engine/host_io.py`)

- **Spawn:** next to every `_build_ship_emitter_cache` site
  (`host_loop.py:1414, 6481, 7669`), call
  `host_io.set_running_lights(iid, specs, phase)` when `lights_for` is
  non-empty. Ships without lights send nothing.
- **Every frame**, alongside `_push_cloak_refraction` (`host_loop.py:731`),
  which already reads each ship's `GetTransitionFraction()`:
  `host_io.set_running_light_levels([(iid, level), ...])` for every ship that
  has lights. A ship in `session.scope_hidden` is sent level 0.
- Rocks are skipped (`ship_iter.iter_non_rock_ships`).

### 4.4 Native (`native/src/renderer/running_light_{math,store,pass}.{h,cc}`)

**`running_light_math` (no GL; unit-tested)**
- `blink_alpha(t, period, duration, phase)`:
  - `duration <= 0` or `period <= 0` or `duration >= period` ⇒ 1;
  - otherwise `u = fmod(t + phase, period)`, `r = 0.1 × duration`, and the
    alpha ramps up over [0, r], holds 1 over [r, duration − r], ramps down over
    [duration − r, duration], and is 0 for the rest of the period. These are
    BC's 10% key ramps, on the authors' timescale.
- `sprite_world_size(size, dials, distance, proj_scale, viewport_h)`:
  `max(size × size_gu_per_radius, min_px × world_units_per_pixel_at(distance))`.

**`RunningLightStore`**
- `set(id, lights, phase)` (an empty list erases), `set_levels(list)` (ids not
  listed are treated as level 0 that frame), `erase(id)`, `clear()`.
- `erase` is called from the `destroy_instance` binding's `was_valid` branch
  (`host_bindings.cc:3224`). `clear` is called from `reset_frame_state`
  (`host_bindings.cc:915`), the mission-swap reset.

**`RunningLightPass`**
- Runs in the space phase right after the `space.weapons` scope
  (`host_bindings.cc:1814`), under its own profiler scope
  `space.running_lights`. It serves both the main view and the viewscreen RTT,
  and is skipped in hologram-only mode.
- For each stored instance with level > 0: look up the instance **by id**
  (`g_world`), not through `for_each_visible_in_pass`. During a cloak
  transition the hull is `set_visible(false)` while its lights must keep
  fading. World position = `t + R·p` with the instance's current-frame `world`
  (scale divided out, as in `resolve_attached_dynamic_lights`), so the lights
  never lag the interpolated hull.
- Alpha = `level × blink_alpha(g_decal_game_time, …)`. Game time, so blinkers
  freeze under pause.
- Draw: all sprites in one dynamic-VBO draw; camera-facing quads; additive
  (`GL_ONE, GL_ONE`, colour premultiplied by alpha); depth test on (the hull
  occludes its far-side lights), depth write off.
- Fragment: a soft radial disc, `rgb × intensity × alpha × falloff(r)`. There
  is **no separate halo**: with HDR on, the core sits above the bloom threshold
  and bloom supplies the glow, like every other bright source; with HDR off
  ("camera realism" off, `settings_store.py:300-308`) the soft edge still reads
  as a small light.
- Sprite budget: 4096 per frame (about 215 ships of 19 lights), clamped and
  logged once if exceeded.

### 4.5 Tuning and developer controls

- Dial group **"running lights"** on the shared `/ L O` keys
  (`engine/dev_dial_groups.register_group`), pushed through
  `host_io.set_running_light_dials(...)`. Read at use, so changes are live.

  | Dial | Start | Meaning |
  |---|---|---|
  | `size_gu_per_radius` | 0.02 | GU per Radius unit (Radius 1.5 ⇒ 0.03 GU ≈ 5 m) |
  | `min_px` | 1.5 | Smallest on-screen diameter |
  | `intensity` | 4.0 | HDR multiplier on the core colour |

  The start values are calibrated from the reference screenshot; final values
  are set live by Mark.
- Developer Options → Lighting → **"Running Lights"** toggle
  (`host_io.set_running_lights_enabled`). **On by default in production**; off
  skips the pass. Not persisted.

## 5. Testing

**pytest**
- Property classes: every setter and getter round-trips; constructor defaults;
  `_Create`/`_Cast`; `GetPropertiesByType(CT_BLINKING_LIGHT_PROPERTY)` returns
  them.
- **Regression:** loading the real `LCintrepidHP.py` through the normal
  hardpoint path gives the ship **19** blinking lights (0 before this change).
  Skips cleanly if the mod is absent.
- `running_lights`:
  - specs: static vs blinker; RGB with alpha dropped; order;
  - `phase_for`: stable for one name, different across names;
  - `level_for`: healthy 1; disabled equals `emitter_flicker`; destroyed 0;
    no power subsystem 1; cloak 0 / 0.5 / 1; dying and dead 0; the forced dev
    glow preview overrides.
- Host loop: spawning a lit ship calls `set_running_lights` once; levels are
  pushed every frame; a scope-hidden ship gets 0; an unlit ship never appears.

**gtest**
- `blink_alpha`: static and degenerate cases are 1; on, off and both ramps at
  the right times; phase shifts the window.
- `sprite_world_size`: world size wins near, the `min_px` floor wins far.
- `RunningLightStore`: set / levels / erase / clear; an unlisted id reads 0.
- GL frame test: a light in front of a hull lights its pixel; the same light
  behind the hull does not; level 0 draws nothing.

**Gate:** `scripts/check_tests.sh` green before merge.

## 6. Live verification (Mark)

Quick Battle as the LC Intrepid:
1. lights visible, sized and coloured like the reference;
2. statics steady, blinkers flash ~1 s every 3 s, and pause freezes them;
3. hull occludes far-side lights;
4. cloak fades them out and back in;
5. destroying the power plant puts them out (disabled ⇒ flicker);
6. lights go out when the ship dies.

## 7. Docs

- Add a "Running lights" row to the CLAUDE.md reference table pointing here.
- `docs/stub_heatmap.md` is generated and drops these rows on its next run;
  do not hand-edit it.

## 8. Risks and open points

- **Size calibration** comes from one screenshot; expect `size_gu_per_radius`
  to move in the live check.
- **Ship scale:** positions and sizes follow the emitter-light convention
  (unscaled GU). A ship with a non-unit `SetScale` keeps light size fixed
  rather than scaling it as BC's node scale would. Revisit only if a mod
  scales a lit ship.
- **Duration ≥ Period** renders always-on; no current content does this.
