#version 410 core

// Breach interior — the far wall of a hull cavity, found by raymarching the
// per-instance DAMAGE field through a per-instance BOX proxy (raymarched-
// breach-interior Task 3; supersedes the old per-carve sphere scoop).
//
// One draw per DAMAGED INSTANCE (breach_pass.cc's draw_box_proxy), not one
// per carve: the box covers the instance's whole damage-field extent, so a
// carve past the old 24-slot sphere ring's cap still gets an interior drawn
// for it -- the field itself has no such cap. For each fragment:
//   1. Reconstruct the view ray in body frame from v_body_pos (this box's
//      far-face position -- see below) and u_camera_pos_body.
//   2. Walk the ray to find where it first enters carved material
//      (find_breach_entry), then raymarch from there to the cavity's far
//      wall (raymarch_breach_cavity, Task 2) -- hit_point/hit_normal.
//   3. Map hit_point to a texture coordinate in the ORIGINAL (uncarved) fill
//      (GL_R8 3D texture). If the fill value is below u_fill_backing, there
//      is no real hull material there → discard: this is what keeps a carve
//      brush's far edge (floating past a thin plate; see raymarch_breach_
//      cavity's KNOWN GAP comment) from painting as though it were a real
//      wall -- "a hole is a hole".
//   4. Triplanar projection of BC's Damage.tga onto hit_point -- muted grey
//      interior shading, unchanged from the pre-Task-3 scoop.
//
// Rendered with glCullFace(GL_FRONT) so only the box's back (far) faces are
// drawn; no geometry can poke out past the hull.
// Depth-test ON, depth-write ON: the proxy hides behind intact hull (depth
// written by the opaque pass) and shows only through an actual hole (no
// depth there).

// v_body_pos is the box's FAR-face position (this pass
// rasterises only the box's back faces -- glCullFace(GL_FRONT), breach.vert)
// -- i.e. exactly the point where this fragment's view ray EXITS the field's
// AABB. v_body_normal/v_world_pos are gone: the box carries no meaningful
// per-vertex normal (unlike the old per-carve sphere, whose vertex WAS the
// outward normal), and the fragment recomputes its own world position from
// whichever body-frame point it ends up shading (hit_point, not v_body_pos)
// via u_model -- see main() below.
in vec3 v_body_pos;

// Original (uncarved) hull fill — static per hull, never rebuilt.
// GL_R8: byte b samples as b/255.0; occ 0..127 → [0, ~0.498].
// u_fill_iso = 64/255.0 (matches the hull clip isovalue).
uniform sampler3D u_fill;
uniform vec3      u_fill_origin;   // body-frame min corner
uniform vec3      u_fill_cell;     // cell size per axis
uniform ivec3     u_fill_dims;     // nx, ny, nz
uniform float     u_fill_iso;      // 64.0/255.0 — solid interior (rim falloff)

// SPIKE (backing-material gate): "is there ANY hull material here?", the same
// threshold opaque.frag's hull cut uses. The two MUST match, or the hole and
// the interior are different shapes again and the gap between them is a window
// through the ship. Discarding at u_fill_iso instead put 39-53% of hull
// triangles (measured, stock hulls) outside the scoop's own mask.
uniform float     u_fill_backing;  // kBackingIsovalue/255.0

uniform sampler2D u_damage_tex;
uniform vec3      u_camera_pos_ws; // camera world position — uploaded CPU-side, avoids per-fragment inverse
uniform float     u_tex_scale;     // body-units -> texture-period scale

// Box-proxy Task 3 additions.
// u_model: ship world matrix -- needed here (not just in breach.vert) because
// main() now shades at hit_point (a body-frame point the raymarch finds,
// generally NOT v_body_pos) and must transform THAT point to world space for
// the view-dependent lighting term below.
// u_camera_pos_body: camera position in THIS instance's body frame,
// precomputed CPU-side (one matrix inverse per draw, not per fragment --
// same idiom as u_camera_pos_ws) -- the ray origin every fragment marches
// from.
uniform mat4  u_model;
uniform vec3  u_camera_pos_body;

