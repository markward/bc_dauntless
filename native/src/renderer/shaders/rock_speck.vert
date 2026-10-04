#version 410 core
// Rock-field speck band (rock_speck.h): speck.vert's screen quad, with
// the on-screen radius and the alpha computed here per frame, so the CPU only
// rebuilds the instance buffer when the band re-streams. Shaded by speck.frag.
// alpha = inner hand-off (rises over the near billboards' outer fade band, so
// each rock goes billboard -> speck) * the cell's thinning * the outer fade.
layout(location = 0) in vec2 a_corner;        // (+-1, +-1)
layout(location = 7) in vec4 a_pos_r;         // xyz relative to the band origin, w radius (GU)
layout(location = 8) in vec4 a_albedo_u;      // rgb albedo, a the cell's thinning hash
layout(location = 9) in vec4 a_seed;          // per-rock shape phases (CPU, from its SYSTEM position)
uniform mat4 u_view;
uniform mat4 u_proj;
uniform vec2 u_viewport;                      // framebuffer size, px
uniform vec2 u_viewport_origin;               // glViewport x, y, px
uniform vec3 u_offset;                        // render-space position of the band origin
uniform vec3 u_eye;                           // render-space camera position
uniform float u_in_gu, u_in_fade_gu;          // the large billboards' edge and fade band
uniform float u_out_gu, u_out_fade_gu;
uniform float u_keep_d0_gu, u_keep_band, u_keep_power;   // d0 = rockfield::speck_keep_d0
out vec3 v_pos;
flat out vec2 v_centre_px;
flat out float v_p;
flat out vec3 v_albedo;
flat out float v_alpha;
flat out vec4 v_seed;                         // per-rock shape phases
void main() {
    vec3 p = a_pos_r.xyz + u_offset;
    float d = length(p - u_eye);
    float a_in = u_in_fade_gu > 0.0 ? clamp((d - (u_in_gu - u_in_fade_gu)) / u_in_fade_gu, 0.0, 1.0)
                                    : (d >= u_in_gu ? 1.0 : 0.0);
    float a_out = u_out_fade_gu > 0.0 ? clamp((u_out_gu - d) / u_out_fade_gu, 0.0, 1.0)
                                      : (d <= u_out_gu ? 1.0 : 0.0);
    float band = max(u_keep_band, 1e-3);
    float keep = (u_keep_d0_gu > 0.0 && d > u_keep_d0_gu) ? pow(u_keep_d0_gu / d, u_keep_power) : 1.0;
    float a_keep = clamp((keep * (1.0 + band) - a_albedo_u.a) / band, 0.0, 1.0);
    float alpha = a_in * a_out * a_keep;
    vec4 clip = u_proj * u_view * vec4(p, 1.0);
    if (alpha <= 0.0 || clip.w <= 0.0) {          // nothing to draw: off-screen, no fill
        gl_Position = vec4(2.0, 2.0, 2.0, 1.0);
        v_pos = p; v_centre_px = vec2(0.0); v_p = 0.0; v_albedo = vec3(0.0); v_alpha = 0.0;
        v_seed = vec4(0.0);
        return;
    }
    // On-screen radius in framebuffer px: r * (proj[1][1] * h / 2) / depth.
    float r_px = a_pos_r.w * u_proj[1][1] * 0.5 * u_viewport.y / clip.w;
    float half_px = max(r_px + 0.5, 1.5);
    v_centre_px = u_viewport_origin + (clip.xy / clip.w * 0.5 + 0.5) * u_viewport;
    clip.xy += a_corner * half_px * (2.0 / u_viewport) * clip.w;
    v_pos = p;
    v_p = r_px;
    v_albedo = a_albedo_u.rgb;
    v_alpha = alpha;
    // Never hashed from a_pos_r: that is relative to the band origin, which
    // moves on every restream (the outline would re-randomise).
    v_seed = a_seed;
    gl_Position = clip;
}
