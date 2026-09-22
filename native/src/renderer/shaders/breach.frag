#version 410 core

// Breach interior — the far wall of a hull cavity, found by raymarching the
// per-instance DAMAGE field starting from the REAL hull surface (raymarched-
// breach-interior Task 3, round 3; supersedes both the original per-carve
// sphere scoop AND round 1's box-proxy-plus-entry-search design).
//
// One draw per DAMAGED INSTANCE, not one per carve: breach_pass.cc draws the
// SAME hull mesh geometry the opaque pass drew (renderer::
// draw_model_positions_only), under the SAME carve stencil. A fragment
// reaching main() below is therefore, by construction, sitting exactly on
// the hull surface at a point sample_hull_field() already reads as carved
// (> margin) -- the identical condition that made opaque.frag discard it and
// the stencil pass mark it 1 in the first place. There is no search for
// where the ray enters the carve: it already starts there. For each
// fragment:
//   1. Reconstruct the view ray in body frame: ro = v_body_pos (the hull
//      surface itself), rd = the direction from the camera through it,
//      continued further into the hull.
//   2. Raymarch from ro to the cavity's far wall (raymarch_breach_cavity,
//      Task 2, UNCHANGED since round 1) -- hit_point/hit_normal.
//   3. Map hit_point to a texture coordinate in the ORIGINAL (uncarved) fill
//      (GL_R8 3D texture). If the fill value is below u_fill_backing, there
//      is no real hull material there → discard: this is what keeps a carve
//      brush's far edge (floating past a thin plate; see raymarch_breach_
//      cavity's KNOWN GAP comment) from painting as though it were a real
//      wall -- "a hole is a hole".
//   4. Triplanar projection of BC's Damage.tga onto hit_point -- muted grey
//      interior shading, unchanged from the pre-Task-3 scoop.
//
// Rendered with the SAME cull/depth state as the opaque pass draws this mesh
// with (normal front-facing, cull BACK) -- this is the real, outward-facing
// hull surface, not a back-face-culled proxy shell; no geometry can poke out
// past the hull because it IS the hull.
// Depth-test ON, depth-write ON: the proxy hides behind intact hull (depth
// written by the opaque pass, at pixels the carve did NOT touch) and shows
// only through an actual hole (no depth written there by the opaque pass,
// since it discarded that fragment).

// v_body_pos is the REAL hull mesh's own vertex position, in the ship's BODY
// frame -- breach.vert composes the mesh's node chain onto the node-local
// vertex and strips the instance world matrix back off, so this is the same
// frame opaque.frag's p_body, the baked damage field, the fill volume,
// u_camera_pos_body and u_breach_center all live in (see breach.vert's own
// derivation). No box, no per-vertex normal computed here: hit_normal (below)
// comes from the field's own gradient, not from mesh geometry.
in vec3 v_body_pos;
in vec3 v_body_normal;   // interior shell only (see u_interior_shell)

// ── Interior shell ────────────────────────────────────────────────────────
// 0 = the scoop (everything this file did before): a FRONT face on the struck
// side, raymarching inward for the cavity wall.
// 1 = the interior shell: the hull's own BACK faces, drawn front-culled under
// the same carve stencil. The fragment IS the interior wall, so there is
// nothing to march to -- hit_point is v_body_pos and the normal is the mesh's
// own (flipped inward).
//
// WHY THIS EXISTS. A BC hull is a single-sided shell drawn cull BACK, and BC's
// authored fill volumes are only a handful of nodes thick (Galaxy 9, Sovereign
// 5, Galor 3 -- docs/engine/damagetool-and-hull-damage-gaps.md). So a carve
// routinely marches out of the fill, the backing gate below discards ("a hole
// is a hole"), the far plating's inside face is culled, and the pixel resolves
// to the SKYBOX: a hole you see space through from the struck side while the
// far side shows intact hull. The shell draws that far plating so a hole shows
// the ship's interior instead of the stars.
//
// ONE shader, not two, and deliberately so: the shell and the scoop meet at
// the rim of every breach, so any divergence in their material or lighting is
// a visible seam. Sharing main()'s entire shading tail makes them identical by
// construction rather than by keeping two files in step -- the failure mode
// this file already carries drift-guard markers for.
uniform int u_interior_shell;

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
uniform float     u_tex_scale;     // body-units -> texture-period scale

