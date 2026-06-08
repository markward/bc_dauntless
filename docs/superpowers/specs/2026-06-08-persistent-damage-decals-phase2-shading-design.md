# Persistent Damage Decals — Phase 2: Scorch + Heat-Glow Shading

**Status:** drafted, awaiting user review
**Date:** 2026-06-08
**Author:** Mark Ward (with Claude)

**Prior art:**
- [`2026-06-08-persistent-damage-decals-design.md`](./2026-06-08-persistent-damage-decals-design.md) — the parent design. This doc is the implementation design for its **Phase 2**. §3/§4 of the parent lock the data model and shader recipe at a high level; this doc makes them concrete. Phase 1 (the decal store + plumbing) shipped 2026-06-08 on branch `feat/damage-decals-phase1`; Phase 2 stacks on that branch.

**Build / runtime facts assumed (verified in repo):**
- The hull renders through `native/src/renderer/shaders/opaque.{vert,frag}`. The vertex shader already outputs `v_position_ws` (world position) and `v_normal_ws` (world normal).
- `renderer::Shader` already exposes `set_vec4_array`, `set_int_array`, `set_float`, `set_mat4`, `set_mat3`.
- `FrameSubmitter::submit_opaque` / `submit_opaque_in_pass` (`native/src/renderer/frame.cc`) iterate `scenegraph::Instance`, so `inst.decals` (the Phase-1 ring) and `inst.world` are in scope. `draw_model` is the per-instance uniform-set point.
- Runtime feature toggles follow the `dauntless_hdr` / `dauntless_rim` / `dauntless_specular` pattern (a translation unit exposing `enabled()` / `set_enabled()`, a host binding `*_set_enabled`).
- Render tests use the `FrameTest` pattern (`native/tests/renderer/frame_test.cc`): offscreen GL via `renderer::Window(…, visible=false)` under `GALLIUM_DRIVER=llvmpipe`, load the Galaxy NIF, render, `glReadPixels`. Tests `GTEST_SKIP()` when BC assets are absent.
- Shader source changes require a `cmake` reconfigure, not just `--build` (shaders are embedded at configure time). Noted because every shader iteration in this phase needs it.
- The extension module is `_dauntless_host` (not the `_open_stbc_host` name in CLAUDE.md).

## 1. Goal

Render the Phase-1 decal ring on the hull: subtle persistent torpedo/disruptor scorch (deposited matter + radial ejecta + a ~10 s blackbody ember) and transient phaser heat-glow, composited per fragment in **body space** so mirrored hull halves never cross-contaminate. This is the visual payoff of the whole feature and the proof that the object-space pivot fixes the bug that killed the UV approach.

The visual target was locked in the Phase-1 brainstorm's visual companion (phaser additive heat bloom that fades to nothing; torpedo "spread B" radial-ejecta scorch cooling white→yellow→orange→red→black over ~10 s). This phase implements that look in GLSL; it does not re-open the look.

## 2. Locked design decisions

### 2.1 Compositing is inline in `opaque.frag`

The decal loop lives in the existing hull fragment shader and composites over the base color in the same draw. Chosen over a separate deferred decal pass because depth is correct for free, the base color and surface normal are directly in hand, and it is one draw call. A `u_decal_count == 0` (or toggle-off) early-out makes undamaged ships and non-ship opaque instances cost nothing beyond the branch.

### 2.2 Compositing is in body space; the ember clock is game time

The fragment reconstructs the ship-body-frame position and normal from the existing world-space varyings:

```glsl
vec3 p_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz;
vec3 n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws);
```

`u_ship_world_inv = inverse(inst.world)` is uploaded once per `draw_model` (the ship world matrix, not the per-node matrix — per-node local transforms are irrelevant because both decals and this reconstruction live in the single ship body frame). Noise is indexed by `p_body` so it is stable on the hull under rotation.

Ember age is `age = u_decal_time - birth_time[i]`, where `u_decal_time` is **game time** — the same clock that set `birth_time` (Phase-1 `engine.appc.damage_decals.current_game_time()`) and that drives `damage_decals_tick`. Consequence: ember cooling freezes on pause and scales with time-compression, consistent with the rest of the sim. (Decision: game time over wall time, 2026-06-08.)

### 2.3 Uniform packing

Per `draw_model`, **active** ring slots (filter on `DamageDecal::active`) pack into three `vec4[24]` arrays plus a count:

