# Transient Impact Feedback — Sparks + Emissive Flicker

**Status:** drafted, awaiting user review
**Date:** 2026-06-09
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-06-damage-attribution-design.md`](./2026-06-06-damage-attribution-design.md) — the attribution model. This spec consumes the per-hit data already broadcast/dispatched: `(target, source, damage, hit_point, normal, radius, post_shield_damage, primary_subsystem)` plus the per-stage `absorbed_shields / absorbed_subsystem / absorbed_hull` totals and `weapon_type` (`"phaser"` / `"torpedo"`). **Attribution is locked; not redesigned here.**
- [`2026-06-08-persistent-damage-decals-design.md`](./2026-06-08-persistent-damage-decals-design.md) and [`2026-06-08-persistent-damage-decals-phase2-shading-design.md`](./2026-06-08-persistent-damage-decals-phase2-shading-design.md) — the persistent damage system. **The emissive flicker is built on its decal-record + body-space-compositing architecture and adds no parallel record list and no change to the decal data layout.** Read §3 of this spec against those.
- [`2026-05-12-object-emitter-emission-design.md`](./2026-05-12-object-emitter-emission-design.md) — the object-emitter machinery. **Not used here** — both effects in this spec are one-shot per impact; sustained, state-driven emitters remain the decals spec's Phase 3–4 work.
- SDK `sdk/Build/scripts/Effects.py` — `CreateWeaponSparks` (line 329) is the stock spark recipe this honours in spirit (`SetAngleVariance(120.0)`, `SetDamping(0.3)`, `data/rough.tga`, white→transparent ramp).

## 1. Goal

Add two **transient, one-shot-per-impact** hit-feedback effects. Neither accumulates or persists between ticks; neither is serialized.

1. **Sparks** — billboard particles thrown off the hull on *heavy direct impacts*. An additive cue that sells the weight of a big hit. Independent of the damage-decal system.
2. **Emissive flicker** — on torpedo hull hits, a brief (~500ms) electrical *stutter* of the ship's **own** emissive map (windows, running lights, engine glow) localised to the impact area. A power-disruption read, distinct from deposited heat. Built **on the existing SCORCH decal record** — no new record, no new data fields.

These are the surface-dressing transients that sit alongside the persistent decals: the decal is what *stays*; sparks and flicker are what *happens at the moment of impact*.

## 2. What is already in place

- **Dispatch site.** `engine/appc/hit_feedback.py:dispatch(...)` runs per impact and already holds `ship`, `source`, `point`, `normal`, `weapon_type`, `radius`, `host`, `ship_instances`, and the three `absorbed_*` totals. It already classifies `Severity.{SHIELD,HULL,CRITICAL}` and fans out to one visual + audio + camera shake. **This is the emission site for both effects.**
- **Transient VFX registry.** `engine/appc/hit_vfx.py` holds the per-impact descriptor list (`_active`), pruned by `update_ages`, read by the renderer via `snapshot()`. SHIELD is filtered out here. Today `spawn(position, normal, severity)` stores a **frozen world position**.
- **Renderer VFX pass.** `native/src/renderer/hit_vfx_pass.cc` already draws: a main billboard quad (`data/Textures/Tactical/TorpedoFlares.tga`, per-tier tint/size/fade) for HULL and CRITICAL, **plus a 6-spark burst for CRITICAL only** — hash-jittered directions in a 30° cone around the surface normal, additive blend, world-fixed origin (`v.world_pos + dir * speed * age`). The spark machinery (`hash3`, `rotate_jitter`, per-spark size/alpha fade) is reusable; it is currently CRITICAL-gated, 30°, single-tint, and world-anchored.
- **Decal ring + decal shader (decals Phases 1–2).** Each `ModelInstance` carries a 24-slot body-frame decal ring; `opaque.frag` loops the active slots and composites SCORCH (deposit + ~10s blackbody ember) and HEAT_GLOW (phaser, ~1.2s additive bloom) in body space, normal-aware (`w_n`), on the game clock (`u_decal_time`). Each record carries `point_body, normal_body, radius, intensity, birth_time, weapon_class`. **The flicker adds one term to this loop and reads only fields that already exist.**

## 3. Locked design decisions

Settled in the brainstorm that produced this spec; not open for relitigation in implementation.

### 3.1 Two independent paths

| | Sparks | Emissive flicker |
|---|---|---|
| Home | hit_vfx descriptor path → `hit_vfx_pass.cc` | a term in `opaque.frag`'s decal loop |
| Backing state | the existing transient `_active` list | the **existing SCORCH decal record** |
| New record list | none | **none** |
| Change to decals data layout | n/a | **none** |
| Clock | descriptor `age` (wall/render, as today) | game time (`u_decal_time`), as the ember |

Sparks are explicitly **independent of the decal system** (transient billboards). The flicker is explicitly **built on the decal system** (a shader term keyed off SCORCH records), satisfying the requirement not to introduce a parallel record list.

### 3.2 Sparks — trigger (policy in Python)

In `hit_feedback.dispatch`, after `classify(...)`:

```
spark = (absorbed_hull >= SPARK_HULL_THRESHOLD) or (severity == Severity.CRITICAL)
```

- Magnitude-based, weapon-agnostic: a single big hit (torpedo) clears the threshold; per-tick phaser dribble does not. CRITICAL (a subsystem state transition this tick) always sparks regardless of magnitude.
- **Policy stays in Python.** When `spark` is true, dispatch sets a `spark_count` (scaled by severity: heavy-HULL < CRITICAL) and the `weapon_type` on the descriptor. The renderer renders exactly what it is told; it contains no trigger logic. Today's hard-coded `sev == 2` spark gate in `hit_vfx_pass.cc` is replaced by reading the descriptor's `spark_count`.

`SPARK_HULL_THRESHOLD` and the severity→count scaling are tune-by-eye constants (§6).

### 3.3 Sparks — hull-anchored origin, detached particles

The descriptor stops storing a frozen world point. It stores the **instance and a body-frame emit frame**:

- `instance_id` (the receiving ship's `ModelInstance`),
- `body_offset` (impact point in the ship body frame),
- `body_normal` (surface normal in the ship body frame).

Each frame, `hit_vfx_pass` resolves the emit **origin** through the ship's current world matrix (`world * body_offset`) and the emit **direction basis** through `mat3(world)`, so the burst tracks the hull as the ship translates *and* rotates. Each spark then flies from that origin on its own ballistic path: `origin + dir * speed * age`, with velocity damping (analogue of the SDK `SetDamping(0.3)`) and **no gravity** (space). This is the detached-particle model — emitter attached to the hull, particles independent once born — matching SDK `SetEmitFromObject(...)` + `SetDetachEmitObject(0)`.

Resolution requires the pass to look up the live world matrix by `instance_id` each frame. If an instance is gone (destroyed), its descriptors are dropped.

Body-frame conversion at spawn happens Python-side in dispatch (it has `ship`, `point`, `normal`, and the `ship_instances` map). World→body uses the same `inverse(ship_world)` path the decal emission already uses.

### 3.4 Sparks — weapon-distinct look

Keyed off `weapon_type` on the descriptor:

| weapon | tint | count | cone half-angle | feel |
|---|---|---|---|---|
| `"torpedo"`, disruptor, default | hot orange | more | wide (~120°, SDK precedent) | explosive debris spray |
| `"phaser"` | cool white-blue | fewer | tight (~40°) | vaporised-metal flash |

Sprite: `data/rough.tga` (stock spark), replacing the current `TorpedoFlares.tga` for the spark sub-quads. The main impact-flash billboard (§3.6) is unchanged. Per-spark size/alpha fade over life reuses the existing curve. Exact counts/cone/speed/lifetime are tune-by-eye (§6).

### 3.5 Emissive flicker — a term on the SCORCH decal record

The flicker is rendered inside `opaque.frag`'s existing decal loop. For each decal `i` with `weapon_class == SCORCH` and `age = u_decal_time - birth_time[i]` in `[0, FLICKER_DURATION]` (~0.5s):

```glsl
float env  = 1.0 - (age / FLICKER_DURATION);          // amplitude envelope → 0
float s     = stutter(age);                            // rapid on/off noise in [-1, 1]
float fall  = exp(-r*r * FLICKER_TIGHTNESS);           // radial falloff within the decal
float k     = STUTTER_GAIN * env * s * fall * w_n;     // signed, normal-aware
glow_local *= (1.0 + k);                               // modulate the SAMPLED glow map up AND down
```

- **Power-disruption read (locked):** the term multiplies the ship's **own** sampled emissive (`u_glow_map` value at the fragment), pushing it above baseline (bloom peaks, fed to the existing HDR path) and below (dropout dips) as the stutter oscillates — the "electrical stutter" behaviour chosen in the brainstorm. It is **not** a new coloured layer and **not** a heat ramp.
- **`stutter(age)`** is a cheap high-frequency oscillation (e.g. hashed noise or `sin` of a high multiple of `age` with a noise term) giving ~8–12 flickers across the window; amplitude is shaped by `env`. Exact form is a tuning detail (§6); the contract is "noisy oscillation, decaying to zero by `FLICKER_DURATION`."
- **Normal-aware** via the same `w_n` the decal loop already computes (§4.1 of the decals Phase-2 spec) — so the flicker, like the deposit, cannot bleed onto a mirrored hull half.
- **Coexists** with the SCORCH blackbody ember (deposited heat, ~10s) running off the *same* record. Different physical story (power vs heat), additively composited.
- **"Torpedo only" = the SCORCH class.** The decals spec (§3.4) puts disruptors in SCORCH alongside torpedoes. Keying the flicker on `weapon_class == SCORCH` therefore fires it for both torpedo and disruptor hits and **never** for phaser (HEAT_GLOW) hits — which is the intended "torpedo-only, not energy-vaporise" boundary. If disruptors should later be excluded, that is a one-line `weapon_type` check, not a structural change.

### 3.6 What stays unchanged

- The generic **impact-flash billboard** (`TorpedoFlares.tga` quad, per-tier) keeps firing for all HULL/CRITICAL impacts. Sparks are an *additive* layer; this spec does not remove or restyle the flash.
- The **SHIELD path** (shield-bubble splash) is untouched — sparks and flicker are hull-impact effects and never fire on a fully shield-absorbed hit (the flicker inherits the decal's `absorbed_hull > 0 && normal != None` gate; sparks require `absorbed_hull >= threshold` or CRITICAL, both of which imply hull penetration).
- Audio and camera shake in `hit_feedback.py` — unchanged.

### 3.7 Differentiation, extent, fields — the three flicker sub-questions, resolved

- **Differentiation (fresh flicker vs permanent emissive content):** dissolves. Permanent emissive is the texture sample; the flicker is a transient per-fragment *multiplier* derived from decal `age`. The flicker is never written to any map, so the two never collide.
- **Spatial extent:** the SCORCH decal's own `radius`, optionally × a small `FLICKER_SPREAD ≥ 1` constant (power disruption may bleed slightly past the scorch core). Parked (§6).
- **Record fields / retroactive change:** **none.** `birth_time`, `weapon_class`, `radius`, `point_body`, `normal_body` already exist on the record and are exactly what the flicker term reads. The decals data layout is unchanged; no retroactive migration.

### 3.8 Runtime-only

Both effects are runtime VFX. Sparks live and die inside `_LIFETIME`; the flicker lives inside `FLICKER_DURATION`. Neither is written to BCS saves. (The SCORCH record the flicker rides on is itself runtime-only per the decals spec §3.7.)

## 4. Components and boundaries

- **`engine/appc/hit_feedback.py`** — adds the spark trigger/policy (§3.2): computes `spark` + `spark_count`, converts the impact to body frame, and calls the extended `hit_vfx.spawn(...)`. No change to classification, audio, shake, or the decal-emission block.
- **`engine/appc/hit_vfx.py`** — `spawn(...)` signature grows to carry `instance_id`, `body_offset`, `body_normal`, `weapon_type`, `spark_count` (alongside `severity`/`age`). `update_ages` / `snapshot` unchanged in shape.
- **`native/src/renderer/hit_vfx_pass.cc` (+ `.h`, descriptor struct)** — descriptor gains the body-frame emit fields, `weapon_type`/tint enum, and `spark_count`. Per-frame: look up the instance world matrix, resolve hull-anchored origin + basis, draw `spark_count` weapon-tinted sparks (wide/tight cone) with damping. The CRITICAL-only gate becomes "draw `spark_count` sparks." Main flash billboard unchanged.
- **`native/src/renderer/shaders/opaque.frag`** — adds the §3.5 flicker term inside the existing decal loop, plus the `stutter`, envelope, and tuning constants (`FLICKER_DURATION`, `STUTTER_GAIN`, `FLICKER_TIGHTNESS`, `FLICKER_SPREAD`). Reads only existing decal uniforms + `u_decal_time` + the already-sampled glow map. (Shader-constant changes need a `cmake` reconfigure, not just `--build` — see CLAUDE.md.)
- No change to the decal ring, the decal upload path in `frame.cc` beyond what Phase 2 already uploads, the combat/attribution math, or the host-loop tick structure.

## 5. Testing

Mirrors the project's split (pure-Python unit tests; offscreen `FrameTest`/llvmpipe render tests that `GTEST_SKIP` without BC assets).

**Sparks — Python (`hit_feedback` / `hit_vfx`):**
1. `absorbed_hull` below `SPARK_HULL_THRESHOLD`, non-critical → `spark_count == 0`.
2. `absorbed_hull` above threshold → `spark_count > 0`; CRITICAL with sub-threshold damage → `spark_count > 0`.
3. `weapon_type == "torpedo"` vs `"phaser"` → correct tint enum + count/cone profile on the descriptor.
4. Descriptor carries `instance_id` and a body-frame `body_offset`/`body_normal` consistent with the world hit point under the ship's world matrix (round-trip within tolerance).
5. SHIELD-absorbed hit → no spark descriptor (unchanged SHIELD filtering).

**Sparks — renderer (`FrameTest`):**
6. A descriptor with a non-identity instance world matrix renders its burst origin at `world * body_offset` (hull-anchored), and re-rendering after mutating the matrix moves the origin accordingly.
7. Burst is gone after `_LIFETIME`; `glGetError() == GL_NO_ERROR` throughout.

**Flicker — renderer (`FrameTest`, seeding the ring directly as decals Phase-2 tests do):**
8. SCORCH decal at `age ≈ 0` → impact region's emissive differs from an undamaged baseline (modulation present, both brighter and darker fragments observable across the window).
9. Same decal at `age > FLICKER_DURATION` → impact region's emissive back to ~baseline **while the blackbody ember is still present** (flicker gone, ember unaffected).
10. HEAT_GLOW (phaser) decal → **no** flicker term applied.
11. Undamaged ship → byte-identical to pre-change baseline; `dauntless_decals` toggle off → no flicker.
12. Mirror-position SCORCH decal pair → flicker does not cross-contaminate the mirrored half (inherits `w_n`).

## 6. Parking lot (tune-by-eye)

- **Sparks:** `SPARK_HULL_THRESHOLD` (GU), severity→`spark_count` scaling, per-class speed/lifetime/cone half-angle, damping coefficient, whether disruptor gets its own tint (rides torpedo for now).
- **Flicker:** `FLICKER_DURATION` (~0.5s), `STUTTER_GAIN`, stutter frequency / waveform, `FLICKER_TIGHTNESS`, `FLICKER_SPREAD` (≥1).
- **Flicker edge cases (judged non-issues):** decal emission throttle (0.2s/ship/class) and merge-then-FIFO reset `birth_time` — fine for low-rate torpedoes (merge re-ignites the flicker). FIFO eviction mid-flicker needs 24 distinct hits within 500ms — accepted.
- **Sprite alternates:** `data/rough.tga` chosen; `spark.tga` / `smooth.tga` available if rough reads wrong at close camera range.

## 7. Non-goals

- **Persistent scorch / deposit / silhouette change** — decals spec.
- **Sustained, state-driven subsystem emitters** (nacelle venting, etc.) — decals spec Phases 3–4 (object-emitter machinery).
- **Tessellation / mesh smoothing** — separate brainstorm.
- **Bridge-interior shake / camera shake / impact audio** — already shipping via `hit_feedback.py`; unchanged.
- **Restyling the generic impact-flash billboard** — kept as-is (§3.6).
- **Save/load** of sparks, flicker, or the records they read — runtime-only (§3.8).
- **New emissive *colour* layer for the flicker** — explicitly rejected; the flicker modulates the ship's own glow map (power disruption), it does not add a hot-coloured layer (that is the SCORCH ember's job).

## 8. Workflow

This spec produces one implementation plan (sparks + flicker can be one session; they share the dispatch site but touch disjoint render paths). Plan via the writing-plans skill → `docs/superpowers/plans/`, execute via subagent-driven-development, merge to main. The flicker stacks on the decals Phase-2 work (it edits `opaque.frag`'s decal loop), so it sequences after Phase 2 lands; sparks have no such dependency and could ship first if convenient.