// u_camera_pos_body: camera position in THIS instance's body frame,
// precomputed CPU-side as inverse(instance_world) * cam_ws (one matrix inverse
// per draw, not per fragment) -- the ray origin every fragment marches from,
// and also the eye point the interior wall is shaded against.
//
// Everything this stage reads about GEOMETRY -- the damage field, the fill
// volume, hit_point, the field gradient, u_breach_center -- is body frame, and
// stays that way: a world-space vector has nothing legal to combine with any
// of it. The ONE exception is light, which genuinely lives in world space and
// arrives through u_ship_world below; see that uniform's comment for the
// cross-frame bug rounds 1-3 shipped by being loose about this. The vertex
// stage still needs u_ship_world_inv (see breach.vert) to get its NODE-LOCAL
// attribute into this frame in the first place.
uniform vec3  u_camera_pos_body;

// ── Scene lighting ────────────────────────────────────────────────────────
// This stage used to hold NO world-space uniform at all, and the comment above
// u_camera_pos_body still explains why that was right for everything it reads:
// the damage field, the fill volume, hit_point and the field gradient are all
// body frame.
//
// Light is the one thing that genuinely lives in world space. Before these,
// the interior was lit by a key light glued to the camera
// ("0.35 + 0.55 * dot(nf, view_dir)"), so a breach could never face away from
// its own light and never sat in shadow -- it was brightest exactly where you
// looked at it, while the hull around it was sun-lit and shadow-mapped. That
// mismatch is what made damage read as a raw crust pasted onto a lit ship.
//
// The trap this must not fall back into: rounds 1-3 carried a ship world
// matrix AND a world-space camera position, then dotted a BODY-frame normal
// against the world-space camera -- a dot product across two frames, correct
// only while the instance carried no rotation. The rule is that a vector is
// converted EXPLICITLY, at the point of use, and the dot product happens
// between two vectors that are provably in the same frame. u_ship_world below
// is the only conversion, and main() uses it for exactly that.
uniform mat4 u_ship_world;        // instance body -> world (no node chain)

const int MAX_DIR_LIGHTS = 4;
uniform vec3 u_ambient_light;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // colour x dimmer

// Directional ambient -- the SAME pair opaque.frag reads, and it has to be the
// same here or the interior's ambient and the surrounding hull's are two
// different quantities. u_ambient_gradient == 0 collapses the term to
// u_ambient_light exactly, byte-identical, which is the stock path.
// (u_ambient_light itself arrives ALREADY multiplied by the frame's
// ambient_scale, exactly as set_ambient_uniforms does for the opaque pass:
// under filmic that is x0.8, and an interior lit 1.25x brighter than the hull
// around it is the same class of mismatch as the camera-glued light was.)
uniform vec3  u_ambient_dir_ws;
uniform float u_ambient_gradient;

// Molten-rim emissive (hull-breach-2c).
// u_breach_age: age of the matching breach event (large value → cold when no match).
// u_rim_life:   kRimLife constant; rim cools to 0 by this age.
uniform float u_breach_age;
uniform float u_rim_life;

// u_breach_center/u_breach_radius: that SAME event's own body-frame centre
// and visible radius (scenegraph::BreachEvent -- BreachPass::render() reads
// both off the freshest active event, same source as u_breach_age). Task 3
// obligation #2: with one draw per INSTANCE (not per carve any more),
// u_breach_age is a single scalar shared by every fragment on the whole
// hull -- a ship can carry several old, cooled breaches alongside one fresh
// one, and age alone cannot tell them apart spatially. Without a position,
// heat (below) would be uniform across the instance and the fresh event's
// glow would re-ignite every OTHER hole on the same hull, not just its own.
// main() additionally gates heat by distance from u_breach_center (scaled
// by u_breach_radius), so only the fragment's OWN nearby hole lights up.
uniform vec3  u_breach_center;
uniform float u_breach_radius;

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

// Cavity-wall raymarch (raymarched-breach-interior Task 2), called DIRECTLY
// from main() below with ro = v_body_pos -- the real hull mesh surface point
// (round 3: no entry search, see the retirement note above this function's
// call site). Originally written and tested in isolation before Task 3
// wired it in -- see native/tests/renderer/breach_raymarch_test.cc, which
// splices this file's own production text onto a test-only main() and still
// exercises this function directly, independent of main()'s own plumbing.
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
// draw_hull_proxy() call for an instance that InstanceFieldCache::get()
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