| Uniform | x | y | z | w |
|---|---|---|---|---|
| `u_decal_a[i]` | point_body.x | point_body.y | point_body.z | intensity |
| `u_decal_b[i]` | normal_body.x | normal_body.y | normal_body.z | radius_model |
| `u_decal_c[i]` | birth_time | weapon_class (0/1 as float) | — | — |

Plus `uniform int u_decal_count;`, `uniform mat4 u_ship_world_inv;`, `uniform float u_decal_time;`. `MAX_DECALS = 24` is a shared constant (mirror of `DamageDecalRing::kMaxDecals`). `weapon_class` rides as a float (0.0/1.0); no separate int array. This is ~72 vec4 of fragment-uniform data, far under the GL 3.3 floor.

Packing happens in C++ in `draw_model` using `Shader::set_vec4_array` (one call per array). Only active slots are packed, compacted to `[0, count)`.

**Units (important).** `_ship_world_matrix` (`engine/host_loop.py`) bakes the flat `BC_MODEL_SCALE` NIF→GU scale **into `inst.world`**. Therefore `inverse(inst.world)` maps world-GU back to the ship's **NIF/model units**, so both the stored `DamageDecal::point_body` and the shader's reconstructed `p_body` are in **model units** — while `DamageDecal::radius` is in **game units** (`r_hit`). The two cannot be compared directly (a ~100× mismatch at `BC_MODEL_SCALE = 0.01`). The packing step converts radius GU→model units using the world-matrix scale `s = length(vec3(world[0]))` (the X column's length; sign-flip from the det-normalisation is irrelevant to `length`): `radius_model = radius / s`. The shader then compares `r` (model units) to `radius_model` (model units) consistently. `point_body` needs no conversion (already model units). All decal math thus stays in model units; nothing else in the shader changes. (Uniform scale assumed, which `_ship_world_matrix` guarantees.)

### 2.4 The shader recipe

For each decal `i` in `[0, u_decal_count)`, compute `d = p_body - point_body[i]`, `r = length(d)`:

- **Normal-aware falloff (the mirroring fix):** `float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, normal_body[i]));` — a decal whose stored normal faces away from this fragment's surface contributes zero, so a +X-nacelle decal cannot bleed onto the −X nacelle even at the same |position|. Geometric, not UV-dependent.
- **Scorch (weapon_class == 1):**
  - `ring = exp(-r*r * CORE_TIGHTNESS)` dense core.
  - `ejecta = radial_streaks(d, p_body)` — multi-octave value noise (procedural fbm, indexed by `p_body` and impact direction; **no texture bind, matches the Phase-1 mockup**) giving direction-varying streaks that thin with `r`.
  - `deposit = clamp(ring + ejecta, 0, 1) * intensity * wn`; composite a dark warm-grey soot **over** the base color (mix, not add).
  - `ember = blackbody(ember_curve(age)) * (exp(-r*r*EMBER_BROAD) + exp(-r*r*EMBER_TIGHT)) * wn` added to emissive (feeds the existing HDR/bloom path). `blackbody` is a white→yellow→orange→red→black control-point ramp; `ember_curve` decays to ~0 by `T_EMBER ≈ 10 s`.
- **Heat-glow (weapon_class == 0):** `glow = exp(-r*r*GLOW_TIGHTNESS) * (1 - age/T_GLOW)`; additive emissive bloom, no deposit; `T_GLOW ≈ 1.2 s` (matches the Phase-1 reclaim window — by the time the slot is reclaimed C++-side the glow has already faded to zero, so there is no pop).
- Undamaged / toggle-off path: `u_decal_count == 0` or `!dauntless_decals` → skip the loop entirely; fragment output is byte-identical to today.

Procedural-noise helper functions (`hash`, `vnoise`, `fbm`, `radial_streaks`, `blackbody`, `ember_curve`) live in `opaque.frag`. Tuning constants (`NORMAL_MIN`, `CORE_TIGHTNESS`, `EMBER_BROAD/TIGHT`, `GLOW_TIGHTNESS`, noise scale, deposit color, the blackbody control points, `T_GLOW`, `T_EMBER`) are finalised by eye against the Galaxy toward the locked look; the contract is the recipe shape, not the exact numbers.

### 2.5 Toggle

`dauntless_decals` translation unit (mirror `native/src/renderer/`'s specular toggle) exposing `enabled()` / `set_enabled(bool)`, default **on**. Host binding `decals_set_enabled(bool)`. `draw_model` reads `dauntless_decals::enabled()` and uploads `u_decal_count = 0` (skipping the pack) when off, so off == stock-BC hull with no per-fragment decal cost.

### 2.6 Game-clock plumbing

A host global (e.g. `g_decal_game_time`, set inside the existing `damage_decals_tick(time)` binding, which already receives `GetGameTime()` every frame from `host_loop`) is read in `frame()` and passed through `submit_opaque` / `submit_opaque_in_pass` → `draw_model` as `u_decal_time`. `damage_decals_tick` is invoked from `host_loop` before `frame()` each tick, so the value is fresh. No new per-frame Python call is added.

## 3. Components and boundaries

- **`opaque.frag`** — owns the decal compositing recipe and its noise/blackbody helpers. Interface: the new uniforms in §2.3. Depends on nothing new at runtime.
- **`frame.cc` / `frame.h`** — `draw_model` packs the ring → uniforms and sets `u_ship_world_inv` / `u_decal_time`; `submit_opaque*` thread the game clock through. Reads `dauntless_decals::enabled()`.
- **`dauntless_decals` toggle unit** — one responsibility: hold the runtime on/off flag. Mirrors the specular toggle exactly.
- **`host_bindings.cc`** — `decals_set_enabled` binding + the `g_decal_game_time` capture in `damage_decals_tick`.
- **Tests** — a render test file exercising the recipe through the real pass.

No change to `opaque.vert`, the Phase-1 ring, the combat/emission path, or the host loop's per-tick structure.

## 4. Testing

Render tests in the `FrameTest` style (offscreen llvmpipe; `GTEST_SKIP` without BC assets). Each loads the Galaxy, creates an instance with an identity-ish world transform, seeds its ring via `inst.decals.add(...)` directly (body-frame), renders the opaque pass, and `glReadPixels`-samples:

1. **Mirroring regression (centerpiece).** Add a Scorch decal at a +X saucer body point with +Z normal. Assert the painted +X screen region darkened vs an undamaged baseline AND the mirror −X region is unchanged within tolerance. This is the exact failure that killed the UV approach; it must be green.
2. **Scorch darkens the region.** Painted region's sampled luminance drops toward soot vs baseline.
3. **Phaser glow is transient.** With `u_decal_time` near a HeatGlow decal's `birth_time`, the region is brighter (emissive) than baseline; with `u_decal_time = birth_time + 2.0` (> `T_GLOW`), the region is back to ~baseline.
4. **Undamaged == baseline.** An instance with an empty ring renders within tight tolerance of the pre-Phase-2 output (no regression to existing ships).
5. **Toggle off.** `dauntless_decals::set_enabled(false)` → a damaged ship renders like the undamaged baseline.
6. **No GL error** across all of the above (`glGetError() == GL_NO_ERROR`).

Body-frame seeding in tests avoids needing the C++ `damage_decal_add` binding; the world→body binding path remains covered by the standalone `world_to_body` gtest (and gets a host-level integration test if/when a `slots()` readback is added — parent spec §6 note).

## 5. Non-goals

- **Silhouette change / tessellation** — separate brainstorm (parent §7). This phase is surface shading only.
- **Sparks / gas emitters** — Phase 3 (Python), anchored to these same decals.
- **Per-weapon brush shapes beyond the two classes** — disruptor rides with Scorch; finer distinctions are post-Phase-2 polish.
- **Re-opening the look** — the Phase-1 companion locked it; this phase reproduces it.
- **Save/load of decals** — runtime-only, unchanged from Phase 1.

## 6. Parking lot

- Final tuning-constant values (§2.4) — set during implementation; record the chosen numbers back here when they land.
- Whether `radial_streaks` should bias along the impact's incoming direction for a more physical ejecta throw (parent §6 Q7) — left radially symmetric for now.
- If procedural fbm proves too soft or too costly at the close camera ranges, fall back to sampling `Noise1-3.tga` triplanar (parent §6 Q6). Default stays procedural.

## 7. Workflow

Implementation plan via the writing-plans skill, then subagent-driven execution on the `feat/damage-decals-phase1` branch (Phase 2 stacks on Phase 1 per the kept-branch decision). When Phase 2 merges, annotate the parent spec's Phase 2 section `shipped <date>` and fold the chosen tuning constants into §6.
