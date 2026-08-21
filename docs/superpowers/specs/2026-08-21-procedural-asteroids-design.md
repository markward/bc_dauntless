# Procedural asteroids and rock damage — design

**Date:** 2026-08-21
**Status:** approved, pre-implementation

## Summary

Replace BC's eight authored asteroid models with procedurally generated rock,
and make weapon damage on rock read as rock rather than as a breached starship
hull.

Two halves, deliberately specified together because either alone is half a
feature — procedural rocks that crater like hulls, or rock craters on the same
dated geometry:

- **Generation.** A pool of generated variants (mesh + base colour + normal
  map), injected at the model-realise seam so everything downstream — lighting,
  shadows, decals, voxel damage, collision — is untouched.
- **Rock damage.** A per-instance surface class, keyed off BC's own
  `SPECIES_ASTEROID`, that swaps the crater interior and suppresses the
  ship-specific venting, electrical discharge and smoke.

## Context

- **Asteroids are `ShipClass` objects, not scenery.** `sdk/.../ships/Asteroid.py`
  is a normal LODModel + hardpoint pair (`HullProperty` 2500 condition, mass
  400, `SetRadius(0.8)`). They already flow through hull carve, breach, hit VFX
  and physics exactly like a starship.
- **Eight classes, not seven.** The seven `asteroid*` classes plus **Amagon**,
  which loads `asteroid3.NIF`, sets `SetShipName("Asteroid")` and declares
  `SetSpecies(712)`. Its `SpeciesToShip` row reads "Cardassian", but that
  column is affiliation, not hull type. Amagon is a genuine asteroid whose
  *class name* looks nothing like one — which is precisely why this design keys
  off species rather than filename.
- **The model-realise seam** is `engine/host_loop.py:3950-3995`, which resolves
  a ship's NIF path and texture search dirs and hands them to the `load_model`
  binding.
- **`assets::upload_mesh(MeshCpu)` and `assets::upload_image` are public** so
  the renderer can build its own meshes; `renderer/sphere_mesh.cc` is the
  precedent. The `TangentBasisTest` rig added on 2026-08-20 builds a complete
  synthetic `Model` (mesh + material + generated texture) by hand and renders it
  through `submit_opaque` — **that rig is the existence proof for this design's
  injection seam.**
- **`Material::StageSlot::Bump`** was given a deliberately source-agnostic
  contract by the normal-map work — *"a texture in this material's bump stage",
  not "a file found on disk"* — specifically so generated maps could attach
  without retrofitting. This design is the first consumer of that.
- **Per-instance properties** live on `scenegraph::Instance` (`rim_eligible` at
  `:47`, `breach_events` at `:132`) with `World::set_*` setters — the pattern
  the surface class follows.
- **Damage geometry is free.** `voxel/source_cache` uses a `*_vox.nif` sibling
  when present and **voxelises the hull mesh otherwise**. A generated asteroid
  has no sibling, so it takes the fallback.

### Constraints discovered while designing

- **Per-instance scale is uniform only.** `_world_matrix_from(loc, rot, s:
  float)` (`host_loop.py:4164`) takes a single scalar, and it is shared by
  ships, astro objects and the render-interpolation path. Non-uniform
  per-instance scale would mean changing all of that for a cosmetic gain, and
  would also break `GetRadius()` as a single meaningful number — which BC uses
  for targeting, the HUD's surface-distance range readout, and collision.
  **Resolution:** bake elongation into the generated variants (axis ratios are
  just generator parameters); per-instance variation is rotation + uniform
  scale.
- **`bound_radius` gates volume-hood.** `renderer/aabb.cc:74` skips any shape
  with `bound_radius <= 0` as "not a volume". BC models carry this from
  `NiTriShapeData`; a generated mesh has no such block, so the generator must
  set it or the asteroid silently stops being a volume for bounds and for the
  collision work landed in `ce68bcf0`.
