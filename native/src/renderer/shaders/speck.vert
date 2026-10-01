#version 410 core
// Far tier specks (far-tier spec §3): a screen-aligned quad per rock below
// ~1.5 px of on-screen radius. Half-size max(p + 0.5, 1.5) framebuffer px:
// p + 0.5 is the AA disc's full support (ruling R12; p alone clipped the
// fringe), and the 1.5 floor keeps the 2x2 square's pixel block strictly
// inside the quad even when a pixel centre sits exactly 1 px from the
// centre (a 1.0 floor left it ON the edge, where the rasteriser may drop it).
// Pixels the kernels give 0 cost only fill.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_pos_p;         // xyz render-space centre, w p_px
layout(location = 8) in vec4 a_albedo_alpha;  // rgb avg albedo, a tier weight
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec2 u_viewport;                      // framebuffer size, px
uniform vec2 u_viewport_origin;               // glViewport x, y, px
out vec3 v_pos;
flat out vec2 v_centre_px;                    // window coords of the centre
flat out float v_p;
flat out vec3 v_albedo;
flat out float v_alpha;
void main() {
    float half_px = max(a_pos_p.w + 0.5, 1.5);
    vec4 clip = u_proj * u_view * vec4(a_pos_p.xyz, 1.0);
    v_centre_px = u_viewport_origin + (clip.xy / clip.w * 0.5 + 0.5) * u_viewport;
    clip.xy += a_corner * half_px * (2.0 / u_viewport) * clip.w;
    v_pos = a_pos_p.xyz;
    v_p = a_pos_p.w;
    v_albedo = a_albedo_alpha.rgb;
    v_alpha = a_albedo_alpha.a;
    gl_Position = clip;
}
