#version 330 core

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
uniform float     u_fill_iso;      // 64.0/255.0

uniform sampler2D u_damage_tex;
uniform vec3      u_camera_pos_ws; // camera world position — uploaded CPU-side, avoids per-fragment inverse
uniform float     u_tex_scale;     // body-units -> texture-period scale

// Molten-rim emissive (hull-breach-2c).
// u_breach_age: age of the matching breach event (large value → cold when no match).
// u_rim_life:   kRimLife constant; rim cools to 0 by this age.
uniform float u_breach_age;
uniform float u_rim_life;

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
    if (fillv < u_fill_iso) discard;

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
        c += blackbody(heat) * rim_w * 1.5;  // 1.5: HDR headroom for glow
    }

    frag_color = vec4(c, 1.0);
}
