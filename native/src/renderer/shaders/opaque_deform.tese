#version 410 core
layout(triangles, equal_spacing, ccw) in;  // ccw = the default front-face winding the opaque GL_TRIANGLES path uses for these meshes

in  vec3  tcp_pos[];
in  vec3  tcp_normal[];
in  vec2  tcp_uv[];
in  float tcp_crush[];   // displacement weight; consumed here (Task 5)

uniform mat4 u_model;          // instance_world * node_world (local -> world)
uniform mat4 u_view;
uniform mat4 u_proj;
uniform mat4 u_ship_world;     // instance_world (body -> world)
uniform mat4 u_ship_world_inv; // inverse(instance_world) (world -> body)

const int MAX_CRATERS = 24;
uniform int  u_crater_count;
uniform vec4 u_crater_a[MAX_CRATERS];  // point_body.xyz, depth
uniform vec4 u_crater_b[MAX_CRATERS];  // impact_dir_body.xyz, radius

out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;

vec3 bary3(vec3 a, vec3 b, vec3 c) {
    return gl_TessCoord.x * a + gl_TessCoord.y * b + gl_TessCoord.z * c;
}

// Body-frame displacement at a body-space point, weighted by per-vertex
// crushability. Each crater pushes along its impact direction; contribution
// falls off smoothly to zero at the crater radius.
vec3 crater_displacement(vec3 p_body, float crush) {
    vec3 disp = vec3(0.0);
    for (int i = 0; i < u_crater_count; ++i) {
        vec3  c_pt   = u_crater_a[i].xyz;
        float depth  = u_crater_a[i].w;
        vec3  dir    = u_crater_b[i].xyz;
        float radius = u_crater_b[i].w;
        if (radius <= 0.0) continue;
        float r = length(p_body - c_pt) / radius;   // 0 center, 1 edge
        if (r >= 1.0) continue;
        float fall = 1.0 - r * r;                    // smooth radial falloff
        fall *= fall;
        disp += depth * fall * crush * dir;
    }
    return disp;
}

void main() {
    vec3  local_pos = bary3(tcp_pos[0], tcp_pos[1], tcp_pos[2]);
    vec3  local_n   = normalize(bary3(tcp_normal[0], tcp_normal[1], tcp_normal[2]));
    vec2  uv        = gl_TessCoord.x * tcp_uv[0]
                    + gl_TessCoord.y * tcp_uv[1]
                    + gl_TessCoord.z * tcp_uv[2];
    float crush     = gl_TessCoord.x * tcp_crush[0]
                    + gl_TessCoord.y * tcp_crush[1]
                    + gl_TessCoord.z * tcp_crush[2];

    vec3 world_pos = (u_model * vec4(local_pos, 1.0)).xyz;
    vec3 body_pos  = (u_ship_world_inv * vec4(world_pos, 1.0)).xyz;

    vec3 disp_body      = crater_displacement(body_pos, crush);
    vec3 displaced_body = body_pos + disp_body;
    vec3 displaced_world = (u_ship_world * vec4(displaced_body, 1.0)).xyz;

    // Normal still from the undisplaced surface; Task 7 recomputes it.
    vec3 world_n = normalize(mat3(u_model) * local_n);

    v_position_ws = displaced_world;
    v_normal_ws   = world_n;
    v_uv          = uv;
    gl_Position   = u_proj * u_view * vec4(displaced_world, 1.0);
}
