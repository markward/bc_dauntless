#version 410 core
// BridgeProbe BRDF LUT: one full-screen triangle over the LUT. The fragment
// shader derives (NdotV, roughness) from gl_FragCoord.
layout(location=0) in vec2 a_pos;
void main() {
    gl_Position = vec4(a_pos, 0.0, 1.0);
}
