#version 330 core

in vec3 v_normal_ws;
in vec2 v_uv;
in vec3 v_position_ws;

uniform sampler2D u_base_color;
uniform vec3 u_diffuse_color;

uniform sampler2D u_glow_map;
uniform vec3 u_emissive_color;
uniform float u_emissive_scale;   // 1 = normal, 0 = destroyed (dark hull)

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
const float RIM_GAIN  = 17.0;  // peak edge brightness (tuned by eye on Galaxy; reduced from 20.8)

uniform vec3 u_ambient_light;
uniform vec3 u_camera_pos_ws;

const int MAX_DIR_LIGHTS = 4;
uniform int  u_dir_light_count;
uniform vec3 u_dir_light_dir_ws[MAX_DIR_LIGHTS];   // direction TOWARD the light
uniform vec3 u_dir_light_color[MAX_DIR_LIGHTS];    // color × dimmer

// ── Sun shadow map (PCF) ─────────────────────────────────────────────────
// Applied ONLY to directional light index 0 (the sun). u_shadows_enabled == 0
// is the stock path: sun_shadow_factor() returns 1.0, so the lighting math is
// byte-identical to the pre-shadow renderer. Bound from the active-shadow state
// in frame.cc::draw_model (Task 5/6).
uniform int             u_shadows_enabled;   // 0/1
uniform mat4            u_light_view_proj;
uniform sampler2DShadow u_shadow_map;        // texture unit 5
uniform float           u_shadow_texel;      // world units/texel (normal-offset bias)

float sun_shadow_factor(vec3 world_pos, vec3 world_normal) {
    if (u_shadows_enabled == 0) return 1.0;
    // Normal-offset bias: push the sample point along the surface normal to
    // suppress self-shadow acne. Task 7 tunes the 1.5 multiplier.
    vec3 p = world_pos + world_normal * (u_shadow_texel * 1.5);
    vec4 lc = u_light_view_proj * vec4(p, 1.0);
    vec3 ndc = lc.xyz / lc.w;
    // ndc.z is glm [0,1] (GLM_FORCE_DEPTH_ZERO_TO_ONE); *0.5+0.5 reproduces GL's
    // window-depth transform applied to the stored pre-pass depth, so store and
    // sample agree. GL clip volume is still [-1,1] (no glClipControl).
    vec3 uvz = ndc * 0.5 + 0.5;            // NDC [-1,1] -> [0,1]
    if (uvz.z > 1.0) return 1.0;           // beyond far plane = lit
    float sum = 0.0;
    vec2 texel = 1.0 / vec2(textureSize(u_shadow_map, 0));
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x) {
            vec3 c = vec3(uvz.xy + vec2(x, y) * texel, uvz.z);
            sum += texture(u_shadow_map, c);   // hardware PCF compare
        }
    return sum / 9.0;
}

// ── Persistent damage decals (Phase 2) ──────────────────────────────────
const int MAX_DECALS = 24;
uniform int   u_decal_count;                 // 0 disables the loop entirely
uniform vec4  u_decal_a[MAX_DECALS];         // point_body.xyz, intensity
uniform vec4  u_decal_b[MAX_DECALS];         // normal_body.xyz, radius (model units)
uniform vec4  u_decal_c[MAX_DECALS];         // birth_time, weapon_class, _, _
uniform mat4  u_ship_world_inv;              // inverse(ship world): world->body
uniform float u_decal_time;                  // game-time seconds (ember clock)

// ── Hull-breach hole: pure damage-sphere clip ─────────────────────────────
// Discard hull fragments inside any active carve sphere. The breach pass
// renders the exposed interior (scoop) within the same spheres, so hole and
// interior align by construction. u_carve_count == 0 (or disabled) = stock path.
//
// u_carve_enabled == 0 is the stock path (zero per-fragment cost).
uniform int  u_carve_enabled;

const int MAX_CARVES = 24;
uniform int  u_carve_count;                    // 0 = no clip
uniform vec4 u_carve_spheres[MAX_CARVES];      // xyz=center_body, w=radius
uniform vec3 u_carve_normals[MAX_CARVES];      // body-frame outward hit normal