// Molten-rim emissive (hull-breach-2c).
// u_breach_age: age of the matching breach event (large value → cold when no match).
// u_rim_life:   kRimLife constant; rim cools to 0 by this age.
uniform float u_breach_age;
uniform float u_rim_life;

// Copied verbatim (not shared: embed_shader reads one file at a time --
// see native/src/renderer/CMakeLists.txt:5-11) from opaque.frag's hull-clip
// field sampling, byte-identical between the drift-guard markers below
// (native/tests/renderer/breach_field_sampling_test.cc). Sampler unit: the
// breach pass already binds unit 0 (u_fill) and unit 1 (u_damage_tex);
// whichever pass wires this uniform MUST put it on unit 2 -- and must set
// that unit on every code path, enabled or not, or an unset sampler
// defaults to unit 0 and collides with u_fill's sampler3D there
// (GL_INVALID_OPERATION on every draw).
// === HULL_FIELD_SAMPLING BEGIN === KEEP IN SYNC with opaque.frag's copy between its own matching markers -- enforced by native/tests/renderer/breach_field_sampling_test.cc
uniform sampler2D u_hull_field;      // R8 slice atlas; DAMAGE field (not hull
                                      // shape -- renderer/instance_field_cache.h);
                                      // 128 = a carve's zero crossing, 1 = the
                                      // most-negative byte ("no damage")
uniform int   u_hull_field_enabled;  // 0 = stock path, zero per-fragment cost
uniform vec3  u_hull_field_origin;   // body frame, model units
uniform vec3  u_hull_field_cell;     // model units per cell
uniform vec3  u_hull_field_dims;     // float (dims.x, dims.y, dims.z) -- avoids int division below
uniform vec2  u_hull_field_tiles;    // tiles_x, tiles_y (voxel::AtlasLayout)
uniform vec2  u_hull_field_texel;    // 1 / atlas size, i.e. (1/width, 1/height)

// Fetch one Z-slice's raw (normalised [0,1]) texel at continuous in-slice
// coordinate `sxy` (sample-space: an integer component lands exactly on that
// index's stored sample; -1 and dims are the replicated border). `slice` is
// a float holding an already-clamped integer index into [0, dims.z - 1].
float hull_field_slice(float slice, vec2 sxy, float tile_w, float tile_h) {
    float tile_ox = mod(slice, u_hull_field_tiles.x) * tile_w;
    float tile_oy = floor(slice / u_hull_field_tiles.x) * tile_h;
    // +1 skips the tile's own border column/row; +0.5 lands on the texel
    // CENTRE so texture() samples exactly the stored value at sxy == integer,
    // matching voxel::pack_field_to_atlas's interior-texel placement.
    vec2 atlas_texel = vec2(tile_ox, tile_oy) + 1.0 + sxy + 0.5;
    return texture(u_hull_field, atlas_texel * u_hull_field_texel).r;
}

