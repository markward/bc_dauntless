#version 410 core
// Viewscreen target readout: positions arrive in target PIXELS (GL origin
// bottom-left, y up), so the fragment shader can do the dot's circle SDF in
// pixel units. u_offset shifts the whole draw (the shadow pass) while v_pix
// stays unshifted, so the SDF moves with the geometry.
layout(location = 0) in vec2 a_pos;
layout(location = 1) in vec2 a_uv;
uniform vec2 u_target;    // target size in pixels
uniform vec2 u_offset;    // pixels; (0,0) except for the shadow
out vec2 v_pix;
out vec2 v_uv;
void main() {
    v_pix = a_pos;
    v_uv  = a_uv;
    gl_Position = vec4((a_pos + u_offset) / u_target * 2.0 - 1.0, 0.0, 1.0);
}