// ── Skeletal framework lattice (Damage.tga alpha stencil) ────────────────────
// Projects Damage.tga's alpha channel onto the hull in an annular band around
// each breach. High alpha = structural strut (kept); low alpha = gap (discarded).
// u_frame_enabled == 0 (no GL context / no texture / no carves) = stock path.
uniform sampler2D u_damage_decal;   // Damage.tga: RGB=scar colour, A=lattice stencil
uniform int       u_frame_enabled;  // 0 = framework skipped (stock path)

// Framework lattice constants (eyeball-tunable). The stencil applies INSIDE the
// breach: hull struts remain where Damage.tga's alpha is opaque, gaps reveal the
// interior behind. The surrounding hull is never touched.
const float kFrameUvScale = 0.6;  // breach radius → texture span (lower = bigger lattice cells)
const float kStrutAlpha   = 0.5;  // keep a hull strut where stencil alpha exceeds this
const float kOpenCore     = 0.35; // inner fraction of the breach always fully open (no struts)

// breach shape — KEEP IN SYNC with breach.vert.
// OBLATE spheroid centred on the hull surface: FULL lateral radius (original
// hole width), compressed to kDepthFactor along the normal (shallow). Noise
// perturbs the lateral radius by azimuth (jagged rim).
const float kDepthFactor = 0.45;  // depth = kDepthFactor * radius (shallow)
const float kShapeAmp    = 0.25;
const float kShapeFreq   = 4.0;
const float kPhase       = 0.13;

float vh3(vec3 p){ return fract(sin(dot(p, vec3(127.1,311.7,74.7))) * 43758.5453123); }
float vnoise3(vec3 p){
    vec3 i = floor(p), f = fract(p);
    vec3 u = f*f*(3.0-2.0*f);
    float n000=vh3(i), n100=vh3(i+vec3(1,0,0)), n010=vh3(i+vec3(0,1,0)), n110=vh3(i+vec3(1,1,0));
    float n001=vh3(i+vec3(0,0,1)), n101=vh3(i+vec3(1,0,1)), n011=vh3(i+vec3(0,1,1)), n111=vh3(i+vec3(1,1,1));
    float nx00=mix(n000,n100,u.x), nx10=mix(n010,n110,u.x), nx01=mix(n001,n101,u.x), nx11=mix(n011,n111,u.x);
    return mix(mix(nx00,nx10,u.y), mix(nx01,nx11,u.y), u.z);
}

// ── Warp-nacelle glow dimming ───────────────────────────────────────────
const int MAX_GLOW_REGIONS = 4;
uniform int  u_glow_region_count;            // 0 disables the loop entirely
uniform vec4 u_glow_region_a[MAX_GLOW_REGIONS];  // center.xyz, radius (model units)
uniform vec4 u_glow_region_b[MAX_GLOW_REGIONS];  // axis.xyz, aft
uniform vec4 u_glow_region_c[MAX_GLOW_REGIONS];  // fore, dim_target, disable_time, flicker_flag
uniform vec4 u_glow_region_d[MAX_GLOW_REGIONS];  // gain (>1 brightens), unused.yzw
const float GLOW_FLICKER_SECS = 0.4;   // blow-out window when a region is destroyed
const float DISABLED_FLOOR    = 0.0;   // flicker troughs reach dark while disabled

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
const float FLICKER_DUR_MIN   = 5.0;    // per-impact flicker duration randomised in [MIN, MAX] s,
const float FLICKER_DUR_MAX   = 60.0;   //   hashed from birth_time and biased toward MIN.
const float FLICKER_DUR_BIAS  = 3.0;    // >1 skews the duration toward MIN (short flickers more likely than long)
const float FLICKER_STUTTER_SECS = 5.0; // initial stutter phase; a disruption longer than this goes solid dark after
const float FLICKER_RMULT_MIN = 1.0;    // per-impact flicker radius multiplier (x decal radius), randomised in
const float FLICKER_RMULT_MAX = 4.0;    //   [MIN, MAX] = 0.5x..2.0x of the former fixed 2.0x
const float STUTTER_GAIN      = 3.0;    // peak signed swing of the glow multiplier (cranked for visibility)
const float FLICKER_TIGHTNESS = 3.0;    // radial falloff (normalised r)
const float STUTTER_FREQ      = 15.0;   // base oscillation rate (slower = more perceptible individual flickers)
const float FLICKER_MAX = 1.0 + STUTTER_GAIN;   // cap multi-decal glow pile-up (~4x); single-hit peak unaffected

