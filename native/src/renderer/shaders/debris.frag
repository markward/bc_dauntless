#version 330 core

in  vec3 v_normal_ws;
in  vec2 v_uv;

uniform vec3  u_chunk_color;  // per-chunk hash color
uniform float u_chunk_alpha;  // fade alpha [0,1]
uniform vec3  u_light_dir;    // world-space normalized direction toward key light

out vec4 frag_color;

void main() {
    vec3 n   = normalize(v_normal_ws);
    float nl = max(dot(n, normalize(u_light_dir)), 0.0);
    vec3 lit = u_chunk_color * (0.3 + 0.7 * nl);   // ambient + diffuse
    frag_color = vec4(lit, u_chunk_alpha);
}
