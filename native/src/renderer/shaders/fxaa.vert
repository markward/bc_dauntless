#version 330 core
layout(location=0) in vec2 a_pos;
out vec2 v_uv;
void main() {
    v_uv = (a_pos + 1.0) * 0.5;   // bottom-up; LDR texture is bottom-up (NO V flip)
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
