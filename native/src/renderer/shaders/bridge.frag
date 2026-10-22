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
// TEMPORARY perf experiment (perf/bridge-4k, DAUNTLESS_BRIDGE_EXP): 128 area
// diffuse off, 256 area specular off, 512 exact acos edge integral.
uniform int u_bridge_exp;
uniform int u_mesh_id;

// Developer-only bridge editor selection tint (spec
// 2026-10-08-bridge-emitters §4): 0 none (production), 1 hover, 2 selected.
uniform int   u_highlight;
uniform float u_highlight_time;

// ── Bridge PBR (spec 2026-10-08-bridge-emitters §9) ────────────────────
// u_pbr = 1 on the main bridge view (static bridge + officers) unless the
// developer A/B switch turned it off; 0 for comm sets, which keep the legacy
// shading below. Per channel the first hit wins: map -> per-shape override
// (< 0 = none) -> default (roughness 1, metalness 0). Debug views 6..10 are
// read only inside the PBR branch. CPU twins: renderer/bridge_pbr.h.
uniform int       u_pbr;
uniform sampler2D u_normal_map;   // unit 1: tangent-space normal (Bump stage)
uniform sampler2D u_rough_map;    // unit 5: roughness in .r
uniform sampler2D u_metal_map;    // unit 6: metalness in .r
uniform int       u_has_normal_map;
uniform int       u_has_rough_map;
uniform int       u_has_metal_map;
uniform float     u_rough_override;
uniform float     u_metal_override;
// Scales every Fresnel term -- F0, the spots' and area lights' F, the
// ambient Fv and the probe's split sum -- so 0 reflects nothing and gives no
// diffuse up to a reflection. 1 for the room (the pbr:: twins hold there);
// 0 for skinned characters: BC paints their hair and cloth near-black, and
// the dielectric sheen (F0 0.04) washed them out grey (2026-10-13).
uniform float     u_reflectance;

// ── Emissive sibling maps (task 17) ────────────────────────────────────
// `<stem>_emissive{,_y,_r}` beside the albedo; BridgePass binds the variant
// for the player's alert level (main bridge view; comm sets the default).
// RGB = emitted colour, alpha ignored, sampled with the base UV. Added AFTER
// the diffuse ceiling, so it can exceed bloom. Both shading paths; never in a
// debug view or the AO pre-pass. A probe capture adds it (decoded) to a base
// probe, with the variant for the probe's state -- see u_capture_glow_src.
uniform sampler2D u_emissive_map;    // unit 10 (renderer::kBridgeEmissiveUnit)
uniform int       u_has_emissive_map;
uniform float     u_emissive_scale;  // renderer::kEmissiveScale

// ── Reflection probes (plan 2026-10-09-bridge-pbr Task 6) ──────────────
// Every prefiltered capture of the room (each state's base and its layers)
// in ONE cube-map array on unit 7. BridgePass hands over one weighted list
// each frame (spec 2026-10-17-bridge-reflection-layers §4.2): entry i is the
// array layer u_probe_layer[i] (a recapture swaps a probe's layer) times
// u_probe_weight[i] -- the bases by their cross-fade weight, the layers by
// value x their state's base weight -- summed, box-projected against the
// bridge model's AABB, with the split-sum BRDF LUT on unit 9. With
// u_probe_entries = 0 unit 7 is EMPTY and must not be sampled.
// u_capture = 1 while BridgePass draws a probe face: linear diffuse-only
// radiance under the same diffuse ceiling as the view (spec §9.5: the probe
// holds a lit room capped at 0.88, so only emitters in it may bloom through
// a reflection) plus the decoded, uncapped glow, no AO, no highlight, no
// specular, the viewscreen black.
uniform samplerCubeArray u_probes;  // unit 7: every probe, one cube layer each
const int           kMaxProbeEntries = 19;  // renderer::kBridgeMaxProbeEntries
uniform int         u_probe_entries;  // 0 .. kMaxProbeEntries
uniform int         u_probe_layer[kMaxProbeEntries];   // array layer per entry
uniform float       u_probe_weight[kMaxProbeEntries];  // weight per entry
uniform sampler2D   u_brdf_lut;   // unit 9: (A, B), x = NdotV, y = roughness
uniform vec3        u_probe_pos;  // capture point, world
uniform float       u_probe_max_mip;  // kBridgeProbeMips - 1, set by BridgePass
uniform vec3        u_box_min;    // bridge AABB, world
uniform vec3        u_box_max;
uniform int         u_capture;
// Per probe (spec 2026-10-17-bridge-reflection-layers §4.1): the state the
// probe shows (BridgePass binds that state's emissive variant) and the layer
// it holds (-1 = the state's base). Per draw: the shape's glow in this probe
// -- src as u_glow_src (-1 none), DISPLAY-space colour. A base shows a glow
// shape at its steady value and every other shape's texture-level default
// (dark at offline); a layer shows only its members' glow, at the peak.
uniform int         u_capture_state;
uniform int         u_capture_layer;
uniform int         u_capture_glow_src;
uniform vec3        u_capture_glow_rgb;
const int kCaptureOffline = 3;    // renderer::kBridgeStateOffline