float stutter(float age) {
    // Deterministic; all fragments of one decal share `age`, so the whole
    // patch flickers together (electrical-disruption read). Mixes two sines
    // for irregularity; result in [-1, 1].
    float s1 = sin(age * STUTTER_FREQ);
    float s2 = sin(age * STUTTER_FREQ * 2.37 + 1.7);  // 2.37 = irrational-ish freq ratio for decoherence; 1.7 = phase offset
    return clamp(0.6 * s1 + 0.4 * s2, -1.0, 1.0);
}

// Multiplier applied to the ship's glow term from all active nacelle
// capsules. 1.0 = untouched. Inside a capsule, ramps from 1.0 toward
// dim_target, with a brief flicker for the first GLOW_FLICKER_SECS after
// the disable edge (reuses stutter()). p_body is the body-frame fragment
// position; now is the game clock (u_decal_time).
float glow_region_mult(vec3 p_body, float now, out float gain) {
    float mult = 1.0;
    gain = 1.0;   // >1 inside a powered impulse region; healthy engines still brighten
    for (int i = 0; i < u_glow_region_count; ++i) {
        vec3  center = u_glow_region_a[i].xyz;
        float radius = u_glow_region_a[i].w;
        vec3  axis   = u_glow_region_b[i].xyz;
        float aft    = u_glow_region_b[i].w;
        float fore   = u_glow_region_c[i].x;
        float target = u_glow_region_c[i].y;
        float dtime  = u_glow_region_c[i].z;

        vec3  d = p_body - center;
        float t = dot(d, axis);
        vec3  perp = d - t * axis;
        // Inside the capsule? lateral within radius AND axial within [aft,fore].
        if (dot(perp, perp) > radius * radius) continue;
        if (t < aft || t > fore) continue;
        // Gain applies regardless of health — a moving healthy engine is exactly
        // the case we brighten — so read it before the healthy short-circuit.
        gain = max(gain, u_glow_region_d[i].x);
        float flick  = u_glow_region_c[i].w;   // 1 = disabled (continuous), 0 = destroyed
        if (dtime < 0.0) continue;             // healthy

        float age = max(now - dtime, 0.0);
        float region_mult;
        if (flick > 0.5) {
            // Disabled: continuous oscillation between floor and full.
            region_mult = mix(DISABLED_FLOOR, 1.0, 0.5 + 0.5 * stutter(age));
        } else {
            // Destroyed: brief blow-out flicker, then settle to target (0 = off).
            float blow = mix(target, 1.0, 0.5 + 0.5 * stutter(age));
            float w    = clamp(age / GLOW_FLICKER_SECS, 0.0, 1.0);
            region_mult = mix(blow, target, w);
        }
        mult = min(mult, region_mult);  // overlapping regions: darkest wins
    }
    return mult;
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
        // Cull at the widest extent any term reaches: the Scorch glow-flicker,
        // whose per-impact random radius reaches up to FLICKER_RMULT_MAX * the
        // decal (deposit) radius.
        if (r >= FLICKER_RMULT_MAX) continue;

        // Normal-aware falloff (the mirroring fix): the stored decal normal dn
        // (from ray_trace -> world_dir_to_body) comes out in the SAME convention
        // as the reconstructed fragment normal n_body, so a fragment on the
        // struck face has dot(n_body, dn) ~+1 and the opposite face ~-1. This
        // keeps a decal from bleeding onto a surface facing the other way.
        float wn = smoothstep(NORMAL_MIN, 1.0, dot(n_body, dn));
        if (wn <= 0.0) continue;

        // Power-disruption flicker (Scorch only): modulate the ship's own glow
        // map. Computed BEFORE the deposit radius cutoff so it can spread wider
        // (its per-impact random rmult * radius) than the soot deposit / ember.
        if (u_decal_c[i].y > 0.5) {
            float birth = u_decal_c[i].x;
            float fage  = u_decal_time - birth;
            // Per-impact randoms, hashed from the unique birth_time (stable
            // across frames, independent via different seeds):
            //  - duration in [MIN,MAX], biased toward MIN (short more likely),
            //  - radius multiplier in [RMULT_MIN, RMULT_MAX] (x decal radius).
            float fdur  = mix(FLICKER_DUR_MIN, FLICKER_DUR_MAX,
                              pow(dhash(vec2(birth, 7.3)), FLICKER_DUR_BIAS));
            float rmult = mix(FLICKER_RMULT_MIN, FLICKER_RMULT_MAX,
                              dhash(vec2(birth, 13.7)));
            float rf = r / rmult;                            // 0 center, 1 at flicker edge
            if (fage >= 0.0 && fage < fdur && rf < 1.0) {    // >= 0: fire at the birth frame
                if (fage < FLICKER_STUTTER_SECS) {
                    // Stutter phase: rapid on/off, amplitude tapering over the phase.
                    float env  = 1.0 - fage / FLICKER_STUTTER_SECS;
                    float fall = exp(-rf * rf * FLICKER_TIGHTNESS);
                    glow_flicker += STUTTER_GAIN * env * stutter(fage) * fall * wn;
                } else {
                    // Past the stutter phase a longer disruption goes SOLID DARK
                    // (lights out) until fdur, then restores. -2 drives gf to 0
                    // (clamped) in the core; soft radial edge so it isn't a hard disc.
                    glow_flicker += -2.0 * wn * (1.0 - smoothstep(0.6, 1.0, rf));
                }
            }
        }

        // Deposit / ember / heat-glow stay confined to the decal radius.
        if (r >= 1.0) continue;

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
        }
    }
}