// Round 1 of this task built a box proxy here (breach.vert placed a unit
// cube at the field's own extent) plus an entry search, find_breach_entry,
// to find where a ray first crossed into carved material before handing off
// to raymarch_breach_cavity below. Round 3 retired BOTH: breach_pass.cc now
// draws the REAL hull mesh under the carve stencil (renderer::
// draw_model_positions_only), so a fragment reaching main() already sits
// exactly on the hull surface at a carved point -- there is nothing left to
// search for. This also retired an entry-search stride that could not
// correctly bound itself either way: sized to the field's cell (the FIRST
// version) it could not reach across a hull-sized box; sized to the
// smallest carve's diameter (the review-round-2 fix) it could step over a
// realistic carve's own much narrower along-normal extent (a carve's depth
// is kCarveDepthFactor=0.45 of its radius, not its full diameter -- see
// this task's report for the measured miss rates). Removing the search
// removes both failure modes at once, rather than trading one for the
// other.


// === HULL_CUT_DECISION BEGIN === KEEP IN SYNC with breach.frag's copy between its own matching markers -- enforced by native/tests/renderer/hull_cut_decision_sync_test.cc
// ── Hull-breach hole: pure damage-sphere clip ─────────────────────────────
// Discard hull fragments inside any active carve sphere. The breach pass
// renders the exposed interior (scoop) within the same spheres, so hole and
// interior align by construction. u_carve_count == 0 (or disabled) = stock path.
//
// u_carve_enabled == 0 is the stock path (zero per-fragment cost).
uniform int  u_carve_enabled;

const int MAX_CARVES = 24;
uniform int  u_carve_count;                    // 0 = no clip
uniform vec4 u_carve_spheres[MAX_CARVES];      // xyz=center_body, w=radius
uniform vec3 u_carve_normals[MAX_CARVES];      // body-frame outward hit normal

// ── Skeletal framework lattice (Damage.tga alpha stencil) ────────────────────
// Projects Damage.tga's alpha channel onto the hull in an annular band around
// each breach. High alpha = structural strut (kept); low alpha = gap (discarded).
// u_frame_enabled == 0 (no GL context / no texture / no carves) = stock path.
uniform sampler2D u_damage_decal;   // Damage.tga: RGB=scar colour, A=lattice stencil
uniform int       u_frame_enabled;  // 0 = framework skipped (stock path)

// Framework lattice constants (eyeball-tunable). The stencil applies INSIDE the
// breach: hull struts remain where Damage.tga's alpha is opaque, gaps reveal the
// interior behind. The surrounding hull is never touched.
const float kFrameUvScale = 0.6;  // breach radius → texture span (lower = bigger lattice cells)
const float kStrutAlpha   = 0.5;  // keep a hull strut where stencil alpha exceeds this.
                                  // A WEAK lever: Damage.tga's alpha is close to
                                  // binary, so 42.1% of the stencil is opaque at
                                  // 0.5 and still 38.4% at 0.9. Raising it barely
                                  // opens the breach; kOpenCore is the real knob.
const float kOpenCore     = 0.75; // inner fraction of the breach RADIUS always fully
                                  // open (no struts). Area goes as the square, so
                                  // this is 56% of the breach open by area, with the
                                  // struts confined to a torn outer rim.
                                  //
                                  // Was 0.35 -- only 12% of the area, leaving ~37% of
                                  // every breach bridged by a lattice spread across
                                  // the whole opening. That reads as a crust on the
                                  // hull rather than a hole through it: you perceive
                                  // the grille, not the gap.

// breach shape — KEEP IN SYNC with breach.vert.
// OBLATE spheroid centred on the hull surface: FULL lateral radius (original
// hole width), compressed to kDepthFactor along the normal (shallow). Noise
// perturbs the lateral radius by azimuth (jagged rim).
const float kDepthFactor = 0.45;  // depth = kDepthFactor * radius (shallow)
const float kShapeAmp    = 0.25;
const float kShapeFreq   = 4.0;
const float kPhase       = 0.13;

// Field-brush dilation, in CELLS. GLSL const has no linkage across the
// C++/GLSL boundary, so these are this shader's own copies of
// voxel::kCarveDepthFloorCells and voxel::kCarveFieldOffsetCells --
// NOT independently chosen values. HullFieldClip.GlslBrushConstantsMatchCxx
// fails if they drift. See field_brush.h for the derivation and the measured
// coverage they buy.
const float kFieldDepthFloor = 1.25;
const float kFieldSdfOffset  = 1.25;