// ── Static spot lights (plan 2026-10-09-bridge-pbr Task 7) ─────────────
// Main bridge view only (comm sets: count 0), PBR path only. BridgePass
// uploads just the u_spot_count entries in use. Radiance is linear colour x
// intensity; never multiplied by AO; no shadows. The probe capture adds the
// spots' DIFFUSE half (static lights are steady, so the probes see them).
const int MAX_SPOTS = 32;           // renderer::kBridgeMaxSpots
uniform int  u_spot_count;
uniform vec3 u_spot_pos[MAX_SPOTS];
uniform vec3 u_spot_dir[MAX_SPOTS];       // unit cone axis
uniform vec3 u_spot_radiance[MAX_SPOTS];
uniform vec4 u_spot_params[MAX_SPOTS];    // x cos_inner, y cos_outer, z range

// ── Static area lights: strips and panels (spec 2026-10-08-bridge-emitters §16.3) ──
// Rectangles: centre (xyz) + range (w), perpendicular half-axes u and v;
// each emits toward cross(u, v) only. Twins of the pbr:: functions of the
// same names in bridge_pbr.h.
const int MAX_AREA_LIGHTS = 32;     // renderer::kBridgeMaxAreaLights
uniform int  u_area_count;
uniform vec4 u_area_center_range[MAX_AREA_LIGHTS];
uniform vec3 u_area_u[MAX_AREA_LIGHTS];
uniform vec3 u_area_v[MAX_AREA_LIGHTS];
uniform vec3 u_area_radiance[MAX_AREA_LIGHTS];
uniform int  u_area_joins[MAX_AREA_LIGHTS];   // spec §16.8: pbr::area_join_weight's bits

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
// 1 Hz pulse, a hovered mesh with a faint constant tint. u_highlight_time is
// the pulse phase from a REAL clock (BridgePass::highlight_phase), never game
// time: the editor runs with the sim frozen. Selection 0.30..0.60 is always
// >= hover 0.15 + 0.15. u_highlight == 0 (production) returns `c` unchanged.
vec3 apply_highlight(vec3 c) {
    if (u_highlight == 0) return c;
    float a = (u_highlight == 2)
        ? 0.45 + 0.15 * sin(u_highlight_time * 6.2831853)
        : 0.15;
    return mix(c, vec3(0.2, 0.9, 1.0), a);
}

// Lit (reflecting) bridge surfaces must never feed bloom -- only emitters
// glow. Identity below 70% of the ceiling, then a soft exponential roll that
// approaches u_diffuse_max (set under bloom's 0.9 threshold) and never
// reaches it. Scales all channels by the max channel's roll, so hue holds.
// Must match the C++ twin renderer::diffuse_ceiling (bridge_lighting_tuning.h).
vec3 diffuse_ceiling(vec3 c, float diffuse_max) {
    if (diffuse_max <= 0.0) return c;
    float b = max(max(c.r, c.g), c.b);
    float knee = 0.7 * diffuse_max;
    if (b <= knee) return c;
    float range = diffuse_max - knee;
    float r = knee + range * (1.0 - exp(-(b - knee) / range));
    return c * (r / b);
}
vec3 diffuse_ceiling(vec3 c) { return diffuse_ceiling(c, u_diffuse_max); }

// ── PBR maths: GLSL twins of renderer::pbr (bridge_pbr.h), same names and
// formulas. The pipeline is gamma-space, so the bridge decodes to light in
// linear and re-encodes before the HDR target.
const float kGamma = 2.2;
const float kPi = 3.14159265358979;

vec3 decode(vec3 c) { return pow(max(c, vec3(0.0)), vec3(kGamma)); }
vec3 encode(vec3 c) { return pow(max(c, vec3(0.0)), vec3(1.0 / kGamma)); }

