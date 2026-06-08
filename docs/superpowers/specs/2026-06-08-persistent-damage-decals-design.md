# Persistent Damage Decals — Object-Space Design

**Status:** drafted, awaiting user review
**Date:** 2026-06-08
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-06-damage-attribution-design.md`](./2026-06-06-damage-attribution-design.md) — the upstream model. This spec consumes the per-hit `WeaponHitEvent` payload `(target, source, damage, hit_point, normal, radius, post_shield_damage, primary_subsystem)` that `engine/appc/combat.py:apply_hit` already broadcasts. **Attribution is locked and is not redesigned here.**
- [`2026-06-07-persistent-damage-vfx-design.md`](./2026-06-07-persistent-damage-vfx-design.md) — **superseded in full by this spec.** That design carried all persistent damage in a per-instance UV-space damage mask. It failed smoke testing for three reasons and is retained only as a record of what not to do (see §2.1).
- [`2026-06-01-damage-vfx-bridge-feedback-design.md`](./2026-06-01-damage-vfx-bridge-feedback-design.md) — interior / bridge-camera damage feedback (sound, shake). Out of scope here; this spec is purely exterior hull representation.
- [`2026-05-12-object-emitter-emission-design.md`](./2026-05-12-object-emitter-emission-design.md) — the object-emitter machinery that Phases 3 and 4 build on.

## 1. Goal

Represent persistent exterior hull damage on the modern engine **without UV-space damage masks** and without per-ship authored damage stages. Each weapon impact leaves an object-space decal record on the receiving ship instance; the hull fragment shader composites those records per fragment.

Two visual classes, driven by weapon type:

1. **Phaser → heat glow.** The armour took the hit without yielding; the hull merely heated and cools. A transient emissive bloom, no deposited matter, no permanent scar.
2. **Torpedo / disruptor → scorch.** The hull heated *and* matter was deposited and sprayed outward from the impact. A subtle, permanent (session-lifetime) soot deposit with radial ejecta, plus a blackbody ember that cools over ~10 s.

Scorch is deliberately a **secondary, subtle** cue. The eventual silhouette/tessellation work (a separate brainstorm — see §7) is what represents *structural* hull damage; the decals and the Python spark/gas emitters that anchor to them (Phases 3–4) are the surface dressing that sells each hit. The old UV attempt failed partly because its scorch was "very far from subtle" and was trying to carry the whole damage story itself.

This is multi-session work. Phases below are ordered by engineering dependency; each ships independently-testable software.

## 2. Diagnosis

### 2.1 Why the UV-space approach was abandoned

The superseded spec stored damage in a per-instance UV-space R8 texture and painted brushes at the hit's mesh UV. Smoke testing surfaced three failures:

1. **Mirrored UVs (architectural, fatal).** BC ships reuse the same UV region across mirrored hull halves to save texture memory. A hit on the port nacelle painted scorch on the starboard nacelle too. No amount of seam-table bookkeeping fixes this cleanly, because the two halves genuinely share UV coordinates.
2. **No visual detail.** The procedural brush produced uniform black splotches with no char / smoke character.
3. **Shield-gating bug.** Damage painted even when shields fully absorbed the hit — a one-line wiring error in the emission path.

Object-space decals dissolve #1 entirely: port and starboard hull halves occupy **distinct body-frame positions**, so a decal anchored in body space cannot appear on the mirrored half. #2 is addressed by the shader recipe in §4. #3 is addressed by the emission gate in §3.3.

### 2.2 What is already in place

- `WeaponHitEvent` is broadcast on every hit carrying mesh-accurate `(hit_point, normal)` in **world** space, the resolved `r_hit` splash radius, the post-shield damage, and the primary subsystem. (`engine/appc/combat.py:apply_hit`, lines 427–438.)
- The hit-feedback dispatch path (`engine/appc/hit_feedback.py`, called from `apply_hit`) already receives `host`, `ship_instances`, `point`, `normal`, `weapon_type`, and the `absorbed_shields` / `absorbed_hull` / `absorbed_subsystem` totals. This is the natural emission site for decal records — it already holds everything needed and already runs per hit.
- The hull fragment shader [`native/src/renderer/shaders/opaque.frag`](../../../native/src/renderer/shaders/opaque.frag) already interpolates `v_position_ws` (world position) and `v_normal_ws` (world normal) per fragment.
- Per-instance uniforms are set once per `draw_model` call in [`native/src/renderer/frame.cc`](../../../native/src/renderer/frame.cc) (lines 60–145), which receives the ship's world matrix as `world`. This is the decal-upload site.
- `host.ray_trace_mesh` already returns the surface point and normal. **The object-space approach needs nothing more from it** — no triangle index, no barycentrics, no per-vertex UVs. This is strictly less than the UV approach required.

### 2.3 What is missing

- No per-instance decal store on `ModelInstance`.
- No `host.damage_decal_add` binding, and no call from the hit path.
- No decal-compositing branch in the hull fragment shader.
- No sustained emitter bound to a decal-state predicate (Phases 3–4).

## 3. Locked design decisions

Settled in the brainstorm that produced this spec; not open for relitigation in implementation.

### 3.1 Object-space decal records are the single source of truth

Each renderer-side `ModelInstance` carries a fixed **24-slot ring** of decal records, stored in the ship's **body frame** so they track the hull as it moves and rotates:

```cpp
struct DamageDecal {
    glm::vec3 point_body;    // impact position, ship-local (body frame)
    glm::vec3 normal_body;   // surface normal, body frame
    float     radius;        // = r_hit from WeaponHitEvent (game units)
    float     intensity;     // accumulated severity; deposit darkness / future hole threshold
    float     birth_time;    // seconds; drives ember cooling
    uint32_t  weapon_class;  // HEAT_GLOW | SCORCH (padded; uint8 semantically)
};
```

Padded to 48 B for `std140` alignment → 24 × 48 B = **1.15 KB per ship instance**, allocated with the `ModelInstance`. (Contrast the discarded 256 KB–1 MB UV texture per ship.)

`point_body` + `normal_body` + `intensity` + `weapon_class` are exactly the inputs a future displacement/tessellation shader needs, so the record is **tessellation-ready without redesign** (§7).

### 3.2 Body-frame storage, body-frame compositing

Decals are stored and uploaded in body frame (static relative to the ship — **no per-frame transform of the decal list**). The fragment shader reconstructs the body-frame fragment position from the existing world-space varying:

```
p_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz
n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws)
```

`u_ship_world_inv` is `inverse(world)` uploaded once per `draw_model`, where `world` is the ship's world matrix (column-vector convention per CLAUDE.md). Compositing and all noise sampling happen in body space. This choice has two payoffs:

- **Hull-stable noise.** Noise indexed by `p_body` is fixed to the hull and does not swim as the ship rotates. (World-space relative vectors rotate with the ship and would shear the noise pattern.)
- **No per-frame decal math.** The uniform array is uploaded unchanged each frame; only `birth_time`-derived ember heat varies, computed cheaply.

Per-node local transforms inside the model are irrelevant: `u_ship_world_inv` maps any node's world fragment position back to the single ship body frame.

### 3.3 The emission gate (the shield-fix)

A decal record is created **only when hull damage was actually dealt** — i.e. `absorbed_hull > 0` (equivalently `post_shield_damage > 0`). Shield-absorbed hits produce their shield-flash VFX through the existing per-event path but **never** create a persistent decal. This is the corrected wiring for failure #3 in §2.1.

The emission call lives in the hit-feedback dispatch path and passes world-space data:

```
host.damage_decal_add(instance_id,
                      world_point, world_normal,
                      radius   = r_hit,
                      intensity = f(absorbed_hull),   # see §3.6
                      weapon_class = class_of(weapon_type))