// Sample the per-instance DAMAGE field at a body-frame point, returning a
// value whose SIGN matches voxel::DistanceField's convention rescaled from
// the packed encoding: negative = no damage at this point (the untouched
// default, -127, everywhere field_carve_oblate's brushes have never reached
// -- this is NOT "inside solid hull" in the hull-SDF sense; it is simply
// "not carved"), positive = carved (a discard). ONE function -- every
// consumer of the field (today's clip, anything added later) must sample
// through here so they cannot drift apart.
//
// Encoding: pack_field_to_atlas stores byte = round(d / scale) + 128, so
// texture() (GL_R8, normalised) returns byte / 255 = (round(d/scale) + 128)
// / 255. Subtracting 128/255 EXACTLY (not 0.5 -- 128/255 = 0.50196..., a
// half-quantisation-step bias toward "outside" at exactly the boundary
// Critical 1's kHullFieldIsoMargin exists to guard) leaves
// round(d/scale) / 255 -- i.e. this function's return value is
// d / (scale * 255), plus at most +-0.5/255 of rounding error. That last
// fact is what makes kHullFieldIsoMargin below scale-independent: see its
// derivation.
//
// Z has no atlas border (slices are whole tiles, not filtered together by
// hardware) -- the two bracketing slices are fetched by hand and lerped,
// which is exactly what the atlas border on X/Y exists to make safe to do
// per-slice via hardware bilinear.
float sample_hull_field(vec3 p_body) {
    // DistanceField cell (x,y,z)'s stored sample sits at body-frame position
    // origin + (idx + 0.5) * cell (voxel/field_brush.cc, distance_field.h),
    // so subtracting 0.5 after dividing by cell converts a corner-relative
    // coordinate into "sample space", where an exact integer lands on a
    // stored sample and hardware bilinear does the rest between them.
    vec3 g = (p_body - u_hull_field_origin) / u_hull_field_cell - 0.5;

    // Clamp X/Y into the atlas' own padded range [-1, dims]: precisely the
    // border pack_field_to_atlas replicated, so this can never read a
    // neighbouring tile no matter how far outside the field's box p_body is.
    vec2 sxy = clamp(g.xy, vec2(-1.0), u_hull_field_dims.xy);

    // Z: clamp into the valid slice range FIRST (there is no border to fall
    // back on), then bracket with the next slice up, clamped at the top edge
    // so s1 never reaches an out-of-range (or unused/kOutside) tile.
    float sz = clamp(g.z, 0.0, u_hull_field_dims.z - 1.0);
    float s0 = floor(sz);
    float s1 = min(s0 + 1.0, u_hull_field_dims.z - 1.0);
    float wz = sz - s0;

    float tile_w = u_hull_field_dims.x + 2.0;   // voxel::AtlasLayout::tile_w
    float tile_h = u_hull_field_dims.y + 2.0;   // voxel::AtlasLayout::tile_h

    float v0 = hull_field_slice(s0, sxy, tile_w, tile_h);
    float v1 = hull_field_slice(s1, sxy, tile_w, tile_h);
    return mix(v0, v1, wz) - (128.0 / 255.0);   // > 0 carved (discard), < 0 no damage
}
// === HULL_FIELD_SAMPLING END ===

// Cavity-wall raymarch (raymarched-breach-interior Task 2), called from
// main() below via find_breach_entry (Task 3) once that has located where
// the view ray first enters carved material. Originally written and tested
// in isolation before Task 3 wired it in -- see
// native/tests/renderer/breach_raymarch_test.cc, which splices this file's
// own production text onto a test-only main() and still exercises this
// function directly, independent of main()'s own box-proxy plumbing.
//
// A fragment that will reach this pass is, by the stencil (breach_pass.cc,
// GL_EQUAL against 1), one where sample_hull_field(entry point) already
// reads > kHullFieldIsoMargin -- i.e. carved. From `ro` (that entry point,
// body frame) this steps `rd` (body frame, UNIT length, pointing FURTHER
// INTO the hull) until the field falls back to <= margin: the far wall of
// the cavity.
//
// PRECONDITION this function does not itself check: call this only when a
// valid per-instance field is actually bound on unit 2 (this pass's unit;
// opaque.frag binds the same atlas on its own unit 6 -- the two passes don't
// share a texture unit, only the sampling code). Task 3's call site owns
// that gate structurally rather than with a per-fragment u_hull_field_
// enabled branch: BreachPass::render() (breach_pass.cc) only ever issues a
// draw_box_proxy() call for an instance that InstanceFieldCache::get()
// already returned a real Entry for, so every fragment that reaches main()
// in this pass has a genuinely bound, current field on unit 2 -- there is no
// "disabled" draw to gate against, unlike opaque.frag which draws every
// instance (damaged or not) through one shared program.
//
// KNOWN GAP, deliberately not fixed here: the field carries DAMAGE ONLY,
// never hull geometry (renderer/instance_field_cache.h). A carve's brush
// (field_carve_oblate) is admitted into the field as a single all-or-
// nothing decision -- carve_has_backing gates whether the WHOLE brush is
// deposited (instance_field_cache.cc's hull_carve_deposit), not a per-cell
// clip of the brush against real hull thickness. So a carve that visually
// cuts clean through a thin plate still leaves a bounded, brush-shaped
// positive region in the field, and this march will still find ITS far
// edge and report a hit there -- a wall floating in open space, not real
// hull material. This function alone cannot tell the two cases apart: it
// only has the damage field, not the hull's own backing/fill volume (bound
// as u_fill above, used today only by main()'s discard mask). Task 3, which
// already has access to both, must additionally check the fill/backing
// volume AT hit_point before treating a reported hit as real -- do not
// treat this function's `true` return as sufficient on its own.

