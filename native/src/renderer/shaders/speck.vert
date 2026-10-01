#version 410 core
// Far tier specks (far-tier spec §3): a screen-aligned quad per rock below
// ~1.5 px of on-screen radius, half-size max(p_px, 1) framebuffer pixels.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_pos_p;         // xyz render-space centre, w p_px
layout(location = 8) in vec4 a_albedo_alpha;  // rgb avg albedo, a tier weight
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec2 u_viewport;                      // framebuffer size, px
out vec2 v_px;                                // fragment offset from the centre, px
out vec3 v_pos;
flat out float v_p;
flat out vec3 v_albedo;
flat out float v_alpha;
void main() {
    float half_px = max(a_pos_p.w, 1.0);
    vec4 clip = u_proj * u_view * vec4(a_pos_p.xyz, 1.0);
    clip.xy += a_corner * half_px * (2.0 / u_viewport) * clip.w;
    v_px = a_corner * half_px;
    v_pos = a_pos_p.xyz;
    v_p = a_pos_p.w;
    v_albedo = a_albedo_alpha.rgb;
    v_alpha = a_albedo_alpha.a;
    gl_Position = clip;
}
