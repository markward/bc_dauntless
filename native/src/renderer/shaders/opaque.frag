#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;
in vec3 v_position_ws;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;

uniform sampler2D u_glow_map;
uniform vec3 u_emissive_color;

uniform sampler2D u_specular_map;
uniform vec3 u_specular_color;
uniform float u_specular_power;
uniform int u_specular_enabled;

// Fresnel rim light. u_rim_strength == 0.0 disables the term (set per
// draw by frame.cc: the global dauntless_rim toggle AND per-instance
// rim_eligible AND material specular). Tinted by the accumulated
// directional light so the rim only shows where a star hits.
//
// RIM_POWER controls falloff width (lower = wider band); RIM_GAIN scales
// the peak. Tuned against the Galaxy, whose materials author specular≈0.9
// and glossiness≈0, giving a near-constant rim_strength≈0.225 — so the
// gain, not the material term, governs how visible the rim reads.
uniform float u_rim_strength;
const float RIM_POWER = 36.0;  // sharp, edge-only falloff (higher = thinner)
const float RIM_GAIN  = 20.8;  // peak edge brightness (tuned by eye on Galaxy)

uniform vec3 u_ambient_light;
uniform vec3 u_camera_pos_ws;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

// ── Persistent damage decals (Phase 2) ──────────────────────────────────
const int MAX_DECALS = 24;
uniform int   u_decal_count;                 // 0 disables the loop entirely
uniform vec4  u_decal_a[MAX_DECALS];         // point_body.xyz, intensity
uniform vec4  u_decal_b[MAX_DECALS];         // normal_body.xyz, radius (model units)
uniform vec4  u_decal_c[MAX_DECALS];         // birth_time, weapon_class, _, _
uniform mat4  u_ship_world_inv;              // inverse(ship world): world->body
uniform float u_decal_time;                  // game-time seconds (ember clock)

const float NORMAL_MIN = 0.15;               // back-face cutoff for falloff
const vec3  SOOT_COLOR = vec3(0.06, 0.05, 0.045);

const float EMBER_TIGHT = 6.0;
const float EMBER_BROAD = 2.0;
const float T_EMBER     = 10.0;          // seconds to cold
const float EMBER_TAU   = T_EMBER / 3.2; // decay time const ~3.1 s; heat ~4% at T_EMBER
const float T_GLOW      = 3.0;           // seconds; phaser heat-glow cool time
const float NOISE_SCALE = 0.03;   // 1/model-units; tuned for NIF-scale p_body

// ── Torpedo/disruptor power-disruption flicker (impact-feedback spec 3.5) ──
// A ~500ms electrical stutter of the ship's OWN glow map within a SCORCH
// decal's radius. Signed multiplier on the sampled glow (above and below
// baseline). Distinct from the blackbody ember on the same record. Phaser
// (HeatGlow) decals never flicker.
const float FLICKER_DURATION  = 0.5;    // seconds (game time)
const float STUTTER_GAIN      = 1.6;    // peak signed swing of the glow multiplier
const float FLICKER_TIGHTNESS = 4.0;    // radial falloff (normalised r)
const float STUTTER_FREQ      = 60.0;   // base oscillation rate; ~8-12 flickers / window

float stutter(float age) {
    // Deterministic; all fragments of one decal share `age`, so the whole
    // patch flickers together (electrical-disruption read). Mixes two sines
    // for irregularity; result in [-1, 1].
    float s1 = sin(age * STUTTER_FREQ);
    float s2 = sin(age * STUTTER_FREQ * 2.37 + 1.7);
    return clamp(0.6 * s1 + 0.4 * s2, -1.0, 1.0);
}

