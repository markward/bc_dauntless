#version 410 core
// Screen-space radial scatter ("crepuscular rays"), GPU-Gems formulation.
// For each light (a lightning flash or the star) we march from the current
// fragment back toward the light's projected screen anchor, accumulating the
// bright HDR cloud colour with exponential decay. The result is additively
// accumulated (blend GL_ONE, GL_ONE) into a half-res target, one draw per
// light, so this shader outputs the premultiplied scatter contribution only.
//
// u_scene is the half-res SOURCE image (nebula_godray_mask.frag): the sky and
// the light's own body only, hulls in front of the light already zeroed, so a
// hull shadows the shafts but never streaks its own lights along them. This
// march runs at half res; nebula_godray_composite.frag blurs it back up.
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_scene;     // half-res masked source (see above)
uniform vec2  u_anchor;        // light screen pos in [0,1] (NDC*0.5+0.5)
uniform float u_on_screen;     // 1 if anchor usable, else 0
uniform vec3  u_color;         // flash tint
uniform float u_intensity;     // flash intensity scale
// dials (live-tuned per the brief)
uniform int   u_samples;       // default 48
uniform float u_decay;         // default 0.96
uniform float u_weight;        // default 0.5
uniform float u_exposure;      // default 0.25
uniform float u_jitter;        // per-pixel sample-uv jitter (uv units) to break
                               // the quarter-res cloud block grid

void main() {
    if (u_on_screen < 0.5 || u_intensity <= 0.0) { frag = vec4(0.0); return; }
    // Per-pixel jitter: the radial march samples the HDR cloud, which is
    // rendered at quarter resolution. Sampling it sharply amplifies its block
    // boundaries into a visible 4x4 lattice. Offsetting each fragment's samples
    // by a fixed sub-block amount (decorrelated from its neighbours) turns the
    // hard grid into fine, far less objectionable noise.
    float h = fract(sin(dot(gl_FragCoord.xy, vec2(12.9898, 78.233))) * 43758.5453);
    vec2 jit = (vec2(h, fract(h * 7.137)) - 0.5) * u_jitter;
    // Step from this fragment toward the anchor in u_samples increments.
    vec2 delta = (v_uv - u_anchor) / float(u_samples);
    vec2 uv = v_uv;
    float illum = 1.0;
    vec3 accum = vec3(0.0);
    for (int i = 0; i < u_samples; ++i) {
        uv -= delta;                            // step toward the anchor
        vec3 s = texture(u_scene, uv + jit).rgb; // jittered: bright flash-lit cloud
        accum += s * (illum * u_weight);
        illum *= u_decay;
    }
    // Tint by the flash colour, scale by exposure * intensity. Premultiplied
    // additive (alpha unused; blend is GL_ONE, GL_ONE).
    frag = vec4(accum * u_color * (u_exposure * u_intensity), 1.0);
}
