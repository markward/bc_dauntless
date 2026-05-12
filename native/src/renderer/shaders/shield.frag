#version 330 core

const int MAX_HITS = 8;

in vec3 v_world_pos;
in vec3 v_ship_local_pos;
in vec3 v_ship_local_normal;

uniform vec4  u_hit_points[MAX_HITS];          // xyz = world point, w unused
uniform vec4  u_hit_color_intensity[MAX_HITS]; // rgb = color, a = current_intensity
uniform int   u_hit_tex_index[MAX_HITS];       // 0..3
uniform float u_hit_radius;
uniform vec3  u_ship_center;                   // world-space ship origin

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

// Impact-centered UV: build a 2D tangent basis at the hit point
// (perpendicular to the "ship center → impact" direction), project the
// fragment-to-impact offset onto that basis, and map ±hit_radius to UV
// edge. Each hit contributes ONE texture sample as a single splash disc
// rather than a tiled pattern. Stable across the bubble surface: no
// top/bottom mirroring from axis-aligned projections.
vec4 splash_sample(int hit_idx, vec3 hit_pos, vec3 frag_pos, float radius) {
    vec3 impact_dir = hit_pos - u_ship_center;
    float impact_len = length(impact_dir);
    if (impact_len < 1e-4) return vec4(0.0);
    impact_dir /= impact_len;

    // Robust orthonormal basis perpendicular to impact_dir. Pick the
    // world axis least aligned with impact_dir to seed the cross product.
    vec3 ref = abs(impact_dir.z) < 0.9 ? vec3(0.0, 0.0, 1.0)
                                        : vec3(0.0, 1.0, 0.0);
    vec3 t1 = normalize(cross(impact_dir, ref));
    vec3 t2 = cross(impact_dir, t1);

    vec3 offset = frag_pos - hit_pos;
    vec2 uv = vec2(dot(offset, t1), dot(offset, t2)) / (2.0 * radius) + 0.5;
    return sample_tex(hit_idx, uv);
}

void main() {
    vec3  color = vec3(0.0);
    float alpha = 0.0;

    for (int i = 0; i < MAX_HITS; ++i) {
        float inten = u_hit_color_intensity[i].a;
        if (inten < 0.01) continue;

        float d = distance(v_world_pos, u_hit_points[i].xyz);
        float falloff = 1.0 - smoothstep(0.0, u_hit_radius, d);
        if (falloff <= 0.0) continue;

        vec4 hex = splash_sample(u_hit_tex_index[i],
                                  u_hit_points[i].xyz,
                                  v_world_pos,
                                  u_hit_radius);
        color += u_hit_color_intensity[i].rgb * inten * falloff * hex.rgb;
        alpha += hex.a * inten * falloff;
    }

    if (alpha < 0.001) discard;
    frag_color = vec4(color, alpha);
}
