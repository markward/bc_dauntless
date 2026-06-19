#version 330 core
layout(location = 0) in vec2 a_pos;   // [-1,3] fullscreen triangle
out vec2 v_uv;
void main() {
    v_uv = a_pos * 0.5 + 0.5;         // orientation irrelevant (noise is isotropic)
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
