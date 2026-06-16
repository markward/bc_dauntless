# Tessellated Hull Damage Deformation — Design

**Date:** 2026-06-16
**Status:** Approved design, ready for implementation plan
**Phase:** 2 (C++ engine + renderer)

## Problem

The original STBC engine simulated hull damage by using "vox" meshes to cut
holes out of ship meshes. That approach produced unconvincing results — notably
giant see-through holes punched through thick parts of the hull.

We want a different approach: use GPU tessellation to deform the hull where it
takes critical damage — pushing in dents, opening ruptured gouges, and crushing
thin extremities (bow tip, saucer rim) inward on heavy impacts. Damage occurs
wherever a weapon strikes the hull and is arbitrary in location; it is **not**
sufficient to pre-bake damage around hardpoints.

### Explicitly out of scope

- **See-through holes / breaches.** No topology change, no visible interior
  through the far side of the hull. The surface stays watertight. (This is the
  specific failure mode of the old vox approach we are avoiding.)
- **Fine surface detail (greebles, panel lines, rivets) on undamaged hulls.**
  That requires per-ship displacement/height-map art we do not have.
  Tessellation alone adds triangles but cannot invent detail. Future work.
- **Collision/ramming damage *generation*.** Ramming is a desired *source* of
  large deformation, but producing a collision damage event is a separate
  combat concern. This design consumes such an event; it does not create it.
- **Save/load serialization** of deformation state (see §9).

## Three damage looks

At a given impact spot, the visual escalates with accumulated `depth`:

1. **Dent** — localized inward displacement; the original hull texture is
   preserved. The shallowest result.
2. **Gouge** — once displacement passes a rupture threshold, the interior fill
   is shown to read as a ruptured hull (charred ring + embers at the edge).
   Baseline interior is the stock `Damage.tga`; a procedural interior is
   available under the Modern VFX toggle (§7).
3. **Edge-crush** — thin extremities (bow tip, saucer rim) are physically
   shoved inward along the impact direction on heavy hits, changing the
   silhouette. Driven by the offline thickness bake (§3); thick hull sections
   resist, thin ones crush dramatically.

All three are pure surface displacement — GL 4.1-compatible, no topology change.

## Severity driver

A given spot's severity is driven by a **crater field** that combines two
behaviours the user called out:

- **Per-hit intensity.** A single big impact (e.g. a ram) deposits a deep,
  wide crater immediately.
- **Accumulation.** Repeated hits to the same region *deepen* an existing
  crater rather than spawning new ones, so torpedo-spamming one section caves
  it in over time.

Both fall out of the same merge-and-accumulate mechanism in the crater field.

---

## Architecture

### 1. Data model — `HullCraterField`

A new per-instance store in the scenegraph, parallel to the existing
`DamageDecalRing` (`native/src/scenegraph/include/scenegraph/damage_decals.h`).
It lives as a member on `scenegraph::Instance`
(`native/src/scenegraph/include/scenegraph/instance.h`).

Each crater is a flat POD record in **body frame** (ship-local, column-vector
basis per CLAUDE.md):

| Field             | Meaning                                                        |
|-------------------|----------------------------------------------------------------|
| `point_body`      | Impact location, body frame, model units                       |
| `impact_dir_body` | Unit impact direction (weapon ray / collision velocity), body  |
| `normal_body`     | Outward surface normal at impact, body frame                   |
| `radius`          | Crater radius, **model units** (GU ÷ instance scale `s`)       |
| `depth`           | Accumulated displacement depth, model units                    |
| `kind`            | Derived at shade time from `depth` vs rupture threshold        |
| `seq`             | FIFO insertion order, for eviction                             |

Rules:

- **Merge + accumulate on add:** a new hit within `kMergeFactor * radius` of an
  existing same-region crater adds to that crater's `depth` (capped at
  `kMaxDepth`) and may grow its `radius`, instead of allocating a new slot.
