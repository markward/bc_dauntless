#version 410 core
layout(vertices = 3) out;

in  vec3  vcp_pos[];
in  vec3  vcp_normal[];
in  vec2  vcp_uv[];
in  float vcp_crush[];

out vec3  tcp_pos[];
out vec3  tcp_normal[];
out vec2  tcp_uv[];
out float tcp_crush[];

void main() {
    tcp_pos[gl_InvocationID]    = vcp_pos[gl_InvocationID];
    tcp_normal[gl_InvocationID] = vcp_normal[gl_InvocationID];
    tcp_uv[gl_InvocationID]     = vcp_uv[gl_InvocationID];
    tcp_crush[gl_InvocationID]  = vcp_crush[gl_InvocationID];

    if (gl_InvocationID == 0) {
        // Identity tessellation (level 1); Task 6 makes this adaptive.
        gl_TessLevelInner[0] = 1.0;
        gl_TessLevelOuter[0] = 1.0;
        gl_TessLevelOuter[1] = 1.0;
        gl_TessLevelOuter[2] = 1.0;
    }
}
