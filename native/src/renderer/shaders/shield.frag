#version 330 core

const int MAX_HITS = 8;
const float TAU = 6.2831853;

in vec3 v_world_pos;
in vec3 v_ship_local_pos;
in vec3 v_ship_local_normal;

uniform vec4  u_hit_points[MAX_HITS];          // xyz = world point, w unused
uniform vec4  u_hit_color_intensity[MAX_HITS]; // rgb = color, a = current_intensity
uniform vec4  u_hit_params[MAX_HITS];          // x = age (s), y = reach (GU),
                                               // z = ring phase jitter, w unused
uniform vec3  u_bubble_center;                 // world-space centre of the bubble
uniform vec3  u_bubble_semi_axes;              // world-space semi-axes of the bubble

// ── every constant below MUST match renderer/shield_state.h ────────────────
// The CPU twins there are what the tests characterise; this file is the
// mirror. Changing a number in one place and not the other silently decouples
// the tests from what actually renders.
const float GATE_FEATHER = 0.25;   // kShieldSplashGateFeather
const float RIPPLE_LIFE  = 0.70;   // kShieldSplashRippleLife
const float RING_LAMBDA  = 1.0 / 3.0;
const float RING_SHARP   = 3.0;
const float RING_TRAIL   = 0.35;   // packet decay BEHIND the front
const float RING_LEAD    = 0.05;   // and ahead of it — crisp, not a hard step
const float DISC_DECAY   = 0.55;
const float CORE_FRAC    = 0.18;
const float CORE_LIFE    = 0.15;   // the flash has its OWN, much shorter clock
const float CORE_POW     = 3.0;
const float CORE_GAIN    = 4.0;    // > 1 ON PURPOSE — drives the HDR bloom
const float GLOW_FRAC    = 0.70;
const float GLOW_GAIN    = 0.25;
const float DISC_GAIN    = 0.45;
const float RING_GAIN    = 0.9;
const float SPLASH_OPACITY = 0.75; // kShieldSplashOpacity
const float REACH_BUBBLE_FRAC = 1.0;  // kShieldSplashReachBubbleFrac

out vec4 frag_color;

// The stored anchor projected onto the bubble surface.
//
// hit_feedback passes the bubble ENTRY point when the shot had a ray and the
// HULL impact point when it did not (collisions, splash damage). The bubble
// stands sqrt(3) off the hull — 2.36 GU on a Galaxy's long axis — so a raw
// hull anchor sits deep inside it, and a world distance measured from there
// would blank bow and stern flashes entirely.
//
// MUST match shield_splash_epicentre() in renderer/shield_state.h.
vec3 splash_epicentre(vec3 hit_world) {
    vec3 n = (hit_world - u_bubble_center) / u_bubble_semi_axes;
    float len = length(n);
    if (len < 1e-6) return u_bubble_center;
    return u_bubble_center + (n / len) * u_bubble_semi_axes;
}

// The splash profile: brightness at world distance `d` from the epicentre,
// `age` seconds after the hit, for a ripple of `reach` GU.
//
// A function of a SCALAR DISTANCE, which is the entire point. The previous
// implementation built a tangent basis at the impact and projected the 3D
// offset onto it to sample a 2D texture, and all three of its distortions came
// from needing that 2D map:
//
//  * the tangent-plane projection itself;
//  * the footprint was measured in the bubble's unit-sphere space, isotropic
//    in ANGLE but mapping back to wildly different world sizes on a
//    4.02/5.58/1.22 GU bubble — measured at the time of the rewrite, one
//    impact spanned 0.15 GU across and 0.67 GU along, a 4.5x elongation;
//  * and `ref` flipped from (0,0,1) to (0,1,0) at abs(n_hit.z) = 0.9, rotating
//    the texture arbitrarily and POPPING as a hit tracked across the bubble.
//
// None of it has anywhere to live now. Four additive terms:
//
//   core  hot Gaussian at the epicentre, gone within the ripple life
//   disc  soft filled cap growing out to the expanding front
//   rings travelling crests, gated BY the disc so nothing rings ahead of it
//   glow  broad afterglow with NO age term — it fades on the hit's own
//         intensity decay instead, giving the fast-ripple/slow-glow split
//
// NOT clamped to 1: the core exceeds it so the HDR bloom has something to
// catch, which a texture sample never could.
//
// MUST match shield_splash_shape() in renderer/shield_state.h.
float splash_shape(float d_gu, float age, float reach, float jitter) {
    if (reach <= 0.0) return 0.0;
    float d = max(d_gu, 0.0);
    float a = clamp(age / RIPPLE_LIFE, 0.0, 1.0);

    // sqrt(a): bursts outward then slows, the way a surface wave does. A
    // linear front reads as a mechanical sweep.
    float front = reach * sqrt(a);

    // max() on the edge because smoothstep with edge0 == edge1 is UNDEFINED in
    // GLSL, and at a == 0 the front is exactly zero.
    float disc = 1.0 - smoothstep(0.0, max(front, 1e-4), d);
    disc *= exp(-d / (reach * DISC_DECAY));
    disc *= (1.0 - a);

    // The crests are a wave PACKET centred on the front. They used to be
    // enveloped by `disc`, which is 1 - smoothstep(0, front, d) and therefore
    // exactly 0 at d == front — so the crest riding the wavefront, the whole
    // thing that reads as motion, was multiplied by zero and the splash's
    // brightest point never left the epicentre. Asymmetric: long trailing
    // decay, short leading one, so the front stays crisp without aliasing.
    float behind = front - d;
    float bt = behind / (reach * (behind >= 0.0 ? RING_TRAIL : RING_LEAD));
    float band = exp(-bt * bt);

    float phase = (front - d) / (reach * RING_LAMBDA) + jitter;
    float rings = pow(max(cos(TAU * phase), 0.0), RING_SHARP) * band * (1.0 - a);

    // The core runs on its OWN short clock. Sharing the ripple's left the
    // flash brighter than the travelling crest for two thirds of the ripple,
    // hiding the motion the rings exist to convey.
    float ca = clamp(age / CORE_LIFE, 0.0, 1.0);
    float cr = d / (reach * CORE_FRAC);
    float core = exp(-cr * cr) * pow(1.0 - ca, CORE_POW) * CORE_GAIN;

    float gr = d / (reach * GLOW_FRAC);
    float glow = exp(-gr * gr);

    return core + disc * DISC_GAIN + rings * RING_GAIN + glow * GLOW_GAIN;
}