- **`App.SPECIES_ASTEROID` does not exist in our shim.** The existing
  `SPECIES_GALAXY..SPECIES_GENERIC` block (`App.py:1611-1622`) is a documented
  **invented sentinel family** — its own comment says "Exact Appc values are not
  available; we use unique sentinel integers — they are only ever passed to
  `TGIcon_Create`". Those sentinels are 0-11; asteroids' real runtime species is
  **712**, set as a literal by all 8 hardpoints. See Risks.

## Non-goals

- **Asteroid field rendering.** `engine/appc/asteroid_field.py` still no-ops
  `SetNumTilesPerAxis` / `SetNumAsteroidsPerTile` / `ConfigField`, so BC's
  ambient tiled fields draw nothing. That is Project D — larger, and separate.
- LOD chains. One resolution per variant; see Risks.
- Replacing any non-asteroid model.
- Changing BC's asteroid hardpoints, hull values, mass or radius.

## Architecture

### Part 1 — generation

**1. The generator (C++).** `generate_asteroid_variant(index) -> {MeshCpu,
Image base, Image normal}`. Icosphere subdivided to ~1-2k triangles, displaced
by multi-octave 3D noise; per-variant axis ratios give elongation. Fully
deterministic: the variant index seeds everything, so the same index always
produces the same rock — which matters for save/reload consistency and for
tests.

Fidelity target is **modest mesh, strong normal map**: the silhouette comes from
geometry, the surface detail from the generated normal map, leaning on the
pipeline shipped on 2026-08-20.

**2. Bounds.** The generator computes `bound_center` / `bound_radius` on the
`MeshCpu` itself, enclosing every displaced vertex. Not a detail — see
Constraints.

**3. Surface bake.** Base colour and normal map are generated from the *same*
noise field as the displacement, in the *same* parameterisation as the mesh's
UVs. Because texture and UVs share one source, the longitude wrap is continuous
by construction rather than concealed. Both attach to the material's existing
`Base` and `Bump` slots.

**4. Injection.** A `generate_asteroid_model(variant)` host binding returns a
`ModelHandle`. One conditional at the model-realise seam: if the ship's species
is `SPECIES_ASTEROID`, generate instead of loading a NIF. Downstream code cannot
tell the difference.

**5. Variant assignment.** Deterministic from the ship's name so a given
asteroid is the same rock across saves and reloads, modulo the pool size.
Per-instance rotation and uniform scale are applied by the existing transform
path.

**Pool size is 32**, a Python-side tunable rather than a C++ constant, so it can
be changed without a rebuild — the same split `hull_carve.py` uses for its
eye-calibration knobs. 32 distinct shapes, each freely rotated and scaled, reads
as unbounded at combat range; raise it if repetition becomes visible in a dense
scene, at a linear cost in load time and VRAM.

### Part 2 — rock damage

**6. Surface class.** `scenegraph::Instance` gains `bool surface_is_rock`,
defaulting to `false`, with a `World::set_surface_rock(id, bool)` setter
mirroring `set_rim_eligible`, a host binding, and an `engine/renderer.py`
wrapper. A bool rather than an enum deliberately: there are exactly two
behaviours today, and an enum with two values is speculative structure. If a
third surface (ice, hull-with-ablative) ever arrives, widening a bool to an enum
is a mechanical change at four call sites. Set at spawn from the ship's species, so **the eight stock asteroid
classes get rock damage even with generation disabled** — Part 2 pays off
independently of Part 1.

**7. Crater interior.** `breach_pass` currently draws a pass-global animated
interior from `game/data/Damage1-4.tga` (`breach_pass.cc:42-50`), triplanar-
projected. For rock instances it instead samples **the instance's own base
colour texture**, triplanar and darkened, so the crater reads as fresh rock of
the same material. This works for stock asteroids and generated ones alike, and
introduces no new texture asset.

**8. Suppression.** For rock instances: `build_venting_descriptors` returns
none (rock vents no plasma), hull electrical discharge is skipped, and
`hull_hit_smoke.maybe_emit` returns early — the last is a Python-side check with
the ship in hand, so species is directly available.