// GLSL const has no linkage across two separately compiled programs, so
// this is breach.frag's own copy of the VALUE -- not a second, independently
// chosen threshold (native/tests/renderer/breach_raymarch_test.cc's
// IsoMarginMatchesOpaqueFragsValue guards the two never drifting apart).
// See opaque.frag's kHullFieldIsoMargin for the derivation: half a
// quantisation step, dimensionless in sample_hull_field's own return units,
// so it is correct for any instance's `scale` unchanged.
const float kHullFieldIsoMargin = 0.5 / 255.0;

// Smallest field-cell axis: the field can in principle be anisotropic, and
// the march must resolve detail on whichever axis is thinnest.
float breach_min_cell() {
    return min(u_hull_field_cell.x, min(u_hull_field_cell.y, u_hull_field_cell.z));
}

// Step-size derivation: a step of a full cell can still land on samples
// that bracket the WHOLE crossing (a single iso crossing between two
// adjacent slice centres is always caught by pigeonhole once the step is
// no larger than the crossing band itself), but it locates that crossing
// coarsely, and it is the minimum margin before a genuinely thin feature
// -- a wall closer to the field's per-cell resolution limit than the ~1
// cell interpolation band above -- can be stepped over entirely between
// two samples that both land on its carved flanks. Half a cell is the
// Nyquist step for a linear feature (the iso crossing is a POINT on a 1-D
// profile along the ray, not a band with area to miss): two samples per
// cell is the minimum spacing that cannot straddle a whole cell width
// without landing inside it at least once. Finer than that only spends
// more fragments for no better a hit, since the crossing itself is then
// refined analytically below (linear interpolation between the two
// bracketing samples, not the step grid) rather than by taking smaller
// steps.
const float kHullFieldStepFrac = 0.5;

// Bounded steps -- an unbounded loop in a fragment shader is a hang, not a
// slow frame. kBreachMaxSteps caps the loop directly and unconditionally:
// see BreachRaymarchStaticGuard.LoopBoundIsANamedCompileTimeConstant.
const int kBreachMaxSteps = 64;

// Longest useful march distance: the field's own body-frame box diagonal
// (length(dims * cell)), NOT a fixed model-unit constant. A first version
// of this used `const float kBreachMaxDist = 64.0` model units, commented
// "past any BC hull's extent" -- that comment was WRONG. 1 model unit =
// 0.01 GU and 1 GU = 175 m (engine/units.py), so 64 model units is 0.64 GU,
// about 112 m -- a small fraction of a real hull, not past its extent.
//
// BC's authored cell is cell = authored_res / quality (voxel/
// hull_volume_cache.h, quality default 2.0); authored_res runs 6-15 across
// the fleet (docs/engine/damagetool-and-hull-damage-gaps.md), so cell runs
// 3.0-7.5 model units, and step_len = kHullFieldStepFrac * cell = 1.5-3.75.
// The OLD fixed 64.0 cap fired at 64/step_len = 17.1-42.7 samples across
// that range -- fewer than kBreachMaxSteps (64), so it WAS the binding
// limiter, on every ship, not just small ones. The field's own box already
// hugs the hull (voxel::distance_field_from_tris' AABB plus its accuracy
// band), so its diagonal both scales automatically with every ship and is
// provably an upper bound for any single straight march that starts inside
// the box: no axis-aligned (or any other) march confined to the box can
// exceed it.
float breach_field_reach() {
    return length(u_hull_field_dims * u_hull_field_cell);
}

