#version 330 core
//
// Image-based ("pseudo") lens flare — John Chapman's feature-generation pass.
// Source is the bloom mip0 texture (already half-res, blurred, thresholded, and
// still HDR-valued), so every bright spot in the scene feeds the flare. The UV
// is flipped about the screen centre; ghosts march along the vector to centre,
// a halo ring is sampled at a fixed radius, and each sample is chromatically
// dispersed. Output is composited additively in resolve.frag.
//
// All the constants below are eye-calibrated — rebuild (cmake reconfigure) to
// change them.

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_src;   // bloom mip0: blurred HDR bright buffer

const int   GHOSTS     = 5;      // number of ghost samples
const float GHOST_DISP = 0.34;   // ghost spacing (fraction toward centre)
const float HALO_WIDTH = 0.47;   // halo ring radius (UV units)
const float CHROMA     = 0.011;  // chromatic dispersion magnitude (UV units)
const float FALLOFF    = 2.2;    // radial edge falloff exponent

// Sample the source with a per-channel offset along `dir` for chromatic
// dispersion (the classic coloured-fringe look on ghosts and the halo).
vec3 sample_chromatic(vec2 uv, vec2 dir) {
    vec2 o = dir * CHROMA;
    return vec3(texture(u_src, uv + o).r,
                texture(u_src, uv    ).g,
                texture(u_src, uv - o).b);
}

void main() {
    // Flip about the screen centre: a bright spot's ghosts land on the opposite
    // side of the frame.
    vec2 uv     = vec2(1.0) - v_uv;
    vec2 center = vec2(0.5);
    vec2 ghostVec = (center - uv) * GHOST_DISP;
    vec2 dir = normalize(ghostVec + vec2(1e-5));

    vec3 result = vec3(0.0);

    // ── Ghosts: march toward centre, weight brighter near the middle ────────
    for (int i = 0; i < GHOSTS; ++i) {
        vec2 suv = uv + ghostVec * float(i);
        float d = length(center - suv);
        float w = pow(1.0 - clamp(d, 0.0, 1.0), FALLOFF);
        result += sample_chromatic(suv, dir) * w;
    }

    // ── Halo ring: single sample at a fixed radius along the centre vector ──
    vec2 haloVec = dir * HALO_WIDTH;
    float hw = length(center - (uv + haloVec)) / length(center);
    hw = pow(1.0 - clamp(hw, 0.0, 1.0), 5.0);
    result += sample_chromatic(uv + haloVec, dir) * hw;

    frag_color = vec4(result, 1.0);
}
