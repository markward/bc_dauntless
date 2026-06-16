#version 410 core
layout(vertices = 3) out;

in  vec3  vcp_pos[];
in  vec3  vcp_normal[];
in  vec2  vcp_uv[];
in  float vcp_crush[];

out vec3  tcp_pos[];
out vec3  tcp_normal[];
out vec2  tcp_uv[];
out float tcp_crush[];   // forwarded; weights displacement in the TES (Task 5)

uniform mat4 u_model;          // local -> world
uniform mat4 u_ship_world_inv; // world -> body

const int MAX_CRATERS = 24;
uniform int  u_crater_count;
uniform vec4 u_crater_a[MAX_CRATERS];  // point_body.xyz, depth
uniform vec4 u_crater_b[MAX_CRATERS];  // impact_dir_body.xyz (unit length), radius

const float MAX_TESS = 16.0;   // cap on subdivision (tuned by eye/perf)
const float MIN_TESS = 1.0;

// Patch centroid in body frame (same chain the TES uses for displacement).
vec3 patch_body_centroid() {
    vec3 c_local = (vcp_pos[0] + vcp_pos[1] + vcp_pos[2]) / 3.0;
    vec3 c_world = (u_model * vec4(c_local, 1.0)).xyz;
    return (u_ship_world_inv * vec4(c_world, 1.0)).xyz;
}

// Subdivide finely near craters, fall to MIN_TESS far away. prox: 1 at a
// crater centre, 0 beyond ~2*radius.
float patch_tess_level() {
    if (u_crater_count == 0) return MIN_TESS;
    vec3 c_body = patch_body_centroid();
    float prox = 0.0;
    for (int i = 0; i < u_crater_count; ++i) {
        float radius = u_crater_b[i].w;
        if (radius <= 0.0) continue;
        float d = length(c_body - u_crater_a[i].xyz);
        prox = max(prox, clamp(1.0 - d / (2.0 * radius), 0.0, 1.0));
    }
    return mix(MIN_TESS, MAX_TESS, prox);
}

void main() {
    tcp_pos[gl_InvocationID]    = vcp_pos[gl_InvocationID];
    tcp_normal[gl_InvocationID] = vcp_normal[gl_InvocationID];
    tcp_uv[gl_InvocationID]     = vcp_uv[gl_InvocationID];
    tcp_crush[gl_InvocationID]  = vcp_crush[gl_InvocationID];

    if (gl_InvocationID == 0) {
        float L = patch_tess_level();
        gl_TessLevelInner[0] = L;
        gl_TessLevelOuter[0] = L;
        gl_TessLevelOuter[1] = L;
        gl_TessLevelOuter[2] = L;
    }
}