float dhash(vec2 v) { return fract(sin(dot(v, vec2(127.1, 311.7))) * 43758.5453); }
float vnoise(vec2 v) {
    vec2 i = floor(v), f = fract(v);
    float a = dhash(i), b = dhash(i + vec2(1,0));
    float c = dhash(i + vec2(0,1)), d = dhash(i + vec2(1,1));
    vec2 u = f * f * (3.0 - 2.0 * f);
    return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
float fbm(vec2 v) {
    float s = 0.0, amp = 0.5, freq = 1.0;
    for (int i = 0; i < 3; ++i) { s += amp * vnoise(v * freq); freq *= 2.1; amp *= 0.5; }
    return s;
}
// Blackbody-ish ramp keyed on heat 0..1 (white-hot -> red -> black).
vec3 blackbody(float heat) {
    vec3 cold = vec3(0.0);
    vec3 red  = vec3(0.59, 0.10, 0.02);
    vec3 org  = vec3(1.0, 0.45, 0.08);
    vec3 white= vec3(1.0, 0.92, 0.72);
    vec3 lo = mix(cold, red, smoothstep(0.0, 0.35, heat));
    vec3 mid= mix(lo, org, smoothstep(0.35, 0.7, heat));
    return mix(mid, white, smoothstep(0.7, 1.0, heat));
}

void apply_damage_decals(vec3 p_body, vec3 n_body,
                         inout vec3 base_lit, inout vec3 emissive,
                         inout float glow_flicker) {
    // Fragment-position noise: depends only on p_body, so compute once for all
    // decals. The z term uses a distinct per-axis scale (not a scalar broadcast)
    // so z variation doesn't collapse onto the x==y diagonal on curved hull.
    float nval = fbm(p_body.xy * NOISE_SCALE
                     + p_body.z * vec2(NOISE_SCALE, NOISE_SCALE * 0.7));

    for (int i = 0; i < u_decal_count; ++i) {
        vec3  point = u_decal_a[i].xyz;
        float intensity = u_decal_a[i].w;
        vec3  dn = u_decal_b[i].xyz;
        float radius = u_decal_b[i].w;
        if (radius <= 0.0) continue;

        float r = length(p_body - point) / radius;   // 0 at center, 1 at edge
        if (r >= 1.0) continue;

        // Normal-aware falloff (the mirroring fix): the stored decal normal dn
        // (from ray_trace -> world_dir_to_body) comes out in the SAME convention
        // as the reconstructed fragment normal n_body, so a fragment on the
        // struck face has dot(n_body, dn) ~+1 and the opposite face ~-1. This
        // keeps a decal from bleeding onto a surface facing the other way.
        float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn));
        if (wn <= 0.0) continue;

        // HeatGlow (phaser, weapon_class 0): additive emissive bloom, NO deposit.
        // Keying the colour on the FULL blackbody ramp (white at life=1 ->
        // orange -> red -> black at life=0) makes the cool-down visibly read as
        // the hull temperature drops over T_GLOW, rather than holding bright
        // then snapping off. `continue` skips the scorch deposit + ember.
        if (u_decal_c[i].y < 0.5) {
            float age  = max(0.0, u_decal_time - u_decal_c[i].x);
            float life = clamp(1.0 - age / T_GLOW, 0.0, 1.0);
            float glow = exp(-r * r * 5.0);
            emissive += blackbody(life) * glow * wn * intensity;
            continue;
        }

        // Spread-B: dense core + noise-broken radial ejecta thinning with r.
        float core   = exp(-r * r * 3.0);
        float reach  = 0.35 + nval * 0.9;             // 0.35 min reach + noise-driven variability
        float ejecta = max(0.0, (reach - r) / reach)  // thins to 0 at `reach`
                       * pow(nval, 1.5)               // gamma: suppress thin/low-noise ejecta
                       * 1.3;                         // peak ejecta scale
        float deposit = clamp(core + ejecta, 0.0, 1.0) * intensity * wn;
        base_lit = mix(base_lit, SOOT_COLOR, deposit);

        // Game-time blackbody ember (Scorch only; weapon_class 1 in c.y).
        // Only fires when age > 0 (decal_time strictly after birth_time), so
        // a decal rendered at exactly its birth frame has no ember contribution
        // — important for the soot-darkening tests that pass decal_time==0.
        if (u_decal_c[i].y > 0.5) {
            float birth = u_decal_c[i].x;
            float age = u_decal_time - birth;
            if (age > 0.0) {
                float heat = exp(-age / EMBER_TAU);
                float ember_glow = (exp(-r * r * EMBER_BROAD) + exp(-r * r * EMBER_TIGHT));
                // heat appears twice (in the colour ramp and as a scalar): a
                // deliberate heat^2 emphasis so the ember pops hot then snaps dark.
                emissive += blackbody(heat) * ember_glow * heat * wn * intensity;
            }
            // Power-disruption flicker: modulate the ship's own glow map for
            // ~500ms. Reuses wn (normal-aware) + the decal's normalized radius r.
            float fl_age = u_decal_time - birth;
            if (fl_age >= 0.0 && fl_age < FLICKER_DURATION) {
                float env  = 1.0 - (fl_age / FLICKER_DURATION);
                float fall = exp(-r * r * FLICKER_TIGHTNESS);
                glow_flicker += STUTTER_GAIN * env * stutter(fl_age) * fall * wn;
            }
        }
    }
}

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 V = normalize(u_camera_pos_ws - v_position_ws);

    vec3 lit_dir  = vec3(0.0);
    vec3 spec_acc = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        vec3 L  = normalize(u_dir_light_dir_ws[i]);
        float nl = max(dot(n, L), 0.0);
        lit_dir += nl * u_dir_light_color[i];

        if (u_specular_enabled != 0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);
            spec_acc += s * u_dir_light_color[i];
        }
    }

    vec4 base = texture(u_base_color, v_uv);
    vec3 lit  = (u_ambient_light + lit_dir) * u_diffuse_color * base.rgb;

    // Reconstruct body-frame fragment pos/normal for object-space decals.
    vec3 p_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz;
    vec3 n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws);
    vec3 decal_emissive = vec3(0.0);
    float glow_flicker = 1.0;
    if (u_decal_count > 0) {
        apply_damage_decals(p_body, n_body, lit, decal_emissive, glow_flicker);
    }

    vec4 glow = texture(u_glow_map, v_uv);
    float gf = max(glow_flicker, 0.0);
    vec3 spec = (u_specular_enabled != 0)
        ? spec_acc * u_specular_color * texture(u_specular_map, v_uv).rgb
        : vec3(0.0);

    vec3 rim = vec3(0.0);
    if (u_rim_strength > 0.0) {
        float f = pow(1.0 - max(dot(n, V), 0.0), RIM_POWER);
        rim = RIM_GAIN * f * lit_dir * u_rim_strength;
    }

    frag_color = vec4(lit + u_emissive_color + glow.rgb * glow.a * gf + spec + rim + decal_emissive, 1.0);
}
