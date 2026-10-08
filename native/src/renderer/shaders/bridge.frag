#version 410 core

in vec2 v_uv;
in vec3 v_world;
in vec3 v_normal;

uniform sampler2D u_base_color;
// Bridge ambient (the SDK's light colour x dimmer): the downlight's strength.
uniform vec3 u_ambient;
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

// Officer lip-sync face blend (default off). When u_face_blend != 0 the head
// mesh samples u_base_color (= face_tex_a) and u_face_b (= face_tex_b) and
// lerps them by u_face_mix, so the mouth cross-fades between viseme textures.
// 0 for all other geometry (byte-identical).
uniform sampler2D u_face_b;
uniform float u_face_mix;
uniform int u_face_blend;

// ── Ceiling downlight ───────────────────────────────────────────────────
// One dull light from the ceiling, as a hemisphere: up-facing surfaces
// receive u_down_top of the bridge ambient, down-facing u_down_bottom. BC's
// baked lightmaps (the Dark slot) are not drawn. Values: kBridgeLighting
// (renderer/bridge_lighting_tuning.h).
uniform vec3  u_eye;              // camera position, world
uniform vec3  u_up;               // interior up, world (bridge frame is +Z)
uniform float u_down_top;
uniform float u_down_bottom;
uniform float u_diffuse_max;      // lit-surface ceiling (0 = off), see diffuse_ceiling
uniform int   u_face_by_winding;  // 1: generated normals face by winding; 0: officers face the eye
uniform int   u_unlit;            // viewscreen feed: full bright, unlit

out vec4 FragColor;

vec3 shading_normal() {
    vec3 n = v_normal;
    // Fallback only: a mesh that reached us with no normal at all.
    if (dot(n, n) < 0.25) n = cross(dFdx(v_world), dFdy(v_world));
    n = normalize(n);
    // Culling is off and winding is mixed: light the side we can see.
    if (u_face_by_winding != 0) {
        if (!gl_FrontFacing) n = -n;
    } else if (dot(n, u_eye - v_world) < 0.0) {
        n = -n;
    }
    return n;
}

// Lit (reflecting) bridge surfaces must never feed bloom -- only emitters
// glow. Identity below 70% of the ceiling, then a soft exponential roll that
// approaches u_diffuse_max (set under bloom's 0.9 threshold) and never
// reaches it. Scales all channels by the max channel's roll, so hue holds.
// Must match the C++ twin renderer::diffuse_ceiling (bridge_lighting_tuning.h).
vec3 diffuse_ceiling(vec3 c) {
    if (u_diffuse_max <= 0.0) return c;
    float b = max(max(c.r, c.g), c.b);
    float knee = 0.7 * u_diffuse_max;
    if (b <= knee) return c;
    float range = u_diffuse_max - knee;
    float r = knee + range * (1.0 - exp(-(b - knee) / range));
    return c * (r / b);
}

void main() {
    vec2 base_uv = v_uv;
    if (u_flip_v != 0) base_uv.y = 1.0 - base_uv.y;
    vec4 base = texture(u_base_color, base_uv);
    if (u_face_blend != 0)
        base = mix(base, texture(u_face_b, base_uv), clamp(u_face_mix, 0.0, 1.0));
    if (base.a < u_alpha_test_threshold) discard;
    if (u_unlit != 0) {
        vec3 col = base.rgb * u_viewscreen_brightness;
        col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
        FragColor = vec4(col, 1.0);
        return;
    }
    vec3 n = shading_normal();
    float h = clamp(dot(n, u_up) * 0.5 + 0.5, 0.0, 1.0);
    vec3 received = u_ambient * mix(u_down_bottom, u_down_top, h);
    vec3 col = diffuse_ceiling(base.rgb * received) * u_viewscreen_brightness;
    col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
    FragColor = vec4(col, 1.0);
}
