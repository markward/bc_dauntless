#version 330 core
in vec2 v_uv;
out vec4 frag_color;
uniform sampler2D u_src;
uniform float u_time;

// Filmic grade strengths — eye-tunable by rebuilding (like the resolve-grade
// consts). Applied in final display space, after tonemap + AA.
const float GRAIN_STRENGTH    = 0.05;   // peak +/- luma jitter at midtones
const float VIGNETTE_STRENGTH = 0.28;   // corner darkening fraction
const float CA_STRENGTH       = 0.005;  // chromatic split, UV units at the corner

// Cheap hash noise in [0,1).
float hash(vec2 p) {
    p = fract(p * vec2(443.897, 441.423));
    p += dot(p, p + 19.19);
    return fract((p.x + p.y) * p.x);
}

void main() {
    vec2 uv = v_uv;
    vec2 d  = uv - vec2(0.5);
    float r = length(d);

    // Chromatic aberration: push R out / B in along the radial, scaled by r
    // so the center is clean and corners separate most.
    vec2 ca = d * (r * CA_STRENGTH);
    vec3 col = vec3(
        texture(u_src, uv + ca).r,
        texture(u_src, uv).g,
        texture(u_src, uv - ca).b);

    // Vignette: smooth radial darkening. smoothstep(0.8,0.45,r) is 1 at center,
    // falling toward the corners (r ~= 0.707).
    float vig = smoothstep(0.8, 0.45, r);
    col *= mix(1.0 - VIGNETTE_STRENGTH, 1.0, vig);

    // Film grain: animated hash noise, weighted toward midtones (less in deep
    // shadow / blown highlight). fract(u_time) reseeds each frame.
    float n   = hash(uv * vec2(1920.0, 1080.0) + fract(u_time) * 100.0) - 0.5;
    float luma = dot(col, vec3(0.2126, 0.7152, 0.0722));
    float midweight = 1.0 - abs(luma - 0.5) * 2.0;   // 1 at mid, 0 at extremes
    col += n * GRAIN_STRENGTH * midweight;

    frag_color = vec4(clamp(col, 0.0, 1.0), 1.0);
}
