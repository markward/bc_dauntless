# Volumetric Nebulae + Tactical Density — Design

**Date:** 2026-06-23
**Status:** Design approved, pending spec review
**Builds on:** the shipped nebula pockets V1 (`docs/superpowers/specs/2026-06-22-nebula-pockets-design.md`, merged `343d8003`). This is the "modern volumetric" round that V1's `NebulaPass::Style{FAITHFUL,VOLUMETRIC}` seam and `set_nebulae` data contract were built to carry.

---

## 1. Vision (Mark's words, paraphrased)

Flying through a nebula should feel like flying through a **thundercloud of charged
particles**. The cloud has **varying density** — you can fly *around* thick clumps to
keep visibility, or *into* them to **hide from enemies**. Your hull should be
**partially obscured** by the cloud in front of you (the V1 gripe: V1 left the hull
crisp). Distant white light pulses, localised hull discharges, and a ship wake are part
of the full dream but are **sequenced follow-ons** (see §8 roadmap).

This project = **the volumetric cloud core + the tactical density gameplay**, because a
single **density field** is what the renderer draws *and* what the stealth check reads —
defining it once, shared, is the whole point.

## 2. Scope

**In scope (this project):**
- A shared, deterministic **fbm density field** bounded by the V1 nebula sphere-union.
- A **raymarched volumetric cloud** (sun-lit single-scatter + self-glow, depth-correct
  hull obscuration) behind the Modern VFX toggle.
- **Tactical density gameplay**: local density → concealment (detection-range falloff +
  lock-break threshold), extending V1's sensor model.
- Converting the HDR target's depth to a sampleable texture (enabler for the above).

**Out of scope (deferred follow-ons, §8):** ② thunder / distant light pulses +
crepuscular rays, ③ localised hull electrical discharges, ④ ship wake. Weapons already
in flight ignore concealment this round.

## 3. Decisions (from brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| Density field | **Procedural 3D fbm**, one formula+seed per nebula, bounded by sphere-union, slow drift | GPU raymarch and CPU stealth evaluate the SAME function → agree by construction; no assets; organic clumps |
| Stealth model | **Concealment range falloff + lock-break threshold**, all ships | Skim a clump for partial cover, bury into the core to vanish; symmetric |
| Toggle vs gameplay | **Gameplay always-on; Modern VFX toggle = visual only** | Consistent with V1 (nebula gameplay never depended on graphics); settings/MP-independent; deterministic field means "what you see thick IS where you're hidden" |
| Cloud lighting | **Sun-lit single-scatter + self-shadow + nebula self-glow**, lit by **up to 4 directional lights** | Real 3D form so clumps read as navigable structure; the 4-light model reserves slots for the ② thunder pulses (no rework later); crepuscular rays fall out of the same math |
| Rendering architecture | **Post-process half-res raymarch reading a converted depth texture** | Standard volumetric approach; depth read stops the march at hulls → obscures the player ship (the V1 gripe fix) |

## 4. Architecture

**Post-process raymarch reading scene depth.** After the scene renders to the HDR
target, a half-res pass marches front-to-back through the fbm field bounded by the
sphere-union, reads scene depth to stop at hulls, and composites into the HDR colour
before the post chain (filmic/bloom/SMAA) — so bloom blooms the bright sunlit edges (and
later the thunder flashes).

