#version 410 core

in vec3 v_normal_ws;
in vec2 v_uv;
in vec3 v_position_ws;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;

uniform sampler2D u_glow_map;
uniform vec3 u_emissive_color;
uniform float u_emissive_scale;   // 1 = normal, 0 = destroyed (dark hull)

uniform sampler2D u_specular_map;
uniform vec3 u_specular_color;
uniform float u_specular_power;
uniform int u_specular_enabled;

// ── Tangent-space normal map (unit 4) ────────────────────────────────────
// BC NIFs carry no tangents and none are added, so the frame is rebuilt
// per-pixel from screen-space derivatives (Mikkelsen). u_normal_enabled == 0
// is the stock path: n_shade == the geometric normal, byte-identical output.
uniform sampler2D u_normal_map;
uniform int   u_normal_enabled;   // 1 only when the material has a Bump texture
uniform float u_normal_strength;  // 0 = flat, 1 = as authored, >1 exaggerates
uniform int   u_normal_flip_g;    // 1 flips green for DirectX-convention maps

// Fresnel rim light. u_rim_strength == 0.0 disables the term (set per
// draw by frame.cc: the global dauntless_rim toggle AND per-instance
// rim_eligible AND material specular). Tinted by the accumulated
// directional light so the rim only shows where a star hits.
//
// RIM_POWER controls falloff width (lower = wider band); RIM_GAIN scales
// the peak. Tuned against the Galaxy, whose materials author specular≈0.9
// and glossiness≈0, giving a near-constant rim_strength≈0.225 — so the
// gain, not the material term, governs how visible the rim reads.
uniform float u_rim_strength;
const float RIM_POWER = 36.0;  // sharp, edge-only falloff (higher = thinner)
const float RIM_GAIN  = 12.75; // peak edge brightness (20.8 -> 17.0 -> -25% 2026-08-16)

uniform vec3 u_ambient_light;
// Directional ambient. u_ambient_gradient == 0 is the stock path: the term
// collapses to u_ambient_light exactly. The axis is the luminance-weighted
// sum of every directional (computed host-side), NOT light 0.
uniform vec3  u_ambient_dir_ws;
uniform float u_ambient_gradient;
uniform vec3 u_camera_pos_ws;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

// ── Dynamic lights (torpedo glow; future hardpoint/beam lights) ────────
// A point light is a degenerate segment (a.xyz == b.xyz). count == 0
// disables the loop entirely (stock path, byte-identical output).
// Attenuation MUST match renderer::dynamic_light_attenuation bit-for-bit:
// use ratio*ratio*ratio*ratio, NOT pow(ratio, 4.0) (GPU pow is not
// correctly rounded; the CPU side guarantees exactly 0 at d == radius).
const int MAX_DYN_LIGHTS = 4;
uniform int  u_dyn_light_count;
uniform vec4 u_dyn_light_a[MAX_DYN_LIGHTS];      // pos_a.xyz, radius
uniform vec4 u_dyn_light_b[MAX_DYN_LIGHTS];      // pos_b.xyz, (w unused)
uniform vec3 u_dyn_light_color[MAX_DYN_LIGHTS];  // color * intensity
uniform vec4 u_dyn_light_dir[MAX_DYN_LIGHTS];    // dir.xyz, spot_tan_x (<0 = not a cone)
uniform vec4 u_dyn_light_up[MAX_DYN_LIGHTS];     // up.xyz,  spot_tan_y

// ── Sun shadow map (PCF) ─────────────────────────────────────────────────
// Applied ONLY to directional light index 0 (the sun). u_shadows_enabled == 0
// is the stock path: sun_shadow_factor() returns 1.0, so the lighting math is
// byte-identical to the pre-shadow renderer. Bound from the active-shadow state
// in frame.cc::draw_model (Task 5/6).
uniform int             u_shadows_enabled;   // 0/1
uniform mat4            u_light_view_proj;
uniform sampler2DShadow u_shadow_map;        // texture unit 5
uniform float           u_shadow_texel;      // world units/texel (normal-offset bias)

float sun_shadow_factor(vec3 world_pos, vec3 world_normal) {
    if (u_shadows_enabled == 0) return 1.0;
    // Normal-offset bias: push the sample point along the surface normal to
    // suppress self-shadow acne. Task 7 tunes the 1.5 multiplier.
    vec3 p = world_pos + world_normal * (u_shadow_texel * 1.5);
    vec4 lc = u_light_view_proj * vec4(p, 1.0);
    vec3 ndc = lc.xyz / lc.w;
    // ndc.z is glm [0,1] (GLM_FORCE_DEPTH_ZERO_TO_ONE); *0.5+0.5 reproduces GL's
    // window-depth transform applied to the stored pre-pass depth, so store and
    // sample agree. GL clip volume is still [-1,1] (no glClipControl).
    vec3 uvz = ndc * 0.5 + 0.5;            // NDC [-1,1] -> [0,1]
    if (uvz.z > 1.0) return 1.0;           // beyond far plane = lit
    float sum = 0.0;
    vec2 texel = 1.0 / vec2(textureSize(u_shadow_map, 0));
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x) {
            vec3 c = vec3(uvz.xy + vec2(x, y) * texel, uvz.z);
            sum += texture(u_shadow_map, c);   // hardware PCF compare
        }
    return sum / 9.0;
}

// ── Persistent damage decals (Phase 2) ──────────────────────────────────
const int MAX_DECALS = 24;
uniform int   u_decal_count;                 // 0 disables the loop entirely
uniform vec4  u_decal_a[MAX_DECALS];         // point_body.xyz, intensity
uniform vec4  u_decal_b[MAX_DECALS];         // normal_body.xyz, radius (model units)
uniform vec4  u_decal_c[MAX_DECALS];         // birth_time, weapon_class, _, _
uniform mat4  u_ship_world_inv;              // inverse(ship world): world->body
uniform float u_decal_time;                  // game-time seconds (ember clock)
uniform vec4  u_decal_d[MAX_DECALS];         // tangent_body.xyz (unit, ⟂ normal; Scuff), _
uniform sampler2D u_scuff_map;               // unit 7: tiling crumpled-metal tangent-space
                                             // normal map (renderer/scuff_texture.h)
uniform int   u_scuff_map_ok;                // 0 = not loaded: scuffs draw albedo only
uniform mat3  u_ship_world_rot;              // body->world rotation (x uniform scale)

// ── Collision scuffs (class 2): a splatted normal map, pre-lighting ───────
// Spec: docs/superpowers/specs/2026-09-20-collision-scuff-normal-decals-design.md §4
// Each scuff is a patch of ONE tiling crumpled-sheet-metal normal map
// (u_scuff_map), sampled in the scuff's own slip frame at a per-scuff random
// offset, so no two scuffs are the same stamp. The relief comes from the
// map; the shader adds bare metal where the sheet creases, a grime fill,
// and a noise-broken edge. Lengths in MODEL units; rebuild to tune.
// Tried and removed (seven live passes, 2026-09-20/21): procedural
// scratches + buckle waves, then a crumple model of dished facets on a
// mesh-oriented panel grid -- every version read as a stencil or a grid.
const float kScuffTexSpan     = 0.25;                 // fraction of the map one scuff's
                                                       // DIAMETER spans (0.25 => a 2048 map
                                                       // shows 512 texels across a scuff)
const float kScuffRelief      = 1.0;                  // relief gain for an impact (dent 1)
const float kScuffGrindRelief = 0.6;                  // ...and for a grind (dent 0), as a
                                                       // fraction of the impact's