float D_ggx(float n_dot_h, float rough) {
    float a = rough * rough, a2 = a * a;
    float d = n_dot_h * n_dot_h * (a2 - 1.0) + 1.0;
    return a2 / max(kPi * d * d, 1e-7);
}
float G_schlick_ggx(float n_dot_x, float k) { return n_dot_x / (n_dot_x * (1.0 - k) + k); }
float G_smith(float n_dot_v, float n_dot_l, float rough) {
    float k = (rough + 1.0) * (rough + 1.0) / 8.0;
    return G_schlick_ggx(n_dot_v, k) * G_schlick_ggx(n_dot_l, k);
}
vec3 F_schlick(float cos_t, vec3 f0) {
    float m = pow(clamp(1.0 - cos_t, 0.0, 1.0), 5.0);
    return f0 + (vec3(1.0) - f0) * m;
}
// Roughness-aware Schlick (Lagarde): twin of pbr::F_schlick_rough. At rough 1
// a dielectric stays at F0 at every angle; at rough 0 this IS F_schlick.
// Weights the AMBIENT diffuse only -- spots keep F_schlick(VdotH), and the
// probe term's Fresnel is already integrated, per roughness, into the LUT.
vec3 F_schlick_rough(float cos_t, vec3 f0, float rough) {
    float m = pow(clamp(1.0 - cos_t, 0.0, 1.0), 5.0);
    return f0 + (max(vec3(1.0 - rough), f0) - f0) * m;
}
vec3 f0_for(vec3 albedo_lin, float metal) { return mix(vec3(0.04), albedo_lin, metal); }

// Lit diffuse is capped (encoded) under bloom; specular adds on top uncapped.
vec3 combine(vec3 diffuse_lin, vec3 spec_lin, float diffuse_max) {
    vec3 d = encode(diffuse_lin);
    vec3 ds = encode(diffuse_lin + spec_lin);
    return diffuse_ceiling(d, diffuse_max) + max(ds - d, vec3(0.0));
}

// The pow base is clamped at 0, as in the C++ twin (NaN guard).
float specular_occlusion(float n_dot_v, float ao, float rough) {
    return clamp(pow(max(n_dot_v + ao, 0.0), exp2(-16.0 * rough - 1.0)) - 1.0 + ao, 0.0, 1.0);
}

// Tangent frame from screen-space derivatives (no mesh tangents) — the July
// spike's pbr_perturb_normal.
vec3 perturb_normal(vec3 N, vec2 uv, vec3 map_n) {
    vec3 dp1 = dFdx(v_world), dp2 = dFdy(v_world);
    vec2 duv1 = dFdx(uv), duv2 = dFdy(uv);
    vec3 dp2perp = cross(dp2, N), dp1perp = cross(N, dp1);
    vec3 T = dp2perp * duv1.x + dp1perp * duv2.x;
    vec3 B = dp2perp * duv1.y + dp1perp * duv2.y;
    float m = max(dot(T, T), dot(B, B));
    if (m < 1e-12) return N;          // no UV gradient (UV-less mesh): no tangent frame
    float invmax = inversesqrt(m);
    return normalize(mat3(T * invmax, B * invmax, N) * map_n);
}

// Parallax-corrected lookup: where the ray pos + t*dir leaves the box, seen
// from the probe. Twin of pbr::box_project.
vec3 box_project(vec3 pos, vec3 dir, vec3 bmin, vec3 bmax, vec3 probe) {
    vec3 inv = 1.0 / dir;
    vec3 t1 = (bmax - pos) * inv, t2 = (bmin - pos) * inv;
    vec3 tf = max(t1, t2);
    float t = min(tf.x, min(tf.y, tf.z));
    return normalize(pos + dir * t - probe);
}

// Prefiltered mip for a roughness. Twin of pbr::prefilter_mip; the top mip
// arrives as u_probe_max_mip (renderer::kBridgeProbeMips - 1).
float prefilter_mip(float rough) { return clamp(rough, 0.0, 1.0) * u_probe_max_mip; }

// The weighted sum of every probe entry along `dir` at `mip` (linear).
vec3 sample_probes(vec3 dir, float mip) {
    vec3 sum = vec3(0.0);
    int n = min(u_probe_entries, kMaxProbeEntries);
    for (int i = 0; i < n; ++i)
        sum += u_probe_weight[i]
             * textureLod(u_probes, vec4(dir, float(u_probe_layer[i])), mip).rgb;
    return sum;
}

