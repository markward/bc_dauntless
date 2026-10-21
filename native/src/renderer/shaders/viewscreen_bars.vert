#version 410 core
// Viewscreen target bars: positions arrive in target PIXELS (GL origin
// bottom-left, y up), so the fragment shader can do its rounded-rect SDF in
// pixel units.
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_uv;
uniform vec2 u_target;    // target size in pixels
out vec2 v_pix;
out vec2 v_uv;
void main() {
    v_pix = a_pos;
    v_uv  = a_uv;
    gl_Position = vec4(a_pos / u_target * 2.0 - 1.0, 0.0, 1.0);
}