const int   kScuffFlipGreen   = 0;                    // 1 if the map's green is DirectX -Y
const vec3  kScuffMetal       = vec3(0.62);           // bare-metal albedo on the creases
const float kScuffAlbedoGain  = 0.4;                  // how far creases go toward kScuffMetal
const float kScuffMetalTilt   = 0.35;                 // |n.xy| at which a crease is fully bare
const float kScuffGrime       = 0.25;                 // soft grime FILL: darkest at the core,
                                                       // fading out with the window (not a ring —
                                                       // a ring drew a circle round every scuff and
                                                       // a grind streak read as crossing rings)
const float kScuffEdgeNoise   = 0.6;                  // fraction the edge is pushed INWARD by
                                                       // noise; breaks the disc outline. Only ever
                                                       // shrinks, so the r >= 1 cull stays exact.
const float kScuffEdgeFreq    = 1.0 / 6.0;            // edge-noise cycles per model unit

// Stencil-marking pass. The breach scoop must draw only where hull was CUT
// AWAY, never in open space — `discard` writes no depth, so from the scoop's
// side a hole in the hull and empty space are indistinguishable, and BC's fill
// mask balloons up to ~3 cells past the hull (measured: 39-55% of mask volume
// lies outside the hull mesh), which is where the scoop was left floating.
//
// Stencil cannot be written by the discarding draw itself — a discarded
// fragment performs no stencil op. So the region is marked by a second draw of
// the same hull through THIS shader with u_carve_invert = 1, which flips the
// test: keep exactly the fragments the normal pass discards, discard the rest.
// Colour and depth writes are masked off by the caller, so only stencil lands.
//
// Reusing this shader rather than writing a marking shader is deliberate: the
// oblate + noise + strut maths stays in ONE place, so the cut region and the
// marked region cannot drift apart. That drift is what caused the original
// see-through bug.
uniform int u_carve_invert;   // 0 = normal hull draw; 1 = stencil-marking draw

// ── Per-instance hull distance field (hull-volume-field-transport, Task 5) ──
// Replaces the 24-sphere ceiling for the hull-clip DISCARD decision: the
// field carries the UNION of every carve ever made (voxel::field_carve_oblate
// is monotonic -- see field_brush.h), not just the 24 most recently active
// spheres above. u_hull_field_enabled == 0 is the stock path -- zero
// per-fragment cost, byte-identical to today. Everything ELSE (the breach
// scoop, the framework lattice below, the decal ring) still derives from the
// sphere list untouched; this block only ever ADDS a discard, it never keeps
// a fragment the sphere block would otherwise cut.
//
// u_hull_field is a 2D R8 slice atlas, NOT a sampler3D: measured on this
// machine, a sampler3D in this shader corrupts shading across four unrelated
// test suites even on a branch that never executes (renderer/field_atlas.h).
// Every Z-slice of the instance's DistanceField is tiled into one 2D texture
// with a replicated 1-texel border per tile, so hardware bilinear filtering
// INSIDE a slice cannot bleed into a neighbouring tile's data.
// === HULL_FIELD_SAMPLING BEGIN === KEEP IN SYNC with breach.frag's copy between its own matching markers -- enforced by native/tests/renderer/breach_field_sampling_test.cc
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

// Discard margin, in sample_hull_field's own return units. MUST be > 0, not
// 0.
//
// NOTE on what this guards, post hull-volume-field-transport's damage-field
// fix: the per-instance field carries DAMAGE, not hull geometry
// (renderer/instance_field_cache.h) -- every untouched cell is -127 ("no
// damage"), nowhere near the zero crossing, so an UNDAMAGED fragment's
// sampled value is never close enough to 0 for quantisation rounding to flip
// its sign. This margin is therefore no longer guarding "every fragment on
// the hull sits at d~0" (that framing described the OLD design, where this
// field was a copy of the hull's own SDF, and rounding noise at that
// everywhere-zero crossing produced hard-edged holes across the whole hull
// the instant a ship took any damage at all -- see the fix's report). What
// remains is the CARVE BOUNDARY: field_carve_oblate writes a real, brush-
// shaped zero crossing at the rim of every cavity it cuts, and a fragment
// right at that rim is exactly as exposed to quantisation rounding as any
// fragment was under the old design -- just now confined to carved regions
// instead of the whole hull. Comparing against a bare 0.0 there would
// speckle that rim in a dithered pattern rather than cutting a clean edge.
//
// Derivation: sample_hull_field's return value is d / (scale * 255) plus at
// most +-0.5/255 of rounding error (see its own derivation above) -- i.e.
// exactly HALF A QUANTISATION STEP of margin, expressed in encoded byte
// units, cancels the per-instance `scale` entirely: half a step in model
// units is 0.5 * scale, and (0.5 * scale) / (scale * 255) == 0.5 / 255
// regardless of what `scale` (cell size, hull, quality) actually is. This
// is therefore the SMALLEST margin that fully absorbs quantisation
// rounding, for any instance -- not an arbitrary safety pad.
//
// SCOPE, and what this constant does NOT cover: the derivation above bounds
// QUANTISATION error only (~0.5*scale, ~0.24 model units at BC's authored
// 15-unit resolution and quality 1). TRILINEAR RECONSTRUCTION error against
// the true continuous carve boundary grows large at sub-cell-thick features
// near a cavity's rim -- the same shape of error that, under the old
// whole-hull-SDF design, discarded thin plating everywhere; here it is
// confined to the immediate vicinity of an actual carve, where a wrong
// discard reads as a slightly wrong hole edge rather than a vanished panel.
// Enlarging kHullFieldIsoMargin to cover that residual is NOT the fix (a
// cell-scaled margin would be ~32x larger here and would start eating small
// carves). That residual is not observable headlessly (every test in
// hull_field_clip_test.cc probes flat, locally-planar synthetic fields) and
// needs the live check: if speckle shows up localised to a carve's own rim
// on a thin-plated ship, that is this residual, not a driver bug or a
// regression of the damage-field fix.
const float kHullFieldIsoMargin = 0.5 / 255.0;


// ── Warp-nacelle glow dimming ───────────────────────────────────────────
const int MAX_GLOW_REGIONS = 12;
uniform int  u_glow_region_count;            // 0 disables the loop entirely
uniform vec4 u_glow_region_a[MAX_GLOW_REGIONS];  // center.xyz, radius (model units)
uniform vec4 u_glow_region_b[MAX_GLOW_REGIONS];  // axis.xyz, aft
uniform vec4 u_glow_region_c[MAX_GLOW_REGIONS];  // fore, dim_target, disable_time, flicker_flag
uniform vec4 u_glow_region_d[MAX_GLOW_REGIONS];  // gain (>1 brightens), unused.yzw
uniform vec4 u_glow_region_e[MAX_GLOW_REGIONS];  // shape_flag, half_extent.xyz
uniform vec4 u_glow_region_f[MAX_GLOW_REGIONS];  // box forward.xyz (body space); .w unused
uniform vec4 u_glow_region_g[MAX_GLOW_REGIONS];  // box up.xyz (body space); .w unused
const float GLOW_FLICKER_SECS = 0.4;   // blow-out window when a region is destroyed
const float DISABLED_FLOOR    = 0.0;   // flicker troughs reach dark while disabled

const float NORMAL_MIN = 0.15;               // back-face cutoff for falloff
const vec3  SOOT_COLOR = vec3(0.06, 0.05, 0.045);

const float EMBER_TIGHT = 6.0;
const float EMBER_BROAD = 2.0;
const float T_EMBER     = 10.0;          // seconds to cold
const float EMBER_TAU   = T_EMBER / 3.2; // decay time const ~3.1 s; heat ~4% at T_EMBER
const float T_GLOW      = 3.0;           // seconds; phaser heat-glow cool time
const float NOISE_SCALE = 0.03;   // 1/model-units; tuned for NIF-scale p_body