Rejected: in-scene geometry raymarch (V1 style, depth-tested) — reintroduces the V1
limitation (can't obscure the player hull); analytic billboards/impostors — not
immersive.

### Components

| Unit | Location | Responsibility |
|---|---|---|
| **Density field** (shared core) | `nebula_density.h` (GLSL snippet) + a **Python** CPU mirror (fbm in Python is cheap at BC ship counts) | `density(p) = sphere_union_falloff(p) · saturate(fbm(p·freq + drift·t)·gain − floor)`. One formula, one seed per nebula. GLSL and CPU are necessarily two implementations of one spec; the **parity test** (§7) is the anti-drift guard. The GPU/CPU **contract**. |
| **HDR depth texture** | `native/src/renderer/hdr_target.{h,cc}` | Depth RBO → depth **texture** + `depth_texture()` accessor. Single-sample target; depth-attachment semantics unchanged for existing depth-testing passes. |
| **Volumetric pass** | `native/src/renderer/nebula_volumetric_pass.{h,cc}` + `shaders/nebula_volumetric.frag` (+ a fullscreen vert) | Half-res front-to-back raymarch; single-scatter from up to 4 directional lights + self-glow; depth-aware stop; dithered + temporally-reprojected; depth-aware upsample + composite into HDR. Selected by `NebulaPass::Style::VOLUMETRIC`. |
| **Concealment model** | `engine/appc/nebula_runtime.py` (extend the existing `NebulaTracker`) | Per tick: CPU-sample density at each ship → `concealment`; apply detection-range falloff; break/deny AI lock past threshold (with hysteresis). Always-on. |
| **AI/sensor integration** | the BC sensor / `SelectTarget` acquisition path (pinned during planning) | Concealment folds into the same detection-range check V1's `sensor_density` touches; lock-break gates target acquisition/retention. |
| **Toggle wiring** | Modern VFX config group + `set_nebulae` payload | "Volumetric Nebulae" toggle (default on) picks VOLUMETRIC vs FAITHFUL **visual**; payload gains the fbm dials + per-nebula seed. |

**Boundaries:** the density field is a pure function (no state, no GL) with two consumers
that never touch each other — the raymarch (pixels) and the concealment model (gameplay).
The depth-texture change is isolated to `hdr_target`. The volumetric pass slots into the
existing `NebulaPass` Style seam; V1's faithful path is untouched.

## 5. Density field & cloud rendering

### Shared field
```
density(p) = sphere_union_falloff(p) · saturate( fbm(p·freq + drift·t) · gain − floor )
```
- `sphere_union_falloff` — smooth 0→1 ramp inward from each `AddNebulaSphere` boundary; keeps the cloud bounded by the authored pockets and soft at the rim.
- `fbm` — 3–4 octaves of gradient noise. `freq`/`gain`/`floor` = clump dials (size, contrast, and how much empty space between clumps so you *can* route around them). `drift·t` slowly advects it.
- **One seed per nebula** (derived from its world position) → deterministic, stable, MP-consistent.
- GLSL in `nebula_density.h`; CPU mirror is a line-for-line port. **A parity test asserts they agree at sample points** — the GPU/CPU contract must not silently drift.

### Raymarch (volumetric pass)
- Front-to-back from the camera through the sphere-union, **half-resolution** into a separate buffer.
- Per step: sample `density`; accumulate **single-scatter** from up to 4 directional lights, each attenuated by a cheap occlusion estimate (a few short steps toward the light, or a precomputed factor) so dense cores self-shadow and sunward edges glow; add nebula **self-glow** (rgb·density) + ambient. Standard transmittance/accum, early-out when transmittance saturates.
- **Depth-aware stop:** clamp each ray to scene depth (new depth texture) → hulls (incl. the player ship in front) occlude and bury into cloud. **The gripe fix.**
- **Cost control:** half-res + blue-noise/dither step offset + temporal reprojection (reuse last frame when the camera barely moved) + bounded max steps; depth-aware upsample; composite into HDR before filmic/bloom.
- **Tuning dials** ("calibrate up then down"): clump `freq`/`gain`/`floor`, drift speed, scatter strength, self-glow, step count — start strong, dial at Vesuvi4 / Multi5.

### Performance honesty
Half-res self-shadowed raymarch is the expensive part. Cheap levers, in order: the
light-occlusion estimate (cheap vs none), step count, temporal reuse. All explicit
constants. Pass is **gated off entirely when the toggle is off** (V1 path, zero cost).

## 6. Tactical-density gameplay

Two complementary halves of one fiction:
- **Observer side (V1, shipped):** a ship's own sensor range is scaled down inside a nebula (`sensor_density`) — "your sensors are degraded in the soup."
- **Target side (new):** how detectable a ship is — "you're buried in a clump." Per tick, CPU-sample the field at each ship → `concealment ∈ [0,1]`.

Both compound, which reads exactly like the dream.

In the existing `NebulaTracker` (already walks every ship in the set each tick):
- **Detection-range falloff:** detect/lock range × `(1 − k·concealment)`. Skim → partial cover; core → near-zero.
- **Lock-break threshold:** above density `T`, AI cannot acquire a lock on that ship and an existing lock breaks ("vanish into the thunderhead"). **Hysteresis/grace timer** prevents boundary flicker.
- **Symmetric & deterministic:** all ships; same fbm the GPU draws → what you see thick IS where you're hidden. Always-on, settings-independent.

**Integration seam (pin during planning):** read the BC sensor / `SelectTarget`
acquisition path; fold the detection-range factor into the same range check V1's sensor
scaling touches; gate acquisition/retention for lock-break. Do not guess the hook now.

**Out of scope:** weapons already in flight keep current behaviour (guidance-vs-
concealment is a possible later follow-on).

## 7. Toggle, integration & testing

**Toggle:** new **"Volumetric Nebulae"** row in the Modern VFX config group, default
**on** (off/off = stock BC). Selects VOLUMETRIC vs FAITHFUL **visual** only; `set_nebulae`
gains fbm dials + per-nebula seed. Toggle off → volumetric pass never constructed/run (V1
byte-identical). Concealment runs regardless of toggle.

**Testing:**
- **Density parity (critical):** unit test — CPU mirror vs GLSL `nebula_density.h` agree at sample points.
- **Concealment (pytest):** fake ships at known field positions → range-falloff + lock-break/hysteresis fire at thresholds; symmetric; deterministic; toggle-independent; no effect outside nebulae.
- **Volumetric pass (C++ FrameTest):** camera inside a seeded field → cloud renders with visible density variation; hull in front correctly obscured; empty/disabled → zero output (byte-identity).
- **Depth texture:** existing depth-testing passes (hulls, dust, shield) still correct after the RBO→texture conversion.
- **Live (Mark's workstation):** Vesuvi4 / Multi5 — fly around clumps, bury into a core, confirm an enemy loses lock; tune dials.

## 8. Roadmap (deferred follow-ons — kept so the dream stays intact)

Each is its own spec→plan→build; ① (this project) is built to make them cheap.

- **② Thunder & light-shafts** — animate the 4 directional light slots as occasional distant white pulses (brighten→dim over a few seconds); crepuscular rays fall out of the existing single-scatter. Needs nothing new in the raymarch.
- **③ Hull electrical discharges** — short-lived additive arcs against the hull (hit_vfx-style, ease-in/fade, ~frames), casting light onto the hull; **rate ∝ the cloud's damage rate**, with occasional strikes even at zero damage.
- **④ Ship wake** — carve/advect the density field behind the ship so it visibly disrupts the cloud it flies through.

## 9. Key risks

- **Depth-texture conversion** touches the HDR target everything renders into — low-risk (single-sample, attachment semantics unchanged) but its FrameTest verification is a real gate, not a formality.
- **Performance** of the half-res self-shadowed raymarch is the genuine unknown; the design front-loads the cheap levers so it can be dialed to Mark's hardware.
- **GPU/CPU density drift** would desync visuals from gameplay; the parity test is the guard.

## 10. Key references

- `docs/superpowers/specs/2026-06-22-nebula-pockets-design.md` + plan — V1 foundation.
- `native/src/renderer/nebula_pass.{h,cc}` — V1 pass + the `Style` enum seam.
- `native/src/renderer/include/renderer/frame.h` (`Lighting`, `MaxDirectionals`) + `opaque.frag` (`MAX_DIR_LIGHTS = 4`) — the 4-light model.
- `native/src/renderer/hdr_target.{h,cc}` — depth RBO to convert. See memory `reference_hdr_depth_rbo`.
- `native/src/renderer/hit_vfx_pass.h` — precedent for ③ (short-lived additive billboards).
- `native/src/renderer/dust_pass.cc` / `ParticleEmitterDescriptor` — precedent for ④ (wake).
- `engine/appc/nebula_runtime.py` — V1 `NebulaTracker` (sensor scaling) to extend for concealment.