```

`apply_hit` and the attribution math are **not modified** beyond plumbing `r_hit` and `weapon_type` through to dispatch (both are already broadcast on the event, so this is wiring, not redesign).

### 3.4 Two decal classes

`weapon_class` is derived from `weapon_type`:

| `weapon_type` | `weapon_class` | Behaviour |
|---|---|---|
| `"phaser"` | `HEAT_GLOW` | Emissive-only additive bloom. No deposit. Fades to nothing over `T_glow ≈ 1.2 s`, after which the slot is **reclaimed**. |
| `"torpedo"`, disruptor, default | `SCORCH` | Permanent spread-B deposit (dense core + triplanar-noise radial ejecta) plus a blackbody ember cooling over `T_ember ≈ 10 s`. Deposit persists for the session. |

Disruptors ride with `SCORCH` (deposited matter) until a future spec says otherwise.

### 3.5 Eviction: merge-then-FIFO

On a new hit:

1. **Merge.** If a **same-class** existing decal lies within `0.5 × radius_new` of the new impact (body-frame distance), deepen that decal instead of allocating: `intensity += Δ` (clamped), and reset its `birth_time` so the ember re-ignites. Co-located repeat fire deepens rather than consuming slots.
2. **Allocate.** Otherwise take a free slot.
3. **Evict.** If no free slot, overwrite the **oldest** decal (FIFO).

`HEAT_GLOW` decals that have fully cooled (`age > T_glow`) are reclaimed each frame before allocation runs, so phaser fire cannot starve the ring.

### 3.6 Intensity mapping

`intensity` scales with the hull damage actually dealt (`absorbed_hull`), normalised against a per-class reference so a single torpedo reads as a clear scar and a glancing phaser tick reads faint. Exact curve is a Phase-2 tuning constant (a parking-lot item, §6 Q1); the contract is monotonic in `absorbed_hull` and clamped to `[0, 1]`.

### 3.7 Runtime-only — not serialized

The decal ring is runtime VFX state. It is **not** written to BCS saves. After load, hull damage is implied only by subsystem condition (as in stock BC), and the ring rebuilds organically as combat resumes. This keeps decals out of the partially-reverse-engineered save format.

### 3.8 Shader iteration mechanism

A plain **uniform array** (`std140`, 24 × 3 vec4 ≈ 72 vec4), uploaded per `draw_model`. Desktop GL 3.3 guarantees far more fragment-uniform capacity than that. A per-fragment loop over ≤24 decals with a distance + normal early-out is negligible even across a fleet. UBO/SSBO/texture-buffer paths are unnecessary because merge-then-FIFO caps the count at 24; they are not used.

## 4. The hull shader recipe

Extends `opaque.frag`. For each live decal `i`, compute body-frame offset `d = p_body − point_body[i]`, radial distance `r = length(d)`, and:

### 4.1 Normal-aware falloff (the mirroring fix)

```
facing = max(dot(n_body, normal_body[i]), 0.0);   // back-faces contribute nothing
w_n    = smoothstep(NORMAL_MIN, 1.0, facing);
```

A decal whose stored normal faces opposite the fragment's surface contributes zero. This is what prevents bleed onto a geometrically-distinct surface that happens to be nearby, and — combined with body-frame anchoring — is why mirrored hull halves never cross-contaminate. The fix is **geometric, not UV-dependent**.

### 4.2 Radial shape — spread B (torpedo)

```
ring   = exp(-r*r * CORE_TIGHTNESS);               // dense central deposit
ejecta = radial_streaks(d, p_body);                // triplanar-noise striations,
                                                   //   reach varies per direction,
                                                   //   thinning with r