// ── Torpedo/disruptor power-disruption flicker (impact-feedback spec 3.5) ──
// A ~500ms electrical stutter of the ship's OWN glow map within a SCORCH
// decal's radius. Signed multiplier on the sampled glow (above and below
// baseline). Distinct from the blackbody ember on the same record. Phaser
// (HeatGlow) decals never flicker.
const float FLICKER_DUR_MIN   = 5.0;    // per-impact flicker duration randomised in [MIN, MAX] s,
const float FLICKER_DUR_MAX   = 60.0;   //   hashed from birth_time and biased toward MIN.
const float FLICKER_DUR_BIAS  = 3.0;    // >1 skews the duration toward MIN (short flickers more likely than long)
const float FLICKER_STUTTER_SECS = 5.0; // initial stutter phase; a disruption longer than this goes solid dark after
const float FLICKER_RMULT_MIN = 1.0;    // per-impact flicker radius multiplier (x decal radius), randomised in
const float FLICKER_RMULT_MAX = 4.0;    //   [MIN, MAX] = 0.5x..2.0x of the former fixed 2.0x
const float STUTTER_GAIN      = 3.0;    // peak signed swing of the glow multiplier (cranked for visibility)
const float FLICKER_TIGHTNESS = 3.0;    // radial falloff (normalised r)
const float STUTTER_FREQ      = 15.0;   // base oscillation rate (slower = more perceptible individual flickers)
const float FLICKER_MAX = 1.0 + STUTTER_GAIN;   // cap multi-decal glow pile-up (~4x); single-hit peak unaffected

float stutter(float age) {
    // Deterministic; all fragments of one decal share `age`, so the whole
    // patch flickers together (electrical-disruption read). Mixes two sines
    // for irregularity; result in [-1, 1].
    float s1 = sin(age * STUTTER_FREQ);
    float s2 = sin(age * STUTTER_FREQ * 2.37 + 1.7);  // 2.37 = irrational-ish freq ratio for decoherence; 1.7 = phase offset
    return clamp(0.6 * s1 + 0.4 * s2, -1.0, 1.0);
}

// Multiplier applied to the ship's glow term from all active nacelle
// capsules. 1.0 = untouched. Inside a capsule, ramps from 1.0 toward
// dim_target, with a brief flicker for the first GLOW_FLICKER_SECS after
// the disable edge (reuses stutter()). p_body is the body-frame fragment
// position; now is the game clock (u_decal_time).
// Aft-face gate: impulse gain applies only to faces whose normal points along
// the region's gate axis (aft). smoothstep band gives a soft edge so the glow
// strip fades in rather than hard-cutting. Side/forward faces stay at gain 1.0.
const float GLOW_GATE_LO = 0.15;   // dot(n, aft) below this -> no boost
const float GLOW_GATE_HI = 0.75;   // dot(n, aft) above this -> full boost

// Hue shift as the engine lights up: GLOW_HUE_PER_GAIN degrees per unit of gain
// above 1, capped at GLOW_HUE_MAX_DEG. With GAIN_MAX=2 (region_gain-1 reaches
// 1.0 at full throttle) -> +10 deg on the HSL wheel (red exhaust warms toward
// orange). Keep PER_GAIN scaled to hit the cap at GAIN_MAX-1.
const float GLOW_HUE_PER_GAIN = 10.0;
const float GLOW_HUE_MAX_DEG  = 10.0;

// Luma-axis (grey-axis) hue rotation via Rodrigues — the standard cheap shader
// hue rotate. `ang` in radians; small angles only (perceptually fine here).
vec3 hue_rotate(vec3 c, float ang) {
    const vec3 k = vec3(0.57735027);   // 1/sqrt(3), the (1,1,1) grey axis
    float cs = cos(ang), sn = sin(ang);
    return c * cs + cross(k, c) * sn + k * dot(k, c) * (1.0 - cs);
}

float glow_region_mult(vec3 p_body, vec3 n_body, float now, out float gain) {
    float mult = 1.0;
    gain = 1.0;   // >1 inside a powered impulse region; healthy engines still brighten
    for (int i = 0; i < u_glow_region_count; ++i) {
        vec3  center = u_glow_region_a[i].xyz;
        float radius = u_glow_region_a[i].w;
        vec3  axis   = u_glow_region_b[i].xyz;
        float aft    = u_glow_region_b[i].w;
        float fore   = u_glow_region_c[i].x;
        float target = u_glow_region_c[i].y;
        float dtime  = u_glow_region_c[i].z;

        vec3 d = p_body - center;
        if (u_glow_region_e[i].x > 0.5) {          // box (axis-aligned or tilted)
            vec3 fwd = u_glow_region_f[i].xyz;
            vec3 upv = u_glow_region_g[i].xyz;
            // Guard on the CROSS magnitude, not just forward: a degenerate basis
            // (zero/parallel forward|up from a hand-authored override) would
            // NaN through normalize(cross) and wrongly light the fragment.
            // Identity basis -> cross = (1,0,0), R = I, d unchanged (byte-identical).
            vec3 rgt = cross(fwd, upv);
            if (dot(rgt, rgt) > 1e-6) {            // valid, non-degenerate orientation
                rgt = normalize(rgt);
                // columns = box-local axes in body space; identity basis -> R = I
                mat3 R = mat3(rgt, normalize(fwd), normalize(upv));
                d = transpose(R) * d;             // body -> box-local
            }
            vec3 h = u_glow_region_e[i].yzw;
            vec3 a = abs(d);
            if (a.x > h.x || a.y > h.y || a.z > h.z) continue;
        } else {                                   // capsule / sphere (unchanged)
            float t = dot(d, axis);
            vec3  perp = d - t * axis;
            if (dot(perp, perp) > radius * radius) continue;
            if (t < aft || t > fore) continue;
        }
        // Gain applies regardless of health — a moving healthy engine is exactly
        // the case we brighten — so read it before the healthy short-circuit.
        // gate_axis (u_glow_region_d.yzw) restricts the boost to aft-facing
        // faces; zero axis = whole-region (legacy, e.g. sensor).
        float rgain = u_glow_region_d[i].x;
        vec3  gate  = u_glow_region_d[i].yzw;
        float nfac  = 1.0;
        if (dot(gate, gate) > 1e-6)
            nfac = smoothstep(GLOW_GATE_LO, GLOW_GATE_HI, dot(n_body, gate));
        gain = max(gain, mix(1.0, rgain, nfac));
        float flick  = u_glow_region_c[i].w;   // 1 = disabled (continuous), 0 = destroyed
        if (dtime < 0.0) continue;             // healthy

        float age = max(now - dtime, 0.0);
        float region_mult;
        if (flick > 0.5) {
            // Disabled: continuous oscillation between floor and full.
            region_mult = mix(DISABLED_FLOOR, 1.0, 0.5 + 0.5 * stutter(age));
        } else {
            // Destroyed: brief blow-out flicker, then settle to target (0 = off).
            float blow = mix(target, 1.0, 0.5 + 0.5 * stutter(age));
            float w    = clamp(age / GLOW_FLICKER_SECS, 0.0, 1.0);
            region_mult = mix(blow, target, w);
        }
        mult = min(mult, region_mult);  // overlapping regions: darkest wins
    }
    return mult;
}