// Windowed inverse-square falloff and smoothstep-squared cone: twins of
// pbr::spot_falloff / pbr::spot_cone (bridge_pbr.h), same formulas.
float spot_falloff(float d, float range) {
    float r = d / max(range, 1e-4);
    float w = clamp(1.0 - r * r * r * r, 0.0, 1.0);
    return w * w / (d * d + 1.0);
}
float spot_cone(float cos_angle, float cos_outer, float cos_inner) {
    float t = clamp((cos_angle - cos_outer) / max(cos_inner - cos_outer, 1e-5), 0.0, 1.0);
    float s = t * t * (3.0 - 2.0 * t);
    return s * s;
}

// Adds every spot's linear diffuse and GGX specular at this fragment. The
// probe capture passes its own normal/view and ignores `spec`.
void accumulate_spots(vec3 N, vec3 V, float NdotV, vec3 albedo, float metal,
                      float rough, vec3 F0, inout vec3 diffuse, inout vec3 spec) {
    for (int i = 0; i < u_spot_count; ++i) {
        vec3 Lv = u_spot_pos[i] - v_world;
        float d = length(Lv);
        vec3 L = Lv / max(d, 1e-4);
        float NdotL = max(dot(N, L), 0.0);
        if (NdotL <= 0.0) continue;
        float att = spot_falloff(d, u_spot_params[i].z)
                  * spot_cone(dot(-L, u_spot_dir[i]), u_spot_params[i].y, u_spot_params[i].x);
        if (att <= 0.0) continue;
        vec3 H = normalize(L + V);
        float NdotH = max(dot(N, H), 0.0);
        vec3 F = F_schlick(max(dot(V, H), 0.0), F0) * u_reflectance;
        vec3 radiance = u_spot_radiance[i] * att * NdotL;
        diffuse += (vec3(1.0) - F) * (1.0 - metal) * albedo / kPi * radiance;
        spec += D_ggx(NdotH, rough) * G_smith(NdotV, NdotL, rough) * F
              / max(4.0 * NdotV * NdotL, 1e-4) * radiance;
    }
}

// ── Static area lights: strips and panels (spec 2026-10-08-bridge-emitters §16.3) ──
// Rectangles: centre c, half-axes u and v (perpendicular); each emits toward
// cross(u, v) only. Diffuse is the exact horizon-clipped Lambert edge
// integral (Heitz); specular is GGX at a representative point (Karis), its
// lobe widened by the light's size. Twins of renderer::pbr's same names
// (bridge_pbr.h) -- that header is the authority; keep this in step.
float range_window(float d, float range) {
    float r = d / max(range, 1e-4);
    float w = clamp(1.0 - r * r * r * r, 0.0, 1.0);
    return w * w;
}

// theta / sin(theta) for cos(theta) = x: Heitz's fitted IntegrateEdge, no
// acos / sin (pbr::area_theta_over_sin; perf-register SIG-134).
float area_theta_over_sin(float x) {
    float y = abs(x);
    float a = 0.8543985 + (0.4965155 + 0.0145206 * y) * y;
    float b = 3.4175940 + (4.1616724 + y) * y;
    float v = a / b;
    float t = (x > 0.0) ? v : 0.5 * inversesqrt(max(1.0 - x * x, 1e-7)) - v;
    return 2.0 * kPi * t;
}

float area_integrate_edge(vec3 v1, vec3 v2) {
    float cos_t = clamp(dot(v1, v2), -1.0, 1.0);
    if ((u_bridge_exp & 512) != 0) {
        float theta = acos(cos_t);
        return cross(v1, v2).z * ((theta > 0.001) ? theta / sin(theta) : 1.0);
    }
    return cross(v1, v2).z * area_theta_over_sin(cos_t);
}

