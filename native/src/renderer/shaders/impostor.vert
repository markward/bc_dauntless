#version 410 core
// Far tier impostors (far-tier spec §3): a unit quad per instance, posed in
// the chosen baked view's plane, linked with the EXISTING opaque.frag.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_centre_half;   // xyz render, w half-size GU
layout(location = 8) in vec4 a_right_view;    // xyz right (world), w view index
layout(location = 9) in vec4 a_up_dither;     // xyz up (world), w signed dither
uniform mat4 u_view;
uniform mat4 u_proj;
uniform int u_uv_flip_y;                      // pinned by FarPassGLTest.AtlasOrientation
out vec3 v_normal_ws;
out vec2 v_uv;
out vec3 v_position_ws;
flat out float v_dither;
void main() {
    vec3 right = a_right_view.xyz, up = a_up_dither.xyz;
    vec3 ws = a_centre_half.xyz + (a_corner.x * right + a_corner.y * up) * a_centre_half.w;
    int view = int(a_right_view.w + 0.5);
    vec2 cell = vec2(float(view % 4), float(view / 4));
    float sy = (u_uv_flip_y != 0) ? -a_corner.y : a_corner.y;
    v_uv = (cell + vec2(a_corner.x, -sy) * 0.5 + 0.5) / 4.0;
    v_normal_ws = normalize(cross(up, right));   // toward the eye along the baked view
    v_position_ws = ws;
    v_dither = a_up_dither.w;
    gl_Position = u_proj * u_view * vec4(ws, 1.0);
}
