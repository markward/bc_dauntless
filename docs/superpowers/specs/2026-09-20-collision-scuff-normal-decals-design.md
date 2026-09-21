# Collision scuff decals — procedural normal + albedo (design)

**Date:** 2026-09-20
**Status:** implemented 2026-09-20 (gate green); awaiting live verification (Damage Preview + QuickBattle ram/grind)
**Area:** damage decals (`scenegraph::DamageDecalRing`, `opaque.frag`), collision response (`engine/appc/collisions.py`)

## Goal

A ship-to-ship collision must leave a visible mark on the hull at the contact,
at every speed. Today a low-speed bump or grind leaves either nothing readable
or the wrong thing; only a hard impact carves a hole. The mark should read as
**scraped, scuffed, slightly buckled metal** — small-scale relief and bare-metal
scratch lines — without moving any geometry.

This closes the gap left open by the abandoned hull-dent work
(`project_hull_dents_abandoned`): vertex displacement on BC meshes (~20 model
units between vertices) can only produce a broad sag. Relief at the scale a
collision actually produces has to be a **fragment-space illusion**, and the
normal-map path shipped 2026-08-20 gives us the lighting hook for it.

## What exists today (measured in the tree, not assumed)

- Collisions route impact damage through `combat.apply_hit(..., weapon_type=None)`
  ([collisions.py:434](../../../engine/appc/collisions.py#L434), grind at
  [collisions.py:293](../../../engine/appc/collisions.py#L293)).
- `damage_decals.weapon_class_for(None)` returns **`WEAPON_CLASS_SCORCH`**, so
  every scrape already deposits a torpedo-style soot decal **with a blackbody
  ember and power-flicker**, at the phaser-default radius (0.15 GU × 2.25) —
  `apply_hit` has no weapon to read a radius from. That is the visual that
  reads wrong today, not an absence of a decal.
- Carve strength accumulates on every collision hit and shows a hole only once
  the field crosses the C++ iso — hence "holes only at high speed". This is
  correct and is **not changed** by this design.
- Decals are **object-space rings evaluated per fragment** in `opaque.frag`
  (`apply_damage_decals`, called *after* lighting, modifies `lit`). There is no
  projected decal geometry. Class is discriminated in the shader by
  `u_decal_c[i].y` (`< 0.5` HeatGlow, `> 0.5` Scorch).
- `perturb_normal` (material `_normal.tga`) produces `n_shade`, which feeds
  directional + dynamic diffuse/specular and the ambient gradient, and must
  **not** feed the shadow bias, the Fresnel rim, `n_body`, or the carve loop.
- The grind path already computes the tangential slip vector
  ([collisions.py:262](../../../engine/appc/collisions.py#L262)); the impact
  path has the contact normal and relative velocity.
- `DamageDecalRing`: 24 slots, merge within `0.5·radius` (Scorch only),
  eviction prefers the oldest HeatGlow, else oldest overall.

## Decisions (from brainstorming, 2026-09-20)

| Question | Decision |
|---|---|
| Normal source | **Procedural in-shader** (analytic height field, closed-form gradient). No texture asset, no authoring-convention traps. |
| Colour term | **Light albedo scrape**: bare-metal lightening confined to scratch lines + a faint grime fill (revised from a rim ring after the first live pass, see §4). No ember, no flicker, no emissive. |
| Patch size | **From contact geometry**: chord of the overlapping hull pieces, clamped to a band. |
| Ring integration | **New class in the existing ring**, not a second ring. |

## Design

### 1. Routing — collisions get their own decal class

- `scenegraph::WeaponClass::Scuff = 2` (`damage_decals.h`); Python mirror
  `WEAPON_CLASS_SCUFF = 2` in `engine/appc/damage_decals.py`.
- `collisions.py` passes `weapon_type="collision"` on both the impact and grind
  `apply_hit` calls. `weapon_class_for("collision")` → Scuff. All other inputs
  keep their current mapping (`"phaser"` → HeatGlow, everything else → Scorch),
  so torpedo/disruptor/splash/warp-core-breach callers are unaffected.
- Audio (`_play_audio`) and smoke (`hull_hit_smoke.maybe_emit`) key on
  `"phaser"` / `"torpedo"` explicitly; `"collision"` lands in the same branch
  `None` does today. **No audible or smoke behaviour changes.** A test pins
  this (`"collision"` and `None` produce identical audio/smoke decisions).
- The host binding's guard `if (weapon_class > 1u) return;` becomes `> 2u`.
- Carve accumulation is untouched: a hard impact scuffs **and** carves.

### 2. Ring policy

- Scuff is **persistent**, same tier as Scorch. Eviction rule generalises from
  "protect Scorch from HeatGlow" to "protect persistent classes from HeatGlow":
  evict the oldest HeatGlow first; if none, evict the oldest overall (Scorch or
  Scuff alike). `tick()` never reclaims a Scuff.
- Scuff **merges** like Scorch: a same-class decal within `0.5·radius` deepens
  intensity, takes the fresh normal **and tangent**, and refreshes `seq`.
  `birth_time` is refreshed too but is unused by the Scuff shader path.
- Streaks need no new geometry: a grind emits at most one decal per 0.2 s
  (`DECAL_EMIT_INTERVAL`), so consecutive decals further apart than `0.5 r`
  allocate new slots and form a chain of circles overlapping at ≥ `0.5 r`
  spacing. Overlapping scuffs share the same slip tangent, so the ripple
  pattern is continuous across the chain, and the shader composites them as
  a **union** (§4) so the chain reads as one scrape rather than a row of
  stamps. Capsule/ellipse records are explicitly **out of scope**.

### 3. Data — one field, one uniform array, one kwarg chain

`DamageDecal` gains `glm::vec3 tangent_body` (unit, body frame, orthogonal to
`normal_body` by construction at insert: `t − n·(t·n)`, renormalised; if that
collapses, a deterministic perpendicular of `n`).

Upload (`frame.cc`): a fourth array `u_decal_d[i] = (tangent_body.xyz, 0)`
alongside `a/b/c`. `MAX_DECALS` stays 24.

Binding: `damage_decal_add(..., weapon_class, time, world_tangent=(0,0,0))`.
The tangent is transformed with `world_dir_to_body` like the normal and handed
to `DamageDecalRing::add`, which owns the orthogonalise-or-derive step (so the
C++ ring tests cover it). A zero tangent means "derive a perpendicular from
the normal". Defaulted so weapon
callers do not change. The façade wrapper is `engine/host_io.damage_decal_add`
(it already lists the binding, so no manifest change — only the wrapper gains
`world_tangent=None`). ⚠️ The four unit-test spies that mirror this wrapper's
positional signature (`test_decal_emission.py`, `test_apply_hit_intensity.py`
and the lambdas in `test_hit_vfx_flash_anchor.py` / `test_combat_cheats.py`)
must accept the new keyword in the same change.

Python thread: `apply_hit(hit_tangent=None, decal_radius=None)` → `hit_feedback.dispatch(tangent=None, decal_radius=None)`
→ `host_io.damage_decal_add(world_tangent=…)`. `hit_tangent` is a world-space
`TGPoint3` or `None`.

Tangent source in `collisions.py`:
- **grind**: the existing slip vector `(tx, ty, tz)` (per-ship sign follows the
  normal handed to that ship, so the scratch direction on each hull is the
  direction the *other* hull moved across it).
- **impact**: relative velocity with its normal component removed. If its
  length is below `1e-6`, pass `None` (the ring's `add` then derives a stable
  perpendicular of the normal — a dead-on bump has no preferred direction).

The tangent's SIGN is visually unobservable: the shader's relief is driven by
`sin(k·u+φ)` and a symmetric noise field with a hashed phase `φ`, so `+T` and
`-T` produce the same pattern class on screen. The per-hull sign convention
above (each ship's scratch runs the way the *other* hull moved across it) is
tested in Python (it decides which value lands in `tangent_body`), but it
cannot be confirmed by looking at a rendered scuff — it would only matter if
a future asymmetric directional term (e.g. a one-sided highlight along +T)
were added to the shader.

Radius: `scuff_radius_gu = clamp(sqrt(2 · R_min · pen), SCUFF_RADIUS_MIN_GU, SCUFF_RADIUS_MAX_GU)`
where `R_min` is the smaller of the two overlapping pieces' scaled radii and
`pen` their overlap (`_deepest_piece_overlap` already computes both; the
whole-bound fallback uses the two root radii and `sum_r − dist`). Computed once
in `_respond_pair` and handed to `_grind_contact`, then passed as
`apply_hit(decal_radius=scuff_radius_gu)` — a **new, decal-only kwarg**
forwarded to `dispatch(decal_radius=…)`, which uses it in place of `radius`
for the `damage_decal_add` call when set. ⚠️ It must NOT travel as
`splash_radius`: `r_hit` also sets the subsystem-damage catchment
([combat.py:816](../../../engine/appc/combat.py#L816)), the carve influence
radius and `WeaponHitEvent.SetRadius`, so reusing it would widen collision
*damage*. Collisions keep today's `r_hit` (the 0.15 GU default) for all of
those. Band `[0.1, 0.5]` GU — **a tuning constant, judged live**. (The
first pass shipped `[0.5, 4.0]`: a Galaxy is only ~±1.8 GU long, so the old
minimum was a 100-model-unit stamp and clamped every real chord UP; ship-piece
contacts chord to ~0.1–0.3 GU.)
`decal_radius_scale(SCUFF) = 1.0` (the chord already is the visual size).

Intensity: the existing `decal_intensity(absorbed_hull)` mapping. Grind ticks
are tiny per frame, so merges accumulate a scuff's intensity over a sustained
scrape, which is the desired read (a longer grind looks worse).

### 4. Shader — a pre-lighting scuff pass

`opaque.frag` splits the decal work into two passes over the ring:

1. **`apply_scuffs(p_body, n_body, inout n_shade, inout base_rgb)`** — runs
   immediately after `n_shade` is produced (after `perturb_normal`, before any
   lighting term). Skips every class except Scuff.
2. The existing **`apply_damage_decals`** (post-lighting) gains an explicit
   `if (u_decal_c[i].y > 1.5) continue;` at the top of its loop. ⚠️ Without
   this, the current `> 0.5` Scorch test silently treats Scuff as Scorch and
   the ember/flicker come back.

`p_body` is currently computed after `n_shade`; it moves up so both are
available (pure reorder, no value change).

Per Scuff decal, in the local frame:

```
dn   = u_decal_b[i].xyz              // body-frame outward normal (stored)
t    = u_decal_d[i].xyz              // body-frame tangent, ⟂ dn by construction
T    = t;  B = cross(dn, t)          // right-handed local frame on the hull
d    = p_body - point
u    = dot(d, T);  w = dot(d, B)     // model units
r    = length(d) / radius            // 0 centre .. 1 edge
edge = fbm((u, w) · k_e) · bl_e · r²       // noise-broken edge; inward-only, band-limited, fades in with r
r_n  = r · (1 + kScuffEdgeNoise · edge)     // r_n >= r, so the r >= 1 cull stays exact
win  = (1 - smoothstep(0.25, 1.0, r_n)) * intensity * wn
wn   = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn))   // same far-face guard as the other classes
```

**The relief is a splatted normal map, not a procedural height field.**
(Eighth live pass, 2026-09-21: every procedural version — scratches +
buckle waves, then a crumple of dished facets on a mesh-oriented panel grid —
read as a stencil or a grid, however it was aligned. Mark supplied a 2048²
crumpled-sheet-metal normal map instead; use it as is.) The map is a project
asset, `native/assets/textures/scuff_normal.png` (or `.tga`; OpenGL +Y
green, `kScuffFlipGreen` if not), loaded once per GL session by
`renderer/scuff_texture.{h,cc}` (`ensure_scuff_normal_texture`, mipmapped,
`GL_REPEAT`) against a new **project asset root** — `renderer::
set_project_asset_root`, pushed at boot beside `set_game_root` from
`engine.paths.project_asset_root()` (`<checkout>/native/assets`), because the
binary only knew BC's install. Bound on unit 7 (assigned once in `Pipeline`'s
constructor) only while a decal is present; absent or undecodable ⇒ logged
once, `u_scuff_map_ok = 0`, and the scuff draws its albedo terms with no
relief rather than vanishing.

Per scuff, in the slip frame:

```
scale = kScuffTexSpan / (2 · radius)                 // uv per model unit
off   = (hash(point.xy + point.z), hash(point.yz + point.x))   // a different patch per scuff
uv    = (u, w) · scale + off
s     = textureGrad(u_scuff_map, uv, duv/dx, duv/dy) · 2 − 1   // explicit gradients: the loop
                                                                // `continue`s per decal, so implicit
                                                                // LOD is undefined; dp/dx, dp/dy
                                                                // are taken once before the loop
s.z   = max(s.z, 0.05)
gain  = kScuffRelief · mix(kScuffGrindRelief, 1, dent)
g     = (s.xy / s.z) · gain · win                     // slope: n' ∝ n + (x/z)·T + (y/z)·B
crease = smoothstep(0.1, kScuffMetalTilt, |s.xy|) · win
```

Each scuff is therefore a differently placed patch of the same sheet,
rotated by its own slip direction — no two are the same stamp. `dent`
(`u_decal_c[i].z`; impact 1 / grind 0, merges keep the max, threaded
`collisions → apply_hit(decal_dent=) → dispatch(decal_dent=) →
host_io.damage_decal_add(dent=) → binding → ring`) now only scales the relief
gain. Mipmaps are the band limit at range; the edge noise is still
band-limited by `scuff_bandlimit(fwidth(p_body) …)`, taken once before the
loop in uniform control flow, and fades in with `r²` so the plateau stays a
plateau (multiplicative noise alone mottled the grime in the core).

Accumulation and perturbation (once per fragment, after the loop):

```
over  = 1 - cov                            // "over" compositing: what this scuff may still add
dn_ws += (g.x·T_ws + g.y·B_ws) · over      // T_ws = normalize(R · T), B_ws = normalize(R · B), R = u_ship_world_rot
metal_mask += crease · over                // NOT max: two patches' max is brighter than either
cov   += win · over                        // union coverage of every scuff so far
n_shade = normalize(n_shade + dn_ws)       // once, after the loop
```

Scuffs composite as a **union, not a sum**: the first live pass summed the
relief, re-mixed the bare metal and multiplied the grime wherever scuffs
overlapped, so a grind streak (a chain of circles) showed brighter, busier
crossings ringed by grime. With "over" coverage the overlap of two scuffs
looks like one scuff.

A `u_ship_world_rot` (`mat3`) uniform is set beside `u_ship_world_inv` when
`u_decal_count > 0`; the inverse is not recomputed in the shader.

**Albedo** (same pass, before lighting), once after the loop when `cov > 0`:

```
base.rgb = mix(base.rgb, kScuffMetal, metal_mask * kScuffAlbedoGain)   // bare metal on the creases
base.rgb *= 1.0 - kScuffGrime * cov
```

`kScuffMetal` is a neutral light grey (`vec3(0.62)`); grime is a soft **fill**,
darkest where coverage is full and fading out through the noisy edge. The
first pass drew grime as a rim *ring* (`r` 0.75–0.95), which put a circle
round every scuff and made a streak read as crossing rings — do not bring
the ring back.

Contract (identical to the material normal map's): the scuff pass writes
**only `n_shade` and `base`**. It never touches the shadow-bias normal, the
Fresnel rim, `n_body`, the carve loop, `decal_emissive`, or `glow_flicker`.

Tuning constants are `kScuff*` `const`s at the top of `opaque.frag` (rebuild to
tune), the same convention as `kHullCarve*`: `kScuffTexSpan = 0.25` (fraction
of the map one scuff's diameter spans), `kScuffRelief = 1.0`,
`kScuffGrindRelief = 0.6`, `kScuffFlipGreen = 0`, `kScuffMetalTilt = 0.35`,
`kScuffAlbedoGain = 0.4`, `kScuffGrime = 0.25`, `kScuffEdgeNoise = 0.6`,
`kScuffEdgeFreq = 1/6`. Starting points for the live pass, not measured values.

Cost: zero when `u_decal_count == 0` (undamaged hull — the production path
stays byte-identical, enforced by the existing empty-ring baseline test). With
decals present it adds one loop over ≤ 24 records with an early `continue` on
class; a Scuff record costs one `textureGrad`, three noise taps for the edge
and the frame maths.

### 5. Live-tuning vehicle

`engine/dev_missions/damage_preview.py` seeds three Scuff decals on the Akira
wreck after its authored damage: small (0.15 GU), medium (0.3 GU), large
(0.5 GU) radii — the band's floor, middle and ceiling; the small one a grind
(`dent = 0`), the other two impacts (`dent = 1`) — three different tangents, the large one straddling the
saucer/hull curve so the far-face guard and the frame construction on a curved
surface get eyeballed. Seeded via `host_io.damage_decal_add` directly (world
point from `ship.GetWorldLocation()` + a body offset rotated through
`GetWorldRotation()`, normal from `ray_trace` when available, else the body
axis). Dev-mode only, like the mission itself.

A second developer mission, **Collision Sim** (`engine/dev_missions/collision_sim.py`),
parks the player Galaxy above a `SetStatic` Warbird so ~10° of pitch or ~20°
of roll grinds the saucer rim into its wings — a reproducible low-speed
contact that needs no AI and no ram. The static Warbird is a fixed anchor and
takes no decals; the scuffs land on the Galaxy (external camera). Placement
is measured in the solver's own PIECE-sphere terms (see the module
docstring) — a mesh-based gap is fiction once the sphere slack is counted.

Two things this mission exposed on 2026-09-21, both fixed on the branch:
`_MissionLoader._realize_session` never cached hull pieces (so every mission
collided on 2×-inflated whole-body spheres), and manual flight never
published the player's angular velocity (so a rotating hull had zero slip —
no grind, no impulse, no scuff — until the first bit of thrust).

Acceptance is the live pass: (a) Damage Preview — does relief + scratch read
as a scrape at close, medium and far range with no sparkle; (b) QuickBattle —
ram an NPC dead-on (scuff with no preferred direction, and a carve if fast),
then grind along its hull (a streak whose ripples run across the slip
direction and whose scratches run along it, on **both** hulls).

### 6. Tests

**C++ ring (`native/tests/scenegraph/damage_decals_test.cc`)**
- Scuff stores a unit tangent orthogonal to its normal; a zero tangent yields
  a deterministic perpendicular.
- Co-located Scuff merges (intensity deepens, tangent refreshed); Scuff does
  not merge with Scorch at the same point.
- Full ring: Scuff evicts the oldest HeatGlow before any Scorch; a ring of
  only Scorch+Scuff evicts the oldest overall.
- `tick()` never reclaims a Scuff.

**FrameTests (offscreen GL, `native/tests/renderer/frame_test.cc`)** — flat
lit quad, directional light, no material normal map:
- `ScuffPerturbsShadingInsideFootprintOnly`: luminance variance inside the
  footprint > threshold; every pixel outside the footprint byte-identical to
  the no-decal render.
- `ScuffHasNoEmberAndLeavesGlowUntouched`: `decal_emissive` contribution zero
  (probe code path / render with zero diffuse and assert black inside the
  patch), glow map pixels unchanged.
- `IsBandLimitedSoItDoesNotSparkleAtRange`: aliasing measured as sensitivity
  to a sub-pixel (0.045 px) shift of the **instance** at range — a
  band-limited scuff changes by < 2 levels/px. The instance, not the seed:
  the seed's body point keys the scuff's patch of the map, so moving it is
  a different patch by design (3.6 measured that way), not aliasing.
- `ScuffDoesNotMirrorToTheFarFace`: a scuff seeded on +Z leaves the −Z face
  byte-identical (the `wn` guard).
- `RotatedInstanceIsTheIdentityImageRotated`: rotating ship + body tangent +
  light by +90° yields the identity image rotated +90° in screen space (to a
  ~100-texel tolerance from the rasteriser's edge tie rule; a transposed
  `u_ship_world_rot` differs on ~16,800 — measured).
- The map tests run against a **synthetic** map served through
  `set_scuff_normal_texture_override` (a 256² corrugation across U,
  amplitude 0.5, 8-texel period), never the shipped file:
  - `FlatMapGivesNoRelief`: a straight-up map leaves the core as flat as the
    undamaged quad (stddev < 1.5; the corrugated map > 6).
  - `MapTurnsWithTheSlipDirection`: tangent X ⇒ vertical bare-metal stripes,
    tangent Y ⇒ horizontal (column vs row profile deviation, ×3).
  - `TwoScuffsSampleDifferentPatchesOfTheMap`: two seeds in the same slip
    frame give column profiles with correlation < 0.8 (a re-render > 0.99).
  - `MissingMapStillDrawsTheAlbedoTerms`: with the project asset root pointed
    at a directory that does not exist, the frame equals the flat-map frame
    byte for byte, not the undamaged quad.

⚠️ The unit-7 sampler is assigned once in `Pipeline`'s constructor, not per
draw: every other path that draws with the opaque program (the carve
stencil, the hull-clip and cloak-parity rigs) would otherwise leave it on
unit 0 with the base `sampler2D`. Harmless for two `sampler2D`s, but its
predecessor was a `samplerBuffer` and two sampler TYPES on one unit is
`GL_INVALID_OPERATION` at draw (24 tests red) — keep the habit. The texture
is a GL object released per context (`reset_scuff_normal_texture`, from the
host's shutdown and the test fixture) or a stale name is bound in the next
context — order-dependent 1282s.
- Existing `UndamagedInstanceGlowMatchesEmptyRingBaseline` keeps passing —
  the production path with no decals is byte-identical.

**Python (`tests/unit/`)**
- `weapon_class_for("collision") == WEAPON_CLASS_SCUFF`; `None` still Scorch.
- `"collision"` and `None` give identical `_play_audio` / `hull_hit_smoke`
  decisions.
- Chord radius: `sqrt(2·R_min·pen)` and the clamp band, both piece and
  whole-bound fallback.
- Grind passes the slip vector as `hit_tangent`; impact passes the
  normal-stripped relative velocity; dead-on impact passes `None`.
- `dispatch` forwards `tangent` and `decal_radius` to `host_io.damage_decal_add`
  (fake host_io); weapon callers pass `None` and the decal keeps `radius`.
- A collision `apply_hit` leaves `r_hit`, the subsystem catchment, the carve
  influence radius and `WeaponHitEvent.GetRadius()` exactly as before.
- The existing façade manifest test stays green (no new binding name).

**Gate:** `scripts/check_tests.sh` before merge. The green gate cannot see the
look — the live pass in §5 is the acceptance test
(`feedback_green_gate_cannot_see_game_feel`).

## Out of scope

- Capsule/elongated scuff records (streaks come from the merge/chain rule).
- Authored scuff normal textures (a hybrid can be layered on later; the
  procedural pass is the foundation either way).
- Any change to carve strength, iso, or the speed at which holes appear.
- Scuffs on bridge sets, characters, or the hologram/SPV passes.
- A Developer Options slider for the `kScuff*` constants (rebuild to tune).

## Alternative considered

A separate `ScuffRing` on `Instance` with its own capacity, uniforms, binding
and toggle. It isolates slot pressure from Scorch, but duplicates the ring,
upload, toggle and tests for a problem not yet observed. If a live grind
visibly evicts scorch marks, split it out then.

## Files

| File | Change |
|---|---|
| `native/src/scenegraph/include/scenegraph/damage_decals.h`, `src/damage_decals.cc` | `WeaponClass::Scuff`, `tangent_body`, merge + eviction rules |
| `native/src/host/host_bindings.cc` | `world_tangent` arg, class guard `> 2u` |
| `native/src/renderer/frame.cc` | `u_decal_d` upload, `u_ship_world_rot`, unit-7 bind of the scuff map |
| `native/src/renderer/scuff_texture.{h,cc}`, `asset_path.{h,cc}` | lazy scuff-map load, test override, project asset root |
| `native/assets/textures/scuff_normal.png` | the map (Mark's crumpled-sheet sample, 2048²) — NOT in `game/` |
| `engine/paths.py`, `engine/renderer.py`, `engine/host_loop.py` | `project_asset_root()`, `set_project_asset_root` façade, boot push |
| `native/src/renderer/shaders/opaque.frag` | `apply_scuffs` pre-lighting pass (splatted map), Scuff `continue` in the post-lighting loop, `kScuff*` consts, `p_body` reorder |
| `engine/host_io.py` | `damage_decal_add(..., world_tangent=None)` wrapper |
| `engine/appc/visible_damage.py` | `queue_body_scuff` (deferred, realises like authored volumes) — the seeding primitive for §5 |
| `engine/appc/damage_decals.py` | `WEAPON_CLASS_SCUFF`, `weapon_class_for("collision")`, radius scale 1.0 |
| `engine/appc/combat.py` | `apply_hit(hit_tangent=None, decal_radius=None)` forwarded to dispatch; `r_hit` untouched |
| `engine/appc/hit_feedback.py` | `dispatch(tangent=None, decal_radius=None)` → `host_io.damage_decal_add` |
| `engine/appc/collisions.py` | `weapon_type="collision"`, chord radius, tangent on impact + grind |
| `engine/dev_missions/damage_preview.py` | three seeded scuffs |
| tests as listed in §6 | |