// Heitz's ClipQuadToHorizon (tangent space, z up). Returns the vertex count.
int area_clip_quad_to_horizon(inout vec3 L[5]) {
    int config = 0;
    if (L[0].z > 0.0) config += 1;
    if (L[1].z > 0.0) config += 2;
    if (L[2].z > 0.0) config += 4;
    if (L[3].z > 0.0) config += 8;
    int n = 0;
    if (config == 0) { n = 0; }
    else if (config == 1) { n = 3; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[3].z * L[0] + L[0].z * L[3]; }
    else if (config == 2) { n = 3; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; }
    else if (config == 3) { n = 4; L[2] = -L[2].z * L[1] + L[1].z * L[2]; L[3] = -L[3].z * L[0] + L[0].z * L[3]; }
    else if (config == 4) { n = 3; L[0] = -L[3].z * L[2] + L[2].z * L[3]; L[1] = -L[1].z * L[2] + L[2].z * L[1]; }
    else if (config == 5) { n = 0; }
    else if (config == 6) { n = 4; L[0] = -L[0].z * L[1] + L[1].z * L[0]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; }
    else if (config == 7) { n = 5; L[4] = -L[3].z * L[0] + L[0].z * L[3]; L[3] = -L[3].z * L[2] + L[2].z * L[3]; }
    else if (config == 8) { n = 3; L[0] = -L[0].z * L[3] + L[3].z * L[0]; L[1] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = L[3]; }
    else if (config == 9) { n = 4; L[1] = -L[1].z * L[0] + L[0].z * L[1]; L[2] = -L[2].z * L[3] + L[3].z * L[2]; }
    else if (config == 10) { n = 0; }
    else if (config == 11) { n = 5; L[4] = L[3]; L[3] = -L[2].z * L[3] + L[3].z * L[2]; L[2] = -L[2].z * L[1] + L[1].z * L[2]; }
    else if (config == 12) { n = 4; L[1] = -L[1].z * L[2] + L[2].z * L[1]; L[0] = -L[0].z * L[3] + L[3].z * L[0]; }
    else if (config == 13) { n = 5; L[4] = L[3]; L[3] = L[2]; L[2] = -L[1].z * L[2] + L[2].z * L[1]; L[1] = -L[1].z * L[0] + L[0].z * L[1]; }
    else if (config == 14) { n = 5; L[4] = -L[0].z * L[3] + L[3].z * L[0]; L[0] = -L[0].z * L[1] + L[1].z * L[0]; }
    else { n = 4; }
    if (n == 3) L[3] = L[0];
    if (n == 4) L[4] = L[0];
    return n;
}

float rect_form_factor(vec3 p, vec3 n, vec3 c0, vec3 c1, vec3 c2, vec3 c3) {
    vec3 ln = normalize(cross(c1 - c0, c3 - c0));
    if (dot(ln, p - c0) <= 0.0) return 0.0;
    vec3 helper = (abs(n.z) < 0.9) ? vec3(0.0, 0.0, 1.0) : vec3(1.0, 0.0, 0.0);
    vec3 t1 = normalize(cross(helper, n));
    vec3 t2 = cross(n, t1);
    vec3 L[5];
    vec3 d0 = c0 - p, d1 = c1 - p, d2 = c2 - p, d3 = c3 - p;
    L[0] = vec3(dot(d0, t1), dot(d0, t2), dot(d0, n));
    L[1] = vec3(dot(d1, t1), dot(d1, t2), dot(d1, n));
    L[2] = vec3(dot(d2, t1), dot(d2, t2), dot(d2, n));
    L[3] = vec3(dot(d3, t1), dot(d3, t2), dot(d3, n));
    L[4] = L[0];
    int m = area_clip_quad_to_horizon(L);
    if (m == 0) return 0.0;
    for (int i = 0; i < 5; ++i) {
        float len = length(L[i]);
        if (len < 1e-9) return 0.0;
        L[i] /= len;
    }
    float s = area_integrate_edge(L[0], L[1]) + area_integrate_edge(L[1], L[2])
            + area_integrate_edge(L[2], L[3]);
    if (m >= 4) s += area_integrate_edge(L[3], L[4]);
    if (m == 5) s += area_integrate_edge(L[4], L[0]);
    return clamp(abs(s) / (2.0 * kPi), 0.0, 1.0);
}

vec3 rect_nearest(vec3 p, vec3 c, vec3 u, vec3 v) {
    float s = clamp(dot(p - c, u) / max(dot(u, u), 1e-12), -1.0, 1.0);
    float t = clamp(dot(p - c, v) / max(dot(v, v), 1e-12), -1.0, 1.0);
    return c + u * s + v * t;
}

vec3 rect_representative(vec3 p, vec3 r, vec3 c, vec3 u, vec3 v) {
    vec3 n = normalize(cross(u, v));
    float denom = dot(r, n);
    if (denom > -1e-6) return rect_nearest(p, c, u, v);
    float t = dot(c - p, n) / denom;
    if (t <= 0.0) return rect_nearest(p, c, u, v);
    return rect_nearest(p + r * t, c, u, v);
}