// Field gradient by central differences, body-frame units. Points toward
// INCREASING field value -- i.e. toward the carved/cavity side, away from
// intact material -- which is the "out of the wall, into the open cavity"
// direction the interior shading needs: a wall lit as though its normal
// pointed at the solid material behind it would read inside-out.
vec3 breach_field_gradient(vec3 p) {
    float h = max(breach_min_cell() * 0.25, 1e-5);
    float dx = sample_hull_field(p + vec3(h, 0.0, 0.0)) - sample_hull_field(p - vec3(h, 0.0, 0.0));
    float dy = sample_hull_field(p + vec3(0.0, h, 0.0)) - sample_hull_field(p - vec3(0.0, h, 0.0));
    float dz = sample_hull_field(p + vec3(0.0, 0.0, h)) - sample_hull_field(p - vec3(0.0, 0.0, h));
    vec3 g = vec3(dx, dy, dz);
    float len = length(g);
    // Degenerate (flat) gradient: fall back to a fixed unit vector rather
    // than dividing by ~0 -- never NaN, even though this should not occur
    // at a genuine iso crossing.
    return len > 1e-8 ? g / len : vec3(0.0, 0.0, 1.0);
}

// `ro`/`rd` body frame; `rd` MUST be unit length (the step below assumes
// unit-speed marching). `hit_point`/`hit_normal` are always written (zeroed
// on a miss) so a caller that ignores the bool return never reads
// undefined `out` values -- this shader's own HDR bloom pass has a
// documented history of turning an uninitialised/NaN value into a black
// square. Returns false -- a MISS, paint nothing, the same "a hole is a
// hole" rule the fill mask above already applies -- when:
//   * `ro` is not already inside carved material (nothing to march INTO), or
//   * the field never falls back below the margin within the bounded
//     step/distance budget.
// See this function's header comment above for the KNOWN GAP a `true`
// return does NOT yet cover: a hit here may be the far edge of a carve
// brush in open space, not real hull material -- Task 3 must additionally
// check the backing/fill volume at hit_point.
bool raymarch_breach_cavity(vec3 ro, vec3 rd, out vec3 hit_point, out vec3 hit_normal) {
    hit_point  = vec3(0.0);
    hit_normal = vec3(0.0);

    float step_len = max(breach_min_cell() * kHullFieldStepFrac, 1e-5);
    float max_dist = breach_field_reach();

    float prev = sample_hull_field(ro);
    if (prev <= kHullFieldIsoMargin) {
        return false;   // not starting inside carved material: no cavity here
    }

    vec3 p_prev = ro;
    // Loop bound is the named compile-time constant directly (not a
    // runtime-derived step count) -- see
    // BreachRaymarchStaticGuard.LoopBoundIsANamedCompileTimeConstant.
    //
    // Which cap binds where: the step budget alone can only ever reach
    // kBreachMaxSteps * kHullFieldStepFrac = 32 cells deep (64*0.5),
    // independent of cell size -- 96-240 model units across BC's real
    // authored_res range (see breach_field_reach's derivation). A full-size
    // warship's own field diagonal is well past that: MEASURED (not
    // derived from hull dimensions -- docs/superpowers/specs/
    // 2026-09-08-dauntless-hull-volumes-design.md Table 2.5, baked against
    // the real implemented SDF baker), Galaxy's actual field is
    // 101x137x37 cells at cell=5.0, i.e. extent 505x685x185 model units,
    // diagonal ~871 model units -- BEFORE any further padding. Galaxy's
    // own budget reach at that same cell=5.0 is 64*0.5*5.0=160 model
    // units, so on the ships this feature exists for, kBreachMaxSteps
    // binds FIRST, by a factor of ~5.4 (871/160) -- not breach_field_reach(),
    // which only ever matters on small craft or this file's own tiny
    // synthetic test fields.
    //
    // Consequence, stated plainly rather than left implicit: a contiguous
    // carved run deeper than ~32 cells (~160 model units on a Galaxy) will
    // still silently miss its far wall. No single carve's own depth
    // approaches that (field_carve_oblate's depth is a small fraction of
    // its radius), but a long chain of merged, overlapping carves boring in
    // the same direction could. Not fixed here -- kBreachMaxSteps is a
    // fragment-cost budget, not something to raise casually.
    for (int i = 0; i < kBreachMaxSteps; ++i) {
        float dist = step_len * float(i + 1);
        if (dist > max_dist) {
            return false;
        }
        vec3 p_next = ro + rd * dist;
        float v = sample_hull_field(p_next);
        if (v <= kHullFieldIsoMargin) {
            // Refine within this one step by linearly interpolating the two
            // bracketing samples -- no extra texture fetch, and exact for a
            // field that (like the true cavity boundary near its wall) is
            // locally linear between them.
            float t = clamp((prev - kHullFieldIsoMargin) / max(prev - v, 1e-6), 0.0, 1.0);
            hit_point  = mix(p_prev, p_next, t);
            hit_normal = breach_field_gradient(hit_point);
            return true;
        }
        prev   = v;
        p_prev = p_next;
    }
    return false;   // ran the whole budget: no crossing, no far wall
}

