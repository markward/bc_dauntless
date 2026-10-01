# Minor rocks — design (modern asteroids, sub-project 3)

**Date:** 2026-10-01
**Status:** built, awaiting live check
**Branch:** `feat/minor-rocks` (worktree `.claude/worktrees/minor-rocks`), forked
from local `main` at `c0210aac` (sub-projects 1 and 2 merged, live-tested).
**Roadmap:** `2026-09-30-modern-asteroids-roadmap.md`, "Sub-project 3: minors".
The standing decisions there are not repeated here. This spec settles the
rest. Sub-projects 3b (far tier) and 4 (profile seeding) will consume this one.
**Builds on:** `2026-09-30-rock-catalogue-design.md` (fragments, LODs, glTF
conventions) and `2026-09-30-rock-class-design.md` (`RockClass`, breakup).

## Intent

A rock never sits bare. Every major carries a cloud of small rocks, BC's tile
fields finally draw something, and the debris of a breakup stays on as gravel
instead of 8 short-lived chunks. Minors are **scenery**:

- instanced, so there can be thousands
- never simulated objects: no set membership, no names, no events
- not targetable, and no weapon can hit them
- shoved aside when the player flies through, with a puff, a grit sound and a
  cosmetic shield flicker, but no damage

## Decisions (Mark, 2026-10-01)

| # | Decision |
|---|---|
| M1 | **Approach A.** C++ owns the instances: generation, animation, culling, LOD, shove state, the contact test and the instanced draw. Python owns which clouds exist, the dials and the fly-through responses. |
| M2 | **Shoved minors stay shoved.** A touched minor takes a damped outward velocity, and the offset it builds up stays, so a cloud keeps a visible wake. They do not spring back. |
| M3 | **Breakup frees the halo as a debris cloud.** The dying rock's halo detaches and drifts on at the parent's velocity. Debris (pieces under 1 GU, plus gravel) joins it. Rock chunks are retired. |
| M4 | **The dials share the nebula's dev keys.** A dial-group registry: `/`, `L` and `O` act on the active group, chosen in Developer Options. |
| — | Design sections 1–5 approved as presented. |

## Facts this design rests on (checked 2026-10-01)

- **The engine has no numpy** (`pyproject.toml` comment). Per-instance work on
  thousands of minors cannot run in Python, which forces M1.
- **GL 4.1 on macOS has no compute shaders**, so the GPU cannot cull or choose
  LODs by itself. Culling and LOD are a CPU step.
- **The only instanced draw** is `dust_pass.cc:315`/`:363`. The opaque path
  draws once per mesh, per node, per instance (`frame.cc:517`, `:981`), with no
  culling.
- **Mesh vertex attributes use locations 0–6** (`mesh_upload.cc:54-72`).
  `assets::Mesh` exposes `vao()`, `vbo()`, `ebo()`, `index_count()`
  (`assets/mesh.h:37-51`). Model handles are recycled on mission swap
  (`frame.cc:425-431`), so they are re-resolved after a swap.
- **Lighting for a new pass:** `renderer::Lighting` (`frame.h:34`, global
  `g_lighting`). `set_ambient_uniforms` (`frame.cc:1043`) is file-static. The
  shadow state comes from `active_shadow_enabled/light/texture()`
  (`frame.cc:1395-1397`). The breach pass already takes `g_lighting` plus
  `ambient_scale` (`host_bindings.cc:1114`).
- **Pass slot:** `render_space_geometry` (`host_bindings.cc:1062`), right after
  `space.opaque` (`:1086-1090`). That target is multisampled and writes depth,
  and the viewscreen RTT calls the same lambda.
- **No geometry LOD exists** (`native/src/host/docs/deferred_work.md:108`).
  Each catalogue fragment has `lod0` (≈1,280 tris) and `lod1` (≈320 tris), plus
  its own 256² base and normal PNGs.
- **Cosmetic shield flash:** `host_io.shield_hit(iid, point, rgba, intensity,
  radius)` (`host_io.py:297`) applies no damage. The renderer keeps an **8-slot
  hit ring** (`shield_state.h:313`), which a stream of grit flashes would
  overwrite, as `hit_feedback.py:78-80` warns.