float dhash(vec2 v) { return fract(sin(dot(v, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 v) {
    vec2 i = floor(v), f = fract(v);
    float a = dhash(i), b = dhash(i + vec2(1,0));
    float c = dhash(i + vec2(0,1)), d = dhash(i + vec2(1,1));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 v) {
    float s = 0.0, amp = 0.5, freq = 1.0;
    for (int i = 0; i < 3; ++i) { s += amp * vnoise(v * freq); freq *= 2.1; amp *= 0.5; }
    return s;
}

// Band-limit a procedural term: 1 when its wavelength spans >= 4 px, 0 at
// <= 2 px. `fw` is the axis footprint in model units per pixel, `k` rad/unit.
float scuff_bandlimit(float fw, float k) {
    float cycles_per_px = fw * k / 6.2831853;
    return 1.0 - smoothstep(0.25, 0.5, cycles_per_px);
}

// Collision scuffs — the PRE-LIGHTING half of the decal ring. Perturbs the
// shading normal (from the splatted map) and the base albedo inside each
// Scuff decal. Writes ONLY n_shade and base_rgb: never the shadow-bias
// normal, the Fresnel rim, n_body, the carve loop, decal_emissive or
// glow_flicker.
void apply_scuffs(vec3 p_body, vec3 n_body, inout vec3 n_shade, inout vec3 base_rgb) {
    vec3 dn_ws = vec3(0.0);
    // Scuffs composite as a UNION, not a sum: `cov` is the "over" coverage of
    // every scuff seen so far, each new one only contributes into (1 - cov),
    // and the albedo terms are applied ONCE after the loop from cov and the
    // over-composited crease mask. A grind streak is a chain of overlapping circles; with
    // per-scuff mixing the crossings doubled the relief, re-lightened the
    // ridges and multiplied the grime (live pass 2026-09-20).
    float cov = 0.0;
    float metal_mask = 0.0;
    // Per-pixel footprint, model units. Uniform control flow: the loop below
    // `continue`s per decal, GLSL derivatives are undefined inside that, and
    // so is texture() with implicit LOD -- the map is sampled with
    // textureGrad from these.
    vec3 fw_p = fwidth(p_body);
    vec3 dpdx = dFdx(p_body);
    vec3 dpdy = dFdy(p_body);
    for (int i = 0; i < u_decal_count; ++i) {
        if (u_decal_c[i].y < 1.5) continue;          // Scuff only (class 2)
        vec3  point  = u_decal_a[i].xyz;
        float inten  = u_decal_a[i].w;
        vec3  dn     = u_decal_b[i].xyz;
        float radius = u_decal_b[i].w;
        if (radius <= 0.0) continue;
        vec3  d = p_body - point;
        float r = length(d) / radius;
        if (r >= 1.0) continue;                       // outside: byte-identical
        // Same far-face guard as the other classes.
        float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn));
        if (wn <= 0.0) continue;

        vec3  T = u_decal_d[i].xyz;
        vec3  B = cross(dn, T);
        float u = dot(d, T);                          // along the slip
        float w = dot(d, B);                          // across the slip
        // Noise-broken, soft edge: push r outward by up to kScuffEdgeNoise so
        // no fragment sees a clean circle. Inward-only (r_n >= r), so the
        // r >= 1 cull above is still the exact outer bound. Band-limited:
        // past ~2 px per wavelength the noise would alias into the window as
        // speckle, so the edge relaxes back to a disc at range (where the
        // outline is sub-pixel anyway).
        float bl_e = scuff_bandlimit(max(dot(abs(T), fw_p), dot(abs(B), fw_p)),
                                     6.2831853 * kScuffEdgeFreq);
        // The noise fades in with r (r^2 here), so the plateau stays a
        // plateau: multiplicative noise alone mottled the grime in the core.
        float edge = fbm(vec2(u, w) * kScuffEdgeFreq) * bl_e * r * r;
        float r_n  = r * (1.0 + kScuffEdgeNoise * edge);
        float win  = (1.0 - smoothstep(0.25, 1.0, r_n)) * inten * wn;
        float over = 1.0 - cov;                       // what this scuff may still add

        // The map, in the slip frame: u along T, w along B, kScuffTexSpan of
        // the map across the diameter, at a per-scuff offset so each scuff is
        // a different patch (GL_REPEAT). Mipmapped through explicit
        // gradients: the band limit at range.
        float scale = kScuffTexSpan / (2.0 * radius);
        vec2  off   = vec2(dhash(point.xy + point.z), dhash(point.yz + point.x));
        vec2  uv    = vec2(u, w) * scale + off;
        vec2  duvdx = vec2(dot(dpdx, T), dot(dpdx, B)) * scale;
        vec2  duvdy = vec2(dot(dpdy, T), dot(dpdy, B)) * scale;
        vec3  s     = vec3(0.0, 0.0, 1.0);
        if (u_scuff_map_ok != 0) {
            s = textureGrad(u_scuff_map, uv, duvdx, duvdy).xyz * 2.0 - 1.0;
            if (kScuffFlipGreen != 0) s.y = -s.y;
            s.z = max(s.z, 0.05);                     // never past horizontal
        }
        // An impact (dent 1) shows the full relief, a grind a fraction of it.
        float dent = clamp(u_decal_c[i].z, 0.0, 1.0);
        float gain = kScuffRelief * mix(kScuffGrindRelief, 1.0, dent);
        // Tangent-space normal (x, y, z) in the (T, B, n) basis => the
        // perturbed normal is n + (x/z) T + (y/z) B before renormalising.
        vec2  g = (s.xy / s.z) * gain * win;
        // Creases -- where the sheet tilts hardest -- show bare metal,
        // composited "over" like the relief: each scuff is a different patch
        // of the map, and a max of two patches is brighter than either.
        float crease = smoothstep(0.1, kScuffMetalTilt, length(s.xy)) * win;
        metal_mask += crease * over;

        vec3 T_ws = normalize(u_ship_world_rot * T);
        vec3 B_ws = normalize(u_ship_world_rot * B);
        dn_ws += (g.x * T_ws + g.y * B_ws) * over;
        cov   += win * over;
    }
    if (cov > 0.0) {
        // Albedo once, from the union: bare metal on the creases, and a soft
        // grime fill that is darkest where coverage is full and fades out
        // through the noisy edge with it.
        base_rgb = mix(base_rgb, kScuffMetal, metal_mask * kScuffAlbedoGain);
        base_rgb *= 1.0 - kScuffGrime * cov;
    }
    if (dot(dn_ws, dn_ws) > 0.0) n_shade = normalize(n_shade + dn_ws);
}

// Blackbody-ish ramp keyed on heat 0..1 (white-hot -> red -> black).
vec3 blackbody(float heat) {
    vec3 cold = vec3(0.0);
    vec3 red  = vec3(0.59, 0.10, 0.02);
    vec3 org  = vec3(1.0, 0.45, 0.08);
    vec3 white= vec3(1.0, 0.92, 0.72);
    vec3 lo = mix(cold, red, smoothstep(0.0, 0.35, heat));
    vec3 mid= mix(lo, org, smoothstep(0.35, 0.7, heat));
    return mix(mid, white, smoothstep(0.7, 1.0, heat));
}

void apply_damage_decals(vec3 p_body, vec3 n_body,
                         inout vec3 base_lit, inout vec3 emissive,
                         inout float glow_flicker) {
    // Fragment-position noise: depends only on p_body, so compute once for all
    // decals. The z term uses a distinct per-axis scale (not a scalar broadcast)
    // so z variation doesn't collapse onto the x==y diagonal on curved hull.
    float nval = fbm(p_body.xy * NOISE_SCALE
                     + p_body.z * vec2(NOISE_SCALE, NOISE_SCALE * 0.7));

    for (int i = 0; i < u_decal_count; ++i) {
        if (u_decal_c[i].y > 1.5) continue;   // Scuff: handled pre-lighting by apply_scuffs
        vec3  point = u_decal_a[i].xyz;
        float intensity = u_decal_a[i].w;
        vec3  dn = u_decal_b[i].xyz;
        float radius = u_decal_b[i].w;
        if (radius <= 0.0) continue;

        float r = length(p_body - point) / radius;   // 0 at center, 1 at edge
        // Cull at the widest extent any term reaches: the Scorch glow-flicker,
        // whose per-impact random radius reaches up to FLICKER_RMULT_MAX * the
        // decal (deposit) radius.
        if (r >= FLICKER_RMULT_MAX) continue;

        // Normal-aware falloff (the mirroring fix): the stored decal normal dn
        // (from ray_trace -> world_dir_to_body) comes out in the SAME convention
        // as the reconstructed fragment normal n_body, so a fragment on the
        // struck face has dot(n_body, dn) ~+1 and the opposite face ~-1. This
        // keeps a decal from bleeding onto a surface facing the other way.
        float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn));
        if (wn <= 0.0) continue;

        // Power-disruption flicker (Scorch only): modulate the ship's own glow
        // map. Computed BEFORE the deposit radius cutoff so it can spread wider
        // (its per-impact random rmult * radius) than the soot deposit / ember.
        if (u_decal_c[i].y > 0.5) {
            float birth = u_decal_c[i].x;
            float fage  = u_decal_time - birth;
            // Per-impact randoms, hashed from the unique birth_time (stable
            // across frames, independent via different seeds):
            //  - duration in [MIN,MAX], biased toward MIN (short more likely),
            //  - radius multiplier in [RMULT_MIN, RMULT_MAX] (x decal radius).
            float fdur  = mix(FLICKER_DUR_MIN, FLICKER_DUR_MAX,
                              pow(dhash(vec2(birth, 7.3)), FLICKER_DUR_BIAS));
            float rmult = mix(FLICKER_RMULT_MIN, FLICKER_RMULT_MAX,
                              dhash(vec2(birth, 13.7)));
            float rf = r / rmult;                            // 0 center, 1 at flicker edge
            if (fage >= 0.0 && fage < fdur && rf < 1.0) {    // >= 0: fire at the birth frame
                if (fage < FLICKER_STUTTER_SECS) {
                    // Stutter phase: rapid on/off, amplitude tapering over the phase.
                    float env  = 1.0 - fage / FLICKER_STUTTER_SECS;
                    float fall = exp(-rf * rf * FLICKER_TIGHTNESS);
                    glow_flicker += STUTTER_GAIN * env * stutter(fage) * fall * wn;
                } else {
                    // Past the stutter phase a longer disruption goes SOLID DARK
                    // (lights out) until fdur, then restores. -2 drives gf to 0
                    // (clamped) in the core; soft radial edge so it isn't a hard disc.
                    glow_flicker += -2.0 * wn * (1.0 - smoothstep(0.6, 1.0, rf));
                }
            }
        }

        // Deposit / ember / heat-glow stay confined to the decal radius.
        if (r >= 1.0) continue;

        // HeatGlow (phaser, weapon_class 0): additive emissive bloom, NO deposit.
        // Keying the colour on the FULL blackbody ramp (white at life=1 ->
        // orange -> red -> black at life=0) makes the cool-down visibly read as
        // the hull temperature drops over T_GLOW, rather than holding bright
        // then snapping off. `continue` skips the scorch deposit + ember.
        if (u_decal_c[i].y < 0.5) {
            float age  = max(0.0, u_decal_time - u_decal_c[i].x);
            float life = clamp(1.0 - age / T_GLOW, 0.0, 1.0);
            float glow = exp(-r * r * 5.0);
            emissive += blackbody(life) * glow * wn * intensity;
            continue;
        }

        // Spread-B: dense core + noise-broken radial ejecta thinning with r.
        float core   = exp(-r * r * 3.0);
        float reach  = 0.35 + nval * 0.9;             // 0.35 min reach + noise-driven variability
        float ejecta = max(0.0, (reach - r) / reach)  // thins to 0 at `reach`
                       * pow(nval, 1.5)               // gamma: suppress thin/low-noise ejecta
                       * 1.3;                         // peak ejecta scale
        float deposit = clamp(core + ejecta, 0.0, 1.0) * intensity * wn;
        base_lit = mix(base_lit, SOOT_COLOR, deposit);

        // Game-time blackbody ember (Scorch only; weapon_class 1 in c.y).
        // Only fires when age > 0 (decal_time strictly after birth_time), so
        // a decal rendered at exactly its birth frame has no ember contribution
        // — important for the soot-darkening tests that pass decal_time==0.
        if (u_decal_c[i].y > 0.5) {
            float birth = u_decal_c[i].x;
            float age = u_decal_time - birth;
            if (age > 0.0) {
                float heat = exp(-age / EMBER_TAU);
                float ember_glow = (exp(-r * r * EMBER_BROAD) + exp(-r * r * EMBER_TIGHT));
                // heat appears twice (in the colour ramp and as a scalar): a
                // deliberate heat^2 emphasis so the ember pops hot then snaps dark.
                emissive += blackbody(heat) * ember_glow * heat * wn * intensity;
            }
        }
    }
}