// Adds every area light's linear diffuse and GGX specular at this fragment
// (pbr::area_light). The probe capture passes its own normal/view and
// ignores `spec`.
// Twin of pbr::area_join_weight (spec §16.8).
float area_join_weight(vec3 p, vec3 r, vec3 c, vec3 u, vec3 nl, int joins, float margin) {
    if (joins == 0) return 1.0;
    float denom = dot(r, nl);
    float t = denom < -1e-6 ? dot(c - p, nl) / denom : -1.0;
    vec3 hit = t > 0.0 ? p + r * t : p - nl * dot(p - c, nl);
    float half_len = length(u);
    float along = dot(hit - c, u) / max(half_len, 1e-6);
    float m = max(margin, 1e-3);
    float w = 1.0;
    if ((joins & 1) != 0) w *= clamp(0.5 + (along + half_len) / m, 0.0, 1.0);
    if ((joins & 2) != 0) w *= clamp(0.5 + (half_len - along) / m, 0.0, 1.0);
    return w;
}

void accumulate_area_lights(vec3 N, vec3 V, float NdotV, vec3 albedo, float metal,
                            float rough, vec3 F0, inout vec3 diffuse, inout vec3 spec) {
    for (int i = 0; i < u_area_count; ++i) {
        vec3 c = u_area_center_range[i].xyz;
        vec3 u = u_area_u[i], v = u_area_v[i];
        // Zero-area early-out, before normalising (pbr::area_light's NaN guard).
        vec3 uv = cross(u, v);
        if (dot(uv, uv) < 1e-12) continue;
        vec3 nl = normalize(uv);
        if (dot(nl, v_world - c) <= 0.0) continue;
        vec3 near_p = rect_nearest(v_world, c, u, v);
        float dn = length(near_p - v_world);
        float win = range_window(dn, u_area_center_range[i].w);
        if (win <= 0.0) continue;
        float ff = (u_bridge_exp & 128) != 0 ? 0.0
                 : rect_form_factor(v_world, N, c - u - v, c + u - v, c + u + v, c - u + v);
        vec3 Ln = (near_p - v_world) / max(dn, 1e-4);
        // Guarded half-vector: Ln == -V on the degenerate on-plane case would
        // otherwise normalize a zero vector (pbr::area_light's other NaN guard).
        vec3 h = Ln + V;
        float hl = length(h);
        vec3 Hd = hl > 1e-6 ? h / hl : N;
        vec3 Fd = F_schlick(max(dot(V, Hd), 0.0), F0) * u_reflectance;
        vec3 rad = u_area_radiance[i] * win;
        diffuse += (vec3(1.0) - Fd) * (1.0 - metal) * albedo * rad * ff;
        if ((u_bridge_exp & 256) != 0) continue;
        vec3 rep = rect_representative(v_world, reflect(-V, N), c, u, v);
        float d = max(length(rep - v_world), 1e-4);
        vec3 L = (rep - v_world) / d;
        float NdotL = max(dot(N, L), 0.0);
        if (NdotL <= 0.0) continue;
        float cos_l = max(dot(-L, nl), 0.0);
        float area = 4.0 * length(u) * length(v);
        float omega = min(area * cos_l / (d * d), 2.0 * kPi);
        float a = rough * rough;
        float a_eff = min(a + sqrt(area / kPi) / (2.0 * d), 1.0);
        vec3 H = normalize(L + V);
        vec3 F = F_schlick(max(dot(V, H), 0.0), F0) * u_reflectance;
        spec += D_ggx(max(dot(N, H), 0.0), sqrt(a_eff)) * G_smith(NdotV, NdotL, rough) * F
              / max(4.0 * NdotV * NdotL, 1e-4) * rad * NdotL * omega
              * area_join_weight(v_world, reflect(-V, N), c, u, nl, u_area_joins[i], d * a_eff);
    }
}

// ── Emitter glow (spec 2026-10-08-bridge-emitters §11.2) ───────────────────
// Per shape, pushed every frame: -1 = none (the texture-level _emissive
// default above), 0 = the alert's emissive map, 1 = the albedo (this
// frame's flipbook texel), 2 = flat. Display space, like the default.
uniform int   u_glow_src;
uniform vec3  u_glow_rgb;     // tint x level x wave x scale
uniform float u_glow_level;   // level x wave x scale: the received-light dip

