# Warp VFX — Star-Trek Warp (Dust Streak + Prism) (Design)

**Date:** 2026-06-22
**Status:** Approved for planning
**Supersedes:** the visual technique of `2026-06-22-warp-vfx-flythrough-design.md`
(the galaxy-vantage flythrough). Reuses that effort's infrastructure; replaces
its background-star-streak/vantage visual with a dust-particle warp streak.

## Goal

Make warp look like Star Trek warp, in four phases:

1. **Align** — the ship slows and turns to face the warp heading; the engines
   spool up (SFX).
2. **Burst** — a huge lightspeed flash ("sonic-boom" of crossing lightspeed)
   with SFX as warp engages.
3. **Transit** — bright dust particles streak past with **prism-colored tips**
   (light dispersed into frequencies); duration scales with galaxy distance.
4. **Exit** — another boom + SFX; the streaks shrink back to ordinary dust as
   the ship arrives in the destination system.

The camera stays unlocked (works from exterior or bridge). A Modern-VFX toggle
(default ON) gates it; OFF = the Stage-1 instant hard cut.

## Background

**BC warp (reference):** ship hides into a C++ warp set with a fixed cutscene
camera, mesh stretches, `starstreak.tga` smears the backdrop, and `warpflash*`
flashes mask the set transitions. The "enter warp" SFX contains the engine
spool-up AND the flash boom in one file; "exit warp" is the exit shock.

**Our dust pass (the lever — verified):** the camera-anchored dust
(`native/src/renderer/dust_pass.cc`, `dust.vert`/`dust.frag`) renders instanced
billboard quads wrapped toroidally around the camera, and **already stretches
each particle's leading edge along a velocity smear** (`u_smear`, capped at
`kMaxSmearLength`; `dust.vert` `offset += 0.5 * a_corner.y * u_smear`). So the
warp streak is a tweak: scale that smear by a warp factor and tint the leading
tip. No mesh/physics/memory changes — pure shader math + two new uniforms.

**What the `feat/warp-vfx-flythrough` branch already built (reuse vs revert):**
- **Reuse (kept):** the `dauntless_warp_vfx` state channel (streak/flash/travel
  + setters), the `resolve.frag` warp **flash** (`u_warp_flash` → `mix(c,white,
  i)`), the `WarpVFX` manager (`engine/warp_vfx.py` — timing + streak/flash
  envelopes), the timed-transit sequence + distance-based duration
  (`engine/appc/warp.py`), and the "Warp Flythrough" config toggle.
- **Revert (clean — verified independent of the above):** the `backdrop.frag`
  star-streak (`u_warp_streak`/`u_warp_travel` in `proc_stars`, the
  `backdrop_pass.cc render()` warp params, the frame() pass-through) and the
  `_aggregate_backdrops` procedural-sky **vantage animation** in `host_loop`.
  The flash, manager, and sequence survive the revert untouched.

## Decisions (locked during brainstorming)

1. **Speed comes from the DUST**, not the background. Revert the background-star
   streak + galaxy-vantage flythrough; drive a dust-pass streak instead.
2. **Cinematic turn (phase 1)** is included now. The warp heading = the galaxy
   src→dst direction (from the system vantage positions), used directly as an
   in-set heading — physically arbitrary (each system is its own 3D set) but
   gives per-destination variety. The ship slerps to it over `T_align`.
3. **Prism tip is procedural** — a hue swept along the streak (no texture).
4. **Ship is ~stationary through transit** (BC-style); the dust + flash sell the
   speed, the set-swap teleports at arrival. (Open follow-up: a small forward
   lunge at burst, if desired after live tuning.)
5. **Dim the background during transit** so the streaks pop and it reads as "in
   warp" (tunable; reverts to full brightness on exit).
6. **Two-phase timeline:** `T_align` (fixed ≈1.5 s) + `T_transit` (distance-
   scaled, the existing `_transit_duration`).
7. **Fail-open:** turn / SFX / streak / dim never block the warp — the set-swap
   always completes and control is always restored.
8. Rework on the existing `feat/warp-vfx-flythrough` branch (most infra stays).

## Architecture

The `WarpSequence` gains an align phase before the transit; the `WarpVFX`
manager owns the whole clock and exposes per-frame state the host applies:

```
T_align (≈1.5s, fixed)          T_transit (distance-scaled)
|---------- ALIGN --------|--BURST--|--------- TRANSIT ---------|-- EXIT --|
remove control            flash      dust streaks held           flash
slow ship -> 0            boom       (prism tips), bg dimmed      boom
slerp -> warp heading     dust↑                                  dust↓->normal
play "enter warp.wav"                                            play "exit warp.wav"
                                                                 set-swap -> destination
                                                                 restore control
```

- **`WarpVFX` manager** (extended): `start(...)` now takes `t_align`,
  `t_transit`, `heading`; `tick(now)` computes a `phase` (align/transit) and
  exposes `turn_fraction()` (0→1 over align), `streak_intensity()` (0 during
  align, ramps at burst, held in transit, →0 at exit), `flash_intensity()` (two
  sharp booms at burst + exit), `travel_dir()` (= heading). Pure math, headless.
- **`WarpSequence_Create`** (flythrough live): `_WarpAlignBegin` (start manager,
  remove control, play enter SFX) → swap actions held by `delay = T_align +
  T_transit` → `_WarpEnd` (stop manager, play exit SFX implicitly via envelope,
  restore control). Toggle off / no procedural-dust ⇒ the instant Stage-1 path.
- **host_loop** per frame while active: feed `r.set_dust_warp_streak(streak)` +
  `r.set_dust_warp_travel(travel)`, set the flash, dim the background, and apply
  the turn (slerp the player ship rotation by `turn_fraction`).