// ── Non-finite cause probe (developer diagnostic) ──────────────────────────
// When u_nan_debug is on, a fragment whose shading went NaN/Inf reports WHICH
// intermediate term did it, as an integer code in the ALPHA channel.
//
// Alpha, and the RGB left exactly as-is — NOT a marker colour. NonfiniteProbe
// finds the offending frame by looking for non-finite RGB, so overwriting RGB
// would stop the probe firing and no frame would ever be dumped. This way the
// frame renders identically, the probe still catches it, and the code rides
// along in a channel the probe can max-reduce and report.
//
// Codes are ordered UPSTREAM FIRST and the search stops at the first hit, so
// what gets reported is the ROOT term rather than everything downstream of it
// (a NaN normal poisons essentially every later term, and "rim is NaN" would
// be a true but useless answer).
uniform int u_nan_debug;   // 0 = off; alpha stays 1.0, production path unchanged

bool nf1(float v) {
    // Same belt-and-braces test as nonfinite_probe.frag: isnan/isinf are the
    // spec answer, the comparison forms survive a fast-math compiler folding
    // those builtins away.
    return isnan(v) || isinf(v) || !(v == v) || !(abs(v) <= 3.4028235e38);
}
bool nf3(vec3 v) { return nf1(v.x) || nf1(v.y) || nf1(v.z); }

out vec4 frag_color;