- **Grit sound:** the project has none. BC registers `"Collision 1"` …
  `"Collision 8"` (`sfx/Explosions/collision1-8.wav`,
  `LoadTacticalSounds.py:123-130`). `TGSound.SetVolume` exists
  (`engine/audio/tg_sound.py:153`).
- **Puff:** `hit_vfx.spawn(pos, severity=CRITICAL, instance_id=None,
  weapon_kind=SPARK_KIND_ROCK, spark_count=n, pSet=…)`, the call
  `engine/rocks/vfx.py` makes for breakup dust.
- **Player box:** `ship._shield_hull_box` (`combat.py:308`, written at realise
  by `_cache_shield_hull_box`) is the hull AABB in the body frame.
- **Dash:** `dash.is_dashing(player)` (`engine/appc/dash.py:199`). A ship in
  set-to-set transit is parked in the `"warp"` set.
- **Chunks today:** `debris_chunk.kMaxLiveChunks = 32` is shared by ship hull
  debris (`hull_breakup.py:90`, `part_detach_render.py:103`) and rock chunks.
  `debris_chunk.spawn_body` has a single caller, `rocks/chunks.py:50`. The pump
  runs in `host_loop.py:11081` (`sim.rock_breakup`).
- **Realisation:** `_reconcile_scene` (`host_loop.py:6578`) reconciles the
  viewed set every frame, so it covers warp, hand-off and cutscene view
  changes. Mission swap resets run in `_drain_pending_swap` (`:6796ff`). The
  native per-frame globals reset in `reset_frame_state`, which
  `tests/host/test_init_resets_frame_state.py` pins.
- **Dev keys:** `dev_nebula_dials.py` records that `/`, `L` and `O` were the only
  keys free on a MacBook in every namespace (`test_dev_key_collisions.py`). The
  nebula dials hold all three.
- **BC tile fields** (SDK):

  | Field | Radius | Tiles³ × per tile | Rocks | Size factor |
  |---|---|---|---|---|
  | Vesuvi 1 | 100 GU | 3³ × 2 | 54 | 10 |
  | Nepenthe 1 | 114.29 GU | 2³ × 3 | 24 | 7 |
  | Beol 4 | 1,000 GU | 3³ × 15 | 405 | 7 |
  | Multi7 (×3) | 500 GU | 3³ × 2 | 54 each | 10 |

  Multi1's field is commented out in the SDK.

## Evidence gaps

- **stbc-reference was unreachable** (connect timeout, 2026-10-01), as it was
  for sub-projects 1 and 2. The Ghidra symbol export lists
  `AsteroidField::GetTileSize` and `Get/SetInner/OuterFieldRadius`, which hints
  that BC's tiles may be a grid wrapping around the camera rather than a fixed
  population. The roadmap's "count = tiles³ × per-tile" across the field
  sphere is a **standing decision, not recovered BC behaviour**.
  `kTileCountMult` exists so that Beol 4 (one rock per ~220 GU on average) can
  be tuned by feel.
- **Size factor** (7 or 10) is mapped to a minor size range by our own rule
  (§1). It is not BC's meaning, which is unknown.

## Design

### 1. Clouds and their sources

**A cloud** is a descriptor:

```
{id, set, anchor, shell_inner, shell_outer, falloff, count,
 r_min, r_max, size_exponent, family, seed}
```

Each cloud generates its instances deterministically from `seed`, so a field
looks the same every time you come back. Every instance gets:
- a local offset in the shell
- a radius from a truncated power law (`size_exponent`)
- a fragment mesh of the cloud's family
- a tumble axis and rate
- a slow orbit about the cloud centre (bounded drift: a halo never
  disperses; tile fields default to no orbit)

**Anchors:**

| Kind | Used by | Position |
|---|---|---|
| `instance` | a major's **halo** | Resolved in C++ through the rock's renderer instance `inst->world` right after the transform-store sweep, so halo and rock share one interpolated pose (the attached-lights pattern). **Translation only**: the halo does not spin with its rock. |
| `point` | **tile fields** | A fixed position in set coordinates, offset by the floating render origin. |
| `free` | **breakup debris** (§4) | Analytic: `p0 + v·(t − t0)`, `t` the pause-aware game clock. It can be rebuilt exactly after a set change. |

