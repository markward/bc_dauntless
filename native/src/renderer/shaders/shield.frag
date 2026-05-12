#version 330 core

const int MAX_HITS = 8;

in vec3 v_world_pos;
in vec3 v_ship_local_pos;
in vec3 v_ship_local_normal;

uniform vec4  u_hit_points[MAX_HITS];          // xyz = world point, w unused
uniform vec4  u_hit_color_intensity[MAX_HITS]; // rgb = color, a = current_intensity
uniform int   u_hit_tex_index[MAX_HITS];       // 0..3
uniform float u_hit_radius;
uniform float u_hex_tile_rate;                 // hexes per ship-local unit

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

// Triplanar projection in ship-local space: pick the axis whose normal
// component is largest. Cheaper than a true 3-way blend and good enough
// for a hex-pattern overlay where seams hide in the additive accumulation.
vec2 triplanar_uv(vec3 p, vec3 n) {
    vec3 w = abs(normalize(n));
    if (w.x >= w.y && w.x >= w.z) return p.yz;
    if (w.y >= w.z)               return p.xz;
    return p.xy;
}

void main() {
    vec2 uv = triplanar_uv(v_ship_local_pos * u_hex_tile_rate, v_ship_local_normal);

    vec3  color = vec3(0.0);
    float alpha = 0.0;

    for (int i = 0; i < MAX_HITS; ++i) {
        float inten = u_hit_color_intensity[i].a;
        if (inten < 0.01) continue;

        float d = distance(v_world_pos, u_hit_points[i].xyz);
        // Bright at hit center, fading to zero at u_hit_radius.
        float falloff = 1.0 - smoothstep(0.0, u_hit_radius, d);
        if (falloff <= 0.0) continue;

        vec4 hex = sample_tex(u_hit_tex_index[i], uv);
        color += u_hit_color_intensity[i].rgb * inten * falloff * hex.rgb;
        alpha += hex.a * inten * falloff;
    }

    if (alpha < 0.001) discard;
    frag_color = vec4(color, alpha);
}
