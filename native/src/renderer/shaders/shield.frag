#version 330 core

const int MAX_HITS = 8;

in vec3 v_world_pos;
in vec3 v_ship_local_pos;
in vec3 v_ship_local_normal;

uniform vec4  u_hit_points[MAX_HITS];          // xyz = world point, w unused
uniform vec4  u_hit_color_intensity[MAX_HITS]; // rgb = color, a = current_intensity
uniform int   u_hit_tex_index[MAX_HITS];       // 0..3
uniform vec3  u_bubble_center;                 // world-space centre of the bubble
uniform vec3  u_bubble_semi_axes;              // world-space semi-axes of the bubble

// Smooth terminator width for the hemisphere gate, in cos(angle). MUST match
// kShieldSplashGateFeather in renderer/shield_state.h.
const float GATE_FEATHER = 0.25;

// Splash size as a chord on the bubble's unit sphere (2·sin(θ/2)).
// MUST match kShieldSplashRadius in renderer/shield_state.h.
const float SPLASH_RADIUS = 0.35;

uniform sampler2D u_shieldhit_0;
uniform sampler2D u_shieldhit_1;
uniform sampler2D u_shieldhit_2;
uniform sampler2D u_shieldhit_3;

out vec4 frag_color;

vec4 sample_tex(int idx, vec2 uv) {
    if      (idx == 0) return texture(u_shieldhit_0, uv);
    else if (idx == 1) return texture(u_shieldhit_1, uv);
    else if (idx == 2) return texture(u_shieldhit_2, uv);
    else               return texture(u_shieldhit_3, uv);
}

// One impact splash: a patch on the BUBBLE surface, centred where the impact
// direction pierces it. Returns rgb/a from the splash texture, already scaled
// by falloff and the hemisphere gate; a==0 means "this hit does not touch this
// fragment".
//
// Everything is measured in the bubble's UNIT-SPHERE space — positions divided
// component-wise by the semi-axes — which is the same space BC's own facing
// chooser works in (ShipClass::TestHit, stbc_reference
// spec/ShieldFacingDamage.md §2.3 step 4). Three things fall out of that, all
// of which earlier revisions got wrong:
//
//  * The footprint is the same shape wherever it lands. Measuring the falloff
//    as a WORLD chord to a splash centre recomputed at each fragment's own
//    distance from the bubble centre made the patch boundary the locus
//    r(dir)·sin(θ/2) = radius/2 — so walking from a bow hit toward the dorsal
//    pole, where a Galaxy's radius collapses 558 → 121, the splash centre
//    chased the fragment inward and the falloff never bit. Bow and flank hits
//    smeared into ribbons 3.5× longer than they were wide, which renders as an
//    arc draped over the ship. In unit space every surface point is at radius
//    1, so the chord is a pure angular measure.
//
//  * A hull hit still lights the bubble above it. `hit_pos` is a point on the
//    HULL and the bubble is √3 ≈ 1.73× the hull AABB, so on a Galaxy a bow hit
//    sits 236 world-units inside the bubble's nose. Normalising discards that
//    radial gap and keeps only the direction, so the patch lands at full
//    brightness however deep the hull surface is.
//
//  * The tangent-basis projection has no sign along the impact direction, so
//    the point diametrically opposite the hit lands on uv (0.5, 0.5) — the
//    texture's CENTRE. Ungated, that painted a second full-brightness splash
//    on the OPPOSITE face; with depth test on and the hull between them, the
//    mirror is the one the player can see, so a ventral hit read as a dorsal
//    one. The hemisphere gate fades it out across the terminator.
//
// MUST match shield_splash_coverage() in renderer/shield_state.h, which is the
// CPU twin the tests characterise — keep in sync.
vec4 splash_sample(int hit_idx, vec3 hit_pos, vec3 frag_pos) {
    vec3 n_hit  = (hit_pos  - u_bubble_center) / u_bubble_semi_axes;
    vec3 n_frag = (frag_pos - u_bubble_center) / u_bubble_semi_axes;
    float lh = length(n_hit);
    float lf = length(n_frag);
    if (lh < 1e-4 || lf < 1e-4) return vec4(0.0);
    n_hit  /= lh;
    n_frag /= lf;

    float gate = smoothstep(0.0, GATE_FEATHER, dot(n_frag, n_hit));
    if (gate <= 0.0) return vec4(0.0);

    // Chord between two unit vectors == 2·sin(θ/2).
    float falloff = 1.0 - smoothstep(0.0, SPLASH_RADIUS, length(n_frag - n_hit));
    if (falloff <= 0.0) return vec4(0.0);

    // Robust orthonormal basis perpendicular to the impact direction. Pick the
    // axis least aligned with it to seed the cross product.
    vec3 ref = abs(n_hit.z) < 0.9 ? vec3(0.0, 0.0, 1.0)
                                   : vec3(0.0, 1.0, 0.0);
    vec3 t1 = normalize(cross(n_hit, ref));
    vec3 t2 = cross(n_hit, t1);

    vec3 offset = n_frag - n_hit;
    vec2 uv = vec2(dot(offset, t1), dot(offset, t2)) / (2.0 * SPLASH_RADIUS) + 0.5;
    return sample_tex(hit_idx, uv) * (gate * falloff);
}

// Overall opacity ceiling. MUST match kShieldSplashOpacity in
// renderer/shield_state.h.
const float SPLASH_OPACITY = 0.75;

// The pass blends GL_ONE, GL_ONE and this writes a PREMULTIPLIED colour, so
// every term — coverage, hit intensity, texture, tint — is applied exactly
// once.
//
// It used to accumulate the texture and the falloff into the colour AND into
// the alpha, under glBlendFunc(GL_SRC_ALPHA, GL_ONE), which multiplies rgb by
// alpha. Each term therefore reached the framebuffer squared: against the real
// shieldhit01.TGA radial profile that left peak output at 0.64% of full
// brightness, which is why impacts registered but were barely visible. Applied
// once, the same peak is 6.93%. Mirrored by shield_splash_intensity() in
// renderer/shield_state.h, whose tests assert linearity in both coverage and
// intensity — a quadratic result there means this got re-squared.
void main() {
    vec3  color = vec3(0.0);
    float total = 0.0;

    for (int i = 0; i < MAX_HITS; ++i) {
        float inten = u_hit_color_intensity[i].a;
        if (inten < 0.01) continue;

        vec4 hex = splash_sample(u_hit_tex_index[i],
                                  u_hit_points[i].xyz,
                                  v_world_pos);
        // The splash textures are greyscale masks, so the alpha channel IS the
        // coverage; sampling rgb as well would square the texture.
        float coverage = hex.a;
        if (coverage <= 0.0) continue;

        float b = coverage * inten * SPLASH_OPACITY;
        color += u_hit_color_intensity[i].rgb * b;
        total += b;
    }

    if (total < 0.001) discard;
    frag_color = vec4(color, 1.0);
}
