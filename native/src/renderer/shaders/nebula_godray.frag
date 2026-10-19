#version 410 core
// Screen-space radial scatter ("crepuscular rays"), GPU-Gems formulation.
// For each light (a lightning flash or the star) we march from the current
// fragment back toward the light's projected screen anchor, accumulating the
// bright HDR cloud colour with exponential decay. The result is additively
// composited into the HDR target (blend GL_ONE, GL_ONE), so this shader
// outputs the premultiplied scatter contribution only.
//
// Only the SOURCE is smeared: sky pixels and the light's own body (depth at or
// beyond u_source_depth). Anything nearer -- a hull in front of the light -- is
// an occluder that contributes zero: it darkens the shafts behind it, but its
// own lit windows and nacelle glows are never streaked along them.
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_scene;     // HDR colour (read-only; composited additively by blend)
uniform sampler2D u_depth;     // HDR depth (resolved, single-sample)
uniform float u_source_depth;  // window depth at/after which a pixel is SOURCE;
                               // 1.0 = sky only (a light with no body)
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
        // Source only if EVERY texel of the colour fetch's bilinear 2x2 is:
        // a single depth tap lets a sky sample beside a hull blend that
        // hull's glow in (a 1-px rim of it streaked down the shaft).
        vec4 d4 = textureGather(u_depth, uv + jit);
        float src = step(u_source_depth, min(min(d4.x, d4.y), min(d4.z, d4.w)));
        accum += s * (src * illum * u_weight);
        illum *= u_decay;
    }
    // Tint by the flash colour, scale by exposure * intensity. Premultiplied
    // additive (alpha unused; blend is GL_ONE, GL_ONE).
    frag = vec4(accum * u_color * (u_exposure * u_intensity), 1.0);
}