**9. Debris.** `breach_debris` is retained but tinted toward rock rather than
hull, so impacts throw chunks and dust.

### Part 3 — the toggle

A Developer Options → **Lighting** row switching procedural vs stock asteroids,
default procedural, **labelled "(applies on mission load)"**. The Lighting tab
is the de-facto visual-toggles tab — it already carries forced glow-state and
the normal-map controls — so the row goes there rather than justifying a third
tab for one switch. Models are
realised once per ship at spawn, so flipping it does not retroactively change
spawned rocks; the dev mission picker is the A/B loop. A live instant switch
would require cache invalidation and re-realising every asteroid instance and is
explicitly out of scope.

Keeping the stock path costs one conditional — it is the path that already
exists — and Part 2 applies to both, so the toggle does not fork the damage
work.

## Data flow

```
ship spawn (species 712)
  → model-realise seam: generate_asteroid_model(variant_for(ship.name))
  → C++: icosphere + noise displacement → MeshCpu (+ bound_center/radius)
        + base colour Image + normal Image → Model with Base/Bump populated
  → ModelHandle → existing instance path (lighting, shadows, decals unchanged)
  → World::set_surface_rock(instance, true)     [from species, both paths]
  → on weapon hit: hull carve voxelises the generated mesh (no _vox sibling)
                   breach interior samples own base texture, darkened
                   venting / discharge / smoke suppressed
                   debris tinted to rock
```

## Testing

- **Generator determinism** — the same variant index yields byte-identical
  vertices, indices and texel data across two calls.
- **Bounds** — `bound_radius > 0` and the sphere encloses every vertex, for
  every variant in the pool. This is the test that would have caught the silent
  "not a volume" failure.
- **Variant distinctness** — different indices produce measurably different
  geometry, so the pool is not N copies of one rock.
- **Species keying** — an asteroid-species ship gets the rock surface class and
  a Galaxy does not; asserted through the host-facing wrapper, not by reaching
  into internals.
- **Rock suppression** — venting descriptors are empty for a rock instance and
  non-empty for a hull instance; `hull_hit_smoke.maybe_emit` no-ops for an
  asteroid-species ship.
- **Render smoke test** — a generated asteroid renders non-black through
  `submit_opaque`, following the `TangentBasisTest` synthetic-model rig.
- **Byte-identical fallback** — with generation disabled, an asteroid renders
  exactly as it does today.

All via `scripts/check_tests.sh`; per project convention, use `ctest --test-dir
build` rather than the raw `renderer_tests` binary, which has pre-existing
in-process GL-state leakage.

## Risks

- **`SPECIES_ASTEROID = 712` is SDK-tier evidence, not binary-confirmed.** All
  eight hardpoints set the literal 712, which is what the value will be at
  runtime, so the matching is correct regardless. But the constant itself should
  be defined from that evidence and labelled as SDK-tier; the clean-room
  reference was unavailable when this was written. **Do not conflate it with the
  0-11 sentinel family** — those are invented and documented as such, and adding
  712 beside them without a comment invites someone to "fix" the inconsistency.
- **Undefined-constant collapse.** If `SPECIES_ASTEROID` is left undefined, the
  comparison silently never matches and every asteroid stays a hull — no error,
  no crash. This class of bug has bitten this project repeatedly; the heatmap
  currently shows `SPECIES_FEDERATION_START` (188 hits) and `SPECIES_UNKNOWN`
  (153 hits) live in exactly this state.
- **Load-time cost.** N variants × (mesh generation + two texture bakes) happens
  at load. Needs a measured budget; if it is material, generate lazily on first
  asteroid spawn rather than eagerly at boot.
- **No LOD.** A field of hundreds (Project D) will want one. Deferred
  deliberately, but the generator should not make LOD generation harder — it
  produces geometry from a subdivision level, so a lower level is available by
  construction.
- **Concurrent work.** `ce68bcf0` landed real collision, and `MeshCpu` gained
  `bound_center`/`bound_radius` for shape-aware collision the same day. This
  design writes those fields; coordinate before changing their semantics.
