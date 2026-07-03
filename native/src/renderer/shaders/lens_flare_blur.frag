#version 330 core
//
// Separable Gaussian blur for the lens-flare texture. Run twice by
// LensFlareHdrPass (horizontal then vertical) to soften the ghosts/halo. Radius
// is live-tunable via the dev "Lens Flare Tuning" panel; 0 = passthrough.

in vec2 v_uv;
out vec4 frag_color;

uniform sampler2D u_src;
uniform vec2  u_dir;      // per-texel step: (1/w,0) horizontal, (0,1/h) vertical

// Eye-calibrated blur radius in texels (locked in after live tuning).
const float RADIUS = 4.5;
const int   TAPS   = 5;   // ceil(RADIUS) taps each side

void main() {
    float sigma = RADIUS * 0.5;
    vec3  sum  = texture(u_src, v_uv).rgb;   // centre tap, weight 1
    float wsum = 1.0;
    for (int i = 1; i <= TAPS; ++i) {
        if (float(i) > RADIUS) break;
        float w = exp(-0.5 * float(i * i) / (sigma * sigma));
        vec2  o = u_dir * float(i);
        sum += (texture(u_src, v_uv + o).rgb + texture(u_src, v_uv - o).rgb) * w;
        wsum += 2.0 * w;
    }
    frag_color = vec4(sum / wsum, 1.0);
}
