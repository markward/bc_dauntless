# Hull Electrical Discharges — Design

**Date:** 2026-06-23
**Status:** Design approved, pending spec review
**Builds on:** the merged nebula trilogy — V1 faithful fog, volumetric clouds + tactical density, and thunder/lightning (`docs/superpowers/specs/2026-06-23-nebula-lightning-design.md`, merged `2481d9d7`). This is follow-on **③** of the nebula roadmap (see `project_nebula_pockets` memory). Only **④ the ship wake** remains after this.

---

## 1. Vision

While flying through a nebula, brief **electrical discharges** crackle across the player's own hull — like static discharge on the ship's skin — that also faintly **light the hull**. They occur "at a greater rate the more damage the cloud is able to do," with **rare strikes even when no damage is happening** (Mark's original words). Small in scale, lasting only a frame or two, no shadows.

## 2. Scope

**In scope:** brief procedural **electric-crackle billboards** at random hull points on the **player ship** while in a nebula; spawn rate that scales with the nebula's damage rate (+ rare idle strikes); a faint **whole-hull emissive flicker** when a discharge fires; gated by the existing **Nebula Lightning** toggle.

**Out of scope:** discharges on *other* ships in the nebula (player-only for V1; extensible later via their instances); real local point-lights (none exist — the flicker approximates "lighting the hull"); ④ the ship wake (the final follow-on).

## 3. Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Arc form | **Quick electric crackles** (additive billboard sprites) | Matches the "small, last a frame or two" vision; rides the `hit_vfx` billboard pattern; smallest scope |
| The look | **Dedicated electric-crackle pass + shader** (not reuse `hit_vfx`'s soft-spark shader) | `hit_vfx`'s shader draws soft sparks; a crackle needs a jagged electric read. A sibling pass keeps `hit_vfx` untouched and gets the right look |
| Hull lighting | **Local crackle glow + subtle whole-hull emissive flicker** | The vision says the discharge lights the hull; no point lights exist, so the additive sprite glows locally and a brief `set_emissive_scale` tick flickers the whole hull |
| Hull points | **Reuse `subsystem_world_position` mounts** + random offset | Subsystems are already distributed across the hull in world space; no new geometry/mesh access |
| Rate | **∝ nebula damage rate + rare idle strikes**, tunable | Directly from the vision |
| Toggle | **None new — gated by the existing Nebula Lightning toggle** | Distant flashes + hull crackle are one electrical-effect family; avoids toggle proliferation |

## 4. Architecture

A **Python discharge driver** (the brain) emits plain descriptors + an emissive value; the host loop feeds a native **crackle pass** and the existing `set_emissive_scale` binding. All timing/randomness lives in the testable driver.

### Components

| Unit | Location | Responsibility |
|---|---|---|
| **Discharge driver** | `engine/appc/hull_discharge.py` (new), ticked per-frame from the host loop | Seeded state machine: while the player is in a nebula, spawn brief discharges at random hull points at a rate ∝ the nebula damage rate (+ rare idle); age/expire them; emit crackle descriptors + a per-frame emissive-flicker value. Pure logic, no GL. |
| **Hull points** | reuse `engine/appc/subsystems.py:subsystem_world_position(sub, ship)` | A discharge anchors at a random subsystem mount + a small random surface offset (world space). |
| **Crackle pass** | `native/src/renderer/hull_discharge_pass.{h,cc}` + `shaders/hull_discharge.vert`/`.frag` | Additive camera-facing billboards with a **procedural jagged electric** look (blue-white), short size-ease + a 2-frame on/off stutter. Mirrors `hit_vfx_pass`. Depth-tested (occluded by nearer hull), depth-write off. |
| **Hull flicker** | host loop → `renderer.set_emissive_scale(instance_id, boost)` (existing binding) | Applies the driver's per-frame emissive boost to the player ship; the driver decays it back to exactly 1.0. |
| **Binding** | `native/src/host/host_bindings.cc` | `set_hull_discharges(list[dict])` → `g_hull_discharges`; render call in `render_space`, gated by `dauntless_nebula_lightning::enabled()` + non-empty. |

**Boundaries:** the driver is pure logic (descriptors + a float out); the crackle pass is data-in→pixels-out; hull points + emissive flicker reuse existing helpers/bindings. Inert outside a nebula / toggle off.

## 5. The discharge driver

Seeded `HullDischargeDriver`, ticked each sim frame, mirroring `nebula_thunder.py`.

- **Inputs/tick:** `in_nebula`, `damage_rate` (the player's nebula `GetDamage()[0]` hull/sec, 0 when not in one), `dt`, the ship world transform, and the hull anchor points.
- **Spawn rate (∝ damage):** `rate = IDLE_RATE + DAMAGE_GAIN · damage_rate` discharges/sec. Each tick spawn with probability `rate · dt`; allow a small per-tick burst (cap `BURST_MAX`) so dense damaging cloud reads as a flurry. `IDLE_RATE` gives the rare zero-damage strikes.
- **Each discharge:** anchors at a random hull point (random subsystem mount + small random offset), jittered size, very short life (`LIFE_MIN…LIFE_MAX`, ~0.06–0.15 s), electric blue-white colour; carries `age` advanced per tick; expired at `age ≥ life`.
- **Emissive flicker:** outputs `emissive_boost = clamp(1 + FLICKER · Σ active_intensity, 1, EMISSIVE_MAX)`; decays to **exactly 1.0** when no discharges are active.
- **Outputs/tick:** `active_discharges() -> [{world_pos, age, life, size, color}]`; `emissive_boost() -> float`. Deterministic given seed + inputs.
- **Dials:** `IDLE_RATE`, `DAMAGE_GAIN`, `BURST_MAX`, `LIFE_MIN/MAX`, size range, `FLICKER`, `EMISSIVE_MAX`, colour, anchor offset.

## 6. Crackle pass & flicker

**Crackle pass.** Sibling of `hit_vfx_pass`: additive camera-facing billboards, **depth-tested** against the scene (a crackle on the far side of the hull from this view is occluded) with depth-write off, drawn after the hull. Consumes descriptors via `set_hull_discharges`; gated by the Nebula Lightning toggle + non-empty list; GL state saved/restored (additive blend, depth-test on, depth-write off → restore canonical).

The look lives in **`hull_discharge.frag`**: a procedural jagged electric sprite — a few thin forked filaments from a hot core, built from cheap value-noise-distorted radial lines, with a 2-frame on/off stutter over the short life so it reads as crackling, not a smooth fade. Blue-white, additive, size eases in fast and snaps off. No texture asset, no shadows. **This is the tuning-heavy part** (filament count, jaggedness, stutter); the constants are live-tuning dials.

**Hull flicker.** The host loop reads `emissive_boost()` each frame and calls `renderer.set_emissive_scale(player_instance_id, boost)`. The emissive scale is **shared ship state**, so the driver owns it only while discharges are active and the host loop must restore exactly **1.0** when idle, on toggle-off, outside the nebula, and on mission swap — a hard invariant (its own test), so the hull is never left stuck bright.

**Failure modes:** no hull points (subsystem list empty) → no spawns; player instance id not yet realized → skip the flicker that frame (descriptors still fine); mission swap → driver reset + emissive 1.0; toggle off / outside nebula → inert + emissive 1.0.

## 7. Toggle, integration & testing

**Toggle:** none new — gated by the existing `dauntless_nebula_lightning::enabled()` / `r.nebula_lightning_enabled()`. Off → no crackles, emissive forced to 1.0.

**Integration (host loop):** beside the lightning wiring — tick the driver each sim frame when in a nebula (reuse the in-nebula signal + the player's nebula `GetDamage()` rate; pass the ship transform + subsystem hull points); per frame `r.set_hull_discharges(active_discharges())` and `r.set_emissive_scale(player_iid, emissive_boost())`; reset the driver + force emissive 1.0 in `reset_sdk_globals`; gate on the toggle.

**Testing:**
- **Driver (pytest, seeded):** spawns only in a nebula; rate scales with `damage_rate` (zero → rare, high → flurry); idle strikes still occur at zero damage; discharges anchor at provided points + expire at `life`; `emissive_boost` rises on a burst and decays to **exactly 1.0**; deterministic; full reset (incl. emissive) on swap.
- **Crackle pass (C++ FrameTest):** a descriptor at a known world point → an additive sprite there; empty list → byte-identical (off-path).
- **Emissive-restore (pytest):** toggle-off / leaving-nebula / no-discharge paths all yield `emissive_boost == 1.0` (the stuck-bright guard).
- **Live (Mark):** Vesuvi4 (light damage) then a dense damaging clump — crackles flick across the hull, rate climbs with damage, hull faintly flickers, rare idle strikes when undamaged; toggle on/off; no stuck-bright hull; framerate holds.

## 8. Key risks

- **The electric look** — a convincing jagged crackle is procedural-shader work; the starting `hull_discharge.frag` will need live tuning to read as "electric," not "noisy blob." Live-tuning dials are front-loaded.
- **Stuck-bright hull** — the shared emissive scale must be restored to exactly 1.0 on every idle/off/swap path; made a hard invariant with its own test.
- **Hull-point coverage** — subsystem mounts may cluster (weapons fore, engines aft); the random offset spreads them, but coverage depends on the ship's subsystem layout. Acceptable for V1; note if a ship looks sparse.

## 9. Key references

- `project_nebula_pockets` memory + the nebula-lightning spec/plan — the effect family this joins; `engine/appc/nebula_thunder.py` is the driver shape to mirror.
- `native/src/renderer/hit_vfx_pass.{h,cc}` + `shaders/hit_vfx.*` + `engine/appc/hit_vfx.py` + the `set_hit_vfx` binding — the additive-billboard pattern the crackle pass copies (with a different, electric shader).
- `engine/appc/nebula_runtime.py` (`GetDamage`, `_apply_env_damage`, `_nebula_tracker._inside`) — the in-nebula signal + per-second damage rate.
- `engine/appc/subsystems.py:subsystem_world_position` — the hull anchor points.
- `renderer.set_emissive_scale(instance_id, scale)` binding — the whole-hull flicker.
- the `dauntless_nebula_lightning` toggle (frame.cc / host_bindings / renderer.py) — the gate this reuses.