**Halo**
- One for every `RockClass` with a realised renderer instance, keyed on the
  rock's name, in the family of the rock's catalogue pick (silicate when the
  catalogue is toggled off).
- Shell from `kHaloInner` × R (1.1) to `kHaloOuter` × R (3.0), with density
  falling off outward (`kHaloFalloff`). R is
  `rocks.rock.effective_radius`.
- Count = clamp(`kHaloPerGU2` × R², `kHaloMin` 12, `kHaloMax` 400).
- Radius from `kHaloRMinGU` (0.03) to min(`kHaloRMaxFrac` × R (0.15),
  `kHaloRMaxGU` 1.0).

**Tile field**
- One for every `AsteroidField` in the set: a uniform sphere of the field
  radius.
- Count = tiles³ × per-tile × `kTileCountMult` (1.0).
- Radius from `kTileRMinGU` (0.05) to `kTileRPerSizeFactor` (0.1) × size
  factor.
- Silicate. No majors.
- `asteroid_field.py` starts storing `SetNumTilesPerAxis`,
  `SetNumAsteroidsPerTile` and `SetAsteroidSizeFactor`, with getters
  (`GetNumTilesPerAxis` / `GetNumAsteroidsPerTile` / `GetAsteroidSizeFactor`,
  all on BC's surface per the symbol export). `ConfigField` /
  `UpdateNodeOnly` stay no-ops. Warp gating (`IsShipInside`) and nav points
  are unchanged.

**Registry (Python, `engine/rocks/minors.py`)**
- Derives the halo and tile clouds from the **viewed set's** contents inside
  `_reconcile_scene`, diffs them against what native holds, and sends only
  adds and removes (`minors_add_cloud` / `minors_remove_cloud`). Clouds in
  other sets are not built.
- Free clouds live in Python per set, keyed by the dead rock's name, and are
  re-sent when their set is viewed again.
- Clears on mission swap (the `_drain_pending_swap` reset list) and natively
  in `reset_frame_state`.
- **Budget:** `kMaxLiveMinors` (20,000) instances across the viewed set's
  clouds. Halos and tile fields are never evicted. Over budget, the **oldest
  free cloud fades out** over `kFreeCloudFadeSeconds` (2 s) and is then
  dropped.

### 2. Rendering (native)

**`MinorField`** (`native/src/renderer/minor_field.{h,cc}`) is pure code with no
GL: the clouds, their instances, shove state, and the per-frame step.

**Per-frame step**, called in `frame()` after the transform-store sweep:
1. Resolve each cloud's anchor.
2. For each instance: pose = anchor + local offset + drift + damped shove
   offset; rotation = tumble axis × rate × t. Scale ramps from 0 over
   `kCloudFadeInSeconds` for a cloud that is growing in (§4), and down over
   2 s for one that is fading out.
3. **Cull:** frustum, then on-screen radius < `kMinPixelRadius` (1.5 px) is
   skipped. Dust and the far tier carry the look beyond that.
4. **LOD:** lod0 when the on-screen radius is at least `kLod0PixelRadius`
   (24 px), otherwise lod1.
5. Bin the survivors by (fragment mesh, LOD) into one compact buffer: a mat3x4
   (three `vec4` rows), 48 B each.

**`MinorPass`** (`native/src/renderer/minor_pass.{h,cc}`)
- Uploads the buffer once per frame.
- Draws inside `render_space_geometry` **right after `space.opaque`**, into the
  same MSAA depth target. Minors are therefore depth-tested against hulls, sit
  under the shield bubble, are seen by the nebula raymarch, and draw on the
  viewscreen RTT too.
- One `glDrawElementsInstanced` per non-empty bin: at most 2 LODs × the
  family's fragment count (8 for silicate), per family in view.
- Its own VAO per (fragment mesh), reusing the model's `vbo()` / `ebo()` with
  instance attributes at locations 7+. The model's VAO is never modified.
- Fragment models load once through the existing loader and are re-resolved
  after a mission swap.

**Shading** (amended while planning, 2026-10-01)
- A new **`minor.vert`** is linked with the existing **`opaque.frag`**, the way
  the skinned program already pairs `skinned.vert` with it
  (`pipeline.cc`). Minors are therefore lit by the *same* fragment code as
  majors, by construction rather than by a copy that could drift.
- `minor.vert` reads the per-instance transform (three `vec4` rows at
  locations 7–9) and writes the three varyings `opaque.vert` writes.
- The pass sets the sun, directional ambient (`g_lighting`, with
  `ambient_scale` passed in as the breach pass does), shadow-map, material
  (base, normal map, no glow, no specular map) and rim uniforms. Every
  ship-only feature is set off: decals, carve, hull field, glow regions,
  dynamic lights, hull-name decals.
- They receive the ship shadow map but cast nothing.
- **The per-instance brightness jitter is dropped.** `opaque.frag` has no
  per-instance input, and the fragment meshes already vary.

**Profiling:** `DAUNTLESS_FRAME_SCOPE("space.minors.step")` and
`"space.minors.draw"`.

**Developer toggle:** Developer Options → Lighting → "Minor rocks", default on,
not persisted. Off means the step and the draw are skipped.

### 3. Fly-through (player only)

**Contact (C++, part of the `MinorField` step)**
- The player is an **oriented box**: `_shield_hull_box` posed by the player's
  rendered transform, inflated by `kContactMarginGU` (0.1). It is pushed with
  `minors_set_player(iid, box)`, and native reads the pose from `inst->world`
  each frame.
- The box is **swept** from last frame's pose to this frame's, so a minor
  cannot be tunnelled past at dash speed.
  - Two cheap rejects keep the test to nearby minors (amended while planning;
    no grid). First, a cloud whose bounding sphere misses the swept capsule is
    skipped. Then a minor farther from the swept segment than its radius plus
    the box's bounding radius is skipped. Only the survivors get the
    sub-stepped box test.
  - **View changes reset the sweep.** On any frame where the viewed set
    changes, the registry sends `minors_set_player(None)` before the player,
    so that frame tests only the current pose. This covers BC's set-to-set
    warp, which lands a few hundred to a few thousand GU from where the ship
    left — far under the teleport guard. A scope-hidden player (a cutscene
    showing another frame) has no contact box at all.
  - **Teleport guard:** a view-space jump of more than `kTeleportGU`
    (20,000 GU) in one frame *within the same view* is treated as a
    hand-off, not flight. That frame does no sweep and tests only the current
    pose. It covers in-view jumps only; view changes are handled above.
- **Shove:** a touched minor gets a velocity of the player's speed ×
  `kShoveTransfer` (0.6) plus `kShoveMinGU` (0.3 GU/s), directed out of the
  box from the contact, and a tumble kick (`kShoveTumble`). The velocity decays
  with half-life `kShoveDampSeconds` (4 s), and **the offset stays** (M2).
- Shove state is a sparse map of touched instances per cloud. It survives
  detach (§4) and is lost when a cloud is rebuilt.
- At most `kMaxShovesPerFrame` (64) touches per frame.
- Each touch appends `{point, minor_radius, rel_speed}` to a contact buffer.
  Python drains it with `minors_drain_contacts()`.

**Responses (Python, `engine/rocks/minor_contact.py`)**, each rate-limited on
its own:

| Response | Rule |
|---|---|
| Puff | `hit_vfx.spawn` with rock-dust sparks (`kPuffSparkCount` 6), only for minors ≥ `kPuffMinRadiusGU` (0.1); at most `kPuffMaxPerSecond` (6) |
| Grit | a random `"Collision 1–8"` at `kGritVolume` (0.25) × size scale, positional at the contact; at most `kGritMaxPerSecond` (4) |
| Shield flicker | only when `combat.shields_block(player)`: `host_io.shield_hit` at the contact, `kShieldFlickerIntensity` (0.3), small radius; at most `kFlickerMaxPerSecond` (2), so it can never fill the 8-slot ring |

- No damage, no events, no camera shake, and no game-state change of any kind.
  Nothing here runs in `render_payload`.
- **Suppression:** while `dash.is_dashing(player)` or the player is in the
  `"warp"` set, minors are still shoved (the wake shows) but every response is
  muted.
- NPC ships, torpedoes and phasers pass through minors. Minors never touch each
  other.

### 4. Breakup integration

**Rock chunks are retired.**
- `engine/rocks/chunks.py` and the chunk specs in `rocks/death.py`
  (`drain_chunk_specs`) are removed.
- `debris_chunk` serves ship hull debris only and gets its 32 slots back.
- The breakup plan's rules (remnant, small rocks ≥ 1 GU as majors, ghosting,
  one major generation, naming, targeting) are unchanged.