- **Bounded capacity** (~16–24 craters/ship; final number tuned during
  implementation against the per-vertex shader loop cost in §4). When full,
  evict the shallowest-oldest crater (a deep crater is more visually important
  than a shallow old one — differs from the decal ring's pure FIFO).
- **Lifetime:** persistent for the ship's lifetime (no transient reclaim — that
  is the decal ring's job). Runtime-only; not serialized (§9).
- **Distinct from decals, fed from the same hit event.** Decals handle
  transient surface scorch/glow shading; craters handle persistent geometry.

### 2. Offline thickness bake → per-vertex crushability

To make thin extremities crush while thick hull resists, each base-mesh vertex
gets a **crushability weight** ∈ [0, 1].

- **Computation:** cast a ray inward from the vertex along its `−normal` and
  measure the distance to the next back-facing intersection = local hull
  thickness. Reuse the existing Möller–Trumbore tracer
  (`native/src/renderer/ray_trace.cc`) against the CPU-resident mesh data.
- **Mapping:** normalize thickness to a weight — thin (small thickness) → 1.0
  (crushes easily); thick → 0.0 (resists). Mapping curve + clamp range tuned
  during implementation.
- **Storage:** a new per-vertex attribute on `assets::MeshCpu::Vertex`
  (`native/src/assets/include/assets/mesh.h`), uploaded as an extra vertex
  attribute (`native/src/assets/src/mesh_upload.cc`).
- **Caching:** the bake is deterministic per model. Compute once and cache to a
  sidecar file keyed by model path; regenerate if missing/stale. Avoids paying
  the O(V) ray-cast cost on every load.

### 3. GPU pipeline — displacement

The base NIF mesh stays static (`GL_STATIC_DRAW`, uploaded once). Deformation
happens entirely on the GPU.

- **GL context bump 3.3 → 4.1 core.** Tessellation control/evaluation shaders
  require GL 4.0+; macOS caps at 4.1 core, so 4.1 is the target. Existing
  `#version 330` shaders compile unchanged under a 4.1 context — this is a
  context-creation change plus additive shaders, not a rewrite. Compute shaders
  (4.3) remain unavailable and are not needed.
- **Shader class** (`native/src/renderer/shader.cc`) extended to accept optional
  TCS/TES stages alongside VS+FS. New `#version 410` tessellation shaders for
  the deform path; the static path keeps the current `opaque.{vert,frag}`
  untouched.
- **Draw path:** deform-eligible instances with active geometry are drawn as
  `GL_PATCHES` through VS → TCS → TES → FS; all other instances use the existing
  `GL_TRIANGLES` static path (`native/src/renderer/frame.cc`,
  `draw_model`).
- **TCS — adaptive tessellation:** per-patch tess level scales up near craters
  and with camera proximity, and falls to ~1 elsewhere. The player ship uses a
  low non-zero baseline even with zero craters (anti-pop, §5).
- **TES — displacement + normal recompute:** for each generated vertex,
  displacement = Σ over active craters of
  `depth · falloff(dist / radius) · crushability_interp`, applied along each
  crater's `impact_dir_body`. `crushability_interp` is the per-base-vertex
  crushability barycentrically interpolated across the patch. The normal is
  recomputed by finite-difference of the displacement field so lighting stays
  correct. Conservative, curvature-aware **Phong smoothing** is applied to the
  player hull here (§5).
- **FS — dent vs gouge shading** (extends current decal logic in
  `native/src/renderer/shaders/opaque.frag`): where accumulated displacement
  exceeds the rupture threshold, blend in the **gouge fill** — triplanar
  `Damage.tga` projected in body space (BC hull UVs mirror/overlap, so a direct
  UV sample would leak port↔starboard; triplanar avoids this), or a procedural
  interior under the Modern VFX toggle. Add a charred edge ring + embers reusing
  the existing decal ember/age code. Below threshold, the original hull texture
  is preserved (dent).

Crater data is uploaded as shader uniforms each frame for eligible instances,
mirroring the existing decal uniform upload (`frame.cc`,
`u_decal_a/b/c` + count).

### 4. Eligibility & cost control

Tessellation is restricted to keep cost bounded:

- **Player ship: always** on the tessellation pipeline (always eligible).
- **Other ships:** a per-frame **eligibility manager** (Python) selects a capped
  set of the N nearest / largest ships. N and the nearest-vs-largest weighting
  are tunable.
- Within the eligible set, **non-player ships only pay the displacement cost
  once they have ≥1 crater**; an undamaged eligible capital ship still renders
  via the cheap static path until it is hit. (The player always tessellates for
  anti-pop, even undamaged.)
- All non-eligible ships use the untouched static path and show damage via
  decals only.

The manager flags instances through a renderer binding
(`engine/renderer.py` wrapper → host binding → `scenegraph::World`
per-instance flag).

### 5. Player-ship always-on tessellation

The player hull is permanently on the tessellation pipeline at a low baseline
tess level, for two reasons:

1. **Anti-pop:** damage onset never causes a visible geometry/lighting jump from
   a sudden static→tessellated switch.
2. **Conservative fidelity smoothing:** curvature-aware Phong / PN-triangle
   smoothing rounds gently-curved hull regions (saucer rims, nacelle curves)
   and recomputes smoother normals — **only** where adjacent face normals
   already diverge gently, leaving sharp panels and corners intact. BC hulls are
   hard-surface; aggressive smoothing balloons flat panels, so this is
   deliberately conservative and is a tuning task during implementation.

Both behaviours sit under the Modern VFX toggle (§7); with it off, the player
render path is byte-identical to stock.

### 6. Data flow (hit → deformation)

```
combat.apply_hit  (engine/appc/combat.py)
  → hit_feedback.dispatch  (engine/appc/hit_feedback.py)
      ├── host.damage_decal_add(...)            # existing — transient scorch
      └── host.hull_deform_add(                 # NEW
              instance_id, world_point, world_normal,
              world_impact_dir, radius, depth, kind)
            → host binding (native/src/host/host_bindings.cc):
                world→body transform of point/normal/dir (reuse
                  world_to_body / world_dir_to_body),
                radius GU→model units (÷ instance scale s),
                HullCraterField.add() with merge + accumulate
```

Emission conditions mirror the decal path: only on hull-absorbing hits
(`absorbed_hull > 0`) where a mesh-trace normal is available (`normal is not
None`) and the renderer is present. `depth`/`kind` are derived from absorbed
hull damage by a new `engine/appc/hull_deformation.py` (mirroring
`engine/appc/damage_decals.py`'s intensity/radius helpers).

Ramming feeds the **same** `hull_deform_add` with a large `radius`/`depth`; the
collision damage source is a dependency, not built here.

### 7. Config — Modern VFX group

Two toggles join the existing **Modern VFX** graphics group (alongside HDR +
Fresnel-rim; see the modern-vfx design):

- **Procedural hull damage** — off (default) = stock `Damage.tga` gouge
  interior; on = shader-synthesized interior (charred metal, exposed ribbing,
  ember edges).
- **Player hull smoothing/tessellation** — enables the §5 always-on player
  tessellation + Phong smoothing.

With the Modern VFX group off, the production render path is byte-identical to
stock BC (consistent with the established off/off = stock-BC philosophy). The
gouge-interior choice affects **only** the FS gouge-fill branch; the
displacement (TCS/TES) is identical either way.

### 8. Error handling & fallbacks

- **GL 4.1 unavailable / tessellation unsupported:** detect at context
  creation; if 4.1 core can't be obtained, disable the deform pipeline entirely
  and fall back to the static path + decals (the feature degrades to current
  behaviour rather than failing).
- **Missing/sphere-fallback hit normal:** no crater is emitted (same guard as
  decals), so a deformation never lands at a bogus location.
- **Thickness-bake sidecar missing/corrupt:** recompute; if the ray-cast bake
  fails for a model, default crushability to a mid value so displacement still
  works (just without thin-extremity emphasis).
- **Crater field full:** evict shallowest-oldest; never grow unbounded.

### 9. Persistence

Deformation state is **runtime-only and not serialized**, matching how damage
decals work today. The crater field is a flat POD array in body frame; if save
support is added later, serialization = dumping that array into the BCS
object-state region with no structural change. No save-format work now.

---

## Components touched

**C++ (native/)**
- `scenegraph/` — new `HullCraterField` (header + impl); `Instance` member;
  `World` per-instance deform-eligible flag + accessors.
- `host/host_bindings.cc` — `hull_deform_add` binding (world→body transform,
  GU→model radius); deform-eligibility setter.
- `host/` GL context creation — request 4.1 core; capability detection +
  fallback.
- `renderer/shader.cc` — optional TCS/TES stage compilation.
- `renderer/` — new `#version 410` tessellation shaders (VS/TCS/TES or extend
  opaque); adaptive TCS; FS gouge-fill (triplanar `Damage.tga` + procedural);
  `frame.cc` patch draw path + crater uniform upload.
- `assets/` — crushability vertex attribute on `MeshCpu::Vertex`; upload;
  offline thickness bake module + sidecar cache (reusing `ray_trace`).

**Python (engine/)**
- `appc/hit_feedback.py` — emit `hull_deform_add` alongside the decal call.
- `appc/hull_deformation.py` — NEW: depth/kind/radius mapping helpers.
- eligibility manager — per-frame selection of player + capped nearest/largest
  ships (location TBD during planning: `host_loop` vs new module).
- `renderer.py` — wrappers for `hull_deform_add` + deform-eligibility.
- config + CEF graphics panel — two Modern VFX toggles.

## Testing strategy

**Python unit tests**
- `hull_deformation` depth/kind threshold mapping + radius (GU) scaling.
- `hit_feedback` emits the deform call **only** on hull-absorbing hits with a
  mesh normal, and not under god mode / sphere-fallback.
- Eligibility selection: player always included; nearest/largest cap respected;
  deterministic ordering.

**C++ unit tests**
- `HullCraterField`: add, merge-within-radius accumulation (depth grows, capped),
  shallowest-oldest eviction at capacity.
- Thickness bake on a known slab geometry: thin axis → high crushability, thick
  axis → low.
- `hull_deform_add` world→body transform of point/normal/impact direction
  (column-vector convention) and GU→model radius conversion.

**Manual / visual verification**
- Ram a ship head-on → bow folds inward along impact direction.
- Torpedo-spam one hull section → crater deepens, dent → gouge transition.
- Undamaged ships and Modern-VFX-off render unchanged from stock.
- Procedural toggle swaps gouge interior without changing displacement.

## Risks

1. **GL 4.1 on macOS's deprecated GL stack** — mitigated: 4.1 core +
   tessellation is supported (it's the macOS ceiling), and the change is
   context-creation + additive shaders with a static-path fallback.
2. **Phong smoothing ballooning hard-surface panels** — mitigated by
   curvature-aware, conservative smoothing; a tuning task, gated behind Modern
   VFX.
3. **Tessellation correctness is hard to unit-test** — leans on manual/visual
   verification; data-layer logic (crater field, bake, transforms) is unit
   tested in isolation.
4. **Per-vertex crater loop cost in TES** — bounded crater capacity + adaptive
   tess levels + eligibility cap keep it in check; final capacity tuned against
   measured cost.