// ── Box-proxy entry search (raymarched-breach-interior Task 3) ─────────────
//
// raymarch_breach_cavity (above) requires its OWN `ro` to already sit inside
// carved material -- true by construction for the old per-carve sphere (its
// geometry WAS shaped to the carve, sized and centred on it) but not for this
// task's box proxy, which covers the instance's WHOLE damage-field box: most
// rays through it never touch a carve at all. These two helpers are what
// main() uses to find where -- if anywhere -- a given view ray first crosses
// into carved territory, before handing that point to raymarch_breach_cavity
// to find the FAR wall of that same cavity.

// Analytic (loop-free) ray/AABB entry distance: the smallest `t >= 0` at
// which `ro + rd*t` crosses into the field's own body-frame box
// (u_hull_field_origin .. + u_hull_field_cell*u_hull_field_dims -- the SAME
// box breach.vert places its proxy geometry at). Standard slab test.
// Components of `rd` at or near 0 produce +-inf in `inv_rd`; the min/max
// reduction below is still correct under IEEE arithmetic (a ray parallel to
// a slab either always or never lies within it along that axis, and +-inf
// sorts to the correct side of both cases).
//
// Clamped to >= 0 so a camera already inside the box (a first-person/cinematic
// view close to a hull breach) searches from the camera itself rather than
// from behind it.
//
// The matching EXIT distance is NOT computed here: it is exactly t_exit as
// main() derives it from v_body_pos, this fragment's own interpolated
// position -- this pass rasterises the box's FAR faces only (see
// breach.vert's header comment), so whatever face survives cull(GL_FRONT) at
// this pixel already IS the ray's own box-exit point.
float breach_box_entry_t(vec3 ro, vec3 rd) {
    vec3 bmin = u_hull_field_origin;
    vec3 bmax = u_hull_field_origin + u_hull_field_cell * u_hull_field_dims;
    vec3 inv_rd = 1.0 / rd;
    vec3 t0 = (bmin - ro) * inv_rd;
    vec3 t1 = (bmax - ro) * inv_rd;
    vec3 tmin = min(t0, t1);
    float t_enter = max(max(tmin.x, tmin.y), tmin.z);
    return max(t_enter, 0.0);
}