**At death** (`rocks/death.py`):
1. **Detach the halo.** `minors_detach(cloud_id, p0, v)` turns the cloud into a
   `free` cloud at the parent's world position and velocity, keeping its
   instances and shove state. Python records `{p0, v, t0, halo descriptor,
   debris list}`.
2. **Debris minors join that cloud:**
   - every planned piece that is not a major: below `kMajorMinRadiusGU`
     (1.0), or a would-be major demoted by `kMaxMajorGeneration`. This
     includes those that `kMaxChunksPerDeath` used to send to dust.
     `kMaxChunksPerDeath` is retired.
   - plus gravel taken from the dust volume: `kDebrisGravelPerGU` × R pieces
     of radius 0.03–0.3 GU
   - capped at `kMaxDebrisMinorsPerDeath` (40), largest first
3. Each debris minor starts at its planned position (relative to the cloud
   anchor) with the plan's outward separation speed and a random tumble. The
   outward speed **decays** with half-life `kDebrisDampSeconds` (6 s), so the
   debris spreads, then settles into a loose cloud drifting with the parent.
   Motion is analytic, `offset = v0·τ·(1 − e^(−t/τ))` with τ = half-life / ln 2,
   so a rebuilt cloud matches a running one exactly (shove aside).
4. Dust and spark VFX are unchanged.
5. A piece rock (generation ≥ 1) crumbles into debris minors and dust the same
   way.