// Body-space erosion of the FIELD's hole edge, so a hole cut beyond the
// 24-carve ring gets a broken rim instead of the brush's smooth ellipsoid.
// Tracked carves do not use this -- they have a real per-carve azimuth and
// their own noise (kShapeAmp above); beyond the ring there is no per-carve
// frame to build an azimuth from, which is the whole point of being out
// there, so the perturbation has to come from a body-space field instead.
//
// ONE-SIDED BY CONSTRUCTION: vnoise3 returns [0,1] and the term is ADDED to
// the iso margin, so it can only ever RAISE the threshold and SHRINK the
// hole. A signed version (the *2-1 remap the sphere block's own rim noise
// uses) would grow the hole past the region field_brush.cc guarantees
// damage in, putting un-backed hull at the rim -- the see-through defect
// this plan removes. HullFieldClip.FieldRimNoiseOnlyShrinksTheHole guards
// the source text; FieldRimNoiseNeverCutsBelowThePlainMargin guards the
// behaviour. breach.frag gets this term too, and must: it runs THIS function,
// verbatim, so that its interior shell keeps exactly what the hull did not
// cut. It used to be deliberately excluded here, on the reasoning that a
// LOWER threshold in breach.frag kept hole (subset of) interior -- true of the
// scoop's raymarch ENTRY, but backwards for the shell, which DISCARDS above
// the threshold and so threw away more hull than the hull itself cut. That
// asymmetry was the one-way hole.
//
// 0.06 in sample_hull_field's return units is about half a cell: scale is
// 4*cell/127 model units per step, so 0.5*cell is 15.875 steps = 0.0623
// after the /255 normalisation. Because scale is proportional to cell, this
// is the same half cell on every ship without needing a uniform.
const float kFieldRimNoise = 0.06;
const float kFieldRimFreq  = 0.35;   // cycles per model unit

float vh3(vec3 p){ return fract(sin(dot(p, vec3(127.1,311.7,74.7))) * 43758.5453123); }
float vnoise3(vec3 p){
    vec3 i = floor(p), f = fract(p);
    vec3 u = f*f*(3.0-2.0*f);
    float n000=vh3(i), n100=vh3(i+vec3(1,0,0)), n010=vh3(i+vec3(0,1,0)), n110=vh3(i+vec3(1,1,0));
    float n001=vh3(i+vec3(0,0,1)), n101=vh3(i+vec3(1,0,1)), n011=vh3(i+vec3(0,1,1)), n111=vh3(i+vec3(1,1,1));
    float nx00=mix(n000,n100,u.x), nx10=mix(n010,n110,u.x), nx01=mix(n001,n101,u.x), nx11=mix(n011,n111,u.x);
    return mix(mix(nx00,nx10,u.y), mix(nx01,nx11,u.y), u.z);
}