// Search for where the view ray first crosses INTO carved material, walking
// from the box's own entry point (t_start, from breach_box_entry_t) out to
// this fragment's own exit point (t_end, == v_body_pos's distance from ro --
// see breach_box_entry_t's comment). Unlike raymarch_breach_cavity, this does
// NOT assume `ro` starts inside carved material -- that guarantee is exactly
// what the old per-carve sphere proxy gave for free, and the box proxy
// cannot: it covers the whole field, so this loop is what tells "this ray
// touches a carve" apart from "it doesn't" before handing off to
// raymarch_breach_cavity.
//
// Same step size as raymarch_breach_cavity (kHullFieldStepFrac * the
// smallest field cell -- see that function's own derivation) and the same
// kBreachMaxSteps bound, for the same reason: this loop's own reach need
// never exceed the field's box diagonal (breach_field_reach()), which bounds
// t_end - t_start by construction -- both ro+rd*t_start and ro+rd*t_end
// (== v_body_pos) lie on or inside the box.
//
// Returns false -- entry_point left at vec3(0.0), caller must discard, same
// "a hole is a hole" rule as everywhere else in this file -- when the ray
// never touches carved material between the box's own walls: the ordinary
// case for most box-proxy fragments, since one instance's box covers its
// WHOLE hull while any single carve is a small local feature within it.
bool find_breach_entry(vec3 ro, vec3 rd, float t_start, float t_end, out vec3 entry_point) {
    entry_point = vec3(0.0);
    float step_len = max(breach_min_cell() * kHullFieldStepFrac, 1e-5);
    for (int j = 0; j < kBreachMaxSteps; ++j) {
        float t = t_start + step_len * float(j);
        if (t > t_end) return false;
        vec3 p = ro + rd * t;
        if (sample_hull_field(p) > kHullFieldIsoMargin) {
            entry_point = p;
            return true;
        }
    }
    return false;   // ran the whole budget: no carved material along this ray
}

out vec4 frag_color;

// Blackbody-ish ramp keyed on heat 0..1 (white-hot -> red -> black).
// Copied from opaque.frag for consistent cooling colour across all damage VFX.
vec3 blackbody(float heat) {
    vec3 cold  = vec3(0.0);
    vec3 red   = vec3(0.59, 0.10, 0.02);
    vec3 org   = vec3(1.0,  0.45, 0.08);
    vec3 white = vec3(1.0,  0.92, 0.72);
    vec3 lo  = mix(cold, red,   smoothstep(0.0,  0.35, heat));
    vec3 mid = mix(lo,   org,   smoothstep(0.35, 0.7,  heat));
    return     mix(mid,  white, smoothstep(0.7,  1.0,  heat));
}

