#version 410 core
layout(location = 0) in vec3 a_position;
layout(location = 1) in vec3 a_normal;
layout(location = 2) in vec2 a_uv;
layout(location = 7) in float a_crushability;

out vec3  vcp_pos;       // local-space control point (pre-u_model)
out vec3  vcp_normal;    // local-space normal
out vec2  vcp_uv;
out float vcp_crush;

void main() {
    vcp_pos    = a_position;
    vcp_normal = a_normal;
    vcp_uv     = a_uv;
    vcp_crush  = a_crushability;
}
