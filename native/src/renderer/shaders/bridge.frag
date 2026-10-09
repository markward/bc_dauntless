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

// ── Screen-space AO (BridgeAoPass) ─────────────────────────────────────
// u_output_normal = 1 in the AO's normal pre-pass: write the world shading
// normal instead of colour. Otherwise, with u_ao_on, the received light is
// multiplied by the AO (never the unlit viewscreen feed).
uniform sampler2D u_ao;           // unit 3: occlusion in .r, 1 = open
uniform sampler2D u_ao_depth;     // unit 4: the pre-pass depth (window depth, raw sampler)
uniform mat4      u_ao_inv_proj;
uniform vec2      u_ao_screen;    // the view's size in pixels (the AO may be smaller)
uniform int       u_ao_on;
uniform int       u_output_normal;

// ── Developer Options debug view (Lighting tab) ────────────────────────
// 0 off (production, byte-identical); 1 normals; 2 light only (albedo = 1);
// 3 AO only; 4 triangle id; 5 mesh id. Never applied to the viewscreen feed
// (u_unlit short-circuits before this is read). u_mesh_id is a per-draw
// counter set by BridgePass::render, stable within a frame.
uniform int u_debug_view;
uniform int u_mesh_id;

// Developer-only bridge editor selection tint (spec
// 2026-10-08-bridge-emitters §4): 0 none (production), 1 hover, 2 selected.
uniform int   u_highlight;
uniform float u_highlight_time;

out vec4 FragColor;

// Integer hash (Squirrel3-style, as used by the bridge-lighting debug-view
// spike) turned into a stable RGB colour -- used by debug views 4 (Triangle
// ID, gl_PrimitiveID) and 5 (Mesh ID, u_mesh_id) so adjacent triangles/meshes
// read as visually distinct flat colours.
vec3 hash_color(uint id) {
    id = id * 747796405u + 2891336453u;
    id = ((id >> ((id >> 28u) + 4u)) ^ id) * 277803737u;
    return vec3((id >> 0u) & 255u, (id >> 8u) & 255u, (id >> 16u) & 255u) / 255.0;
}

float ao_view_z(vec2 uv) {
    float win = texture(u_ao_depth, uv).r;
    vec4 v = u_ao_inv_proj * vec4(uv * 2.0 - 1.0, (win - 0.5) * 2.0, 1.0);
    return v.z / v.w;
}

// Depth-aware 4x4 filter over the AO texture. The AO kernel's rotation comes
// from a 4x4 tile, so a 4x4 average cancels it; each tap is weighted by how
// close its depth is to this pixel's, so the average never mixes the AO of a
// foreground silhouette with the surface behind it (a halo round officers).
float ao_term() {
    if (u_ao_on == 0) return 1.0;
    vec2 uvc = gl_FragCoord.xy / u_ao_screen;          // this fragment, 0..1
    vec2 tex = 1.0 / vec2(textureSize(u_ao, 0));      // one AO texel
    float zc = ao_view_z(uvc);                         // full-resolution depth
    float tol = 0.02 * abs(zc) + 0.25;   // depth tolerance grows with distance
    vec2 uv0 = uvc - 1.5 * tex;
    float sum = 0.0, wsum = 0.0;
    for (int y = 0; y < 4; ++y)
        for (int x = 0; x < 4; ++x) {
            vec2 uv = uv0 + vec2(x, y) * tex;
            float w = exp(-abs(ao_view_z(uv) - zc) / tol);
            sum += texture(u_ao, uv).r * w;
            wsum += w;
        }
    return wsum > 1e-4 ? sum / wsum : texture(u_ao, uvc).r;
}

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

// Developer-only bridge editor selection tint (spec
// 2026-10-08-bridge-emitters §4): mixes the selected mesh toward cyan with a
// slow pulse, a hovered mesh with a faint constant tint. u_highlight == 0
// (production) returns `c` unchanged.
vec3 apply_highlight(vec3 c) {
    if (u_highlight == 0) return c;
    float a = (u_highlight == 2)
        ? 0.35 + 0.15 * sin(u_highlight_time * 6.2831853)
        : 0.15;
    return mix(c, vec3(0.2, 0.9, 1.0), a);
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
    if (u_output_normal != 0) { FragColor = vec4(shading_normal(), 1.0); return; }
    if (u_unlit != 0) {
        vec3 col = base.rgb * u_viewscreen_brightness;
        col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
        FragColor = vec4(apply_highlight(col), 1.0);
        return;
    }
    vec3 n = shading_normal();
    if (u_debug_view == 1) { FragColor = vec4(n * 0.5 + 0.5, 1.0); return; }
    float ao = ao_term();
    if (u_debug_view == 3) { FragColor = vec4(vec3(ao), 1.0); return; }
    if (u_debug_view == 4 || u_debug_view == 5) {
        uint id = uint(u_debug_view == 4 ? gl_PrimitiveID : u_mesh_id);
        FragColor = vec4(hash_color(id), 1.0);
        return;
    }
    vec3 albedo = (u_debug_view == 2) ? vec3(1.0) : base.rgb;
    float h = clamp(dot(n, u_up) * 0.5 + 0.5, 0.0, 1.0);
    vec3 received = u_ambient * mix(u_down_bottom, u_down_top, h) * ao;
    vec3 col = diffuse_ceiling(albedo * received) * u_viewscreen_brightness;
    col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
    FragColor = vec4(apply_highlight(col), 1.0);
}
