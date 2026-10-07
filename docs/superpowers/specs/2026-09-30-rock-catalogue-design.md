# Rock catalogue: offline asteroid assets and a glTF loader (design)

**Date:** 2026-09-30
**Status:** design, awaiting review
**Programme:** sub-project 1 of *modern asteroids*. See
`2026-09-30-modern-asteroids-roadmap.md` for sub-projects 2–4 and the decisions
already taken for them.
**Supersedes:** the *generation* half of
`2026-08-21-procedural-asteroids-design.md`. That spec's *rock damage* half moves
to sub-project 2.

## Summary

We are replacing BC's asteroid meshes with a committed, generated **rock
catalogue**: 13 major rocks and 24 fragments in four material families. Each rock
has LODs, baked textures, a far-tier impostor and a damage volume. The catalogue
is written to disk by an offline native tool and loaded at runtime through a new,
deliberately minimal **glTF loader**.

BC's asteroid scripts then draw a deterministic random catalogue rock, sized to
the stock mesh they asked for.

This is the asset foundation for the rest of the programme: rock class, minors,
seeding, far tier and, later, planetary rings. It is also the first step towards
glTF as the format for native Dauntless mods.

## Why

- **BC has only four asteroid meshes.** `asteroidh1`–`h3.NIF` are byte-identical
  copies of `asteroid1`–`3`, and Amagon loads `asteroid3.NIF`. Seven scripts, plus
  Amagon, share four dated shapes.
- **Runtime generation was too slow.** Branch `feat/procedural-asteroids`
  generated rocks at realise time. The mesh was cheap: all 32 variants took about
  140 ms (commit `9f422f60`). The per-variant surface bake was not: two 512²
  textures took about 1 s per variant in the test build (commit `4b9fb7e2`). Doing
  the same work offline removes the cost entirely.
- **Later sub-projects need a fixed, shared library.** Instanced minors need a
  small set of fixed meshes. The far tier needs per-rock impostors and average
  albedo. Breakup needs fragments that look broken. A committed catalogue provides
  all of these.

## Facts this design rests on (verified 2026-09-30)

- **Render size.** Every ship, rocks included, renders at NIF units × a flat
  `BC_MODEL_SCALE = 0.01` (`engine/host_loop.py:5596`) × the SDK's `SetScale`.
  - The `AddLOD(..., 4.50, 4.50, ...)` numbers in the asteroid scripts are
    surface and internal **damage resistance**, not scale
    (`engine/appc/lod_models.py:64`).
