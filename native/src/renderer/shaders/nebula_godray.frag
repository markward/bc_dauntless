#version 330 core
// Screen-space radial scatter ("crepuscular rays"), GPU-Gems formulation.
// For each lightning flash we march from the current fragment back toward the
// flash's projected screen anchor, accumulating the bright HDR cloud colour
// with exponential decay. The result is additively composited into the HDR
// target (blend GL_ONE, GL_ONE), so this shader outputs the premultiplied
// scatter contribution only.
in vec2 v_uv;
out vec4 frag;

uniform sampler2D u_scene;     // HDR colour (read-only; composited additively by blend)
uniform vec2  u_anchor;        // light screen pos in [0,1] (NDC*0.5+0.5)
uniform float u_on_screen;     // 1 if anchor usable, else 0
uniform vec3  u_color;         // flash tint
uniform float u_intensity;     // flash intensity scale
// dials (live-tuned per the brief)
uniform int   u_samples;       // default 48
uniform float u_decay;         // default 0.96
uniform float u_weight;        // default 0.5
uniform float u_exposure;      // default 0.25

void main() {
    if (u_on_screen < 0.5 || u_intensity <= 0.0) { frag = vec4(0.0); return; }
    // Step from this fragment toward the anchor in u_samples increments.
    vec2 delta = (v_uv - u_anchor) / float(u_samples);
    vec2 uv = v_uv;
    float illum = 1.0;
    vec3 accum = vec3(0.0);
    for (int i = 0; i < u_samples; ++i) {
        uv -= delta;                       // step toward the anchor
        vec3 s = texture(u_scene, uv).rgb; // bright flash-lit cloud
        accum += s * (illum * u_weight);
        illum *= u_decay;
    }
    // Tint by the flash colour, scale by exposure * intensity. Premultiplied
    // additive (alpha unused; blend is GL_ONE, GL_ONE).
    frag = vec4(accum * u_color * (u_exposure * u_intensity), 1.0);
}