// One impact splash at this fragment. Returns 0 if the hit does not reach it.
//
// The hemisphere gate survives the rewrite because a world distance is a
// straight CHORD: on a hull whose bubble is thinner than the reach, the far
// side is genuinely within range and would light up. It is an orientation
// question, so it stays in unit-sphere space where the bubble is a sphere.
//
// MUST match shield_splash_coverage() in renderer/shield_state.h.
float splash_sample(vec3 hit_pos, vec3 frag_pos, float age, float reach,
                    float jitter) {
    vec3 n_hit  = (hit_pos  - u_bubble_center) / u_bubble_semi_axes;
    vec3 n_frag = (frag_pos - u_bubble_center) / u_bubble_semi_axes;
    float lh = length(n_hit);
    float lf = length(n_frag);
    if (lh < 1e-4 || lf < 1e-4) return 0.0;
    n_hit  /= lh;
    n_frag /= lf;

    float gate = smoothstep(0.0, GATE_FEATHER, dot(n_frag, n_hit));
    if (gate <= 0.0) return 0.0;

    // Bound the reach to the bubble's radius in the hit direction. The reach is
    // absolute (0.6-2.0 GU) but the bubble scales with the hull, so on a small
    // target the splash stayed bright all the way to the gate's terminator —
    // and a terminator is a great circle, which projects to a straight line.
    // That cut the splash into a dome with a hard FLAT bottom, seen live.
    // A CLAMP, not a proportional law: on any hull big enough to hold the
    // splash it changes nothing. MUST match shield_splash_reach_on_bubble().
    vec3 epi = splash_epicentre(hit_pos);
    float bubble_r = length(epi - u_bubble_center);
    float eff = bubble_r > 0.0 ? min(reach, REACH_BUBBLE_FRAC * bubble_r) : reach;

    float d = length(frag_pos - epi);
    return splash_shape(d, age, eff, jitter) * gate;
}

// The pass blends GL_ONE, GL_ONE and this writes a PREMULTIPLIED colour, so
// every term — coverage, hit intensity, tint — is applied exactly once.
//
// It used to accumulate the texture and the falloff into the colour AND into
// the alpha, under glBlendFunc(GL_SRC_ALPHA, GL_ONE), which multiplies rgb by
// alpha. Each term therefore reached the framebuffer squared, leaving peak
// output at 0.64% of full brightness. Mirrored by shield_splash_intensity() in
// renderer/shield_state.h, whose tests assert linearity in both coverage and
// intensity — a quadratic result there means this got re-squared.
void main() {
    vec3  color = vec3(0.0);
    float total = 0.0;

    for (int i = 0; i < MAX_HITS; ++i) {
        float inten = u_hit_color_intensity[i].a;
        if (inten < 0.01) continue;

        float coverage = splash_sample(u_hit_points[i].xyz,
                                       v_world_pos,
                                       u_hit_params[i].x,   // age, seconds
                                       u_hit_params[i].y,   // reach, GU
                                       u_hit_params[i].z);  // ring jitter
        if (coverage <= 0.0) continue;

        float b = coverage * inten * SPLASH_OPACITY;
        color += u_hit_color_intensity[i].rgb * b;
        total += b;
    }

    if (total < 0.001) discard;
    frag_color = vec4(color, 1.0);
}
