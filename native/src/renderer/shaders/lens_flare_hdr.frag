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

uniform sampler2D u_src;    // bloom mip0: blurred HDR bright buffer
uniform sampler2D u_coarse; // smallest bloom mip: frame-wide bright energy
uniform float u_aspect;     // viewport width / height
uniform float u_budget;     // flare-budget strength; 0 = linear (budget off)

// Mean luminance of the thresholded bright buffer, from a grid of taps over the
// smallest bloom mip. This measures AREA as well as brightness, which is the
// whole point: a phaser beam is no brighter than a torpedo glow, it is simply
// vastly larger, and only an area-aware measure can tell them apart.
float bright_energy() {
    vec3 acc = vec3(0.0);
    for (int y = 0; y < 4; ++y) {
        for (int x = 0; x < 4; ++x) {
            acc += texture(u_coarse, (vec2(float(x), float(y)) + 0.5) / 4.0).rgb;
        }
    }
    return dot(acc / 16.0, vec3(0.2126, 0.7152, 0.0722));
}

// UV deltas are anisotropic on a non-square frame: one horizontal UV unit spans
// `aspect` times more pixels than one vertical unit. Every RADIUS measured here
// must therefore be taken in "height units" (x scaled by aspect), or the halo
// ring and the radial falloff come out as ellipses stretched across the frame —
// 2.3x on a 21:9 window, 3.2x on a 32:9 one, which reads as long horizontal
// smears rather than compact ghosts.
//
// Ghost POSITIONS need no correction: scaling one axis maps a line through the
// centre to another line through the centre, so the march is already right.
vec2 to_height_units(vec2 d) { return d * vec2(u_aspect, 1.0); }

// Eye-calibrated constants (locked in after live tuning). Rebuild to change.
const int   GHOSTS     = 5;      // number of ghost samples
const float GHOST_DISP = 0.5;    // ghost spacing (fraction toward centre)
const float HALO_WIDTH = 0.68;   // halo ring radius (frame heights)
const float HALO_GAIN  = 0.5;    // halo brightness (1.0 = pre-2026-08-06)
const float HALO_SOFTNESS = 3.0; // ring band falloff; lower = wider/softer (was 5.0)
const float CHROMA     = 0.003;  // chromatic dispersion magnitude (UV units)
const float FALLOFF    = 5.0;    // radial edge falloff exponent

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
    // Unit direction in height units, and the same step expressed back in UV so
    // a fixed offset covers a constant number of PIXELS in both axes.
    vec2 dir    = normalize(to_height_units(ghostVec) + vec2(1e-5));
    vec2 dir_uv = dir / vec2(u_aspect, 1.0);

    vec3 result = vec3(0.0);

    // ── Ghosts: march toward centre, weight brighter near the middle ────────
    vec3  ghosts = vec3(0.0);
    float wsum   = 0.0;
    for (int i = 0; i < GHOSTS; ++i) {
        vec2 suv = uv + ghostVec * float(i);
        float d = length(to_height_units(center - suv));
        float w = pow(1.0 - clamp(d, 0.0, 1.0), FALLOFF);
        ghosts += sample_chromatic(suv, dir_uv) * w;
        wsum   += w;
    }
    // Weighted AVERAGE, not sum. Firing at a target dead ahead — the default
    // combat framing — puts the source at the screen centre, where the flip
    // leaves it, so EVERY ghost samples that same spot at w~1 and a plain sum
    // deposits GHOSTS x the source brightness there ("disco lighting").
    // Averaging bounds the ghost term by the source brightness for any
    // geometry. The max(...,1) floor leaves the off-centre case, where the
    // weights already sum below 1, exactly as it was.
    result += ghosts / max(wsum, 1.0);

    // ── Halo ring: single sample at a fixed radius along the centre vector ──
    // Once the radius is aspect-correct this is a true circle, and at full
    // gain it reads as a hard arc across the frame rather than a soft bloom.
    // A lower exponent widens the band and HALO_GAIN takes the edge off.
    vec2 haloVec = dir_uv * HALO_WIDTH;
    float hw = length(to_height_units(center - (uv + haloVec))) / length(center);
    hw = pow(1.0 - clamp(hw, 0.0, 1.0), HALO_SOFTNESS);
    result += sample_chromatic(uv + haloVec, dir_uv) * hw * HALO_GAIN;

    // ── Flare budget ────────────────────────────────────────────────────────
    // Soft-limit the whole flare by how much of the frame is already bright.
    // Ordinary scenes (a star, a torpedo, nacelle glows) barely register, so
    // this is ~1.0 and they flare exactly as before; a full-power beam fired
    // dead ahead saturates the bright buffer and is pulled back hard.
    result /= (1.0 + u_budget * bright_energy());

    frag_color = vec4(result, 1.0);
}