**Pieces get halos through §1**: the remnant and any small rock of 1 GU or more
are `RockClass` objects.
- A cloud that appears **mid-scene** grows in over `kCloudFadeInSeconds` (1.5 s).
- A cloud present when its set is realised appears at once.

**A rock removed without breaking up** (deleted by a mission) loses its halo
with no free cloud.

**Mission bookkeeping is untouched.** Debris minors are not objects: no names,
no events, no set membership. `ET_OBJECT_EXPLODING` / `ET_OBJECT_DESTROYED`
and death scripts behave exactly as now.

### 5. Dials and testing

**Dials (`engine/rocks/minor_dials.py`)**
- Every number in §1–4 lives in one `DEFAULTS` dict.
- Python-owned values (counts, shells, size ranges, debris rules, response caps
  and intensities, budget) are read at use. A count, shell or size change
  rebuilds the viewed set's clouds.
- Native-owned values (pixel thresholds, LOD switch, drift and tumble rates,
  shove parameters, fade times) go to native as one
  `minors_set_dials(dict)` call, following `system_nebula_set_dials`.
- Not persisted. The conftest autouse reset restores the defaults.

**Dial-group registry (M4)**
- `engine/dev_dial_groups.py` owns `/`, `L` and `O`. `dev_nebula_dials`
  becomes the first group, unchanged in behaviour and dials, and the minors
  the second.
- `/` cycles the dials of the **active group**. `L` / `O` step the selected dial.
- Developer Options → Lighting gets a row, "Dial keys: nebula / minors", that
  cycles the active group (default: nebula, so existing muscle memory holds).
- Every press prints `[<group> dials] selected=… {…}`.
- `test_dev_key_collisions.py` stays green: no new keys are claimed.

**Tests.** Everything runs under `scripts/check_tests.sh`, which must exit 0.

- **C++ `MinorField` (no GL, ctest):**
  - generation is deterministic per seed
  - counts and radius ranges match the descriptor
  - instances lie inside their shell, with the falloff honoured
  - frustum and pixel cull are correct
  - LOD bins switch at the threshold
  - an `instance` anchor follows a moved transform, by translation only
  - analytic free-cloud motion matches a step-by-step integration
  - detach keeps instances and shove state
  - fade-in and fade-out scale ramps
