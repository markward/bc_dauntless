#version 410 core
layout(location = 0) in vec2 a_corner;   // unit-disk-local position
layout(location = 1) in vec2 a_uv;

uniform vec2  u_screen_center;            // NDC coordinates
uniform float u_scale;                    // NDC-Y radius of the disk
uniform float u_aspect;                   // viewport_w / viewport_h

out vec2 v_uv;

void main() {
    vec2 ndc = u_screen_center
             + vec2(a_corner.x / u_aspect, a_corner.y) * u_scale;
    gl_Position = vec4(ndc, 0.0, 1.0);
    v_uv = a_uv;
}
