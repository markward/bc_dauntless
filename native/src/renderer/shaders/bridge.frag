#version 330 core

in vec2 v_uv;
in vec2 v_uv1;

uniform sampler2D u_base_color;
uniform sampler2D u_dark_map;  // baked lightmap on UV set 1; white where absent
uniform vec3 u_ambient;
uniform vec3 u_emissive;       // per-material self-illumination floor
// Sentinel < 0 disables the discard — see BridgePass::draw_mesh, which
// sets this from Material::alpha_test_enabled / alpha_test_threshold.
uniform float u_alpha_test_threshold;
// Non-zero only for the viewscreen RTT feed: an FBO colour attachment is
// bottom-up (GL origin bottom-left) whereas the NIF screen UVs are authored
// top-down like every .tga, so the feed samples upside-down without this
// flip. Same fix as cef_composite_pass.cc. Affects the base sample only.
uniform int u_flip_v;
// Brightness multiplier for the viewscreen feed, used for ViewOn/ViewOff
// fade transitions. 1.0 for all other bridge geometry (byte-identical).
uniform float u_viewscreen_brightness;
// Warp boom flash, applied ONLY to the viewscreen feed: mixes the feed toward
// white by this amount so the lightspeed flash is confined to the viewscreen on
// the bridge (the surrounding interior never flashes). 0.0 for all other
// geometry (byte-identical).
uniform float u_viewscreen_flash;

out vec4 FragColor;

void main() {
    vec2 base_uv = v_uv;
    if (u_flip_v != 0) base_uv.y = 1.0 - base_uv.y;
    vec4 base = texture(u_base_color, base_uv);
    if (base.a < u_alpha_test_threshold) discard;
    vec3 lm = texture(u_dark_map, v_uv1).rgb;
    // Per-material emissive sets a floor on the lighting term.
    // Fully-emissive materials (BC's ceiling light panels, console
    // screens) have emissive=(1,1,1) and stay bright under any
    // ambient — that's how red-alert dim affects walls/floor without
    // dimming the light fixtures themselves.
    vec3 light = max(u_ambient, u_emissive);
    vec3 col = base.rgb * lm * light * u_viewscreen_brightness;
    col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
    FragColor = vec4(col, 1.0);
}