## Components

### Native (cmake rebuild)
- **`dust.vert`/`dust.frag` + `dust_pass.{cc,h}`:** add `u_warp_dust_streak`
  (0..1) + `u_warp_travel`; scale the existing smear by `1 + K*streak` along
  travel; in the fragment shader tint the leading tip with a procedural prism
  hue (swept along the particle's streak axis), fading in with streak; ramp
  brightness with streak. `DustPass::render(...)` gains the two params (default
  0 / (0,1,0) ⇒ off-parity). New `dust_set_warp_streak`/`dust_set_warp_travel`
  bindings (mirror `set_dust_*`), read per-frame in `frame()`.
- **Revert** the `backdrop.frag` warp-streak uniforms + `proc_stars` elongation,
  the `backdrop_pass.cc render()` warp params + frame() pass-through (back to the
  pre-Task-2 signature). Keep `resolve.frag`'s flash untouched.

### `engine/renderer.py`
- `set_dust_warp_streak(float)`, `set_dust_warp_travel(tuple)` (mirror the dust
  setters). Keep the flash setters; the backdrop-streak wrappers can stay
  (now unused) or be removed — remove for cleanliness.

### `engine/warp_vfx.py` (extend the manager)
- `start(heading, t_align, t_transit, now)` (drop the src/dst vantage — no longer
  animating the sky); `tick(now)`; `phase()`; `turn_fraction()`;
  `streak_intensity()`; `flash_intensity()` (two booms); `travel_dir()` (heading);
  `is_active()`; `stop()`.

### `engine/appc/warp.py`
- `_WarpTurnAction`-equivalent driven via the manager's `turn_fraction` (host
  applies the slerp); `_WarpSoundAction(sound_name)` (fail-open
  `TGSoundManager.PlaySound`); align+transit sequence (swap held by
  `T_align+T_transit`); heading = `_normalize(dst_vantage - src_vantage)`;
  `T_align` constant + the existing distance-based `T_transit`. Remove the
  vantage-animation start args; keep `configure_warp_vfx`.

### `engine/host_loop.py`
- Per frame while `warp_vfx.is_active()`: feed dust streak/travel + flash; dim
  the active set's sun/backdrop brightness by a `(1 - dim*progress)` factor
  during transit (revert the local-object DROP from the flythrough work — we
  now DIM rather than drop, so the streaks have something to fly against);
  apply the turn slerp to the player ship by `turn_fraction`; remove the
  `_aggregate_backdrops` vantage override.

## Error handling & edge cases

- **Fail-open:** `_WarpAlignBegin`/`_WarpEnd`/turn/SFX wrap their effects in
  try/except; the swap + control-restore always run. Toggle off ⇒ instant cut.
- **Control:** removed at align start, restored at phase 4 (and on stop/teardown
  so an interrupted warp can't leave control locked).
- **No heading** (unmapped vantage): default forward `(0,1,0)`; the ship doesn't
  turn (turn_fraction maps to a zero-angle slerp), streaks still play.
- **Mission swap / teardown mid-warp:** `WarpVFX.stop()` → streak/flash 0, dim
  cleared, control restored, turn setpoint cleared.
- **Off-parity:** streak 0 / flash 0 / not active ⇒ dust, resolve, and ship
  motion are byte-identical to today (every effect gated on `is_active()` /
  intensity `> 0`).

## Testing

**Headless (pytest):**
- Manager: `phase()` transitions align→transit at `T_align`; `turn_fraction` 0→1
  over align then 1; `streak_intensity` 0 in align, peaks/holds in transit, →0 at
  exit; `flash_intensity` has two booms (burst + exit); `travel_dir == heading`;
  `stop()` zeroes everything.
- Sequence: flythrough-on builds align+transit (swap held by `T_align+T_transit`),
  off = instant; heading = normalized src→dst; SFX/turn actions fail-open (a
  raising hook doesn't abort the swap); control restored.
- Existing warp + Stage-1 tests stay green (flythrough off headless).

**Native:** dust + (reverted) backdrop shaders compile; streak-0 dust frame
byte-identical; no NEW ctest failures vs base.

**Live human gate (Mark):** warp from exterior — ship slows + turns, boom flash,
bright prism dust streaks fly past, exit boom, streaks shrink to normal dust,
arrive in the new system; SFX timed to the visuals; toggle off = instant cut.
Tune: streak length (`K`), prism hue spread, flash boom envelope, `T_align`,
background dim, brightness.

## Out of scope

- Ship-mesh stretch (the `WES_*` shader effect).
- The galaxy-vantage flythrough (reverted) and background-star streak.
- A forward ship lunge at burst (follow-up if wanted after tuning).
- Multiplayer warp; bridge-viewscreen framing.
- Deriving the heading from anything physically meaningful (none exists across
  sets) — the galaxy-direction heading is a deliberate cinematic choice.

## Related

`2026-06-22-warp-vfx-flythrough-design.md` (infra reused), `[[project_warp_mechanism_sdk]]`,
`[[project_modern_vfx_design]]`, `[[feedback_vfx_calibrate_up_then_down]]`,
`[[feedback_shader_rebuild]]`, `[[feedback_camera_no_world_up]]` (note: the
arbitrary heading is a deliberate cinematic exception, not a world-up reference
in normal play), `native/src/renderer/dust_pass.cc`,
`native/src/renderer/shaders/dust.vert`, `engine/warp_vfx.py`,
`engine/appc/warp.py`, `game/sfx/enter warp.wav`, `game/sfx/exit warp.wav`.