- **C++ contact:**
  - a swept box at 10,000 GU/s hits a minor a point test would miss
  - shove direction points outward
  - velocity halves at the half-life while the offset stays
  - `kMaxShovesPerFrame` holds
  - a rebuild clears shove state
- **C++ render** (headless GL, in the existing breach-pass test style):
  - a minor and the same fragment mesh drawn through `draw_model` at the
    same pose and lighting give identical pixels (same fragment shader)
  - the draw count equals the number of non-empty bins
  - the model's VAO state is unchanged after the pass
- **Bindings:** `minors_*` added to the `host_io` manifest
  (`test_host_io_binding_manifest.py`) and reset in `reset_frame_state`
  (`test_init_resets_frame_state.py`).
- **Python registry:**
  - halos for every realised `RockClass` and tile clouds for every
    `AsteroidField` in the viewed set, and none for other sets
  - diffs send only changes
  - clears on mission swap
  - budget eviction takes the oldest free cloud first
  - mid-scene clouds fade in
  - the `asteroid_field.py` setters and getters round-trip, and warp gating
    is unchanged
- **Python breakup:**
  - no `debris_chunk` spawns from rocks
  - the debris minor count follows the rule and the cap
  - the halo detaches with the parent's position and velocity
  - mission events are unchanged (existing E1M2 tests stay green)
- **Python responses:** each rate limit, the shields-up gate on the flicker,
  and suppression while dashing or in the warp set.
- **Headless VFX probe:** a scripted player flight of 10 s at full impulse and
  10 s dashing, through Beol 4's tile cloud and through Multi1's halos, driving
  the real native `MinorField` step through the extension module (no GL).
  `MinorField` is exposed to Python as its own class
  (`_dauntless_host.MinorField`), separate from the global the renderer
  uses, so the probe needs no `init()`.
  It counts puffs, grit plays and shield flashes, and asserts each stays within
  its cap and that no damage or event occurs.
- **E2E through the mission harness** (entry at the mission):
  - E2M1 at Beol 4 registers a 405-minor tile cloud
  - Multi1 registers 54 halos
  - destroying an E1M2 debris rock leaves a free cloud and zero rock chunks
- **Performance:** a ctest benchmark of the `MinorField` step at 20,000
  instances *reports* its time and asserts nothing. The acceptance numbers are
  live, from the frame profiler.

## Live check (Mark)

`./build/dauntless --developer` from the worktree, then:

- **E2M1 / Beol 4:** the tile field is visible, and warp gating inside it still
  holds.
- **E4M6 / Nepenthe:** the field draws, and "Center of Asteroid Field" nav
  points still work.
- **E1M2:** halos ride the swarm toward Haven. A destroyed rock leaves a
  drifting debris cloud, its pieces have their own halos, and no chunks
  appear.
- **QuickBattle in Multi1:** 54 halos. Read `space.minors.*` and the frame
  totals in the frame profiler (`` ` ``).
- **Everywhere:** fly through a cloud with shields up and with shields down.
  Look for the wake, the puffs, the grit and the flicker, and check that no
  hit effect fires constantly. Expect dial-tuning rounds through the shared
  `/ L O` keys.

## Out of scope

- Profile seeding, the density-field interface and Vesuvi's 0.4 band edit
  (sub-project 4).
- The far tier and impostors (3b). Minors below 1.5 px are simply culled here.
- Minors for NPC ships, weapons hitting minors, and minor-vs-minor contact.
- Shadow casting by minors.
- Persisting shove state across a cloud rebuild.
- Planetary rings and sensor occlusion.

## Risks

- **Surface mismatch between minors and majors.** A second shader can drift
  from `opaque.frag`. The pixel-agreement test pins it, but only for the
  shared lighting terms.
- **Tile-field density is a guess** (see Evidence gaps). Dialled live.
- **CPU step cost** grows with the number of instances in view. The budget,
  the pixel cull and the profiler scopes bound and expose it. GPU cost cannot
  be measured on this Mac.
- **Shield ring contention.** The flicker cap (2/s) is chosen so that, together
  with real hits, the 8-slot ring is not flooded. The probe pins the cap, not
  the visual result.
