#version 410 core
// BridgeProbe prefilter: one full-screen triangle per (face, mip). The
// fragment shader derives the cube direction from gl_FragCoord, so the
// vertex stage only covers the viewport.
layout(location=0) in vec2 a_pos;
void main() {
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
