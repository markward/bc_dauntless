#version 410 core

// Breach interior scoop — inner wall of a carve sphere, masked by the ship's
// ORIGINAL (uncarved) fill.
//
// For each fragment:
//   1. Map v_body_pos to a texture coordinate in the original fill (GL_R8 3D
//      texture). If the fill value is below u_fill_iso (= 64/255), there is
//      no solid hull material there → discard. This makes the scoop only
//      render where real ship interior exists: it fades to nothing (genuine
//      see-through) where the sphere extends into open space or past a thin
//      hull wall.
//   2. Triplanar projection of BC's Damage.tga — muted grey interior shading
//      identical to the previous breach.frag's approach, now applied to the
//      sphere's inner wall rather than a DC mesh.
//
// Rendered with glCullFace(GL_FRONT) so only back faces (the recessed inner
// wall) are drawn; no geometry can poke out past the hull.
// Depth-test ON, depth-write ON: the scoop hides behind intact hull (depth
// written by the opaque pass) and shows only through the hole (no depth there).

in vec3 v_body_pos;
in vec3 v_body_normal;
in vec3 v_world_pos;

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
    // ── Fill mask ──────────────────────────────────────────────────────────
    // Discard where the original hull fill says "no material here" (open space
    // or past a thin hull wall). Clamp-to-edge wrap means fragments outside
    // the fill grid sample the boundary value; explicit range check + discard
    // for out-of-grid fragments keeps the scoop finite.
    vec3 tc = (v_body_pos - u_fill_origin) / (u_fill_cell * vec3(u_fill_dims));
    if (any(lessThan(tc, vec3(0.0))) || any(greaterThan(tc, vec3(1.0)))) discard;
    float fillv = texture(u_fill, tc).r;
    if (fillv < u_fill_backing) discard;

    // ── Triplanar blend ────────────────────────────────────────────────────
    vec3 n = normalize(v_body_normal);
    vec3 w = abs(n);
    w = max(w, vec3(1e-4));
    w /= (w.x + w.y + w.z);

    vec3 uvw = v_body_pos * u_tex_scale;
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
    // The inner wall is rendered back-face (cull-front), so gl_FrontFacing is
    // false; faceforward() corrects the normal toward the viewer for shading.
    vec3 cam_pos  = u_camera_pos_ws;
    vec3 view_dir = normalize(cam_pos - v_world_pos);
    // v_body_normal is the OUTWARD sphere normal; faceforward flips it inward
    // (toward camera) for the lighting dot product.
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
