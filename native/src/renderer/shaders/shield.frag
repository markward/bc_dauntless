#version 330 core

const int MAX_HITS = 8;

in vec3 v_world_pos;
in vec3 v_ship_local_pos;
in vec3 v_ship_local_normal;

uniform vec4  u_hit_points[MAX_HITS];          // xyz = world point, w unused
uniform vec4  u_hit_color_intensity[MAX_HITS]; // rgb = color, a = current_intensity
uniform int   u_hit_tex_index[MAX_HITS];       // 0..3
uniform float u_hit_radius;
uniform vec3  u_bubble_center;                 // world-space centre of the bubble

// Smooth terminator width for the hemisphere gate, in cos(angle). MUST match
// kShieldSplashGateFeather in renderer/shield_state.h.
const float GATE_FEATHER = 0.25;

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

// One impact splash: a disc on the BUBBLE surface, centred where the impact
// direction pierces it. Returns rgb/a from the splash texture, already scaled
// by falloff and the hemisphere gate; a==0 means "this hit does not touch this
// fragment".
//
// Two things this has to get right, both of which it previously got wrong:
//
//  * The splash must be centred on the BUBBLE, not on the hit point. `hit_pos`
//    is a point on the HULL, and the bubble is √3 ≈ 1.73× the hull AABB — so
//    on a Galaxy a bow hit sits 236 world-units inside the bubble's nose.
//    Measuring falloff straight from `hit_pos` charges that gap against the
//    splash radius, which on the long axes is most of the budget. We project
//    the impact direction onto the fragment's own radius instead, so the
//    splash lands on the bubble at full brightness regardless of how deep the
//    hull surface is, and the radius means the same thing on every axis.
//
//  * The tangent-basis projection has no sign along impact_dir, so the point
//    diametrically opposite the hit lands on uv (0.5, 0.5) — the texture's
//    CENTRE. Ungated, that painted a second full-brightness splash on the
//    OPPOSITE face of the bubble; with depth test on and the hull between
//    them, the mirror is the one the player can see, so a ventral hit read as
//    a dorsal one. The hemisphere gate fades the contribution out across the
//    terminator. Keep in sync with shield_splash_gate() in
//    renderer/shield_state.h.
vec4 splash_sample(int hit_idx, vec3 hit_pos, vec3 frag_pos, float radius) {
    vec3 impact_dir = hit_pos - u_bubble_center;
    float impact_len = length(impact_dir);
    if (impact_len < 1e-4) return vec4(0.0);
    impact_dir /= impact_len;

    vec3 frag_dir = frag_pos - u_bubble_center;
    float frag_len = length(frag_dir);
    if (frag_len < 1e-4) return vec4(0.0);

    float gate = smoothstep(0.0, GATE_FEATHER,
                            dot(frag_dir / frag_len, impact_dir));
    if (gate <= 0.0) return vec4(0.0);

    // Splash centre: the impact direction carried out to this fragment's own
    // distance from the bubble centre.
    vec3 splash_center = u_bubble_center + impact_dir * frag_len;
    float falloff = 1.0 - smoothstep(0.0, radius, distance(frag_pos, splash_center));
    if (falloff <= 0.0) return vec4(0.0);

    // Robust orthonormal basis perpendicular to impact_dir. Pick the
    // world axis least aligned with impact_dir to seed the cross product.
    vec3 ref = abs(impact_dir.z) < 0.9 ? vec3(0.0, 0.0, 1.0)
                                        : vec3(0.0, 1.0, 0.0);
    vec3 t1 = normalize(cross(impact_dir, ref));
    vec3 t2 = cross(impact_dir, t1);

    vec3 offset = frag_pos - splash_center;
    vec2 uv = vec2(dot(offset, t1), dot(offset, t2)) / (2.0 * radius) + 0.5;
    return sample_tex(hit_idx, uv) * (gate * falloff);
}

void main() {
    vec3  color = vec3(0.0);
    float alpha = 0.0;

    for (int i = 0; i < MAX_HITS; ++i) {
        float inten = u_hit_color_intensity[i].a;
        if (inten < 0.01) continue;

        vec4 hex = splash_sample(u_hit_tex_index[i],
                                  u_hit_points[i].xyz,
                                  v_world_pos,
                                  u_hit_radius);
        if (hex.a <= 0.0) continue;

        color += u_hit_color_intensity[i].rgb * inten * hex.rgb;
        alpha += hex.a * inten;
    }

    if (alpha < 0.001) discard;
    frag_color = vec4(color, alpha * 0.75);  // 25% opacity reduction for shield impacts
}