// Cotangent frame from screen-space derivatives. Returns N unchanged whenever
// the frame or the resulting normal degenerates -- a zero-length tangent would
// divide to NaN, and a NaN normal poisons every downstream term and spreads
// through the HDR bloom chain as hard-edged black rectangles (the same class of
// bug the rim's clamp() above exists to prevent).
//
// `sigma` is the Toksvig length: how much the normals under this pixel agree,
// 1 = perfectly, less = a minified busy patch (mipmapping averages the encoded
// vectors, and averaged unit vectors are SHORTER -- that length is the only
// record of the spread, and renormalising below would throw it away). The
// specular term uses it to broaden the lobe where the surface is busy at the
// current viewing distance; up close every texel is unit length and sigma is
// 1, so nothing changes. Strength scales the perturbation ANGLE by ~k, so the
// recorded variance (1-s)/s scales by k^2: at strength 0 the perturbation is
// gone and so is its variance (sigma == 1), keeping strength 0 == disabled.
vec3 perturb_normal(vec3 N, vec3 p, vec2 uv, out float sigma) {
    sigma = 1.0;
    vec3 dp1  = dFdx(p);
    vec3 dp2  = dFdy(p);
    vec2 duv1 = dFdx(uv);
    vec2 duv2 = dFdy(uv);

    vec3 dp2perp = cross(dp2, N);
    vec3 dp1perp = cross(N, dp1);
    vec3 T = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 B = dp2perp * duv1.y + dp1perp * duv2.y;

    float maxlen = max(dot(T, T), dot(B, B));
    if (!(maxlen > 1e-20)) return N; // zero-area UV triangle (also catches NaN)

    vec3 s = texture(u_normal_map, uv).xyz * 2.0 - 1.0;
    if (u_normal_flip_g != 0) s.y = -s.y;
    s.z = max(s.z, 0.0);             // malformed map (undershot/object-space/
                                      // greyscale-misnamed blue) must not flip
                                      // the normal to face-away at strength 0

    float len_raw = clamp(length(s), 1e-3, 1.0);   // 8-bit unit vectors land
                                                    // a hair over 1: clamp
    float var = (1.0 - len_raw) / len_raw
              * u_normal_strength * u_normal_strength;
    sigma = 1.0 / (1.0 + var);

    s.xy *= u_normal_strength;       // strength 0 => s == (0, 0, z) => N

    float invmax = inversesqrt(maxlen);
    vec3 n = mat3(T * invmax, B * invmax, N) * s;
    float len2 = dot(n, n);
    if (!(len2 > 1e-20)) return N;   // sample/strength collapsed the vector (also catches NaN)
    return n * inversesqrt(len2);
}

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
// Glow suppression around a breach. A breached compartment is open to space,
// so its windows should not still be lit right up to the torn edge -- that
// reads as a decal pasted over a working deck. Fully dark at the hole rim,
// back to normal glow by kGlowKillReach * the carve radius. 1.5 is tight on
// purpose: enough to clear the lit windows off the tear without darkening a
// visible patch of surrounding hull.
// Kill radius, as a multiple of the carve radius. The reach varies per
// AZIMUTH between these two, so the dead zone is lobed rather than a clean
// disc -- a perfect circle of dark windows reads as a stencil stamped on the
// hull, the same failure the procedural scuff relief hit repeatedly. Same
// tool the hole's own rim uses: an azimuthal vnoise3 seeded from the carve
// centre, so it is stable across frames and cannot crawl.
const float kGlowKillReachMin = 1.5;
const float kGlowKillReachMax = 3.0;
const float kGlowLobeFreq     = 2.5;   // lobes around the breach (rim uses 4.0)