// Was the hull cut away at this body-frame point?
//
// THE one place that answers it. It used to live inline in this file's main(),
// which meant anything else needing the same answer had to approximate it --
// and the breach pass's interior shell did exactly that, testing the RAW field
// where this tests the field only outside a tracked carve's dilated region and
// at a threshold raised by rim noise. The shell therefore threw away plating
// the hull itself keeps, and you saw stars through a hole whose far side
// showed intact hull: a ONE-WAY hole, live-reported on the Galaxy's forward
// saucer. "The cut and the interior are two different shapes" is the same root
// cause as the original see-through bug; this function exists so there is only
// one shape.
//
// Returns true = cut away here. The CALLER decides what to do with that.
bool hull_cut_at(vec3 p_body) {
    bool field_suppressed = false;
    // Loop-invariant: the field lattice is per-instance, not per-carve. Hoisted
    // out of the carve loop below, where it was recomputed for every one of up
    // to 24 active carves on every fragment.
    float cellmin = min(u_hull_field_cell.x,
                        min(u_hull_field_cell.y, u_hull_field_cell.z));
    if (u_carve_enabled != 0 && u_carve_count > 0) {
        for (int i = 0; i < u_carve_count; i++) {
            vec3 c  = u_carve_spheres[i].xyz;
            float r = u_carve_spheres[i].w;
            vec3 n  = u_carve_normals[i];
            // Oblate breach centred on the hull surface: full lateral radius,
            // shallow along the normal.
            vec3 v       = p_body - c;
            float along  = dot(v, n);
            vec3 lateral = v - along * n;
            float ld     = length(lateral);
            // Region the FIELD BRUSH dilated this carve to (field_brush.cc).
            // The field is deliberately generous -- a carve is rounded up to
            // what the lattice can hold -- so suppressing the field only
            // inside the nominal oblate would let it cut a smooth ring
            // around every tracked hole, erasing the noise rim and the
            // struts. This bound is a strict superset of the `e < 1.0` hole
            // test below (its lateral extent is r*(1+kShapeAmp) >= r_eff),
            // which is why no union with the unperturbed test is needed.
            // Computed OUTSIDE the guard below on purpose: the dilated
            // region reaches past that guard's box whenever the cell is
            // coarse relative to the carve.
            // `cellmin` is loop-INVARIANT -- hoisted above the loop, where it
            // is computed once per fragment instead of once per active carve.
            //
            // Compared SQUARED: `unit < dil` with both sides non-negative is
            // exactly `unit^2 < dil^2`, so this drops a sqrt from every
            // fragment-carve pair (up to 24 per fragment) with no change of
            // result whatsoever.
            float lat = r * (1.0 + kShapeAmp);
            float dep = max(kDepthFactor * r, kFieldDepthFloor * cellmin);
            float dil = 1.0 + (kFieldSdfOffset * cellmin) / min(lat, dep);
            float unit2 = (ld * ld) / (lat * lat) + (along * along) / (dep * dep);
            if (unit2 < dil * dil) field_suppressed = true;
            if (ld < r * (1.0 + kShapeAmp) && abs(along) < kDepthFactor * r * (1.0 + kShapeAmp)) {
                // Azimuthal noise on the lateral radius (jagged rim); same
                // azimuth term the scoop uses, so the hole edge aligns.
                vec3 az = ld > 1e-4 ? lateral / ld : vec3(1.0, 0.0, 0.0);
                float r_eff = r * (1.0 + kShapeAmp * (vnoise3(az * kShapeFreq + c * kPhase) * 2.0 - 1.0));
                float dz = along / (kDepthFactor * r);
                float e  = (ld * ld) / (r_eff * r_eff) + dz * dz;   // <1 inside the oblate
                // No suppression bookkeeping here: `field_suppressed` was set
                // above from the dilated bound, which contains BOTH this
                // perturbed test and the unperturbed oblate the brush carves.
                // The band r_eff < ld < r (where the noise dips the rim
                // inward) is inside what the field cut but outside `e < 1.0`;
                // before the dilated bound existed that band had to be unioned
                // in by hand, or the field cut a smooth-edged ring there with
                // no scoop behind it (breach.vert builds the scoop from r_eff
                // too) -- a see-through gap around roughly half of every
                // tracked breach's rim.
                if (e < 1.0) {
                    // ── Skeletal framework lattice (INSIDE the breach) ──────────
                    // Don't cut a clean hole: leave torn HULL STRUTS bridging the
                    // breach where Damage.tga's stencil is opaque; the gaps between
                    // struts reveal the recessed interior behind. Struts cluster
                    // toward the rim (open core) so it still reads as a hole. The
                    // surrounding hull (outside the oblate) is left untouched.
                    bool cut = true;
                    if (u_frame_enabled != 0) {
                        // tangent-plane UV around the breach axis (basis from n)
                        vec3 up = abs(n.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
                        vec3 t  = normalize(cross(up, n));
                        vec3 b  = cross(n, t);
                        // Per-carve stencil ORIENTATION. Without this, `t`/`b`
                        // depend only on the breach normal, so every breach on
                        // a similarly-facing surface -- the whole top of a
                        // saucer -- gets Damage.tga stamped with the same basis
                        // AND the same centred crop. Adjacent hits then read as
                        // one stamp repeated rather than as separate damage.
                        //
                        // Seeded from the carve centre: stable across frames
                        // (so the lattice does not crawl), different per carve,
                        // and identical in the u_carve_invert marking pass
                        // because that derives it from the same `c`. If the two
                        // ever disagreed the stencil would stop matching the
                        // hole it is cut from.
                        float ang = vh3(c * 0.37) * 6.28318530718;
                        float cs  = cos(ang), sn = sin(ang);
                        vec2  luv = vec2(dot(lateral, t), dot(lateral, b));
                        luv = vec2(cs * luv.x - sn * luv.y,
                                   sn * luv.x + cs * luv.y);
                        vec2 uv = luv / (r * kFrameUvScale) * 0.5 + 0.5;
                        float a    = texture(u_damage_decal, uv).a;
                        float frac = sqrt(e);                   // 0 center .. 1 rim
                        // Keep a hull strut where the stencil is opaque (the lattice)
                        // AND we're outside the open core; everything else is cut.
                        if (a > kStrutAlpha && frac > kOpenCore) cut = false;
                    }
                    // The CALLER decides what a cut means (the opaque pass
                    // discards, or stamps the stencil in its marking draw; the
                    // breach pass's interior shell keeps only what was NOT
                    // cut). This function only answers the question.
                    if (cut) return true;
                }
            }
        }
    }

    // ── Hull-field clip (hull-volume-field-transport, Task 5) ──────────────
    // Evaluated AFTER the sphere block, and only where `!field_suppressed`:
    // a TRACKED carve's shape, jagged noise rim, and framework-lattice strut
    // decision above are computed from real geometry (the sphere, its
    // normal, Damage.tga's stencil); the field has none of that -- it only
    // knows "carved or not" at a point. If the field discarded unconditionally
    // it would OVERRIDE the sphere block's own decision inside every tracked
    // oblate: every strut the lattice just decided to keep would still be cut
    // (field_carve_oblate carved that exact region unconditionally), and the
    // jagged noise rim would be replaced by the field's smooth, un-perturbed
    // edge.
    //
    // The gate is the region the brush DILATED a tracked carve to, not the
    // nominal oblate: field_brush.cc rounds every carve up to the smallest
    // shape the lattice can hold (kCarveDepthFloorCells,
    // kCarveFieldOffsetCells), so a ring outside the nominal oblate is still
    // damaged in the field. Suppressing only inside the nominal oblate would
    // let the field cut that ring with a smooth edge, visibly enlarging every
    // tracked hole and erasing the rim.
    //
    // Gating on `!field_suppressed` means the field can only ever ADD a
    // discard where the sphere block does not already govern -- i.e. damage
    // beyond the 24-sphere ceiling, which is the plan's actual win. Inside a
    // tracked carve's dilated region, the sphere block's decision (struts,
    // noise rim, hole shape) is authoritative and untouched.
    if (u_hull_field_enabled != 0 && !field_suppressed) {
        // kHullFieldIsoMargin, not 0.0: see its derivation above this
        // function. An UNDAMAGED fragment here reads -127 ("no damage"),
        // nowhere near zero, so the margin is not guarding it -- it guards
        // fragments right at a carve's own rim, where field_carve_oblate's
        // brush actually crosses zero and quantisation rounding could
        // otherwise decide the sign in a dithered speckle pattern instead
        // of real geometry.
        //
        // The threshold is raised (never lowered) by body-space noise, so
        // the field's own hole edge breaks up instead of reading as the
        // brush's smooth ellipsoid. See kFieldRimNoise for why the term is
        // strictly one-sided.
        // SHORT-CIRCUIT, and it is load-bearing for frame rate, not tidiness.
        // vnoise3 is EIGHT sin-based hashes, and this block runs on every
        // fragment of every damaged hull that no tracked carve suppresses --
        // i.e. essentially the whole visible surface of every ship that has
        // ever been hit. Evaluating the noise there unconditionally cost
        // eight transcendentals per fragment across the entire fleet.
        //
        // kFieldRimNoise * vnoise3(...) is >= 0 by construction (vnoise3
        // returns [0,1] and the term is added, never subtracted -- see the
        // constant's comment and FieldRimNoiseNeverCutsBelowThePlainMargin).
        // So `fv > kHullFieldIsoMargin` is a NECESSARY condition for a cut,
        // and testing it first is EXACTLY equivalent, not an approximation:
        // any fragment it rejects would have been rejected by the full test
        // too, whatever the noise happened to be. Undamaged fragments -- the
        // overwhelming majority -- now pay two texture fetches instead of
        // two fetches plus eight sins.
        float fv = sample_hull_field(p_body);
        bool field_cut = false;
        if (fv > kHullFieldIsoMargin) {
            field_cut = fv
                      > kHullFieldIsoMargin + kFieldRimNoise * vnoise3(p_body * kFieldRimFreq);
        }
        if (field_cut) return true;
    }
    return false;
}
// === HULL_CUT_DECISION END ===

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
    // v_body_pos is the REAL hull mesh surface point this fragment sits on
    // -- already inside carved material by construction (see this file's
    // header comment): the stencil that gates this whole pass is stamped
    // from the SAME sample_hull_field(surface point) > margin condition
    // that makes THIS fragment reach main() at all. ro is simply that
    // point; rd continues the camera's own view ray further into the hull
    // (not the surface normal -- a hole viewed at a glancing angle should
    // still look like a hole, following the actual line of sight).
    vec3 ro = v_body_pos;
    vec3 rd = v_body_pos - u_camera_pos_body;
    float rd_len = length(rd);
    if (rd_len < 1e-6) discard;   // camera exactly on the hull surface: degenerate ray, nothing to march
    rd /= rd_len;

    vec3 hit_point, hit_normal;
    // Fill value AT the shaded point. The scoop reads it from the original
    // uncarved fill volume (below) and reuses it for the molten-rim band; the
    // shell has no march and no backing gate, so it takes the solid-material
    // value, putting it deep in the "not rim" end of the band. A hole's molten
    // rim belongs to the cut edge on the struck sheet, not to the floor you
    // see through it.
    float fillv = 1.0;
    if (u_interior_shell != 0) {
        // ── Interior shell ─────────────────────────────────────────────────
        // This fragment is a BACK face of the hull -- the inside of the far
        // plating, seen through a hole in the near plating. It IS the wall, so
        // there is no march and no backing gate (the gate exists to reject a
        // hit floating in open space; a real mesh vertex cannot be).
        //
        // The one thing it MUST reject is its own sheet. In a closed mesh the
        // struck sheet's back face is CO-PLANAR with the front face the carve
        // just discarded, so drawing it would plug every breach with the very
        // plating that was cut away -- a breach reading as a crust rather than
        // a hole (the failure carve_cavity_test.cc's header describes).
        //
        // It asks the HULL'S OWN decision, not a lookalike. An earlier version
        // tested the raw field here, which is NOT what opaque.frag cuts on:
        // that file suppresses the field inside a tracked carve's dilated
        // region and raises its threshold with rim noise. Where the brush
        // reached plating the oblate did not cut -- routine, because the
        // dilation is driven by the FIELD CELL, not the carve radius -- the
        // shell threw away plating the hull keeps, and the result was stars
        // from one side and intact hull from the other. A ONE-WAY hole.
        //
        // Consequence, stated rather than left implicit: where a carve cuts
        // through BOTH sheets, both are rejected and you see space -- from
        // either side, symmetrically. That is a genuinely perforated hull, and
        // a two-way hole is the correct picture of one.
        if (hull_cut_at(v_body_pos)) discard;

        hit_point  = v_body_pos;
        // Face the normal back along the view ray. The mesh normal points out
        // of the hull, and this is the surface's INSIDE, so the inward-facing
        // direction is the one the shading tail wants -- the same role the
        // field gradient plays for the scoop (out of the wall, into the open
        // cavity).
        hit_normal = normalize(v_body_normal);
        if (dot(hit_normal, rd) > 0.0) hit_normal = -hit_normal;
    } else {

    // ── March to the far wall of the cavity ─────────────────────────────────
    // No entry search: ro already sits inside carved material (see above),
    // exactly the precondition raymarch_breach_cavity's own header documents.
    if (!raymarch_breach_cavity(ro, rd, hit_point, hit_normal)) discard;

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
    fillv = texture(u_fill, tc).r;
    if (fillv < u_fill_backing) discard;

    }   // end scoop branch (u_interior_shell == 0)

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
    // graceful degradation, never a black hole to the stars. The texture
    // DOMINATES (kBase is only a dark floor at the texture's darkest spots) so
    // the scorch detail reads clearly instead of being washed out by the base.
    //
    // A charring pass (darker base, sub-unity gain, a soot cloud) plus a
    // cavity-depth occlusion multiply were tried here and REMOVED after a live
    // look: stacked on top of scene ambient they made every breach read as a
    // black hole. The arithmetic, for whoever is tempted to retry it: the fake
    // light this shader used to carry had a hard 0.35 FLOOR, while the scene's
    // own ambient is DEFAULT_AMBIENT 0.10 (x0.8 under filmic = 0.08). Swapping
    // the floor for real ambient already dropped an unlit interior to ~23% of
    // its old brightness; a 0.59x darker base and a 0.30 occlusion floor on top
    // of that reached ~3.5%. Darkening has no headroom here until the interior
    // has a light that reaches it -- tune the LIGHT, not the material.
    const vec3 kBase = vec3(0.16, 0.17, 0.19);
    tex = kBase + tex * 1.1;

    // ── Double-sided lighting ──────────────────────────────────────────────
    // The wall this shades is a point INSIDE the hull found by the raymarch,
    // while the fragment itself came from the outward-facing hull surface
    // (this pass draws the real mesh with the opaque pass's own winding, cull
    // BACK, so gl_FrontFacing is true here). The field gradient at hit_point
    // therefore has no fixed relationship to the fragment's own facing, and
    // faceforward() turns it toward the viewer for shading.
    //
    // EVERYTHING here is BODY space. `n` is the damage field's own gradient at
    // hit_point, so it is a body-frame direction and there is no world-space
    // vector it can legally be dotted with. Earlier rounds transformed
    // hit_point to world space and used u_camera_pos_ws, which made `ndl`
    // below a dot product across two frames: correct only while the instance
    // world matrix carried no rotation, i.e. never for a ship that is moving
    // or turning. That did not blank anything (light stayed in [0.35, 0.90]),
    // it just shaded the interior by the ship's heading -- flat at some
    // attitudes, swimming as the hull turned.
    //
    // u_camera_pos_body is already the camera in this instance's body frame
    // (breach_pass.cc: inverse(world_xf) * cam_ws), and it is already the
    // other endpoint of the ray this fragment marched, so reusing it here
    // costs nothing, needs no world round-trip and no world-space uniform,
    // and keeps the shading ray and the march ray the same ray by
    // construction.
    vec3 view_dir = normalize(u_camera_pos_body - hit_point);
    // n (hit_normal) already points out of the wall into the open cavity;
    // faceforward flips it toward the camera, so the wall you are looking at
    // is the face that gets lit.
    vec3 nf = faceforward(n, -view_dir, n);

    // ── Scene lighting ─────────────────────────────────────────────────────
    // Body -> world, explicitly, right here, so the dot products below are
    // between two vectors provably in the SAME frame (see u_ship_world's own
    // comment for the cross-frame bug this shape exists to prevent). BC hulls
    // carry uniform scale only, so mat3 is the correct normal transform and
    // normalize() absorbs the scale factor.
    vec3 n_ws = normalize(mat3(u_ship_world) * nf);

    // Ambient, by opaque.frag's own formula (see u_ambient_dir_ws above). The
    // clamp is not decorative: a degenerate normal makes the dot NaN, and
    // clamp(NaN,-1,1) resolves to -1 on this driver rather than propagating --
    // the same guard opaque.frag carries, for the same measured reason.
    vec3 light = u_ambient_light;
    if (u_ambient_gradient > 0.0) {
        float amb_d = clamp(dot(n_ws, u_ambient_dir_ws), -1.0, 1.0);
        light = u_ambient_light * (1.0 + u_ambient_gradient * amb_d);
    }
    // Clamped to the array's own size, not trusted from the uniform: an
    // unbounded (or over-long) loop in a fragment shader is a hang and an
    // out-of-bounds read, not a slow frame. Same reason kBreachMaxSteps caps
    // the raymarch with a named compile-time constant.
    int dir_count = min(u_dir_light_count, MAX_DIR_LIGHTS);
    for (int i = 0; i < dir_count; ++i) {
        vec3 L = normalize(u_dir_light_dir_ws[i]);
        light += max(dot(n_ws, L), 0.0) * u_dir_light_color[i];
    }

    // Mute: desaturate slightly, keep brightness moderate. Keep more of the
    // texture's own colour (0.75) so the scorch detail reads.
    float luma = dot(tex, vec3(0.299, 0.587, 0.114));
    vec3 muted  = mix(vec3(luma), tex, 0.75);
    vec3 c      = muted * light;

    // ── Molten rim emissive ──────────────────────────────────────────────────
    // heat: 1 at birth (age=0) → 0 at kRimLife, ADDITIONALLY gated by
    // distance from the freshest event's own centre (u_breach_center's own
    // comment above -- Task 3 obligation #2): u_breach_age is one scalar
    // shared by every fragment on the whole instance now that there is one
    // draw per instance, not per carve, so without a positional gate a
    // fresh hit anywhere on the hull would re-ignite every OTHER, already-
    // cooled hole on the same instance too.
    float heat = clamp(1.0 - u_breach_age / u_rim_life, 0.0, 1.0);
    if (heat > 0.0) {
        // kEventFalloffMul: multiple of the event's own carve radius before
        // the glow fully fades. 3x gives a soft halo a bit larger than the
        // hole itself without reaching a neighbouring breach elsewhere on
        // the hull. max(u_breach_radius, 1e-3) avoids a degenerate
        // zero-radius smoothstep (edge==edge*mul==0) -- unreachable when
        // heat>0 already implies a real event was bound (radius>0), but
        // cheap to guard defensively anyway.
        const float kEventFalloffMul = 3.0;
        float event_dist   = length(hit_point - u_breach_center);
        float event_radius = max(u_breach_radius, 1e-3);
        float event_w = 1.0 - smoothstep(event_radius, event_radius * kEventFalloffMul, event_dist);
        heat *= event_w;
    }
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
