#version 330 core

in vec2 v_uv;
in vec2 v_uv1;

uniform sampler2D u_base_color;
uniform sampler2D u_dark_map;  // lightmap on UV set 1; white where absent
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
    FragColor = vec4(base.rgb * lm * light, 1.0);
}