deposit = clamp(ring + ejecta, 0, 1) * intensity[i] * w_n;
```

`radial_streaks` samples multi-octave value noise indexed by `p_body` (hull-stable) and by impact direction, so matter sprays outward in irregular streaks that thin with distance — the spread-B look validated in the visual companion. Deposit colour is a dark warm-grey soot, composited over the base hull colour (not additive).

### 4.3 Blackbody ember (torpedo)

```
heat = ember_curve(age_i);    // age_i = u_time - birth_time[i]; exp-ish decay over ~10 s
glow = (exp(-r*r*EMBER_BROAD) + exp(-r*r*EMBER_TIGHT)) * heat;
emissive += blackbody(heat) * glow * w_n;          // white→yellow→orange→red→black ramp
```

`blackbody(heat)` walks a control-point ramp (white-hot → yellow → orange → red → deep ember → black). The curve dwells in the reds as it cools; `T_ember ≈ 10 s` to fully black. Emissive feeds the existing HDR/bloom path so fresh hits bloom.

### 4.4 Heat glow (phaser)

```
glow = exp(-r*r*GLOW_TIGHTNESS) * (1.0 - age_i / T_glow);   // additive, no deposit
emissive += blackbody(glow_heat) * glow * w_n;
```

Pure additive emissive bloom, no deposit composite. Cools and vanishes in ~1.2 s; the slot is then reclaimed (§3.5).

### 4.5 Instances without damage

A ship with an empty ring uploads `decal_count = 0`; the loop runs zero iterations and the hull renders exactly as today. No branch cost beyond the count check.

## 5. Phases

Each phase is an independently-shippable session: plan → implement → merge.

### Phase 1 — Decal store + plumbing (no shader read)

- Add the 24-slot ring to `ModelInstance` (C++).
- Add the `host.damage_decal_add(instance_id, world_point, world_normal, radius, intensity, weapon_class)` binding: resolve the instance, transform world→body via `inverse(ship_world)`, apply merge-then-FIFO (§3.5).
- Wire the call into the hit-feedback dispatch path, **gated on `absorbed_hull > 0`** (the §3.3 shield-fix). Plumb `r_hit` and `weapon_type` → `weapon_class` through dispatch.
- Per-frame aging pass: reclaim cold `HEAT_GLOW` slots; no rendering yet.
- Tests: a synthetic hit at a known world point writes a body-frame record at the expected position; a shield-absorbed hit writes nothing; two co-located same-class hits merge (one slot, deeper intensity); 25 distinct hits evict the oldest; a port-side and starboard-side hit at mirror positions produce two records at distinct body-frame coordinates.

Visual result: none. Substrate only.

### Phase 2 — Scorch + heat-glow shading

- Extend `opaque.frag` with the decal uniform array, `u_ship_world_inv`, `u_time`, and the §4 recipe (normal-aware falloff, spread-B deposit, blackbody ember, phaser glow).
- Upload the live decal array + `u_ship_world_inv` per `draw_model` in `frame.cc`.
- Tests: render a known-damaged ship and sample the framebuffer — torpedo region shows a soot deposit; phaser region shows an emissive bloom that is gone after `T_glow`; a mirror-position decal pair does **not** cross-contaminate (the regression that killed the UV approach); an undamaged ship renders byte-identical to baseline.

Visual result: subtle scorch + heat glow appear where hits land. The mirroring bug is gone. This is the spec's primary visual payoff.

### Phase 3 — Impact-site emitters (Python)

- New module under `engine/appc/` for sustained impact-site emitters, built on the object-emitter machinery ([`2026-05-12-object-emitter-emission-design.md`](./2026-05-12-object-emitter-emission-design.md)).
- Per tick, per ship, sample the decal ring; where a `SCORCH` decal's intensity exceeds a threshold and no emitter is bound there, spawn a spark/gas emitter anchored to that body-frame position. Randomised emit angle and lifetime.
- Despawn when intensity drops below threshold (repair) or the instance is destroyed.
- Reads the same store Phase 1 populates; a read-only host binding exposes the ring to Python.
- Tests: a ship with painted `SCORCH` damage at known positions spawns the expected emitter count; clearing damage despawns them; `HEAT_GLOW` decals never spawn emitters.

Visual result: damaged hulls leak sparks and gas from torpedo impact sites — the layer that, with the decal, sells the hit.

### Phase 4 — Subsystem-driven emitters

- Extend the Phase 3 module with predicate/anchor pairs registered per (ship-class, subsystem). Defaults: warp nacelles vent while `WarpEngines.IsDamaged() and not IsDestroyed()`; impulse engines smoke while damaged; warp core sparks while critical.
- Anchor via `subsystem.GetPosition()` → world through `_subsystem_world_position` (already in `combat.py`).
- Optional duration cap to match the original modder behaviour.
- Tests: damage a Galaxy's warp engines, advance ticks, assert an emitter appears at the nacelle; clear damage, assert it fades.

Visual result: damaged subsystems visibly vent — nacelles, impulse engines, warp core.

## 6. Parking lot

- **Q1 — intensity curve (§3.6).** Exact `f(absorbed_hull) → [0,1]` mapping and the per-class reference damage. Tune in Phase 2 by eye; the contract (monotonic, clamped) is fixed.
- **Q2 — merge radius constant.** `0.5 × radius_new` is the starting point; may want per-class values (phaser glows merge more eagerly than torpedo scars). Revisit in Phase 2.
- **Q3 — shader constants.** `CORE_TIGHTNESS`, `EMBER_BROAD/TIGHT`, `GLOW_TIGHTNESS`, `NORMAL_MIN`, `T_glow`, `T_ember`, and the blackbody control points are tuning values, finalised against real ships in Phase 2. Shader-constant changes require a `cmake` reconfigure (not just `--build`).
- **Q4 — emitter pooling (Phase 3).** A heavy fleet engagement could spawn many sustained emitters; the object-emitter system may need a global cap / per-instance priority. Investigate in Phase 3.
- **Q5 — per-instance ring GC.** Free the ring (trivial, it's inline in `ModelInstance`) on instance destruction; ensure no dangling emitter bindings (Phase 3+).
- **Q6 — noise source.** Whether to sample an existing `Noise1-3.tga` triplanar or generate value noise procedurally in-shader. Procedural avoids a texture bind; decide in Phase 2.
- **Q7 — directional ejecta bias.** A real torpedo throws matter along its travel vector. The record carries enough to bias the spread along the incoming direction later; spread-B is currently radially symmetric. Polish item.

## 7. Downstream: silhouette / tessellation (separate brainstorm)

Real structural damage — dents and holes that change the ship's silhouette — is **explicitly out of scope here** and gets its own brainstorm and spec. This spec only guarantees the decal record is a sufficient input for it: `point_body` (where), `normal_body` (displacement direction), `intensity` (how deep / whether to punch through), and `weapon_class` (torpedo punches, phaser does not) are already carried. A future tessellation/displacement pass consumes the same ring with no record-format change. No tessellation pipeline work happens under this spec.

## 8. Non-goals

- **UV-space damage masks.** Superseded; see §2.1.
- **Authored per-ship damage stages.** Everything derives from the runtime ring and existing subsystem state.
- **Save/load of decals.** Runtime-only (§3.7).
- **Structural silhouette change / tessellation.** Separate brainstorm (§7).
- **One-shot hit-flash / shield ripple / spark burst per impact.** Those remain in `engine/appc/hit_feedback.py` / `hit_vfx.py`, fire per-event, and do not accumulate. This spec covers only what persists between ticks.
- **Bridge-interior damage feedback.** Covered by `2026-06-01-damage-vfx-bridge-feedback-design.md`.
- **Repair animations.** Intensity can drop (clearing a decal), but the animated transition is not designed here. Stock BC had none.

## 9. Workflow

This spec produces four independently-plannable sessions (Phases 1→4 in order). Each starts from the brainstorming-skill flow against this spec, produces a plan in `docs/superpowers/plans/`, executes via subagent-driven-development, and merges to main. When a phase ships, annotate its section with `shipped $DATE` and fold any resolved parking-lot question into §6.