- **Stock mesh half-extents** (recorded in the branch's `asteroid_gen.h`):

  | NIF | Half-extent (NIF units) | ×0.01 (GU) | Hardpoint radius |
  |---|---|---|---|
  | asteroid | ≈74 | 0.74 | 0.8 |
  | asteroid1 | ≈23 | 0.23 | 0.24 |
  | asteroid2 | ≈55 | 0.55 | 0.744 |
  | asteroid3 | ≈478 | 4.78 | 5.0 |

  BC's hardpoint radii track the meshes, so mission scales were authored against
  these sizes.
- **Model loading has one entry point, and it only handles NIF.**
  - `AssetCache::load` (`native/src/assets/src/cache.cc:149-222`) sends
    everything to `nif::load`. There is no extension dispatch.
  - Python hands it absolute paths through `load_model`
    (`host_bindings.cc:548`).
- **The native model is already glTF-shaped.** `Model` is flat arrays with a
  `parent_index` node tree (`2026-05-09-asset-pipeline-design.md`). `MeshCpu` has
  position, normal and uv, but **no tangents**: `opaque.frag` rebuilds the tangent
  frame from screen-space derivatives. `Model` has **no stored bounds**; they are
  computed (`renderer/aabb.h`).
- **Image decoding.** stb_image is vendored with TGA and PNG enabled
  (`texture_decode.cc:3-6`). PNG is reachable through `decode_image`.
  `stb_image_write` is vendored.
- **JSON.** nlohmann_json v3.11.3 is already fetched (`native/CMakeLists.txt:45-50`).
- **Damage volumes.** `SourceVolumeCache` uses a `<stem>_vox` NIF sibling when
  one exists, and otherwise voxelises the hull at a fixed 48³
  (`native/src/voxel/src/source_cache.cc`).
  - `.dhv` is a signed-distance **bake cache** (`voxel/dhv.h`), not a source
    volume, so it is not reused here.

## Decisions (from the brainstorm)

| # | Decision |
|---|---|
| D1 | The catalogue is **generated offline and committed** under `native/assets/rocks/`. |
| D2 | **Four material families**, tagged in the manifest: silicate, carbonaceous, icy, metallic. BC scripts draw from silicate. |
| D3 | BC scripts get a **random shape at the authored size**: deterministic per object name, scaled to the stock mesh's size. |
| D4 | The redirect is **Python-level and catalogue-driven**, not the `replacements/` overlay. Rocks are a library, not replacements. |
| D5 | The tool also bakes **LODs, a far-tier impostor and average albedo**, plus a **damage volume**, for every rock. |
| D6 | Files are **glTF**, the intended format for future native mods. |
| D7 | The tool is **native C++ with cgltf** for both reading and writing, reusing the branch's generator. |

## Part 1: catalogue contents and layout

### Contents

Each rock is one shape with one family's surface. The counts live in
`recipe.json`; the starting counts are:

| Family | Majors | Fragments |
|---|---|---|
| silicate (grey) | 5 | 8 |
| carbonaceous (dark) | 3 | 6 |
| icy | 3 | 6 |
| metallic | 2 | 4 |
| **total** | **13** | **24** |

Per rock:

| | Majors | Fragments |
|---|---|---|
| Mesh LODs | icosphere subdivision 4 / 3 / 2 (5,120 / 1,280 / 320 tris) | subdivision 3 / 2 before plane cuts (1,280 / 320 tris) |
| Textures | base colour + normal, 1024², PNG | base colour + normal, 256², PNG |
| Far-tier impostor | 4×4 view atlas, albedo + normal, 512² | same |
| Damage volume | `.dvox` sidecar | `.dvox` sidecar (fragments become majors in breakup) |

- Subdivision levels, texture sizes and volume resolution are all recipe
  parameters.
- There is **no PBR**, matching the renderer (see the PBR spike memory). Gloss is
  a per-family material constant.

### Normalisation

Every rock is written centred on the origin, with LOD0's bounding sphere radius
at exactly **100 m** (100 glTF units; see the units convention in Part 3); lower
LODs share LOD0's centre and scale, so their radius is at most 100 m. LOD0's
100 m is ≈57.14 BC model units, or ≈0.571 GU at scale 1. Sizing a rock to a
particular use happens at load (Part 3), never in the files.

### Layout

```
native/assets/rocks/
  recipe.json              tool input — the source of truth
  catalogue.json           tool output — the manifest the engine reads
  majors/<family>_<nn>/    lod0.gltf lod0.bin lod1.gltf lod1.bin lod2.gltf lod2.bin
                           base.png normal.png impostor_base.png impostor_normal.png
                           volume.dvox
  fragments/<family>_<nn>/ lod0.* lod1.* base.png normal.png impostor_*.png volume.dvox
  review/contact_sheet.png every rock's front impostor view in a labelled grid
```

The LODs of one rock share its textures and volume.

`catalogue.json` records, for each rock:
- `id`
- `kind` (`major`/`fragment`)
- `family`
- LOD file paths
- bound radius in metres (always 100; recorded so a hand-edited rock can differ)
- average albedo (linear RGB)
- gloss
- impostor paths
- volume path

It also records the tool version and the recipe hash.

## Part 2: the generation tool

### Structure

- The branch's `asteroid_gen.{h,cc}` and `asteroid_noise.h` move out of the
  runtime `assets` library into a new small **`rockgen`** library. The runtime
  never generates rocks again.
- The **`rock_catalogue`** CLI (`native/tools/rock_catalogue/`) links `rockgen`,
  the existing `voxel` library and cgltf. It is built by the canonical `build/`
  tree, like `native/tools/dump_bounds`, and never through a parallel tree.
- Invocation:

  ```
  rock_catalogue --recipe native/assets/rocks/recipe.json --out native/assets/rocks [--only <id>]
  ```

- **cgltf** is vendored under `native/third_party/cgltf/` (single header, MIT),
  in the same way as stb.

### Shapes

- **Majors** use the branch's noise-displaced icosphere, with per-rock axis
  ratios, parameterised per family:
  - displacement amplitude
  - octaves
  - axis-ratio range
  - crater count and size (silicate and carbonaceous only)
- **LODs** sample the *same* displacement field at a lower subdivision, so the
  silhouette is stable across LOD switches.
- **Fragments must look broken, not round.** Each is a displaced blob cut by 2–4
  random planes, giving flat fracture faces with lightly roughened edges. The
  planes are chosen per fragment from its seed.
- After shaping, LOD0 is recentred and rescaled so its bounding sphere radius
  is exactly 100 m; every lower LOD reuses LOD0's centre and scale, so its
  radius is at most 100 m and it never pops against LOD0.

### Surfaces

- Base colour and normal are baked from the same noise field as the shape, in
  the mesh's UVs, as on the branch. The branch's spherical UV seam split is
  kept: seam vertices are duplicated with u+1 and rely on `GL_REPEAT`.
- Each family sets:
  - its palette
  - detail octaves
  - normal strength
  - gloss
- Normal maps are tangent-space with +Y up (OpenGL), consistent with the UV
  direction, because the renderer derives the tangent frame from UV
  derivatives.
- Rocks bake in parallel, one worker per rock. Output order and content do not
  depend on thread scheduling.

### Far-tier impostor

- A small CPU rasteriser in the tool (no GL) renders LOD1 from 16 fixed view
  directions into a 4×4 atlas, writing both albedo and normal.
- The view directions and the atlas layout are recorded in `catalogue.json`, so
  the far-tier renderer (sub-project 3b) does not have to hard-code them.
- Average albedo is the mean of the base texture over the mesh's surface, and is
  written to the manifest.

### Damage volume

- The existing `voxelize_tris` runs on LOD0 at the recipe resolution (default
  48³, the same as today's runtime fallback). The result is written as `.dvox`
  (format in Part 3).

### Review sheet

- Each rock's front impostor view is tiled into `review/contact_sheet.png`,
  labelled with its id and family, so the catalogue can be judged without
  launching the game.

### Determinism

- The same recipe and the same tool version produce byte-identical files.
- All randomness comes from a seed derived from `(recipe seed, rock id)`.
- PNGs are written with fixed compression settings.
- glTF JSON is written with stable key order and fixed float formatting.

## Part 3: runtime loading

### glTF loader (native)

- `AssetCache::load` gains its **first extension dispatch**:
  - `.gltf` / `.glb` goes to the new `gltf::load` (`native/src/assets/src/gltf_load.cc`, built on cgltf)
  - every other extension goes to `nif::load`, unchanged
- The loader builds the **same `Model`** as the NIF path:
  - nodes
  - meshes, with CPU data kept when `keep_cpu_data` is set
  - one `Material` per glTF material, with the `Base` and `Bump` stages bound
  - PNG textures via `decode_image`

  Downstream code (lighting, carve, bounds, ray trace, hull pieces) cannot tell
  which loader produced a model.
- **Supported:**
  - static triangle meshes
  - `POSITION`, `NORMAL`, `TEXCOORD_0`
  - `uint16` and `uint32` indices
  - the node TRS/matrix hierarchy
  - `baseColorTexture`, `baseColorFactor`, `normalTexture`
  - external `.bin` buffers and `.glb`
  - embedded images (`.glb` buffer views and base64 data URIs)
  - sparse accessors
- **Not supported:** skins, animation, morph targets, cameras, lights, and any
  extension. Each is **skipped with a one-time warning** per file — except an
  extension listed in `extensionsRequired`, which is a load error (see
  Conventions).
  - A primitive without `POSITION` is a load error (`AssetError`).
  - So is a non-triangle mode.
- **Conventions.** Mods will inherit these, so they are stated here and
  re-confirmed when the mod format gets its own design:
  - **Axes.** Files are standard glTF: Y-up, right-handed, with the asset's
    front facing +Z, so its right-hand side is −X. BC's model frame is Z-up, +Y
    forward and +X starboard. The loader maps `(x, y, z)_glTF → (−x, z, y)_BC`,
    a proper rotation (det +1, so no winding flip), and applies it to positions
    and normals. An asset exported from Blender therefore arrives the right way
    up and facing forward. The mapping is pinned by an asymmetric fixture test
    (Testing).
  - **Units.** 1 glTF unit = **1 metre**, as the glTF 2.0 specification defines.
    One BC model unit is 1.75 m (0.01 GU × 175 m), so the loader multiplies
    positions by `kGltfMetresToModelUnits = 1 / 1.75` after the axis mapping.
    A 642 m ship is authored as 642 units. Mod docs will note Blender's default
    1 km viewport clip for large stations.
  - **Normal maps** are +Y (OpenGL), matching ours. They get no
    `reconstruct_normal_map_z` pass.
  - **Texture URIs** resolve relative to the `.gltf` file. BC texture search
    directories and `mesh_fix` patches do not apply to glTF.
  - **Textures: PNG only** (JPEG is not decoded; a JPEG texture loads
    untextured with a warning).
  - **A required extension the loader does not support is a load error**
    (`AssetError` naming the extension). An extension that is only in
    `extensionsUsed` stays a one-time warning.
- **Cache.** glTF entries use the existing canonical-path key, plus the load
  scale (below).

### Load scale

- `load_model` gains an optional uniform `scale` (default 1.0). It multiplies
  vertex positions at build time, and it is part of the cache key.
- Because the scale is baked into the vertices, `model_aabb`, `model_bounds`, hull
  pieces, the carve field and the volume lookup all see the scaled mesh, with no
  special cases.
- The `.dvox` volume is scaled the same way when `SourceVolumeCache` reads it.

### Hull source keying (found while planning)

`Model::source` is the key for every damage-volume consumer: `CarveFieldCache`,
`SourceVolumeCache`, the `.dhv` `HullVolumeCache`, `hull_volume_resolution`, and
the hull-split bindings. The last two caches also **re-read the file** to
voxelise it or bake its SDF, and they only understand NIF. So both the glTF
format and the load scale have to reach them:

- **Source string.** `Model::source` is the file path when `scale == 1`, and
  otherwise `<path>#s=<scale, %.6g>`. Distinct scales therefore get distinct
  cache entries everywhere with no key changes. `assets/hull_source.h` provides
  `hull_source_string(path, scale)` and `split_hull_source(source) -> {path,
  scale}`.
- **One triangle source.** `voxel::collect_hull_triangles_from_source(source)`
  splits the source, reads NIF or glTF by extension, and applies the scale. It
  replaces the direct `nif::load` + `collect_hull_triangles_from_nif` calls in
  `SourceVolumeCache` and in `HullVolumeCache`'s bake.
- **The filesystem half.** Only the split path touches the filesystem: the
  existence checks and the `.dhv` size/mtime fingerprint. The `.dhv`
  `source_path` and key keep the full source string.
- **A GL-free glTF reader.** `assets::gltf::load_cpu(path, scale)` returns
  flattened `MeshCpu`s already in BC's frame and units, material image paths,
  and the `extras` volume path. The GPU build and the voxel library share it.

### `.dvox` damage volume sidecar

- **Layout:**
  - magic `DVX1`
  - `u16` format version = 1
  - `ivec3` dims
  - `vec3` origin
  - `vec3` cell size, in the same units as its glTF (metres). The reader applies
    the same axis mapping, metre conversion and load scale as the mesh
  - bit-packed occupancy, x-fastest, padded to a byte
- **Linking.** A glTF file points at its volume through standard glTF `extras`
  on the asset object: `"extras": {"dauntless_volume": "volume.dvox"}`. The path
  is relative to the `.gltf`.
- **Lookup.** `SourceVolumeCache::get_for_hull` does the following for a glTF
  hull:
  1. It reads the `extras` using cgltf, parsing only the JSON.
  2. If `dauntless_volume` names a file, it loads the `.dvox`.
  3. Otherwise it voxelises the glTF triangles at 48³, exactly as it does for a
     NIF with no `_vox` sibling.

### Catalogue module (Python)

`engine/rocks/catalogue.py` exposes:

- `load()` reads `catalogue.json` from `paths.project_asset_root() / "rocks"`
  **at use**, with no module-level path. It is memoised per resolved path.
- `pick(key: str, kind: str = "major", family: str = "silicate") -> Rock` picks
  `crc32(key) % len(candidates)` over the rocks of that kind and family, in
  manifest order.
- `Rock` carries:
  - `id`
  - `family`
  - `lod_paths` (absolute)
  - `bound_radius`
  - `avg_albedo`
  - `gloss`
  - `impostor`
  - `volume`

### BC redirect

- At the model-realise seam (`engine/host_loop.py` `realize_set_objects`,
  `_ship_nif_path`), a ship gets `catalogue.pick(ship.GetName(), "major",
  "silicate")` **when its `FilenameHigh` is one of the four stock asteroid
  NIFs**:
  - `data/Models/Misc/Asteroids/asteroid.NIF`
  - `asteroid1.NIF`
  - `asteroid2.NIF`
  - `asteroid3.NIF`
  - `asteroidh1.NIF`, `asteroidh2.NIF`, `asteroidh3.NIF`

  Amagon points at `asteroid3.NIF`. The `h` scripts load their **own** files
  (`ships/Asteroidh1.py` → `asteroidh1.NIF`): byte-identical to `asteroid1`–`3`
  but separate paths, so they are keyed separately at the same radii (they
  were missed until 2026-10-07 and drew BC's mesh). Matching is
  case-insensitive.
- **Keyed on the stock filenames, not species 712**, so a mod that ships its own
  asteroid model is left alone.
- **Size.** Load scale = `STOCK_RADIUS_MU[nif] / (rock.bound_radius_m / 1.75)`.
  `STOCK_RADIUS_MU` is the stock mesh's bounding radius in BC model units: the
  largest vertex distance from the model origin, the same definition the tool
  normalises rocks by. The divisor is the rock's radius after the loader's metre
  conversion. The four
  constants live in `engine/rocks/catalogue.py`, and an asset-backed test measures
  the real NIFs against them (Testing). The ship's `SetScale` still applies on
  top, exactly as today.
- **LOD.** Only `lod0` loads. The engine has no geometry LOD, and LOD switching
  arrives with minors (sub-project 3).
- **Unchanged in this sub-project:** hardpoint radius, hull, mass and genus.
  Sub-project 2 replaces them.
- **Developer toggle.** Developer Options gets a row, "Rocks: catalogue / stock
  BC", labelled *(applies to rocks loaded after toggling)*. The default is catalogue. It sits on
  the same tab the branch used for its procedural toggle (Lighting, the de facto
  visual-toggles tab at the time -- moved to a dedicated Environments tab in the
  2026-10-05 Developer Options cleanup). It is not persisted, and it exists for A/B checks.

## Testing

Every test runs under `scripts/check_tests.sh`, which must exit 0.

- **rockgen (C++):**
  - **determinism:** byte-identical mesh and texels across two runs
  - **bounds:** LOD0's bounding sphere radius is 100 m ± ε for every recipe
    rock, and every lower LOD shares LOD0's centre and scale (radius ≤ 100 m)
  - **distinctness:** different ids give measurably different geometry
  - **fragment faces:** every fragment has 2–4 near-planar face clusters
  - **LOD fidelity:** each LOD's radial profile stays within tolerance of LOD0
  - the branch's **UV-seam** test is kept
- **glTF loader (C++):**
  - **round trip:** the tool writes a rock and the loader reads back equal
    vertices, indices and UVs
  - **axis conversion:** an asymmetric fixture with distinct markers on glTF
    +Y (up), +Z (front) and −X (right) lands them on BC +Z, +Y and +X, and
    triangle winding is preserved
  - **unsupported features:** a fixture with a skin and an animation loads its
    static mesh and warns once
  - **missing `POSITION`:** throws `AssetError`
  - **materials:** Base and Bump bind to the PNGs
  - **metres:** a fixture cube 1.75 m on a side loads as 1 BC model unit on a
    side
  - **scale:** `scale=2` doubles the AABB and gives a distinct cache entry
- **`.dvox` (C++):**
  - write/read round trip
  - `SourceVolumeCache` prefers the `extras` sidecar
  - it falls back to 48³ voxelisation when the sidecar is absent
- **Drift (C++ or pytest):** two committed rocks, one major and one fragment,
  are regenerated with `--only` and compared byte for byte with the committed
  files.
- **Python:**
  - the catalogue is read at use (`tests/unit/test_path_indirection.py` stays
    green)
  - `pick` is deterministic and covers every candidate across a name sweep
  - the redirect fires for the four stock NIFs (in any case) and for nothing else
  - the load scale produces the stock size
  - the developer toggle is respected
  - the conftest autouse reset covers the toggle
- **Asset-backed:** the measured AABBs of the four stock NIFs match
  `STOCK_RADIUS_MU`. BC content is found through the configured content root,
  never a hard-coded `game/`. With a root configured, a skip fails the gate
  unless baselined.
- **Host (hidden GL window):** `load_model` on a catalogue rock at a stock scale
  gives the expected `model_aabb`.

**Live check (Mark):** run `./build/dauntless --developer` and check:
- E1M2 (Vesuvi 6 debris and moving asteroids)
- E3M2 (Vesuvi 4 "Unknown Debris": scanning still works)
- QuickBattle in Belaruz 4
- in each, flipping the catalogue/stock toggle

## Non-goals

These are deferred, not dropped. Each is recorded in the roadmap:

- the rock class, hardpoint removal, and leaving the ship-cost paths (sub-project 2)
- rock damage visuals, salvaged from the branch (sub-project 2)
- chipping and breakup (sub-project 2)
- minors, instancing and runtime LOD switching (sub-project 3)
- far-tier rendering (sub-project 3b)
- seeding, the density-field interface and tile fields (sub-projects 3 and 4)
- the Vesuvi band change from 0.5 to 0.4 (sub-project 4)
- sensor occlusion by rocks (a later play-test experiment)
- the full glTF mod format (its own design)

## Risks

- **Repo size.** The committed catalogue is tens of MB, which is accepted (D1).
  Texture sizes are recipe parameters if it needs trimming.
- **Normal-map tangent frame.** The shader derives tangents from UV derivatives,
  so a bake whose normal map disagrees with its UV direction would light
  inverted. The branch validated its bake. The round-trip test and the live
  check re-verify it.
- **The glTF axis convention becomes a mod precedent.** It is pinned by a
  fixture test and flagged for re-confirmation in the mod-format design.
- **Branch drift.** `feat/procedural-asteroids` forked in August. Only its
  generator files are ported here, not its renderer changes, so drift is
  limited to the build files.