out vec4 frag_color;

void main() {
    vec3 n = normalize(v_normal_ws);
    vec3 V = normalize(u_camera_pos_ws - v_position_ws);

    // Body-frame fragment position (object-space carve + decals).
    vec3 p_body = (u_ship_world_inv * vec4(v_position_ws, 1.0)).xyz;

    // ── Hull-breach hole: pure damage-sphere clip ──────────────────────────
    // Discard hull fragments inside any active carve sphere. The breach pass
    // renders the exposed interior (scoop) within the same spheres, so hole and
    // interior align by construction. u_carve_count == 0 (or disabled) = stock path.
    if (u_carve_enabled != 0 && u_carve_count > 0) {
        for (int i = 0; i < u_carve_count; i++) {
            vec3 c  = u_carve_spheres[i].xyz;
            float r = u_carve_spheres[i].w;
            vec3 n  = u_carve_normals[i];
            // Oblate breach centred on the hull surface: full lateral radius,
            // shallow along the normal.
            vec3 v       = p_body - c;
            float along  = dot(v, n);
            vec3 lateral = v - along * n;
            float ld     = length(lateral);
            if (ld < r * (1.0 + kShapeAmp) && abs(along) < kDepthFactor * r * (1.0 + kShapeAmp)) {
                // Azimuthal noise on the lateral radius (jagged rim); same
                // azimuth term the scoop uses, so the hole edge aligns.
                vec3 az = ld > 1e-4 ? lateral / ld : vec3(1.0, 0.0, 0.0);
                float r_eff = r * (1.0 + kShapeAmp * (vnoise3(az * kShapeFreq + c * kPhase) * 2.0 - 1.0));
                float dz = along / (kDepthFactor * r);
                float e  = (ld * ld) / (r_eff * r_eff) + dz * dz;   // <1 inside the oblate
                if (e < 1.0) {
                    // ── Skeletal framework lattice (INSIDE the breach) ──────────
                    // Don't cut a clean hole: leave torn HULL STRUTS bridging the
                    // breach where Damage.tga's stencil is opaque; the gaps between
                    // struts reveal the recessed interior behind. Struts cluster
                    // toward the rim (open core) so it still reads as a hole. The
                    // surrounding hull (outside the oblate) is left untouched.
                    bool cut = true;
                    if (u_frame_enabled != 0) {
                        // tangent-plane UV around the breach axis (basis from n)
                        vec3 up = abs(n.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0);
                        vec3 t  = normalize(cross(up, n));
                        vec3 b  = cross(n, t);
                        vec2 uv = vec2(dot(lateral, t), dot(lateral, b))
                                  / (r * kFrameUvScale) * 0.5 + 0.5;
                        float a    = texture(u_damage_decal, uv).a;
                        float frac = sqrt(e);                   // 0 center .. 1 rim
                        // Keep a hull strut where the stencil is opaque (the lattice)
                        // AND we're outside the open core; everything else is cut.
                        if (a > kStrutAlpha && frac > kOpenCore) cut = false;
                    }
                    if (cut) discard;
                }
            }
        }
    }

    // Shadow attenuates ONLY the sun (directional index 0). When shadows are
    // off, sun_shadow_factor() returns 1.0, so the ×sf below is the identity
    // and the accumulated light is byte-identical to the pre-shadow path.
    float sun_sf = sun_shadow_factor(v_position_ws, n);

    vec3 lit_dir  = vec3(0.0);
    vec3 spec_acc = vec3(0.0);
    for (int i = 0; i < u_dir_light_count; ++i) {
        vec3 L  = normalize(u_dir_light_dir_ws[i]);
        float nl = max(dot(n, L), 0.0);
        float sf = (i == 0) ? sun_sf : 1.0;   // sun-only shadow
        lit_dir += sf * nl * u_dir_light_color[i];

        if (u_specular_enabled != 0) {
            vec3 H = normalize(L + V);
            float s = pow(max(dot(n, H), 0.0), u_specular_power) * step(0.0, nl);
            spec_acc += sf * s * u_dir_light_color[i];
        }
    }

    vec4 base = texture(u_base_color, v_uv);
    vec3 lit  = (u_ambient_light + lit_dir) * u_diffuse_color * base.rgb;

    // Body-frame normal for object-space decals.
    vec3 n_body = normalize(mat3(u_ship_world_inv) * v_normal_ws);

    vec3 decal_emissive = vec3(0.0);
    float glow_flicker = 1.0;
    if (u_decal_count > 0) {
        apply_damage_decals(p_body, n_body, lit, decal_emissive, glow_flicker);
    }

    vec4 glow = texture(u_glow_map, v_uv);
    float gf = clamp(glow_flicker, 0.0, FLICKER_MAX);
    vec3 spec = (u_specular_enabled != 0)
        ? spec_acc * u_specular_color * texture(u_specular_map, v_uv).rgb
        : vec3(0.0);

    vec3 rim = vec3(0.0);
    if (u_rim_strength > 0.0) {
        float f = pow(1.0 - max(dot(n, V), 0.0), RIM_POWER);
        rim = RIM_GAIN * f * lit_dir * u_rim_strength;
    }

    float nac = 1.0;
    float region_gain = 1.0;
    if (u_glow_region_count > 0) {
        nac = glow_region_mult(p_body, u_decal_time, region_gain);  // reuse existing body-frame pos
    }

    // Self-illumination (material emissive + window/light glow map) scales by
    // u_emissive_scale so a destroyed ship goes dark; diffuse-lit, specular,
    // rim, and damage-decal embers are external/transient and stay. region_gain
    // (>1) drives the impulse glow with engine power/speed; HDR bloom picks it up.
    vec3 self_illum = u_emissive_scale * (u_emissive_color + glow.rgb * glow.a * gf * nac * region_gain);
    vec3 final_color = lit + self_illum + spec + rim + decal_emissive;

    frag_color = vec4(final_color, 1.0);
}
