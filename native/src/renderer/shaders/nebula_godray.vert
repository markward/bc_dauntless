#version 330 core
// Fullscreen triangle generated entirely from gl_VertexID — no vertex buffer.
// v_uv spans [0,1] across the screen; the radial god-ray march works in this
// UV space, smearing the bright HDR cloud toward the flash's screen anchor.
out vec2 v_uv;
void main() {
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    v_uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}