vec3 emissive_term(vec2 uv, vec3 albedo) {
    if (u_debug_view != 0) return vec3(0.0);
    if (u_glow_src < 0) {
        if (u_has_emissive_map == 0) return vec3(0.0);
        return texture(u_emissive_map, uv).rgb * u_emissive_scale;
    }
    vec3 src = vec3(1.0);
    if (u_glow_src == 0)
        src = u_has_emissive_map != 0 ? texture(u_emissive_map, uv).rgb : vec3(0.0);
    else if (u_glow_src == 1)
        src = albedo;
    return src * u_glow_rgb;
}

// The received light a glowing texel keeps (spec §6.1, §11.2): a lit screen
// shows its emission, not emission + room light. m = 1 for albedo / flat,
// the emissive texel's max channel for a map (its black areas stay ordinary
// receivers).
float glow_dip(vec2 uv) {
    if (u_glow_src < 0 || u_debug_view != 0) return 1.0;
    float m = 1.0;
    if (u_glow_src == 0) {
        vec3 e = u_has_emissive_map != 0 ? texture(u_emissive_map, uv).rgb : vec3(0.0);
        m = max(e.r, max(e.g, e.b));
    }
    return 1.0 - m * clamp(u_glow_level, 0.0, 1.0);
}

float channel(int has_map, sampler2D map, float override_v, float dflt) {
    if (has_map != 0) return texture(map, v_uv).r;
    return override_v >= 0.0 ? override_v : dflt;
}