// Back-face cutoff for the glow suppression. Deliberately its OWN constant
// rather than a reference to NORMAL_MIN: that one is declared above
// apply_scuffs, which runs long before this block, so it cannot be moved in
// here -- and the two are separate visual decisions anyway (how far a scorch
// decal wraps a curve vs how far a dead compartment reaches around one). The
// value matches today because the same curvature tolerance suits both.
const float kGlowNormalMin = 0.15;

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
// `n_body` is used ONLY by the glow term, never by the cut decision -- a
// fragment is cut or not according to where it is, not which way it faces.
//
// `glow_kill` (out): 0 = glow untouched, 1 = fully suppressed. Returned from
// HERE rather than computed in a second loop of its own, because this loop is
// hot -- it runs for every fragment of every damaged hull, up to 24 times --
// and the per-carve distance it needs has already been computed. Consumers
// that do not want it pass a dummy; the compiler drops the term.
bool hull_cut_at(vec3 p_body, vec3 n_body, out float glow_kill) {
    glow_kill = 0.0;
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

            // Glow suppression around this breach.
            //
            // The normal gate is what keeps the dark patch on the struck FACE.
            // 3D distance alone does not: it only limits the bleed to sections
            // thinner than the kill radius, which on a saucer is most of them,
            // and the dark spot showed through to an undamaged underside. This
            // is the same shape of weight apply_damage_decals uses, for
            // exactly the same reason -- see kGlowNormalMin.
            //
            // The cheap distance test comes FIRST and guards the vnoise3: this
            // loop runs for every fragment of every damaged hull, up to 24
            // times, and the noise is eight sins. Almost every fragment is far
            // from any given carve, so the short-circuit is what keeps this
            // affordable -- the same reasoning as the field clip's own
            // margin-before-noise ordering below.
            float gd = length(v);
            if (gd < r * kGlowKillReachMax) {
                float gwn = smoothstep(kGlowNormalMin, 1.0, dot(n_body, n));
                if (gwn > 0.0) {
                    vec3 gaz = ld > 1e-4 ? lateral / ld : vec3(1.0, 0.0, 0.0);
                    float reach = mix(kGlowKillReachMin, kGlowKillReachMax,
                                      vnoise3(gaz * kGlowLobeFreq + c * kPhase));
                    glow_kill = max(glow_kill,
                                    gwn * (1.0 - smoothstep(r, r * reach, gd)));
                }
            }

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


void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 V = normalize(u_camera_pos_ws - v_position_ws);

    // n stays GEOMETRIC: the shadow bias must offset along real geometry, and
    // the Fresnel rim is a silhouette effect that crawls and sparkles across
    // greeble detail if it tracks a perturbed normal. n_shade carries the
    // normal-map perturbation for the lighting terms.
    float n_sigma = 1.0;
    vec3 n_shade = (u_normal_enabled != 0)
        ? perturb_normal(n, v_position_ws, v_uv, n_sigma)
        : n;

    // Body-frame fragment position (object-space carve + decals).
    vec3 p_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz;
    // Body-frame normal for object-space decals.
    vec3 n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws);
    vec4 base = texture(u_base_color, v_uv);

    // Collision scuffs (class 2): the PRE-LIGHTING half of the decal ring.
    // Must run before the Toksvig spec_ft line below and before any lighting
    // term reads n_shade, since it perturbs n_shade (and, from Task 3, base.rgb).
    if (u_decal_count > 0) {
        apply_scuffs(p_body, n_body, n_shade, base.rgb);
    }

    // Toksvig specular anti-aliasing. ft folds the normal spread under this
    // pixel into a lower exponent; the (1+p')/(1+p) factor keeps the lobe's
    // energy constant so a broadened highlight dims instead of blooming. At
    // n_sigma == 1 (no map, or up close) ft == 1 and both are the identity, so
    // the un-mapped path is byte-identical.
    float spec_ft = n_sigma / (n_sigma + u_specular_power * (1.0 - n_sigma));
    float spec_power = u_specular_power * spec_ft;
    float spec_norm  = (1.0 + spec_power) / (1.0 + u_specular_power);

    // ── Hull-breach hole: pure damage-sphere clip ──────────────────────────
    // Discard hull fragments inside any active carve sphere. The breach pass
    // renders the exposed interior (scoop) within the same spheres, so hole and
    // interior align by construction. u_carve_count == 0 (or disabled) = stock path.
    //
    // UNCHANGED from before the hull-field clip existed, with one addition:
    // `field_suppressed` records whether this fragment fell inside the region
    // the FIELD BRUSH dilated any TRACKED carve to (field_brush.cc), so the
    // field block below can defer to this block wherever it applies. See that
    // block's comment for why.
    float glow_kill = 0.0;
    bool marked = false;
    if (hull_cut_at(p_body, n_body, glow_kill)) {
        if (u_carve_invert != 0) marked = true;
        else                     discard;
    }

    // Marking pass: anything NOT marked by EITHER mechanism (field or sphere)
    // must not stamp the stencil. Covers the old "no carves at all" fallback
    // too: with both blocks above skipped (disabled or empty), `marked` is
    // still false here, so this discards exactly as it always did.
    if (u_carve_invert != 0 && !marked) discard;

    // Shadow attenuates ONLY the sun (directional index 0). When shadows are
    // off, sun_shadow_factor() returns 1.0, so the ×sf below is the identity
    // and the accumulated light is byte-identical to the pre-shadow path.
    float sun_sf = sun_shadow_factor(v_position_ws, n);

    vec3 lit_dir  = vec3(0.0);
    vec3 spec_acc = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        vec3 L  = normalize(u_dir_light_dir_ws[i]);
        float nl = max(dot(n_shade, L), 0.0);
        float sf = (i == 0) ? sun_sf : 1.0;   // sun-only shadow
        lit_dir += sf * nl * u_dir_light_color[i];

        if (u_specular_enabled != 0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(n_shade, H), 0.0), spec_power) * spec_norm * step(0.0, nl);
            spec_acc += sf * s * u_dir_light_color[i];
        }
    }

    // ── Dynamic lights (torpedo glow, etc.) ─────────────────────────────
    // No shadow interaction (dynamic lights never cast shadows) and never
    // added to the rim/Fresnel term (a passing torpedo must not flash the
    // rim) — both are enforced simply by NOT touching sun_sf/rim below.
    // u_dyn_light_count == 0 (the production path until Task 10 wires a
    // caller) skips the loop entirely: lit_dyn stays vec3(0.0) and its fold
    // into `lit` below is `x + 0.0`, IEEE-identical to the pre-Task-9 shader.
    vec3 lit_dyn = vec3(0.0);
    for (int i = 0; i < u_dyn_light_count; ++i) {
        vec3  a      = u_dyn_light_a[i].xyz;
        float radius = u_dyn_light_a[i].w;
        if (radius <= 0.0) continue;
        vec3  b = u_dyn_light_b[i].xyz;

        // Closest point on the segment ab to this fragment.
        vec3  ab = b - a;
        float h  = clamp(dot(v_position_ws - a, ab) / max(dot(ab, ab), 1e-6), 0.0, 1.0);
        vec3  lp = a + ab * h;

        float d     = length(lp - v_position_ws);
        float ratio = d / radius;
        // ratio*ratio*ratio*ratio, NOT pow(ratio, 4.0): GPU pow is not
        // correctly rounded; must bit-match renderer::dynamic_light_attenuation.
        float w   = clamp(1.0 - ratio*ratio*ratio*ratio, 0.0, 1.0);
        // Threshold-offset radius-relative reference (kDynLightShipCeilingGU=40,
        // kDynLightFalloffK=0.3 in dynamic_lights.h — keep in sync).
        float ref = 1.0 + max(0.0, radius - 40.0) * 0.3;
        float dr  = d / ref;
        float att = (w * w) / (dr * dr + 1.0);

        vec3  L  = (lp - v_position_ws) / max(d, 1e-6);
        float nl = max(dot(n_shade, L), 0.0);

        // Cone/spot gate: spot_tan_x < 0 => not a cone => spot == 1.0
        // (byte-identical to the pre-cone shader for point/strip lights).
        float tx = u_dyn_light_dir[i].w;
        float spot = 1.0;
        if (tx >= 0.0) {
            vec3 fwd = normalize(u_dyn_light_dir[i].xyz);
            vec3 upv = normalize(u_dyn_light_up[i].xyz);
            vec3 rgt = cross(fwd, upv);
            if (dot(rgt, rgt) > 1e-6) {          // guard degenerate up
                rgt = normalize(rgt);
                upv = cross(rgt, fwd);
                float ty = u_dyn_light_up[i].w;
                vec3  dld = normalize(-L);        // light -> fragment
                float fz  = dot(dld, fwd);
                // tx/ty must be strictly positive, not merely >= 0 like the
                // outer gate. A cone authored with radius 0 (SetLightEmitter-
                // Radius(i, 0.0) -- one keystroke in the SPV's light editor)
                // yields spot_tan == 0 exactly, and then:
                //   * off the axis planes, num/0 == +/-Inf, e == Inf, the
                //     smoothstep saturates and spot == 0 -- emits nothing;
                //   * ON an axis plane the numerator is exactly 0 too, giving
                //     0/0 == NaN. That does NOT poison the fragment here:
                //     spot is 1.0 - smoothstep(...), smoothstep clamps
                //     internally, and clamp(NaN, 0, 1) == 0 on IEEE-maxNum
                //     hardware -- so spot comes out as 1.0 and the light is
                //     applied at FULL strength precisely where the cone has no
                //     interior. A light leak, not a black pixel. (Hardware that
                //     propagates NaN through clamp would get the black pixel
                //     instead; 0/0 is undefined behaviour either way.)
                // Requiring tx/ty > 0 sends a degenerate cone down the else
                // branch, so it uniformly emits nothing.
                if (fz > 1e-4 && tx > 0.0 && ty > 0.0) {
                    float ex = dot(dld, rgt) / (fz * tx);
                    float ey = dot(dld, upv) / (fz * ty);
                    float e  = ex*ex + ey*ey;     // <= 1 inside the elliptical cone
                    spot = 1.0 - smoothstep(1.0 - 0.15, 1.0, e);  // soft edge
                } else {
                    spot = 0.0;                   // behind the aim
                }
            }
        }
        att *= spot;

        lit_dyn += att * nl * u_dyn_light_color[i];

        if (u_specular_enabled != 0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(n_shade, H), 0.0), spec_power) * spec_norm * step(0.0, nl);
            spec_acc += att * s * u_dyn_light_color[i];
        }
    }

    // lit_dyn folds in EXACTLY where ambient + directional combine, so
    // material/diffuse color and base texture multiply it the same way.
    // MEAN-PRESERVING: dot(N, dir) averages to zero over a sphere, so the
    // average ambient across a closed hull is unchanged and this only
    // REDISTRIBUTES ambient. Do NOT rewrite as
    //     u_ambient_light + u_ambient_gradient * (0.5 + 0.5 * d)
    // which adds light and brightens the whole scene.
    //
    // Byte-identity at u_ambient_gradient == 0 is a BRANCH, not a driver
    // property: the modulated form below is only ever evaluated when the
    // gradient is on, so the off path is u_ambient_light, unconditionally,
    // regardless of what n_shade or u_ambient_dir_ws happen to hold.
    vec3 amb = u_ambient_light;
    if (u_ambient_gradient > 0.0) {
        // n_shade and u_ambient_dir_ws are both unit vectors, so a correct
        // dot product already lands in [-1, 1] -- clamp() here is a
        // mathematical no-op on any legitimate input and cannot change a
        // correct result. What it buys is the degenerate case: a fully
        // zeroed vertex normal (see the a_normal comment on this fixture's
        // HullClipTest counterpart) makes n_shade itself NaN, and
        // clamp(NaN, -1, 1) resolves to -1 ON THIS DRIVER -- MEASURED, the
        // same IEEE-maxNum framing already used above for the spot-cone
        // clamp (clamp(NaN, 0, 1) == 0), not a GLSL language guarantee.
        // Hardware that propagates NaN through clamp would leave amb_d, and
        // this whole branch's ambient term, NaN instead; 0/0-style results
        // are undefined behaviour either way. A `v == v` self-compare and a
        // bare isnan() were both tried here first and both still left
        // HullClipTest.DegenerateNormalWithGradientOnStaysFinite non-finite
        // (measured, not inferred -- the probe still flagged 64 cells with
        // isnan() in place). clamp() also catches +-Inf, which isnan() does
        // not: an infinite u_ambient_dir_ws would otherwise give
        // 0.0 * Inf == NaN here too.
        float amb_d = clamp(dot(n_shade, u_ambient_dir_ws), -1.0, 1.0);
        amb = u_ambient_light * (1.0 + u_ambient_gradient * amb_d);
    }
    vec3 lit  = (amb + lit_dir + lit_dyn) * u_diffuse_color * base.rgb;

    vec3 decal_emissive = vec3(0.0);
    float glow_flicker = 1.0;
    if (u_decal_count > 0) {
        apply_damage_decals(p_body, n_body, lit, decal_emissive, glow_flicker);
    }

    vec4 glow = texture(u_glow_map, v_uv);
    float gf = clamp(glow_flicker, 0.0, FLICKER_MAX);
    vec3 spec = (u_specular_enabled != 0)
        ? spec_acc * u_specular_color * texture(u_specular_map, v_uv).rgb
        : vec3(0.0);

    vec3 rim = vec3(0.0);
    if (u_rim_strength > 0.0) {
        // clamp, NOT max. n and V are both normalize()d, so dot() can land a
        // single ulp ABOVE 1.0 when a normal points exactly at the camera --
        // making the base a tiny NEGATIVE number. pow(x, y) is undefined for
        // x < 0 in GLSL and evaluates as exp2(y * log2(x)), so log2 of a
        // negative gives NaN. max() only ever guarded the dot < 0 end.
        //
        // This was the source of the HDR black-square bug: one face-on hull
        // pixel per few thousand frames went NaN here, and the bloom chain
        // spread it into a hard-edged black rectangle tens of pixels across.
        // The bloom prefilter no longer propagates it, but the NaN itself
        // belongs dead at the source. cloak_refraction.frag already clamps the
        // same quantity for the same reason.
        float ndv = clamp(dot(n, V), 0.0, 1.0);
        float f = pow(1.0 - ndv, RIM_POWER);
        rim = RIM_GAIN * f * lit_dir * u_rim_strength;
    }

    float nac = 1.0;
    float region_gain = 1.0;
    if (u_glow_region_count > 0) {
        nac = glow_region_mult(p_body, n_body, u_decal_time, region_gain);  // body-frame pos + normal
    }

    // Self-illumination (material emissive + window/light glow map) scales by
    // u_emissive_scale so a destroyed ship goes dark; diffuse-lit, specular,
    // rim, and damage-decal embers are external/transient and stay. region_gain
    // (>1) drives the impulse glow with engine power/speed; HDR bloom picks it
    // up. A subtle hue shift tracks the same boost so the exhaust warms as it
    // powers up (only where boosted: hue_deg is 0 when region_gain == 1).
    float hue_deg = clamp(GLOW_HUE_PER_GAIN * (region_gain - 1.0),
                          0.0, GLOW_HUE_MAX_DEG);
    vec3 glow_rgb = (hue_deg > 0.0) ? hue_rotate(glow.rgb, radians(hue_deg))
                                    : glow.rgb;
    // The material emissive is MODULATED BY THE BASE TEXTURE, not added flat.
    // BC's fixed-function pipeline computes a vertex colour of
    // (emissive + ambient + diffuse) and then modulates the texture by it —
    // D3DTOP_MODULATE, the same APPLY_MODULATE our own material_build records
    // for these stages. Adding u_emissive_color untextured instead makes a
    // hull-wide emissive wash the ship out to flat white.
    //
    // Stock BC content hides this: 40 of the Akira's 44 materials are emissive
    // 0.0, and the four that are 0.502 ('Engine - Big', 'Engine - Small',
    // 'Red Bulb') sit on already-bright texels, so added and modulated look
    // identical there. Community ship mods routinely carry a 3ds Max default of
    // ~0.8 self-illumination across EVERY material, covering the whole hull —
    // grey hull in the original game, blown-out white here. That is the case
    // that tells the two formulations apart.
    //
    // The glow-map term is already textured (glow_rgb is a texture sample), so
    // only the material term needs the base multiply. A material emissive of
    // 0.0 leaves this byte-identical to before.
    // glow_alive: windows go dark around a breach (hull_cut_at's out param).
    // It multiplies the GLOW-MAP term only -- the material emissive is a
    // property of the surface, not of a lit compartment behind it.
    // Steady. A failing-power FLICKER was built here (stutter for 60 s from
    // the carve's birth, then settle dark) and REMOVED after a live look: it
    // read as wrong rather than as damage. Deliberately gone rather than
    // switched off, so no dead knob is left implying it is still an option --
    // git history carries it if it is ever wanted back.
    float glow_alive = 1.0 - clamp(glow_kill, 0.0, 1.0);
    vec3 self_illum = u_emissive_scale *
        (u_emissive_color * base.rgb
         + glow_rgb * glow.a * gf * nac * region_gain * glow_alive);

    // Emissive surfaces are light SOURCES, not mirrors. Suppress the reflective
    // diffuse + specular terms where the glow map emits, so a sunlit glow strip
    // (nacelle bussards, windows) doesn't stack reflection on top of its own
    // emission and blow past the bloom / lens-flare threshold — the "why is the
    // nacelle lensing only when it faces the sun" artefact. Keyed on the glow
    // map's own LUMINANCE (not glow.a alone: the no-glow-map fallback is opaque
    // black, alpha=1, so alpha is not a reliable emissive mask). Non-emissive
    // hull (glow.rgb == 0) yields refl_mask == 1 → byte-identical to before.
    // Scaled by glow_alive too: a window that is no longer emitting is no
    // longer a light source, so it goes back to reflecting the sun like any
    // other plating instead of staying masked out of the diffuse term.
    float emit_lum  = dot(glow.rgb, vec3(0.2126, 0.7152, 0.0722)) * glow.a * glow_alive;
    float refl_mask = 1.0 - clamp(emit_lum, 0.0, 1.0);
    vec3 final_color = lit * refl_mask + self_illum + spec * refl_mask
                     + rim + decal_emissive;

    // Cause code for the non-finite probe (see u_nan_debug above). Off => the
    // alpha written is the literal 1.0 this shader has always written.
    float out_alpha = 1.0;
    if (u_nan_debug != 0) {
        int code = 0;
        if      (nf3(n))              code = 1;   // normalize(v_normal_ws) — zero/degenerate normal
        else if (nf3(n_shade))        code = 18;  // perturbed normal — degenerate tangent frame
        else if (nf3(V))              code = 2;   // view vector (camera at the fragment)
        else if (nf1(sun_sf))         code = 3;   // sun_shadow_factor
        else if (nf3(lit_dir))        code = 4;   // directional diffuse
        else if (nf3(spec_acc))       code = 5;   // specular accum — normalize(L+V) with L == -V
        else if (nf3(lit_dyn))        code = 6;   // dynamic lights — cone 0/0, att*nl*Inf
        else if (nf3(n_body))         code = 7;   // body-frame normal
        else if (nf3(base.rgb))       code = 8;   // base colour texture
        else if (nf3(decal_emissive)) code = 9;   // damage-decal ember / heat-glow
        else if (nf1(glow_flicker))   code = 10;  // decal glow flicker
        else if (nf3(lit))            code = 11;  // combined diffuse (post-decal soot mix)
        else if (nf3(spec))           code = 12;  // specular * specular map
        else if (nf3(rim))            code = 13;  // Fresnel rim
        else if (nf1(nac) || nf1(region_gain)) code = 14;  // glow_region_mult
        else if (nf3(glow_rgb))       code = 15;  // hue_rotate of the glow map
        else if (nf3(self_illum))     code = 16;  // self illumination
        else if (nf3(final_color))    code = 17;  // finite inputs, non-finite result
        if (code != 0) out_alpha = float(code);
    }
    frag_color = vec4(final_color, out_alpha);
}