void main() {
    // ── Reconstruct the view ray in body frame ─────────────────────────────
    // v_body_pos is this fragment's position on the box's FAR face -- the
    // only faces this pass rasterises (glCullFace(GL_FRONT), breach.vert).
    // For a convex box that IS the ray's own box-exit point, so the whole
    // ray is determined by it plus u_camera_pos_body.
    vec3 ro = u_camera_pos_body;
    vec3 rd = v_body_pos - ro;
    float t_exit = length(rd);
    if (t_exit < 1e-6) discard;   // camera exactly on the box surface: degenerate ray, nothing to march
    rd /= t_exit;

    // ── Find where the ray first enters carved material ────────────────────
    // This instance's box covers its WHOLE hull, not just one carve -- most
    // rays through it never touch damage at all. find_breach_entry (see its
    // header comment, above) is what tells that case apart, walking from the
    // box's own analytic entry point out to this fragment's own exit point.
    float t_enter = breach_box_entry_t(ro, rd);
    vec3 entry_point;
    if (!find_breach_entry(ro, rd, t_enter, t_exit, entry_point)) discard;

    // ── March to the far wall of THAT cavity ────────────────────────────────
    vec3 hit_point, hit_normal;
    if (!raymarch_breach_cavity(entry_point, rd, hit_point, hit_normal)) discard;

    // ── Fill mask (Task 3 obligation #1) ────────────────────────────────────
    // The march alone cannot tell a real cavity wall from a carve brush's far
    // edge floating past a thin plate -- see raymarch_breach_cavity's KNOWN
    // GAP comment above. Only the fill/backing volume knows where real hull
    // material actually is. A hit with nothing behind it must not be
    // painted: "a hole is a hole", the same rule this file already applied
    // to v_body_pos before the raymarch existed -- now applied to hit_point,
    // the point actually being shaded.
    //
    // Clamp-to-edge wrap means fragments outside the fill grid would sample
    // the boundary value; the explicit range check + discard for out-of-grid
    // fragments keeps the scoop finite, same as before.
    vec3 tc = (hit_point - u_fill_origin) / (u_fill_cell * vec3(u_fill_dims));
    if (any(lessThan(tc, vec3(0.0))) || any(greaterThan(tc, vec3(1.0)))) discard;
    float fillv = texture(u_fill, tc).r;
    if (fillv < u_fill_backing) discard;

    // ── Triplanar blend ────────────────────────────────────────────────────
    // hit_normal is the field's own gradient at hit_point (raymarch_breach_
    // cavity), pointing out of the wall into the open cavity -- the same role
    // v_body_normal played for the old sphere (its outward normal).
    vec3 n = normalize(hit_normal);
    vec3 w = abs(n);
    w = max(w, vec3(1e-4));
    w /= (w.x + w.y + w.z);

    vec3 uvw = hit_point * u_tex_scale;
    vec3 cx  = texture(u_damage_tex, uvw.yz).rgb;   // project along +X
    vec3 cy  = texture(u_damage_tex, uvw.zx).rgb;   // project along +Y
    vec3 cz  = texture(u_damage_tex, uvw.xy).rgb;   // project along +Z
    vec3 tex = cx * w.x + cy * w.y + cz * w.z;

    // Neutral metallic base so the cross-section always reads as structural
    // hull interior; Damage.tga modulates it. With no texture bound (mod ship /
    // missing asset) the sample is ~0, leaving just the muted grey base —
    // graceful degradation, never a black hole to the stars. The texture now
    // DOMINATES (kBase is only a dark floor at the texture's darkest spots) so
    // the scorch detail reads clearly instead of being washed out by the base.
    const vec3 kBase = vec3(0.16, 0.17, 0.19);
    tex = kBase + tex * 1.1;

    // ── Double-sided lighting ──────────────────────────────────────────────
    // The interior wall is found via a back-culled proxy (cull-front), so
    // gl_FrontFacing is false; faceforward() corrects the normal toward the
    // viewer for shading. hit_world is hit_point transformed to world space
    // (NOT v_world_pos -- the box's own far-face world position -- which is
    // generally a different, farther point than the true interior surface).
    vec3 hit_world = (u_model * vec4(hit_point, 1.0)).xyz;
    vec3 cam_pos  = u_camera_pos_ws;
    vec3 view_dir = normalize(cam_pos - hit_world);
    // n (hit_normal) already points out of the wall into the open cavity;
    // faceforward flips it toward the camera for the lighting dot product,
    // same role v_body_normal played for the old sphere.
    vec3 nf = faceforward(n, -view_dir, n);

    // Fixed key light from camera-ish direction: interior reads as shadowed
    // structural guts rather than a bright splat.
    float ndl   = max(dot(nf, view_dir), 0.0);
    float light = 0.35 + 0.55 * ndl;

    // Mute: desaturate slightly, keep brightness moderate. Keep more of the
    // texture's own colour (0.75) so the scorch detail reads.
    float luma = dot(tex, vec3(0.299, 0.587, 0.114));
    vec3 muted  = mix(vec3(luma), tex, 0.75);
    vec3 c      = muted * light;

    // ── Molten rim emissive ──────────────────────────────────────────────────
    // heat: 1 at birth (age=0) → 0 at kRimLife. Clamped to [0,1].
    float heat = clamp(1.0 - u_breach_age / u_rim_life, 0.0, 1.0);
    if (heat > 0.0) {
        // Rim weight: proximity to the iso surface (the shallow cut edge where
        // the hole opens). Near the rim the fill is just above iso; deeper into
        // solid material the fill rises higher. So fragments close to iso (rim)
        // get rim_w ≈ 1; fragments deep in solid material get rim_w ≈ 0.
        // kRimBand: fill units above iso that still count as "rim region".
        const float kRimBand = 0.12;
        float rim_w = 1.0 - smoothstep(u_fill_iso, u_fill_iso + kRimBand, fillv);
        c += blackbody(heat) * rim_w * 3.0;  // gain: brighter molten glow (eyeball-tunable)
    }

    frag_color = vec4(c, 1.0);
}