void main() {
    vec2 base_uv = v_uv;
    if (u_flip_v != 0) base_uv.y = 1.0 - base_uv.y;
    vec4 base = texture(u_base_color, base_uv);
    if (u_face_blend != 0)
        base = mix(base, texture(u_face_b, base_uv), clamp(u_face_mix, 0.0, 1.0));
    if (base.a < u_alpha_test_threshold) discard;
    if (u_output_normal != 0) { FragColor = vec4(shading_normal(), 1.0); return; }
    if (u_capture != 0) {
        // Probe capture: the probe stores LINEAR (capped) radiance. The viewscreen
        // feed is black (it changes every frame; a probe is captured once).
        if (u_unlit != 0) { FragColor = vec4(0.0, 0.0, 0.0, 1.0); return; }
        vec3 nc = shading_normal();
        float metal_c = clamp(channel(u_has_metal_map, u_metal_map, u_metal_override, 0.0), 0.0, 1.0);
        float hc = clamp(dot(nc, u_up) * 0.5 + 0.5, 0.0, 1.0);
        vec3 albedo_c = decode(base.rgb);
        vec3 lit = albedo_c * (1.0 - metal_c)
                 * decode(u_ambient * mix(u_down_bottom, u_down_top, hc));
        // The spots' and area lights' diffuse half only: a probe holds no
        // specular. It shares accumulate_spots / accumulate_area_lights, so
        // it carries the (1 - F) factor that the capture's downlight term
        // above does not -- ~4% at F0 0.04. Accepted: the probe only feeds
        // the (small) dielectric reflection.
        if (u_spot_count > 0 || u_area_count > 0) {
            float rough_c = clamp(channel(u_has_rough_map, u_rough_map, u_rough_override, 1.0), 0.04, 1.0);
            vec3 Vc = normalize(u_eye - v_world);
            vec3 spec_unused = vec3(0.0);
            accumulate_spots(nc, Vc, max(dot(nc, Vc), 1e-4), albedo_c, metal_c, rough_c,
                             f0_for(albedo_c, metal_c), lit, spec_unused);
            accumulate_area_lights(nc, Vc, max(dot(nc, Vc), 1e-4), albedo_c, metal_c, rough_c,
                                   f0_for(albedo_c, metal_c), lit, spec_unused);
        }
        // Glow, in display space like the view's emissive_term: a glow
        // shape's source x its colour in this probe; else, in a base only,
        // the texture-level default for the probe's state (dark offline).
        vec3 glow_c = vec3(0.0);
        if (u_capture_glow_src >= 0) {
            vec3 src = vec3(1.0);
            if (u_capture_glow_src == 0)
                src = u_has_emissive_map != 0 ? texture(u_emissive_map, base_uv).rgb : vec3(0.0);
            else if (u_capture_glow_src == 1)
                src = base.rgb;
            glow_c = src * u_capture_glow_rgb;
        } else if (u_capture_layer < 0 && u_capture_state != kCaptureOffline
                   && u_has_emissive_map != 0) {
            glow_c = texture(u_emissive_map, base_uv).rgb * u_emissive_scale;
        }
        // The view caps lit diffuse in display space; the probe stores the
        // same capped radiance, back in linear -- then the glow, decoded and
        // UNCAPPED (> 1 stays HDR, so a reflected emitter can bloom).
        FragColor = vec4(decode(diffuse_ceiling(encode(lit), u_diffuse_max)) + decode(glow_c),
                         1.0);
        return;
    }
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
    if (u_pbr != 0) {
        vec3 N = n;
        if (u_has_normal_map != 0)
            N = perturb_normal(n, base_uv, texture(u_normal_map, base_uv).xyz * 2.0 - 1.0);
        float rough = clamp(channel(u_has_rough_map, u_rough_map, u_rough_override, 1.0), 0.04, 1.0);
        float metal = clamp(channel(u_has_metal_map, u_metal_map, u_metal_override, 0.0), 0.0, 1.0);
        if (u_debug_view == 6) { FragColor = vec4(vec3(rough), 1.0); return; }
        if (u_debug_view == 7) { FragColor = vec4(vec3(metal), 1.0); return; }
        if (u_debug_view == 10) { FragColor = vec4(N * 0.5 + 0.5, 1.0); return; }
        vec3 albedo = (u_debug_view == 2) ? vec3(1.0) : decode(base.rgb);
        vec3 V = normalize(u_eye - v_world);
        float NdotV = max(dot(N, V), 1e-4);
        vec3 F0 = f0_for(albedo, metal) * u_reflectance;
        // Roughness-aware: plain Schlick here darkened a rough dielectric by
        // up to ~1/3 at grazing views, re-lighting the room when PBR is on.
        vec3 Fv = F_schlick_rough(NdotV, F0, rough) * u_reflectance;
        float h = clamp(dot(N, u_up) * 0.5 + 0.5, 0.0, 1.0);
        // The downlight (AO included) is authored in display space: decode
        // the WHOLE legacy received term, so AO reads exactly as it does today.
        vec3 received = decode(u_ambient * mix(u_down_bottom, u_down_top, h) * ao);
        vec3 diffuse = albedo * (1.0 - metal) * (vec3(1.0) - Fv) * received;
        vec3 spec = vec3(0.0);
        vec3 R = reflect(-V, N);
        // Reflection layers only: BridgePass sends just the layer entries
        // (none: black).
        if (u_debug_view == 11) { FragColor = vec4(encode(sample_probes(R, 0.0)), 1.0); return; }
        if (u_probe_entries > 0) {
            if (u_debug_view == 9) { FragColor = vec4(encode(sample_probes(R, 0.0)), 1.0); return; }
            vec3 Rb = box_project(v_world, R, u_box_min, u_box_max, u_probe_pos);
            // A ray exactly along a face it starts on is 0 * inf: fall back
            // to the unprojected direction rather than feed NaN to bloom.
            if (any(isnan(Rb)) || any(isinf(Rb))) Rb = R;
            float mip = prefilter_mip(rough);
            vec3 pre = sample_probes(Rb, mip);
            vec2 ab = texture(u_brdf_lut, vec2(NdotV, rough)).rg;
            spec = pre * (F0 * ab.x + ab.y * u_reflectance)
                 * specular_occlusion(NdotV, ao, rough);
        }
        // Static spots and area lights: direct light, never multiplied by AO.
        // Their diffuse goes through the ceiling in combine(); only specular
        // may exceed it.
        accumulate_spots(N, V, NdotV, albedo, metal, rough, F0, diffuse, spec);
        accumulate_area_lights(N, V, NdotV, albedo, metal, rough, F0, diffuse, spec);
        float dip = glow_dip(base_uv);
        diffuse *= dip;
        spec *= dip;
        if (u_debug_view == 8) { FragColor = vec4(encode(spec), 1.0); return; }
        vec3 col = (combine(diffuse, spec, u_diffuse_max) + emissive_term(base_uv, base.rgb))
                 * u_viewscreen_brightness;
        col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
        FragColor = vec4(apply_highlight(col), 1.0);
        return;
    }
    vec3 albedo = (u_debug_view == 2) ? vec3(1.0) : base.rgb;
    float h = clamp(dot(n, u_up) * 0.5 + 0.5, 0.0, 1.0);
    vec3 received = u_ambient * mix(u_down_bottom, u_down_top, h) * ao * glow_dip(base_uv);
    vec3 col = (diffuse_ceiling(albedo * received) + emissive_term(base_uv, base.rgb))
             * u_viewscreen_brightness;
    col = mix(col, vec3(1.0), clamp(u_viewscreen_flash, 0.0, 1.0));
    FragColor = vec4(apply_highlight(col), 1.0);
}
