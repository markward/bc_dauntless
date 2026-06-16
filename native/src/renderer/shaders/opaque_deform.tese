#version 410 core
layout(triangles, equal_spacing, ccw) in;  // ccw = the default front-face winding the opaque GL_TRIANGLES path uses for these meshes

in  vec3  tcp_pos[];
in  vec3  tcp_normal[];
in  vec2  tcp_uv[];
in  float tcp_crush[];   // displacement weight; forwarded unused this stage, consumed in Task 5

uniform mat4 u_model;   // instance_world * node_world (local -> world)
uniform mat4 u_view;
uniform mat4 u_proj;

out vec3 v_normal_ws;   // matches opaque.frag inputs
out vec2 v_uv;
out vec3 v_position_ws;

vec3 bary3(vec3 a, vec3 b, vec3 c) {
    return gl_TessCoord.x * a + gl_TessCoord.y * b + gl_TessCoord.z * c;
}

void main() {
    vec3  local_pos = bary3(tcp_pos[0], tcp_pos[1], tcp_pos[2]);
    vec3  local_n   = normalize(bary3(tcp_normal[0], tcp_normal[1], tcp_normal[2]));
    vec2  uv        = gl_TessCoord.x * tcp_uv[0]
                    + gl_TessCoord.y * tcp_uv[1]
                    + gl_TessCoord.z * tcp_uv[2];

    vec3 world_pos = (u_model * vec4(local_pos, 1.0)).xyz;
    vec3 world_n   = normalize(mat3(u_model) * local_n);

    v_position_ws = world_pos;
    v_normal_ws   = world_n;
    v_uv          = uv;
    gl_Position   = u_proj * u_view * vec4(world_pos, 1.0);
}
